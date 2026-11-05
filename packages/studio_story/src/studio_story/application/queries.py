"""剧本读取与数据投影。

调用方负责项目权限。查询不写入、不提交；ORM 返回值依赖调用方 Session。
本层按当前记录读取，不为工作流冻结版本，也不自动筛选已审核内容。
"""

from __future__ import annotations

import logging
from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.orm import Session

from studio_platform.exceptions import ConflictError, NotFoundError
from studio_story.contracts import ScriptBaselineReference, ScriptSnapshot
from studio_story.domain.script_baseline import (
    build_script_fingerprint_input,
    script_text_of_content,
)
from studio_story.domain.script_baseline import (
    fingerprint_script as fingerprint_script_input,
)
from studio_story.infrastructure.persistence.models import Script, SourceDocument

logger = logging.getLogger(__name__)


def _latest_script_row(db: Session, project_id: str, *, refresh: bool = False) -> Script | None:
    """读取最新行；需要防止 identity map 陈旧内容时显式刷新。"""
    statement = select(Script).where(Script.project_id == project_id).order_by(Script.version.desc())
    if refresh:
        statement = statement.execution_options(populate_existing=True)
    return db.scalar(statement)


def latest_script(db: Session, project_id: str) -> Script | None:
    """按 version 降序读取项目最新剧本，无记录返回 None。

    不限制 approved 状态，不改变数据库；需要指定审核版本时由上游明确选择。
    """
    return _latest_script_row(db, project_id)


def _script_snapshot(script: Script) -> ScriptSnapshot:
    """在所属模块内将 ORM 投影成深副本；不给跨模块调用方暴露 Session。"""
    return ScriptSnapshot(
        id=script.id,
        project_id=script.project_id,
        version=script.version,
        title=script.title,
        logline=script.logline,
        synopsis=script.synopsis,
        genre=script.genre,
        tone=script.tone,
        content=deepcopy(script.content or {}),
        script_text=script_text_of(script),
        fingerprint=script_fingerprint(script),
        approved=script.approved,
    )


def latest_script_snapshot(db: Session, project_id: str, *, refresh: bool = False) -> ScriptSnapshot | None:
    """读取最新剧本 DTO；refresh=True 时刷新已加载的 ORM 行，再生成深副本。"""
    script = _latest_script_row(db, project_id, refresh=refresh)
    return _script_snapshot(script) if script is not None else None


def get_script_snapshot(db: Session, project_id: str, script_id: str) -> ScriptSnapshot:
    """刷新并读取项目内指定剧本 DTO；错误语义与旧读取接口保持一致。"""
    return _script_snapshot(get_project_script(db, project_id, script_id))


def script_payload(script: Script | None) -> dict:
    """把剧本投影为生成下游所需字典，输入 None 时返回空字典。

    不查询或写入；content 沿用现有 JSON 值，调用方应按只读结果使用。
    """
    if script is None:
        return {}
    return {
        "id": script.id,
        "version": script.version,
        "title": script.title,
        "logline": script.logline,
        "synopsis": script.synopsis,
        "genre": script.genre,
        "tone": script.tone,
        "content": script.content or {},
        "approved": script.approved,
        "script_text": script_text_of(script),
        "workspace_meta": (script.content or {}).get("workspace_meta", {}),
    }


def script_text_of(script: Script) -> str:
    """读取持久化正文；旧版仅有梗概/事件时返回空字符串，不将摘要冒充全文。"""
    return script_text_of_content(script.content)


def script_fingerprint(script: Script) -> str:
    """对正文、标题、摘要和业务结构生成稳定指纹，不包含审批与执行标记。

    Notes:
        只排除 content 顶层的记录身份、出处和工作台流程元数据；结构内部的同名
        业务字段仍参与散列。键顺序不影响结果，正文空白和结构列表顺序会影响结果。
        不查询、不修改记录；这不是完整配置快照或语义等价证明。
    """
    value = build_script_fingerprint_input(
        title=script.title,
        logline=script.logline,
        synopsis=script.synopsis,
        genre=script.genre,
        tone=script.tone,
        content=script.content,
    )
    return fingerprint_script_input(value)


def _matching_script_baseline(
    db: Session, project_id: str, script_id: str, fingerprint: str | None
) -> tuple[Script, str]:
    """读取并校验最新剧本，返回当前 ORM 行和已计算指纹。"""
    if not isinstance(fingerprint, str) or not fingerprint:
        raise ConflictError(
            "当前工作流缺少剧本基线指纹，无法确认旧稿安全，请取消旧流程后重新开始",
            details={"project_id": project_id, "script_id": script_id, "reason": "missing_fingerprint"},
        )
    current = _latest_script_row(db, project_id, refresh=True)
    details = {
        "project_id": project_id,
        "script_id": script_id,
        "current_script_id": current.id if current else None,
    }
    if current is None or current.id != script_id:
        raise ConflictError(
            "剧本版本已更新，当前工作流基于旧稿，请取消旧流程后重新开始",
            details={**details, "reason": "script_version_changed"},
        )
    current_fingerprint = script_fingerprint(current)
    if current_fingerprint != fingerprint:
        raise ConflictError(
            "剧本正文或结构已更新，当前工作流基于旧稿，请取消旧流程后重新开始",
            details={**details, "reason": "script_content_changed"},
        )
    return current, current_fingerprint


def assert_script_baseline(db: Session, project_id: str, script_id: str, fingerprint: str | None) -> Script:
    """兼容接口：校验最新稿基线并返回当前 ORM 行。

    Raises:
        ConflictError: 旧流程未记录指纹、项目最新版本不同，或原位修改改变了业务内容。

    Notes:
        调用方先完成项目授权。查询刷新已有 ORM 缓存，不写入、不提交，不撤销历史
        资产或批准。没有指纹的旧完整流程不能补算当前指纹冒充原始基线。
    """
    current, _ = _matching_script_baseline(db, project_id, script_id, fingerprint)
    return current


def assert_script_baseline_reference(
    db: Session, project_id: str, script_id: str, fingerprint: str | None
) -> ScriptBaselineReference:
    """校验剧本基线并返回不含 ORM 实体的 DTO，供 workflow/reviews 等跨模块调用。"""
    current, current_fingerprint = _matching_script_baseline(db, project_id, script_id, fingerprint)
    return ScriptBaselineReference(
        project_id=current.project_id,
        script_id=current.id,
        version=current.version,
        fingerprint=current_fingerprint,
    )


def assert_script_baseline_snapshot(
    db: Session, project_id: str, script_id: str, fingerprint: str | None
) -> ScriptSnapshot:
    """刷新、校验剧本基线并返回正文深副本；冲突顺序沿用旧接口。"""
    current, _ = _matching_script_baseline(db, project_id, script_id, fingerprint)
    return _script_snapshot(current)


def get_project_script(db: Session, project_id: str, script_id: str) -> Script:
    """读取指定项目的剧本版本；跨项目 ID 与不存在统一抛 NotFoundError。

    不修改或提交事务。populate_existing 保证已有 Session 中的旧 ORM 实例也刷新。
    """
    script = db.scalar(
        select(Script)
        .where(Script.id == script_id, Script.project_id == project_id)
        .execution_options(populate_existing=True)
    )
    if script is None:
        raise NotFoundError("剧本版本不存在", details={"script_id": script_id})
    return script


def list_script_versions(db: Session, project_id: str) -> list[Script]:
    """按版本倒序返回同项目历史，不按批准状态筛选；授权由调用方完成。"""
    return list(
        db.scalars(select(Script).where(Script.project_id == project_id).order_by(Script.version.desc()))
    )


def _latest_document_id(db: Session, project_id: str) -> str:
    """按创建时间返回项目最新源文档 ID，缺失时返回空字符串。

    只提供关联引用，不验证该文档与当前章节集合的一一对应。
    """
    row = db.scalar(
        select(SourceDocument)
        .where(SourceDocument.project_id == project_id)
        .order_by(SourceDocument.created_at.desc())
    )
    return row.id if row else ""
