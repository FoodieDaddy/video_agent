"""小说源文档保存、文本解析与章节查询。

写入口要求调用方已授权项目访问，使用传入 Session 并 flush，不自行提交。
原文文件由资产模块写入存储；外部文件写入不会因数据库回滚自动撤销。
解析仅替换对应文档的章节，项目级章节查询则包含该项目所有文档的章节。
"""

from __future__ import annotations

import io
import logging
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Asset, Project
from app.modules.assets.public import save_asset_reference
from app.modules.platform import storage as storage_utils
from app.modules.platform.constants import AssetKind, ProjectStatus
from app.modules.platform.exceptions import NotFoundError, ValidationAppError
from app.modules.platform.execution.runtime import AppRuntime
from app.modules.platform.ids import new_id
from app.modules.platform.resources import PROJECT_ROOT
from app.modules.platform.text import narrative
from app.modules.projects import public as project_service
from app.modules.story.infrastructure.persistence.models import SourceDocument, StoryChapter

logger = logging.getLogger(__name__)

SAMPLE_NAME = "novel_sample.txt"
# 样例资源保持原先锚定源码的语义，不随可注入的 settings.REPO_ROOT 改变。
# 资源常量与配置根独立；保留本模块 REPO_ROOT 供既有调用方单独覆盖。
REPO_ROOT = PROJECT_ROOT


def decode_text(content: bytes) -> str:
    """按 UTF-8、UTF-8 BOM、GB18030、Latin-1 的顺序解码字节。

    这是无 I/O 的兼容解码；末尾替换策略只保证返回字符串，不保证编码识别准确。
    """
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _extract_docx(content: bytes) -> str:
    """按文档顺序读取 DOCX 正文段落与表格；不处理图片文字或 OCR。

    表格单元格以制表符分隔，行及单元格内的段落/嵌套表格以换行分隔。
    合并单元格只输出一次实际文本，不按文字内容去重，避免误删重复的角色名或对白。

    缺少 python-docx 时抛 ValidationAppError，损坏文档的解析异常继续向上传播。
    """
    try:
        from docx import Document  # type: ignore
        from docx.document import Document as DocumentObject
        from docx.table import Table, _Cell
        from docx.text.paragraph import Paragraph
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ValidationAppError("解析 .docx 需要安装 python-docx") from exc
    document = Document(io.BytesIO(content))

    def iter_text(container: DocumentObject | _Cell) -> Iterator[str]:
        for block in container.iter_inner_content():
            if isinstance(block, Paragraph):
                if block.text.strip():
                    yield block.text
            elif isinstance(block, Table):
                seen_cells = set()
                for row in block.rows:
                    row_cells = set()
                    values = []
                    for cell in row.cells:
                        # row.cells 会把合并区域映射回同一个 XML 单元格。公共 API
                        # 没有跨行合并身份，故仅在此用 _tc 识别来源；不自行遍历 XML。
                        origin = cell._tc
                        if origin in row_cells:
                            continue
                        row_cells.add(origin)
                        if origin in seen_cells:
                            # 垂直合并的后续行保留空列，避免对白移到角色列。
                            values.append("")
                        else:
                            seen_cells.add(origin)
                            values.append("\n".join(iter_text(cell)))
                    text = "\t".join(values).rstrip("\t")
                    if text.strip():
                        yield text

    return "\n".join(iter_text(document))


def extract_text(content: bytes, filename: str) -> str:
    """按文件扩展名提取文本：DOCX 读取有序段落/表格，其余走解码与文本规整。

    不写数据库或文件；该入口没有额外实现 PDF 文本提取、OCR 或格式真实性验证。
    """
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
    """保存源文件资产并创建 uploaded 文档记录。

    Args:
        db: 调用方 Session；只 flush，不提交。
        runtime: 资产存储能力与配置。
        project: 已授权项目，上传大小和文件策略由调用方检查。
        content: 非空原文字节。

    Returns:
        新 SourceDocument，并将项目置为 ingested。

    Raises:
        ValidationAppError: content 为空。
        Exception: 存储和数据库错误传播。

    Notes:
        存储文件不会因数据库回滚自动删除；重复调用新增文档与资产，不提供幂等。
    """
    if not content:
        raise ValidationAppError("上传内容为空")
    filename = filename or "novel.txt"
    extension = Path(filename).suffix or ".txt"
    asset = save_asset_reference(
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
        asset_id=asset.asset_id,
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
    """读取源文件并替换该文档的章节记录。

    Args:
        db: 调用方事务 Session；仅 flush。
        runtime: 原文件读取能力。
        document: 已授权且归属已核对的源文档。

    Returns:
        本次新建的章节列表，同时更新文档状态、字符数与章节数。

    Raises:
        NotFoundError: 源文件资产不存在。
        ValidationAppError: 文本为空、不能切章，或 DOCX 依赖缺失。
        Exception: 实际文件读取和格式解析错误传播。

    Notes:
        删除范围仅为本 document_id；重复解析会重新分配章节 ID，不是无副作用重放。
        不提交，由外层回滚或提交；不调用模型。
    """
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

    db.query(StoryChapter).filter(StoryChapter.document_id == document.id).delete(synchronize_session=False)
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
    """顺序保存原文件并解析章节。

    Args:
        project: 已授权项目。
        content: 通过上传策略校验的原文字节，其余参数传给保存入口。

    Returns:
        文档和章节列表，均处于调用方 Session。

    Raises:
        Exception: 保存或解析入口的原有错误直接传播。

    Notes:
        两步之间不提交；失败由外层处理事务。已写文件不自动撤销，重试会新增文档。
    """
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
    """读取内置示例小说并完成导入解析。

    Args:
        project: 已授权目标项目。
        runtime: 提供文件存储及配置相邻资源路径。

    Returns:
        已解析的 SourceDocument。

    Raises:
        ValidationAppError: 两处资源位置均无样例，或导入解析不满足契约。
        Exception: 文件和存储错误传播。

    Notes:
        资源根与可注入配置根独立；仅 flush、不提交，重复导入创建新文档。
    """
    for candidate in (
        REPO_ROOT / "samples" / SAMPLE_NAME,
        runtime.settings.config_dir.parent / "samples" / SAMPLE_NAME,
    ):
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
    """按创建时间降序读取项目的全部源文档；权限由调用方事先确认。

    无匹配返回空列表；只读、不提交，返回值为当前 Session 的 ORM 实体。
    """
    return list(
        db.scalars(
            select(SourceDocument)
            .where(SourceDocument.project_id == project_id)
            .order_by(SourceDocument.created_at.desc())
        )
    )


def chapters(db: Session, project_id: str) -> list[StoryChapter]:
    """读取项目全部源文档的章节并按 index 排序，未匹配时返回空列表。

    该查询不自动限定最新文档；不同文档可有相同 index。只读，权限由调用方确认。
    """
    return list(
        db.scalars(
            select(StoryChapter).where(StoryChapter.project_id == project_id).order_by(StoryChapter.index)
        )
    )


def chapter_payloads(db: Session, project_id: str) -> list[dict]:
    """将项目级章节查询投影为模型输入字典，包含正文、摘要和字符数。

    查询范围与 chapters 相同，未匹配时返回空列表；不写入或提交。
    """
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
    """将单个章节投影为对外字典；包含正文，调用方负责访问授权。

    不触发额外查询或写入；字段来自所给 ORM 实体，不构成内容质量评估。
    """
    return {
        "id": chapter.id,
        "index": chapter.index,
        "title": chapter.title,
        "summary": chapter.summary,
        "char_count": chapter.char_count,
        "content": chapter.content,
    }


def document_public(document: SourceDocument) -> dict:
    """将源文档投影为元信息字典，不读取原文件字节。

    不查询、不写入或提交；meta 是现有记录的投影，调用方应按只读结果使用。
    """
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
