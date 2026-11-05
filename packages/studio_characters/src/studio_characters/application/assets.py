"""人物形象生成、形象版本登记与读取用例。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from studio_ai_runtime.public import run_agent
from studio_assets import public as asset_service
from studio_characters.application.queries import list_characters, profile_of
from studio_characters.infrastructure.agents.character_image import CharacterImageInput
from studio_characters.infrastructure.persistence.models import Character, CharacterAsset
from studio_platform.constants import (
    AssetKind,
    CharacterStatus,
)
from studio_platform.exceptions import NotFoundError, WorkflowError
from studio_platform.execution.runtime import AppRuntime
from studio_platform.ids import new_id
from studio_platform.persistence.models import Task
from studio_projects.contracts import ProjectContext as Project

logger = logging.getLogger(__name__)

CHARACTER_ASSET_KINDS = ("portrait", "full_body", "turnaround")


def character_asset_version(db: Session, character_id: str, kind: str) -> int:
    """读取人物某类形象资产的最大版本并建议下一个编号。

    仅查询，不预留编号或加锁；并发分配由调用方协调。
    """
    current = db.scalar(
        select(func.max(CharacterAsset.version)).where(
            CharacterAsset.character_id == character_id, CharacterAsset.kind == kind
        )
    )
    return int(current or 0) + 1


async def generate_character_assets(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    characters: list[Character] | None = None,
    character_ids: list[str] | None = None,
    kinds: tuple[str, ...] = CHARACTER_ASSET_KINDS,
    task: Task | None = None,
    workflow_run_id: str = "",
    user_id: str = "",
    stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """逐人物、逐种类生成形象资产，并保留单项失败明细。

    Args:
        db: 调用方拥有的 Session；本函数不提交。
        runtime: 提供图片执行和文件存储能力的运行上下文。
        project: 已授权项目；传入 characters 须属于该项目。
        characters: 候选列表；None 或空列表时读取项目全部人物。
        character_ids: 供新跨模块调用使用的身份列表；提供时在本模块读取并核对项目归属。
        kinds: 每个人物顺序生成的形象种类。
        stop: 生成每个种类前检查的停止回调，不中断已发出的模型请求。

    Returns:
        含 characters、assets_created、failures、kinds 的字典；允许部分成功。

    Raises:
        WorkflowError: 没有可处理人物。
        Exception: 模型单项异常收集进 failures；后续资产保存或数据库错误仍可能传播。

    Notes:
        成功项写存储并追加资产版本；只 flush，不提交。失败或停止不撤销已完成项。
        重试可能再次生成与计费，不提供请求幂等或并发版本锁。
    """
    if character_ids is not None:
        selected = []
        for character_id in character_ids:
            character = db.get(Character, character_id)
            if character is None or character.project_id != project.id:
                raise NotFoundError("人物不存在", details={"character_id": character_id})
            selected.append(character)
        characters = selected
    else:
        characters = characters or list_characters(db, project.id)
    if not characters:
        raise WorkflowError("还没有人物档案，无法生成角色形象")

    created = 0
    failures: list[dict[str, str]] = []
    for character in characters:
        profile = profile_of(db, character)
        profile_content = (profile.content if profile else {}) or {}
        reference_bytes: bytes | None = None
        parent_asset_id = ""
        for kind in kinds:
            if stop and stop():
                break
            inputs = CharacterImageInput(
                project_id=project.id,
                character_id=character.id,
                name=character.name,
                profile=profile_content,
                kind=kind,
                reference_image=reference_bytes,
                style_tokens=list(character.appearance_keywords or [])[:6],
                label=f"{character.name}_{kind}",
            )
            try:
                result = await run_agent(
                    db,
                    runtime,
                    project=project,
                    agent_id="character_image",
                    payload=inputs,
                    task=task,
                    workflow_run_id=workflow_run_id,
                    user_id=user_id,
                )
            except Exception as exc:
                logger.warning("character image failed for %s/%s: %s", character.id, kind, exc)
                failures.append({"character": character.name, "kind": kind, "error": str(exc)[:300]})
                continue

            output = result.output
            content = getattr(output, "content", None)
            if not content:
                failures.append({"character": character.name, "kind": kind, "error": "provider 未返回图片"})
                continue
            asset = asset_service.save_asset_reference(
                db,
                runtime,
                project_id=project.id,
                kind=AssetKind.CHARACTER_IMAGE.value,
                content=content,
                extension=".png",
                mime_type=getattr(output, "mime", "image/png"),
                width=getattr(output, "width", None) or None,
                height=getattr(output, "height", None) or None,
                model_id=result.model_id,
                prompt_version=result.prompt_version,
                config_version=result.config_version,
                meta={"character_id": character.id, "kind": kind},
                created_by=user_id,
            )
            version = character_asset_version(db, character.id, kind)
            db.add(
                CharacterAsset(
                    id=new_id("casset"),
                    project_id=project.id,
                    character_id=character.id,
                    asset_id=asset.asset_id,
                    kind=kind,
                    version=version,
                    approved=False,
                    parent_asset_id=parent_asset_id,
                    model_id=result.model_id,
                    prompt_version=result.prompt_version,
                    config_version=result.config_version,
                    meta={
                        "prompt": (result.meta or {}).get("prompt", ""),
                        "label": f"{character.name}_{kind}",
                    },
                )
            )
            asset_service.record_asset_version(
                db,
                project_id=project.id,
                asset_id=asset.asset_id,
                entity_type="character_asset",
                entity_id=character.id,
                version=version,
                note=kind,
                is_active=kind == "portrait",
            )
            if kind == "portrait":
                reference_bytes = content
                parent_asset_id = asset.asset_id
            created += 1
        db.flush()

    return {
        "characters": len(characters),
        "assets_created": created,
        "failures": failures,
        "kinds": list(kinds),
    }


def character_assets(db: Session, character_id: str) -> list[CharacterAsset]:
    """按创建时间降序读取人物的全部形象资产；人物归属由调用方核对，只读、不提交。"""
    return list(
        db.scalars(
            select(CharacterAsset)
            .where(CharacterAsset.character_id == character_id)
            .order_by(CharacterAsset.created_at.desc())
        )
    )


def character_asset_public(db: Session, row: CharacterAsset) -> dict:
    """读取关联 Asset 并投影形象资产信息；缺失资产时 URL 为空，不写入或提交。"""
    asset = asset_service.asset_reference(db, row.asset_id)
    return {
        "id": row.id,
        "character_id": row.character_id,
        "asset_id": row.asset_id,
        "kind": row.kind,
        "version": row.version,
        "approved": row.approved,
        "parent_asset_id": row.parent_asset_id,
        "model_id": row.model_id,
        "prompt_version": row.prompt_version,
        "config_version": row.config_version,
        "url": asset_service.asset_url(asset) if asset else "",
        "meta": row.meta or {},
    }


def ensure_character_approved(db: Session, character: Character) -> None:
    """仅把所给人物实体 status 设为 approved 并 flush，不提交。

    此兼容辅助不核对项目，不批准档案版本或创建 Review；不能当成人物审核完整入口。
    """
    character.status = CharacterStatus.APPROVED.value
    db.flush()
