"""模块2扩展：手写/导入/版本恢复/AI润色续写的独立验收。

默认离线且禁止HTTP；--live读取既有YAML/.env，仅真实执行一次润色和一次续写。
每次模型操作最多2048输出token、一个候选、一次尝试；不修改正式配置。
复用原模块2的沙箱、脱敏和清理规则，不启动应用或进入人物/媒体工作流。
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from module2_script_agent import (  # noqa: E402
    FAIL,
    PASS,
    Redactor,
    SafeStream,
    _cleanup,
    build_sandbox,
    effective_fingerprint,
    no_network,
)
from sqlalchemy import select  # noqa: E402

from app.models.ops import AgentRun, ModelCallLog  # noqa: E402
from studio_platform.exceptions import ConflictError, NotFoundError, ValidationAppError  # noqa: E402
from studio_platform.execution.task_runner import reset_runner  # noqa: E402
from studio_platform.persistence.session import reset_engine, session_scope  # noqa: E402
from studio_projects import public as projects  # noqa: E402
from studio_story import public as story  # noqa: E402

GROUPS = (
    "sandbox",
    "manual_versions",
    "imports",
    "history_restore",
    "polish",
    "continue",
    "call_evidence",
    "project_isolation",
    "invalid_input",
    "cleanup",
)


def run(*, live: bool, keep: bool, report_json: Path | None) -> int:
    """报告只保存摘要与出处；正文和密钥不写入输出，正式数据不参与检查。"""
    saved_environment = os.environ.copy()
    redactor = Redactor()
    redactor.remember_environment()
    rows: dict[str, dict] = {}
    sandbox = None
    runtime = None
    evidence = {}

    def passed(name: str, **detail) -> None:
        rows[name] = {"status": PASS, **detail}
        print(f"[PASS] {name}: {json.dumps(redactor.clean(detail), ensure_ascii=False)}", flush=True)

    with (
        contextlib.redirect_stdout(SafeStream(sys.stdout, redactor)),
        contextlib.redirect_stderr(SafeStream(sys.stderr, redactor)),
    ):
        try:
            sandbox, _, runtime = build_sandbox(keep=keep, offline=not live)
            redactor.remember_environment()
            config = runtime.config_store.agent("script")
            provider = runtime.config_store.provider("llm", config.model.provider)
            if live and provider.protocol_name() == "mock":
                raise AssertionError("真实检查不能使用mock供应商")
            if live and not provider.resolved_api_key():
                raise AssertionError("所选供应商没有密钥")
            redactor.secrets.add(provider.resolved_api_key() or "")
            redactor.secrets.discard("")
            config.generation = config.generation.model_copy(
                update={"max_output_tokens": 2048, "max_retries": 0}
            )
            config.structured_output = config.structured_output.model_copy(update={"repair_attempts": 0})
            config.model = config.model.model_copy(
                update={"fallback_provider": None, "fallback_model_id": None}
            )
            config.config_version = effective_fingerprint(runtime.config_store)
            passed(
                "sandbox",
                mode="live" if live else "offline",
                provider=config.model.provider,
                model=config.model.model_id,
            )
            with session_scope() as db:
                project = projects.create_project(db, owner_id="workspace_check", name="模块2剧本工作区")
                pid = project.id
                original = "第一场 雨夜，书店。\n林简：你终于回来了...\n苏晚把一封旧信放在柜台上。"
                first = story.create_script_version(
                    db, project=project, title="书店手稿", script_text=original
                )
                first_id = first.id
                current = story.create_script_version(
                    db,
                    project=project,
                    title="书店修订",
                    script_text=original + "\n门铃轻响。",
                    base_script_id=first.id,
                )
                try:
                    story.create_script_version(
                        db, project=project, title="过期稿", script_text="不得覆盖", base_script_id=first.id
                    )
                    raise AssertionError("过期基线未被拒绝")
                except ConflictError:
                    pass
                assert story.get_project_script(db, pid, first_id).content["script_text"] == original
                passed(
                    "manual_versions", versions=[first.version, current.version], stale_write_rejected=True
                )
                from docx import Document

                document = Document()
                document.add_paragraph(original)
                buffer = io.BytesIO()
                document.save(buffer)
                files = [
                    ("稿.txt", original.encode("utf-8-sig")),
                    ("稿.md", original.encode()),
                    (
                        "稿.json",
                        json.dumps(
                            {"title": "书店手稿", "script_text": original}, ensure_ascii=False
                        ).encode(),
                    ),
                    ("稿.docx", buffer.getvalue()),
                ]
                for filename, content in files:
                    current = story.import_script_version(
                        db, project=project, filename=filename, content=content, base_script_id=current.id
                    )
                    assert current.content["script_text"].strip() == original
                passed("imports", formats=["txt", "md", "json", "docx"], latest=current.version)
                current = story.restore_script_version(
                    db, project=project, script_id=first_id, base_script_id=current.id
                )
                assert current.content["script_text"] == original and not current.approved
                passed("history_restore", version=current.version, original_unchanged=True)
                base_for_ai = current.id
            # 每次独立事务，避免把前面的构造与模型外部等待混成一次提交。
            for operation in ("polish", "continue"):
                with session_scope() as db:
                    project = projects.get_project(db, pid, "workspace_check")
                    base = story.get_project_script(db, pid, base_for_ai)
                    before = story.script_text_of(base)
                    context = contextlib.nullcontext() if live else no_network()
                    with context:
                        current = asyncio.run(
                            story.revise_script(
                                db,
                                runtime,
                                project=project,
                                base_script_id=base.id,
                                operation=operation,
                                instruction="保留林简、苏晚与旧信情节。正文简短；润色不超过150字，续写新增不超过100字。",
                                user_id="workspace_check",
                            )
                        )
                    after = story.script_text_of(current)
                    assert after.strip()
                    if operation == "continue":
                        assert after.startswith(before + "\n\n") and len(after) > len(before)
                    base_for_ai = current.id
                    passed(
                        operation,
                        script_id=current.id,
                        version=current.version,
                        text_length=len(after),
                        original_prefix_preserved=operation == "continue",
                    )
            with session_scope() as db:
                runs = list(db.scalars(select(AgentRun).where(AgentRun.project_id == pid)))
                logs = list(db.scalars(select(ModelCallLog).where(ModelCallLog.project_id == pid)))
                assert len(runs) == len(logs) == 2
                assert all(
                    row.agent_id == "script"
                    and row.model_provider == config.model.provider
                    and row.attempts == 1
                    for row in runs
                )
                if live:
                    assert all(
                        (row.meta or {}).get("provider_meta", {}).get("offline") is not True for row in runs
                    )
                evidence = {
                    "agent_runs": len(runs),
                    "model_logs": len(logs),
                    "provider": config.model.provider,
                    "model": config.model.model_id,
                    "tokens_in": sum(row.tokens_in for row in runs),
                    "tokens_out": sum(row.tokens_out for row in runs),
                    "attempts": sum(row.attempts for row in runs),
                }
                passed("call_evidence", **evidence)
                other = projects.create_project(db, owner_id="workspace_check", name="隔离哨兵")
                try:
                    story.get_project_script(db, other.id, first_id)
                    raise AssertionError("跨项目读取未被拒绝")
                except NotFoundError:
                    pass
                passed("project_isolation", cross_project_rejected=True)
                project = projects.get_project(db, pid, "workspace_check")
                try:
                    story.import_script_version(
                        db, project=project, filename="bad.json", content=b"{", base_script_id=base_for_ai
                    )
                    raise AssertionError("损坏导入未被拒绝")
                except ValidationAppError:
                    pass
                passed("invalid_input", bad_json_rejected=True)
        except Exception as exc:
            name = next((name for name in GROUPS if name not in rows), "sandbox")
            rows[name] = {"status": FAIL, "error": redactor.text(f"{type(exc).__name__}: {exc}")}
            print(f"[FAIL] {name}: {rows[name]['error']}", flush=True)
        finally:
            try:
                if runtime is not None:
                    reset_runner(runtime)
                reset_engine()
                if sandbox is not None and not keep:
                    _cleanup(sandbox)
                passed("cleanup", removed=sandbox is not None and not sandbox.exists(), kept=keep)
            except Exception as exc:
                rows["cleanup"] = {"status": FAIL, "error": redactor.text(str(exc))}
            os.environ.clear()
            os.environ.update(saved_environment)
        success = len(rows) == len(GROUPS) and all(row["status"] == PASS for row in rows.values())
        payload = redactor.clean(
            {
                "mode": "live" if live else "offline",
                "rows": rows,
                "evidence": evidence,
                "sandbox": str(sandbox) if keep else None,
                "passed": success,
            }
        )
        if report_json is not None:
            report_json = report_json.expanduser().resolve()
            report_json.parent.mkdir(parents=True, exist_ok=True)
            report_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"RESULT: {sum(row['status'] == PASS for row in rows.values())}/{len(GROUPS)} passed")
        return 0 if success else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="按既有.env/YAML真实润色、续写各一次，可能计费")
    mode.add_argument("--offline", action="store_true", help="显式选择默认离线模式")
    parser.add_argument("--keep", action="store_true", help="保留隔离沙箱供检查")
    parser.add_argument("--report-json", type=Path, help="写入脱敏报告")
    args = parser.parse_args(argv)
    return run(live=args.live, keep=args.keep, report_json=args.report_json)


if __name__ == "__main__":
    raise SystemExit(main())
