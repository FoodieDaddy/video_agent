"""剧本工作台：人工正文、文件导入、历史恢复及基于当前稿的 AI 编辑。

所有入口要求调用方已授权 project；只 flush，不提交。新接口总是追加未批准版本，
不改写历史、不启动工作流、不撤销或改写下游资产。旧 update_script 仍保留原位语义。
base_script_id 是最新版本的乐观校验，不提供数据库级唯一版本号或分布式锁。
"""

from __future__ import annotations

import io
import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ops import Task
from app.models.project import Project
from app.models.story import Script, StoryEvent
from app.modules.ai_runtime.public import run_agent
from app.modules.platform.constants import ProjectStatus
from app.modules.platform.exceptions import AgentSchemaError, ConflictError, ValidationAppError
from app.modules.platform.execution.runtime import AppRuntime
from app.modules.platform.ids import new_id
from app.modules.platform.persistence.versions import next_version
from app.modules.projects.public import touch_status
from app.modules.story.contracts import ScriptInput, ScriptOutput

from .documents import extract_text
from .queries import get_project_script, script_payload, script_text_of

logger = logging.getLogger(__name__)

MAX_SCRIPT_BYTES = 2 * 1024 * 1024
MAX_SCRIPT_CHARACTERS = 200_000
MAX_DOCX_EXPANDED_BYTES = 16 * 1024 * 1024
CONTINUATION_SEPARATOR = "\n\n"


def _text(value: object, field: str, *, maximum: int | None = None, required: bool = False) -> str:
    if not isinstance(value, str):
        raise ValidationAppError(f"{field}必须是字符串")
    if required and not value.strip():
        raise ValidationAppError(f"{field}不能为空")
    if maximum is not None and len(value) > maximum:
        raise ValidationAppError(f"{field}超过 {maximum} 字符上限")
    return value


def _body(value: object) -> str:
    text = _text(value, "剧本正文", maximum=MAX_SCRIPT_CHARACTERS, required=True)
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValidationAppError("剧本正文包含无效的 Unicode 字符") from exc
    if size > MAX_SCRIPT_BYTES:
        raise ValidationAppError("剧本正文超过 2MiB 上限")
    # 不 strip 正文：续写需要逐字保留原始稿的空白和换行。
    return text


def _current_base(
    db: Session,
    project_id: str,
    base_script_id: str | None,
    *,
    generation_completed: bool = False,
) -> Script | None:
    # 查询实际列并刷新 identity map，不能仅拿 Session 已缓存的 Script 对象作并发检查。
    current = db.scalar(
        select(Script)
        .where(Script.project_id == project_id)
        .order_by(Script.version.desc())
        .execution_options(populate_existing=True)
    )
    if base_script_id and not generation_completed:
        get_project_script(db, project_id, base_script_id)
    if (current.id if current else None) != (base_script_id or None):
        raise ConflictError(
            "剧本已更新，请刷新后基于最新版本保存",
            details={
                "project_id": project_id,
                "base_script_id": base_script_id,
                "current_script_id": current.id if current else None,
                "generation_completed": generation_completed,
            },
        )
    return current


def _events_of(db: Session, project_id: str, script: Script) -> list[dict[str, Any]]:
    """兼容旧稿只展开落表的事件；每次同时限定项目和剧本，不信任导入的外部行 ID。"""
    return [
        {
            "title": row.title,
            "description": row.description,
            "chapter_index": row.chapter_index,
            "characters": list(row.character_names or []),
            "location": row.location_name,
            "importance": row.importance,
        }
        for row in db.scalars(
            select(StoryEvent)
            .where(StoryEvent.project_id == project_id, StoryEvent.script_id == script.id)
            .order_by(StoryEvent.order_index)
        )
    ]


def _prepare(
    raw: dict[str, Any],
    *,
    title: str,
    script_text: str,
    logline: str,
    synopsis: str,
    genre: str,
    tone: str,
) -> dict[str, Any]:
    """验证整份数据后才允许落表；保留扩展字段，但不复用来源审核标记。"""
    values = {
        "title": _text(title, "剧本标题", maximum=255, required=True).strip(),
        "script_text": _body(script_text),
        "logline": _text(logline, "一句话故事"),
        "synopsis": _text(synopsis, "故事梗概"),
        "genre": _text(genre, "类型", maximum=64),
        "tone": _text(tone, "基调", maximum=120),
    }
    payload = {**deepcopy(raw), **values}
    for field in (
        "id",
        "project_id",
        "version",
        "status",
        "approved",
        "agent_id",
        "model_id",
        "prompt_version",
        "config_version",
        "created_at",
        "updated_at",
        "workspace_meta",
    ):
        payload.pop(field, None)
    try:
        normalized = ScriptOutput.model_validate(payload, strict=True)
        for event in normalized.events:
            _text(event.title, "事件标题", maximum=255)
            _text(event.location, "事件地点", maximum=255)
            if not 0 <= event.importance <= 1:
                raise ValidationAppError("事件 importance 必须介于 0 和 1")
        # JSON 字段不能容纳任意 Python 对象或 NaN/Infinity，错误要在 Script 创建之前暴露。
        json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ValidationAppError("剧本结构不合法", details={"reason": str(exc)[:500]}) from exc
    payload.update(normalized.model_dump(mode="json"))
    payload["script_text"] = values["script_text"]
    payload.pop("workspace_meta", None)
    return payload


def _persist(
    db: Session,
    *,
    project: Project,
    prepared: dict[str, Any],
    base: Script | None,
    source: str,
    user_id: str,
    model_id: str = "",
    prompt_version: str = "",
    config_version: str = "",
    restored_from_script_id: str | None = None,
    structure_status: str = "provided",
    source_document_id: str | None = None,
) -> Script:
    """仅持久化已经完全验证的数据；旧事件和下游批准均不修改。"""
    content = deepcopy(prepared)
    content["workspace_meta"] = {
        "source": source,
        "base_script_id": base.id if base else None,
        "created_by": user_id,
        "requires_reconfirmation": True,
        "structure_status": structure_status,
        **({"restored_from_script_id": restored_from_script_id} if restored_from_script_id else {}),
    }
    script = Script(
        id=new_id("script"),
        project_id=project.id,
        version=next_version(db, Script.version, Script, project.id),
        status="draft" if source in {"polish", "continue"} else "edited",
        title=content["title"],
        logline=content["logline"],
        synopsis=content["synopsis"],
        genre=content["genre"],
        tone=content["tone"],
        content=content,
        source_document_id=source_document_id
        if source_document_id is not None
        else (base.source_document_id if base else ""),
        agent_id="script" if source in {"polish", "continue"} else "human",
        model_id=model_id,
        prompt_version=prompt_version,
        config_version=config_version,
        approved=False,
    )
    db.add(script)
    db.flush()
    for index, event in enumerate(content.get("events", []), start=1):
        db.add(
            StoryEvent(
                id=new_id("event"),
                project_id=project.id,
                script_id=script.id,
                order_index=index,
                title=event["title"],
                description=event["description"],
                chapter_index=event.get("chapter_index"),
                location_name=event.get("location", ""),
                character_names=list(event.get("characters", [])),
                importance=event.get("importance", 0.5),
            )
        )
    # 只表示有可读的新剧本；旧下游记录仍保留，须由用户重新确认后再使用。
    touch_status(db, project, ProjectStatus.SCRIPT_READY)
    db.flush()
    logger.info(
        "script workspace project=%s script=%s version=%s source=%s",
        project.id,
        script.id,
        script.version,
        source,
    )
    return script


def create_script_version(
    db: Session,
    *,
    project: Project,
    title: str,
    script_text: str,
    logline: str = "",
    synopsis: str = "",
    genre: str | None = None,
    tone: str | None = None,
    content: dict[str, Any] | None = None,
    base_script_id: str | None = None,
    user_id: str = "",
) -> Script:
    """人工新建或保存完整正文为新版本；已存在剧本时必须提供最新基线。

    Returns:
        当前 Session 中新的未批准 Script，旧行和批准资产保持原值。

    Raises:
        ValidationAppError: 标题、正文或结构不合法，所有校验先于写入。
        ConflictError: 缺失最新基线或所选基线已经过期。
        NotFoundError: 基线不属于此项目或不存在。

    Notes:
        仅 flush、不提交，无文件或模型副作用。未提供 content 且正文改变时清空旧
        事件、对白、章节摘要并标为 needs_analysis；正文相同才保留并重建事件归属。
        新稿要求重新确认，重复同一基线保存会冲突，不是透明重试的幂等接口。
    """
    base = _current_base(db, project.id, base_script_id)
    if content is not None and not isinstance(content, dict):
        raise ValidationAppError("剧本 content 必须是对象")
    raw = deepcopy(content if content is not None else (base.content if base else {}) or {})
    body_changed = base is None or script_text != script_text_of(base)
    if content is None and body_changed:
        for field in ("events", "dialogues", "chapters"):
            raw[field] = []
    elif base and "events" not in raw:
        raw["events"] = _events_of(db, project.id, base)
    prepared = _prepare(
        raw,
        title=title,
        script_text=script_text,
        logline=logline,
        synopsis=synopsis,
        genre=genre
        if genre is not None
        else raw.get("genre", base.genre if base is not None else project.genre),
        tone=tone if tone is not None else raw.get("tone", base.tone if base is not None else ""),
    )
    _current_base(db, project.id, base_script_id)
    return _persist(
        db,
        project=project,
        prepared=prepared,
        base=base,
        source="manual",
        user_id=user_id,
        structure_status="needs_analysis" if content is None and body_changed else "provided",
    )


def import_script_version(
    db: Session,
    *,
    project: Project,
    filename: str,
    content: bytes,
    base_script_id: str | None = None,
    user_id: str = "",
) -> Script:
    """把 TXT/MD/JSON/DOCX 导入为剧本新版本，不创建小说、章节或任务。

    文件不超过 2MiB，正文还受 200000 字符及 UTF-8 2MiB 限制。JSON 接受
    ScriptOutput 或 API 的顶层元数据 + content 对象；不接受跨项目 project_id。
    全部解码/结构校验先于写入，损坏文件统一为 ValidationAppError；只 flush。
    """
    _current_base(db, project.id, base_script_id)
    if not isinstance(content, bytes) or not content:
        raise ValidationAppError("导入文件不能为空")
    if len(content) > MAX_SCRIPT_BYTES:
        raise ValidationAppError("导入文件超过 2MiB 上限")
    suffix = Path(filename or "").suffix.lower()
    if suffix not in {".txt", ".md", ".json", ".docx"}:
        raise ValidationAppError("仅支持 TXT、MD、JSON、DOCX 剧本文件")
    raw: dict[str, Any] = {}
    if suffix == ".json":
        try:
            imported = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            raise ValidationAppError("剧本 JSON 文件无效") from exc
        if not isinstance(imported, dict):
            raise ValidationAppError("剧本 JSON 顶层必须是对象")
        if imported.get("project_id", project.id) != project.id:
            raise ValidationAppError("不能导入其他项目的剧本记录")
        nested = imported.get("content", {})
        if not isinstance(nested, dict):
            raise ValidationAppError("剧本 JSON 的 content 必须是对象")
        raw = {**nested, **{k: v for k, v in imported.items() if k != "content"}}
        if raw.get("project_id", project.id) != project.id:
            raise ValidationAppError("不能导入其他项目的剧本记录")
        # API 导出的独立事件字段与 Agent 结构不同，只复制业务值，绝不使用旧行 ID。
        if isinstance(raw.get("events"), list):
            raw["events"] = [
                {
                    **event,
                    "characters": event.get("characters", event.get("character_names", [])),
                    "location": event.get("location", event.get("location_name", "")),
                }
                if isinstance(event, dict)
                else event
                for event in raw["events"]
            ]
        text = raw.get("script_text", "")
    else:
        try:
            if suffix == ".docx":
                # 上传字节限制不等同于解压后限制。只检查目录元数据，不把压缩包
                # 解到磁盘；阻止异常膨胀文件进入python-docx的XML解析。
                with ZipFile(io.BytesIO(content)) as archive:
                    entries = archive.infolist()
                    if (
                        len(entries) > 2000
                        or sum(entry.file_size for entry in entries) > MAX_DOCX_EXPANDED_BYTES
                    ):
                        raise ValidationAppError("DOCX解压后超过16MiB或条目数量上限")
            # 纯文本保留原始换行；DOCX 复用已有段落提取，不进行小说章节解析。
            text = extract_text(content, filename) if suffix == ".docx" else content.decode("utf-8-sig")
        except ValidationAppError:
            raise
        except Exception as exc:
            raise ValidationAppError("无法读取剧本文件，请检查文件内容与 UTF-8 编码") from exc
    prepared = _prepare(
        raw,
        title=raw.get("title", Path(filename).stem),
        script_text=text,
        logline=raw.get("logline", ""),
        synopsis=raw.get("synopsis", ""),
        genre=raw.get("genre", project.genre),
        tone=raw.get("tone", ""),
    )
    base = _current_base(db, project.id, base_script_id)
    return _persist(
        db,
        project=project,
        prepared=prepared,
        base=base,
        source="import",
        user_id=user_id,
        structure_status="provided"
        if any(prepared.get(key) for key in ("events", "dialogues", "chapters"))
        else "needs_analysis",
    )


def restore_script_version(
    db: Session,
    *,
    project: Project,
    script_id: str,
    base_script_id: str,
    user_id: str = "",
) -> Script:
    """复制同项目历史正文为最新未批准版本，要求 base_script_id 仍为当前稿。

    不把历史批准带到新版本，不改源稿；历史无正文时拒绝恢复而不是拿梗概补全文。
    事件从指定来源稿读取并新建归属；只 flush、不提交，不执行模型或工作流。
    """
    base = _current_base(db, project.id, base_script_id)
    source = get_project_script(db, project.id, script_id)
    raw = deepcopy(source.content or {})
    if "events" not in raw:
        raw["events"] = _events_of(db, project.id, source)
    prepared = _prepare(
        raw,
        title=source.title,
        script_text=script_text_of(source),
        logline=source.logline,
        synopsis=source.synopsis,
        genre=source.genre,
        tone=source.tone,
    )
    _current_base(db, project.id, base_script_id)
    return _persist(
        db,
        project=project,
        prepared=prepared,
        base=base,
        source="restore",
        user_id=user_id,
        restored_from_script_id=source.id,
        structure_status=(source.content or {}).get("workspace_meta", {}).get("structure_status", "provided"),
        source_document_id=source.source_document_id,
    )


async def revise_script(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    base_script_id: str,
    operation: str,
    instruction: str = "",
    task: Task | None = None,
    workflow_run_id: str = "",
    user_id: str = "",
) -> Script:
    """对明确的当前稿进行 AI 润色/续写，验证后追加版本，不覆盖原稿。

    polish 返回完整新正文；continue 只接受新增片段，由应用逐字保留原稿后追加
    两个换行及片段。开始和模型成功后均校验最新基线；兼容旧 PATCH 的原位修改
    也比较正文/元数据快照。失败时不写入新的 Script/StoryEvent。

    Notes:
        run_agent 在外部等待前 flush 审计，可能持有写事务且发生费用。本函数不
        commit；最终基线冲突带 generation_completed=True，任务调用方可据此窄范围
        提交已完成调用的审计/费用。其他错误沿用外层回滚，不保证失败审计独立持久化。
        数据库回滚不能撤销真实模型费用；重试可能再次计费，也不提供分布式版本锁。
    """
    if operation not in {"polish", "continue"}:
        raise ValidationAppError("AI 剧本操作只能是 polish 或 continue")
    instruction = _text(instruction, "创作要求", maximum=10_000)
    base = _current_base(db, project.id, base_script_id)
    if base is None:
        raise ValidationAppError("请先保存剧本正文")
    original = _body(script_text_of(base))
    snapshot = deepcopy(script_payload(base))
    context = deepcopy(snapshot)
    context.pop("script_text", None)
    context["content"].pop("script_text", None)
    # 正文只通过专用字段发送一次，结构上下文不再重复整稿，避免无意义的 token 开销。
    result = await run_agent(
        db,
        runtime,
        project=project,
        agent_id="script",
        payload=ScriptInput(
            operation=operation,
            script_text=original,
            current_script=context,
            instruction=instruction,
            language=project.language,
            genre=project.genre,
            title_hint=base.title,
        ),
        task=task,
        workflow_run_id=workflow_run_id,
        user_id=user_id,
    )
    try:
        output = ScriptOutput.model_validate(result.output, strict=True)
        addition = _body(output.script_text)
        if operation == "continue" and addition.strip().startswith(original.strip()):
            raise ValidationAppError("续写结果重复了原稿，必须只返回新增片段")
        text = original + CONTINUATION_SEPARATOR + addition if operation == "continue" else addition
        prepared = _prepare(
            output.model_dump(mode="json"),
            title=output.title,
            script_text=text,
            logline=output.logline or base.logline,
            synopsis=output.synopsis or base.synopsis,
            genre=output.genre or base.genre,
            tone=output.tone or base.tone,
        )
    except (ValidationError, ValidationAppError) as exc:
        raise AgentSchemaError("AI 剧本结果不合法", details={"reason": str(exc)[:500]}) from exc
    # 完成前刷新整个 identity map，防止基线对象或最新查询复用旧值。
    db.expire_all()
    current = _current_base(db, project.id, base_script_id, generation_completed=True)
    if current is None or script_payload(current) != snapshot:
        raise ConflictError(
            "原稿在生成期间被修改，请刷新后重试",
            details={
                "project_id": project.id,
                "base_script_id": base_script_id,
                "current_script_id": current.id if current else None,
                "generation_completed": True,
            },
        )
    return _persist(
        db,
        project=project,
        prepared=prepared,
        base=current,
        source=operation,
        user_id=user_id,
        model_id=result.model_id,
        prompt_version=result.prompt_version,
        config_version=result.config_version,
        structure_status="provided"
        if any(prepared.get(key) for key in ("events", "dialogues", "chapters"))
        else "needs_analysis",
    )
