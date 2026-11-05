"""剧本生成与人工编辑用例。

调用方负责项目授权及 Session 事务；本文件只 flush，不隐式 commit。
生成会请求模型并追加记录，外部调用的用量不会随数据库回滚撤销。
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.ops import Task
from app.models.project import Project
from app.modules.ai_runtime.public import run_agent
from app.modules.platform.constants import ProjectStatus
from app.modules.platform.exceptions import WorkflowError
from app.modules.platform.execution.runtime import AppRuntime
from app.modules.platform.ids import new_id
from app.modules.platform.persistence.versions import next_version as _next_version
from app.modules.projects.public import touch_status
from app.modules.story.application import documents
from app.modules.story.infrastructure.persistence.models import Script, StoryEvent
from app.schemas.script import ScriptInput

from .queries import _latest_document_id

logger = logging.getLogger(__name__)


def update_script(
    db: Session,
    *,
    script: Script,
    title: str | None = None,
    logline: str | None = None,
    synopsis: str | None = None,
    content: dict | None = None,
    status: str = "edited",
) -> Script:
    """原地修改给定剧本的已提供字段，并设置状态。

    Args:
        script: 调用方已验证项目权限的剧本 ORM 实体。
        content: None 时保留原值，否则整体替换 JSON 内容。
        status: 写入剧本行的状态，默认 edited。

    Returns:
        同一 Script 行，不新增剧本版本。

    Notes:
        仅 flush、不提交；不自动重建独立 StoryEvent 行，也不改变原有批准标记。
        下游重新生成和审批策略由调用方按现有流程处理。
    """
    if title is not None:
        script.title = title.strip()[:255]
    if logline is not None:
        script.logline = logline
    if synopsis is not None:
        script.synopsis = synopsis
    if content is not None:
        script.content = content
    script.status = status
    db.flush()
    return script


async def generate_script(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    task: Task | None = None,
    workflow_run_id: str = "",
    user_id: str = "",
) -> Script:
    """从项目章节生成结构化剧本并追加 Script 与 StoryEvent。

    Args:
        db: 调用方事务 Session；仅 flush，不提交。
        runtime: 模型执行、配置和审计上下文。
        project: 已授权且具有章节的项目。

    Returns:
        新 draft 剧本，包含模型、提示词和配置出处；部分章节/事件可能由 Agent 补全。

    Raises:
        WorkflowError: 没有可用章节。
        Exception: 模型、Schema 和数据库错误传播。

    Notes:
        请求模型并更新项目为 script_ready；外部用量不会因数据库回滚撤销。
        重复成功调用新增版本，不提供请求幂等或并发版本锁。
    """
    chapters = documents.chapter_payloads(db, project.id)
    if not chapters:
        raise WorkflowError("请先上传并解析小说文本，再进行剧本解析")

    # 模块 2 输入是章节 dict 列表，输出按 ScriptOutput 校验后完整存入 Script.content；
    # events 同时展开为 StoryEvent 行。模块 3 的人物/场景提取实际消费 Script.content
    # 和原始章节列表，二者不能与这里单独落表的 StoryEvent 混淆。
    result = await run_agent(
        db,
        runtime,
        project=project,
        agent_id="script",
        payload=ScriptInput(
            chapters=chapters,
            language=project.language,
            genre=project.genre,
            title_hint=project.name,
        ),
        task=task,
        workflow_run_id=workflow_run_id,
        user_id=user_id,
    )
    output = result.output
    version = _next_version(db, Script.version, Script, project.id)
    script = Script(
        id=new_id("script"),
        project_id=project.id,
        version=version,
        status="draft",
        title=output.title or project.name,
        logline=output.logline,
        synopsis=output.synopsis,
        genre=output.genre or project.genre,
        tone=output.tone,
        content=output.model_dump(mode="json"),
        source_document_id=_latest_document_id(db, project.id),
        agent_id="script",
        model_id=result.model_id,
        prompt_version=result.prompt_version,
        config_version=result.config_version,
    )
    db.add(script)
    db.flush()

    for index, event in enumerate(output.events, start=1):
        db.add(
            StoryEvent(
                id=new_id("event"),
                project_id=project.id,
                script_id=script.id,
                order_index=index,
                title=event.title,
                description=event.description,
                chapter_index=event.chapter_index,
                location_name=event.location,
                character_names=list(event.characters),
                importance=float(event.importance),
            )
        )

    touch_status(db, project, ProjectStatus.SCRIPT_READY)
    db.flush()
    logger.info("script v%s generated for project %s", version, project.id)
    return script
