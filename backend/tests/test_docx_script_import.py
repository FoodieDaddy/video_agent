"""DOCX 剧本正文回归：仅 BytesIO 与内存 SQLite，不写正式文件或调用模型。"""

from io import BytesIO

import pytest
from docx import Document
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401 注册全部外键映射，共用单一 Base。
from app.models.ops import AgentRun, Task
from app.models.story import SourceDocument
from app.modules.platform.persistence.base import Base
from app.modules.projects.public import create_project
from app.modules.story.application.documents import extract_text
from app.modules.story.public import import_script_version


def docx_bytes(document):
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False, autoflush=False) as session:
        yield session
        session.rollback()
    engine.dispose()


def test_docx_dialogue_table_survives_script_import_in_document_order(db):
    document = Document()
    document.add_paragraph("场一：雨夜，书店。")
    table = document.add_table(rows=3, cols=2)
    for row, values in zip(
        table.rows, [("角色", "对白"), ("林简", "请把那封信留下。"), ("苏晚", "明天我会回来。")], strict=True
    ):
        for cell, value in zip(row.cells, values, strict=True):
            cell.text = value
    document.add_paragraph("林简关上书店的门。")
    project = create_project(db, owner_id="docx-test", name="DOCX隔离导入")

    script = import_script_version(db, project=project, filename="对白表.docx", content=docx_bytes(document))

    assert script.content["script_text"] == (
        "场一：雨夜，书店。\n角色\t对白\n林简\t请把那封信留下。\n苏晚\t明天我会回来。\n林简关上书店的门。"
    )
    assert script.project_id == project.id and script.agent_id == "human"
    for model in (SourceDocument, Task, AgentRun):
        assert db.scalar(select(func.count()).select_from(model)) == 0


def test_docx_merged_cells_do_not_repeat_but_distinct_equal_text_is_preserved():
    document = Document()
    table = document.add_table(rows=4, cols=2)
    table.cell(0, 0).text = "场一"
    table.cell(0, 0).merge(table.cell(0, 1))
    table.cell(1, 0).text = "林简"
    table.cell(1, 1).text = "第一句"
    table.cell(2, 1).text = "第二句"
    table.cell(1, 0).merge(table.cell(2, 0))
    table.cell(3, 0).text = "林简"
    table.cell(3, 1).text = "第三句"

    text = extract_text(docx_bytes(document), "合并单元格.docx")

    assert text == "场一\n林简\t第一句\n\t第二句\n林简\t第三句"
    assert text.count("场一") == 1
    assert text.count("林简") == 2


def test_docx_nested_tables_follow_cell_paragraph_order():
    document = Document()
    document.add_paragraph("开场")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "旁白"
    cell = table.cell(0, 1)
    cell.text = "表前"
    nested = cell.add_table(rows=1, cols=2)
    nested.cell(0, 0).text = "动作"
    nested.cell(0, 1).text = "开门"
    cell.add_paragraph("表后")
    document.add_paragraph("结束")

    assert extract_text(docx_bytes(document), "嵌套.docx") == "开场\n旁白\t表前\n动作\t开门\n表后\n结束"


def test_docx_paragraph_only_keeps_existing_whitespace_and_empty_paragraph_rules():
    document = Document()
    document.add_paragraph("  第一段  ")
    document.add_paragraph("")
    document.add_paragraph("  ")
    document.add_paragraph("第二段\n换行")

    assert extract_text(docx_bytes(document), "纯段落.docx") == "  第一段  \n第二段\n换行"


def test_docx_table_only_is_valid_nonempty_script(db):
    document = Document()
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "林简"
    table.cell(0, 1).text = "只有表格的对白，也应当保存。"
    project = create_project(db, owner_id="docx-test", name="仅表格剧本")

    script = import_script_version(db, project=project, filename="仅表格.docx", content=docx_bytes(document))

    assert script.content["script_text"] == "林简\t只有表格的对白，也应当保存。"
