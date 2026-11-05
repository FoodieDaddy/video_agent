"""场景提取、描述与人工编辑用例。

调用方保证项目授权及实体归属；本文件使用已有 Session 并 flush，不负责提交。
模型请求、属性更新和档案追加保持现有语义，不承诺请求幂等或并发版本分配。
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.ai_runtime.public import run_agent
from app.modules.platform.exceptions import WorkflowError
from app.modules.platform.execution.runtime import AppRuntime
from app.modules.platform.ids import new_id
from app.modules.platform.persistence.models import Task
from app.modules.projects.contracts import ProjectContext as Project
from app.modules.scenes.infrastructure.persistence.models import Scene, SceneProfile
from app.modules.scenes.schemas.scene import SceneDescriptionInput, SceneExtractionInput
from app.modules.story import public as documents
from app.modules.story.public import latest_script_snapshot

from .queries import list_scenes, scene_profile_of

logger = logging.getLogger(__name__)


def update_scene(
    db: Session,
    *,
    scene: Scene,
    name: str | None = None,
    summary: str | None = None,
    profile: dict | None = None,
) -> Scene:
    """更新场景字段；传入 profile 时合并并新建人工档案。

    Args:
        scene: 已授权且归属已核对的场景 ORM 实体。
        profile: None 表示不追加档案，空字典仍会新建版本。

    Returns:
        同一 Scene；仅改 name 或 summary 不创建档案。

    Notes:
        profile 分支移动 canonical、置 draft 并清零批准版本；只 flush、不提交。
        重复编辑会继续追加版本，不提供请求幂等。
    """
    if name is not None and name.strip():
        scene.name = name.strip()[:200]
    if summary is not None:
        scene.summary = summary
    if profile is not None:
        current = scene_profile_of(db, scene)
        merged = dict(current.content or {}) if current else {}
        merged.update(profile)
        version = (
            int(
                db.scalar(select(func.max(SceneProfile.version)).where(SceneProfile.scene_id == scene.id))
                or 0
            )
            + 1
        )
        row = SceneProfile(
            id=new_id("sprofile"),
            project_id=scene.project_id,
            scene_id=scene.id,
            version=version,
            content=merged,
            approved=False,
            agent_id="human",
        )
        db.add(row)
        db.flush()
        scene.canonical_profile_id = row.id
        scene.status = "draft"
        scene.approved_version = 0
    db.flush()
    return scene


async def extract_scenes(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    task: Task | None = None,
    workflow_run_id: str = "",
    user_id: str = "",
) -> list[Scene]:
    # 场景提取与人物提取共享模块 2 的输入边界：最新 Script.content + 原始章节。
    """从最新剧本与章节提取场景并保存本次候选。

    Args:
        project: 已授权且具有剧本的项目。
        runtime: 场景提取 Agent 配置与执行能力。

    Returns:
        本次 Scene 列表；同项目按精确名称复用，未再次出现的旧场景保留。

    Raises:
        WorkflowError: 项目没有剧本。
        Exception: 模型、Schema、数据库错误传播。

    Notes:
        当前只保存名称、章节索引、环境摘要；已有非空摘要保留，细分属性未完整持久化。
        候选置 draft 并 flush、不提交；外部调用和属性更新不属于无副作用重放。
    """
    script = latest_script_snapshot(db, project.id)
    if script is None:
        raise WorkflowError("还没有剧本，无法提取场景")

    result = await run_agent(
        db,
        runtime,
        project=project,
        agent_id="scene_extraction",
        payload=SceneExtractionInput(
            chapter_texts=documents.chapter_payloads(db, project.id),
            script=script.content or {},
        ),
        task=task,
        workflow_run_id=workflow_run_id,
        user_id=user_id,
    )
    # 同项目精确同名复用场景 ID，未再次出现的旧场景仍保留。此处仅把候选的名称、
    # 章节索引和 environment 摘要接到 Scene；时间、光照等细分字段未分别持久化。
    existing = {scene.name: scene for scene in list_scenes(db, project.id)}
    scenes: list[Scene] = []
    for candidate in result.output.scenes:
        scene = existing.get(candidate.name)
        if scene is None:
            scene = Scene(
                id=new_id("scene"),
                project_id=project.id,
                name=candidate.name,
                slug=candidate.name,
                chapter_index=candidate.chapter_index,
            )
            db.add(scene)
            existing[candidate.name] = scene
        scene.summary = scene.summary or candidate.environment
        scene.chapter_index = candidate.chapter_index or scene.chapter_index
        scene.status = "draft"
        scenes.append(scene)
    db.flush()
    return scenes


async def describe_scenes(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    scenes: list[Scene],
    task: Task | None = None,
    workflow_run_id: str = "",
    user_id: str = "",
) -> list[SceneProfile]:
    # 描述阶段逐场景调用模型，当前输入来自 Scene.name/summary；提取结果中的
    # time_of_day、mood、architecture 没有在前一步存入 Scene，此处传空值，
    # 由描述模型及其 postprocess 生成/补全，不能称为完整透传提取阶段的细分属性。
    """逐场景生成新档案并更新 canonical 引用。

    Args:
        project: 已授权项目。
        scenes: 调用方保证属于 project 的场景候选。
        runtime: 场景描述配置与模型执行能力。

    Returns:
        本次 SceneProfile 列表；模型非空输出名称不会在本用例额外纠正。

    Raises:
        Exception: 模型、Schema 和数据库错误传播。

    Notes:
        输入主要是名称和摘要，时间/氛围/建筑传空值；模型或后处理的默认值不是原文证据。
        只 flush、不提交；成功重放新增版本，不承诺并发版本分配安全。
    """
    profiles: list[SceneProfile] = []
    for scene in scenes:
        result = await run_agent(
            db,
            runtime,
            project=project,
            agent_id="scene_description",
            payload=SceneDescriptionInput(
                name=scene.name,
                evidence=scene.summary or "",
                time_of_day="",
                mood="",
                architecture="",
            ),
            task=task,
            workflow_run_id=workflow_run_id,
            user_id=user_id,
        )
        output = result.output
        # 与人物档案一样追加版本，并将 canonical 指针指向新档案；旧档案保留，
        # 人工审核标记由 reviews 服务负责。
        current = db.scalar(select(func.max(SceneProfile.version)).where(SceneProfile.scene_id == scene.id))
        profile = SceneProfile(
            id=new_id("sprofile"),
            project_id=project.id,
            scene_id=scene.id,
            version=int(current or 0) + 1,
            content=output.model_dump(mode="json"),
            agent_id="scene_description",
            model_id=result.model_id,
            prompt_version=result.prompt_version,
            config_version=result.config_version,
        )
        db.add(profile)
        db.flush()
        scene.canonical_profile_id = profile.id
        scene.summary = output.description or scene.summary
        profiles.append(profile)
    db.flush()
    return profiles
