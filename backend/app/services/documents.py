"""Source document ingestion.

Uploaded novels are stored as an immutable asset (bytes live in object storage)
and immediately split into chapters so the rest of the pipeline never has to
parse raw text again.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import AssetKind, ProjectStatus
from app.core.exceptions import NotFoundError, ValidationAppError
from app.core.ids import new_id
from app.models.project import Asset, Project
from app.models.story import SourceDocument, StoryChapter
from app.services import projects as project_service
from app.services.assets import save_asset
from app.services.runtime import AppRuntime
from app.utils import narrative
from app.utils import storage as storage_utils

logger = logging.getLogger(__name__)

SAMPLE_NAME = "novel_sample.txt"
REPO_ROOT = Path(__file__).resolve().parents[3]


def decode_text(content: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _extract_docx(content: bytes) -> str:
    try:
        from docx import Document  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ValidationAppError("解析 .docx 需要安装 python-docx") from exc
    document = Document(io.BytesIO(content))
    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    return "\n".join(paragraph for paragraph in paragraphs if paragraph.strip())


def extract_text(content: bytes, filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".docx":
        return _extract_docx(content)
    return narrative.normalize_text(decode_text(content))


def store_document(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    filename: str,
    content: bytes,
    content_type: str = "",
    user_id: str = "",
) -> SourceDocument:
    if not content:
        raise ValidationAppError("上传内容为空")
    filename = filename or "novel.txt"
    extension = Path(filename).suffix or ".txt"
    asset = save_asset(
        db,
        runtime,
        project_id=project.id,
        kind=AssetKind.SOURCE_DOCUMENT.value,
        content=content,
        extension=extension,
        mime_type=content_type or storage_utils.guess_mime(filename, "text/plain"),
        meta={"filename": filename},
        created_by=user_id,
    )
    document = SourceDocument(
        id=new_id("doc"),
        project_id=project.id,
        filename=filename,
        content_type=content_type or asset.mime_type,
        asset_id=asset.id,
        size_bytes=len(content),
        status="uploaded",
        created_by=user_id,
        meta={"storage_key": asset.storage_key},
    )
    db.add(document)
    db.flush()
    project_service.touch_status(db, project, ProjectStatus.INGESTED)
    return document


def parse_document(db: Session, runtime: AppRuntime, document: SourceDocument) -> list[StoryChapter]:
    """Split the stored document into chapters (idempotent, replaces old rows)."""
    asset = db.get(Asset, document.asset_id)
    if asset is None:
        raise NotFoundError("源文件资产不存在", details={"document_id": document.id})
    raw = runtime.read_media(asset.storage_key)
    text = extract_text(raw, document.filename)
    if not text:
        raise ValidationAppError("文档没有可解析的文本内容")

    chapters = narrative.split_chapters(text, title_hint=Path(document.filename).stem)
    if not chapters:
        raise ValidationAppError("无法从文档中切分出章节")

    db.query(StoryChapter).filter(StoryChapter.document_id == document.id).delete(
        synchronize_session=False
    )
    rows: list[StoryChapter] = []
    for item in chapters:
        body = str(item.get("content") or "")
        row = StoryChapter(
            id=new_id("chapter"),
            project_id=document.project_id,
            document_id=document.id,
            index=int(item.get("index") or len(rows) + 1),
            title=str(item.get("title") or f"第{len(rows) + 1}章"),
            content=body,
            char_count=len(body),
            summary=narrative.summarize(body, 180),
        )
        db.add(row)
        rows.append(row)

    document.status = "parsed"
    document.error = ""
    document.meta = {
        **(document.meta or {}),
        "chapter_count": len(rows),
        "char_count": len(text),
    }
    db.flush()
    logger.info("document %s parsed into %s chapters", document.id, len(rows))
    return rows


def ingest_bytes(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    filename: str,
    content: bytes,
    content_type: str = "",
    user_id: str = "",
) -> tuple[SourceDocument, list[StoryChapter]]:
    document = store_document(
        db,
        runtime,
        project=project,
        filename=filename,
        content=content,
        content_type=content_type,
        user_id=user_id,
    )
    chapters = parse_document(db, runtime, document)
    return document, chapters


def ingest_sample(db: Session, runtime: AppRuntime, *, project: Project, user_id: str = "") -> SourceDocument:
    """Load the bundled demo novel so the pipeline is runnable without uploads."""
    for candidate in (REPO_ROOT / "samples" / SAMPLE_NAME, runtime.settings.config_dir.parent / "samples" / SAMPLE_NAME):
        if candidate.is_file():
            content = candidate.read_bytes()
            document, _ = ingest_bytes(
                db,
                runtime,
                project=project,
                filename=candidate.name,
                content=content,
                content_type="text/plain",
                user_id=user_id,
            )
            return document
    raise ValidationAppError("示例小说 samples/novel_sample.txt 不存在")


def list_documents(db: Session, project_id: str) -> list[SourceDocument]:
    return list(
        db.scalars(
            select(SourceDocument)
            .where(SourceDocument.project_id == project_id)
            .order_by(SourceDocument.created_at.desc())
        )
    )


def chapters(db: Session, project_id: str) -> list[StoryChapter]:
    return list(
        db.scalars(
            select(StoryChapter)
            .where(StoryChapter.project_id == project_id)
            .order_by(StoryChapter.index)
        )
    )


def chapter_payloads(db: Session, project_id: str) -> list[dict]:
    return [
        {
            "index": chapter.index,
            "title": chapter.title,
            "content": chapter.content,
            "summary": chapter.summary,
            "char_count": chapter.char_count,
        }
        for chapter in chapters(db, project_id)
    ]


def chapter_public(chapter: StoryChapter) -> dict:
    return {
        "id": chapter.id,
        "index": chapter.index,
        "title": chapter.title,
        "summary": chapter.summary,
        "char_count": chapter.char_count,
        "content": chapter.content,
    }


def document_public(document: SourceDocument) -> dict:
    return {
        "id": document.id,
        "filename": document.filename,
        "content_type": document.content_type,
        "size_bytes": document.size_bytes,
        "status": document.status,
        "error": document.error,
        "meta": document.meta or {},
        "created_at": document.created_at.isoformat() if document.created_at else None,
    }
