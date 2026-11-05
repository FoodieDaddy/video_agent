"""人物提取、档案生成与人工编辑用例。

project、character 和候选列表的授权与同项目归属由调用方保证。
使用外层 Session 并 flush，不提交；模型调用、版本追加与关系替换均可能有副作用。
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.ops import Task
from app.models.project import Project
from app.modules.ai_runtime.public import run_agent
from app.modules.characters.infrastructure.persistence.models import (
    Character,
    CharacterProfile,
    CharacterRelationship,
)
from app.modules.platform.constants import CharacterStatus, ProjectStatus
from app.modules.platform.exceptions import WorkflowError
from app.modules.platform.execution.runtime import AppRuntime
from app.modules.platform.ids import new_id
from app.modules.projects.public import touch_status
from app.modules.story import public as documents
from app.modules.story.public import latest_script
from app.schemas.character import CharacterDescriptionInput, CharacterExtractionInput

from .queries import _profile_version, list_characters, profile_of

logger = logging.getLogger(__name__)


def update_character(
    db: Session,
    *,
    character: Character,
    name: str | None = None,
    summary: str | None = None,
    appearance_keywords: list[str] | None = None,
    profile: dict | None = None,
) -> Character:
    """更新人物字段；传入 profile 时才追加人工档案版本。

    Args:
        character: 已授权且归属已核对的人物 ORM 实体。
        profile: None 表示不编辑档案；空字典也会触发合并并新建版本。

    Returns:
        同一 Character；仅 name、summary 或 appearance_keywords 修改不会新增档案。

    Notes:
        profile 分支移动 canonical、置 draft 并清零 approved_version；仅改其他字段不触发该分支。
        只 flush、不提交；重复 profile 请求会追加版本，调用方控制权限与重试。
    """
    if name is not None and name.strip():
        character.name = name.strip()[:120]
    if summary is not None:
        character.summary = summary
    if appearance_keywords is not None:
        character.appearance_keywords = [str(item) for item in appearance_keywords]
    if profile is not None:
        current = profile_of(db, character)
        merged = dict(current.content or {}) if current else {}
        merged.update(profile)
        row = CharacterProfile(
            id=new_id("cprofile"),
            project_id=character.project_id,
            character_id=character.id,
            version=_profile_version(db, character.id),
            status="edited",
            content=merged,
            source="human",
            approved=False,
            agent_id="human",
        )
        db.add(row)
        db.flush()
        character.canonical_profile_id = row.id
        character.status = CharacterStatus.DRAFT.value
        character.approved_version = 0
    db.flush()
    return character


async def extract_characters(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    task: Task | None = None,
    workflow_run_id: str = "",
    user_id: str = "",
) -> list[Character]:
    # 模块 3 从项目最新剧本与原始章节提取候选；模型给出的是名字，数据库实体 ID
    # 由下面的持久化步骤分配，不能把模型名字直接当作人物外键。
    """从最新剧本和项目章节提取并保存本次人物与关系。

    Args:
        project: 已授权项目；需先存在剧本。
        runtime: 提供人物提取 Agent 的配置与执行能力。

    Returns:
        本次候选对应的 Character ORM 列表；按项目内精确名称复用，未出现的旧人物保留。

    Raises:
        WorkflowError: 项目没有剧本。
        Exception: 模型、契约和数据库错误传播。

    Notes:
        不在此归并别名；本项目旧关系整体替换，无效端点与自身关系跳过。
        只 flush、不提交；调用模型并更新属性和关系，重放不保证无副作用。
    """
    script = latest_script(db, project.id)
    if script is None:
        raise WorkflowError("还没有剧本，无法提取人物")

    result = await run_agent(
        db,
        runtime,
        project=project,
        agent_id="character_extraction",
        payload=CharacterExtractionInput(
            script=script.content or {},
            chapter_texts=documents.chapter_payloads(db, project.id),
            language=project.language,
        ),
        task=task,
        workflow_run_id=workflow_run_id,
        user_id=user_id,
    )
    output = result.output

    # 仅在同一项目内按精确同名复用人物 ID，并更新本次返回的属性；未再次被提取的
    # 旧人物仍保留。因此重复提取不等于删除重建全体人物，也不是严格的无副作用重放。
    existing = {character.name: character for character in list_characters(db, project.id)}
    characters: list[Character] = []
    for candidate in output.characters:
        character = existing.get(candidate.name)
        if character is None:
            character = Character(
                id=new_id("char"),
                project_id=project.id,
                name=candidate.name,
                status=CharacterStatus.DRAFT.value,
                source="extracted",
            )
            db.add(character)
            existing[candidate.name] = character
        character.aliases = list(candidate.aliases)
        character.role_type = candidate.role_hint or character.role_type
        character.summary = candidate.evidence or character.summary
        character.meta = {
            **(character.meta or {}),
            "evidence": candidate.evidence,
            "gender_hint": candidate.gender_hint,
            "age_hint": candidate.age_hint,
        }
        characters.append(character)
    db.flush()

    # 关系采用项目内整体替换：清除旧关系，再把本次候选间的名字转换为实体 ID。
    # 端点不在本次候选中或指向同一人物时跳过，不会创建悬空关系或自环。
    by_name = {character.name: character for character in characters}
    db.query(CharacterRelationship).filter(CharacterRelationship.project_id == project.id).delete(
        synchronize_session=False
    )
    for relation in output.relationships:
        source, target = by_name.get(relation.source), by_name.get(relation.target)
        if source is None or target is None or source.id == target.id:
            continue
        db.add(
            CharacterRelationship(
                id=new_id("crel"),
                project_id=project.id,
                source_character_id=source.id,
                target_character_id=target.id,
                relation=relation.relation,
                description=relation.description,
            )
        )
    db.flush()
    logger.info("extracted %s characters for project %s", len(characters), project.id)
    return characters


async def describe_characters(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    characters: list[Character],
    task: Task | None = None,
    workflow_run_id: str = "",
    user_id: str = "",
) -> list[CharacterProfile]:
    """逐人物生成档案版本并更新 canonical。

    Args:
        project: 已授权项目。
        characters: 调用方保证属于该项目的已提取候选；空列表不会请求模型。
        runtime: 人物档案模型配置、执行和审计能力。

    Returns:
        新档案列表，人物摘要与关键词同步更新；项目按原行为置为 characters_ready。

    Raises:
        Exception: 模型、Schema、数据库等错误传播。

    Notes:
        输入含摘要/evidence_list、原文章节和最新剧本；source_facts 分组不构成事实核查。
        只 flush、不提交，成功重试追加版本；空列表仍执行项目状态更新。
    """
    # 每个人物分别接收已提取的证据、原始章节和最新剧本；章节/剧本提供背景，
    # source_facts 与 inferred_items 的字段区分本身不代表完成了事实核查。
    script = latest_script(db, project.id)
    chapter_texts = documents.chapter_payloads(db, project.id)
    profiles: list[CharacterProfile] = []
    for character in characters:
        evidence = [character.summary] if character.summary else []
        evidence.extend(str(item) for item in (character.meta or {}).get("evidence_list", []) if item)
        result = await run_agent(
            db,
            runtime,
            project=project,
            agent_id="character_description",
            payload=CharacterDescriptionInput(
                name=character.name,
                evidence=evidence,
                chapter_texts=chapter_texts,
                script=script.content if script else {},
                language=project.language,
            ),
            task=task,
            workflow_run_id=workflow_run_id,
            user_id=user_id,
        )
        output = result.output
        # 本路径追加 max(version)+1 的草稿，不覆盖旧档案内容；canonical 指针随后
        # 切换到新版本。生成档案和审核通过是两个步骤，approved_version 由审核更新。
        version = _profile_version(db, character.id)
        profile = CharacterProfile(
            id=new_id("cprofile"),
            project_id=project.id,
            character_id=character.id,
            version=version,
            status="draft",
            content=output.model_dump(mode="json"),
            source="ai",
            agent_id="character_description",
            model_id=result.model_id,
            prompt_version=result.prompt_version,
            config_version=result.config_version,
        )
        db.add(profile)
        db.flush()
        character.canonical_profile_id = profile.id
        character.appearance_keywords = list(output.visual_keywords)
        character.summary = output.appearance or character.summary
        if character.role_type in ("", "supporting") and output.role_type:
            character.role_type = output.role_type
        profiles.append(profile)
    db.flush()
    touch_status(db, project, ProjectStatus.CHARACTERS_READY)
    return profiles
