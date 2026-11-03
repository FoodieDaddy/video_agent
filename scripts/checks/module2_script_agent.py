r"""模块 2：剧本解析（script agent）—— 小说章节 -> 结构化剧本。

与模块 1 的分工：

    模块 1  验证"配置 + 模型连接 + JSON 提取"这一层能不能用（纯技术通路）。
    模块 2  验证"业务编排 + 字段契约 + 失败修复"这一层能不能用（业务通路）。

模块边界（本文件覆盖的代码，按调用顺序）：

    1. app/services/pipeline.py::generate_script     从章节取文本 -> 调智能体 -> 写 Script/StoryEvent
    2. app/agents/script.py::ScriptAgent             变量组装（chapters/source_excerpt）与 postprocess 兜底
    3. app/agents/base.py::StructuredLLMAgent.invoke  结构化调用：schema 校验 -> 修复重试 -> 兜底模型
    4. app/services/agent_runner.py::run_agent        执行外壳：AgentRun / ModelCallLog / 预算 / 评估
    5. app/schemas/script.py                          ScriptInput / ScriptOutput 字段契约（title 必填等）
    6. config/prompts/script/*.md                     提示词模板（system + user，string.Template 占位符）
    7. config/schemas/script.schema.json              对外的 JSON Schema 文档副本

本模块【不】做的事：

    - 不启动 HTTP 服务（全部走服务层函数）
    - 不跑工作流、不审核、不生成人物/场景/视频
    - 不写仓库里的 data/studio.db（用临时目录里的独立 SQLite，跑完即删）

八项检查：

    1 sandbox           临时数据目录 + 建库建表 + runtime（不污染正式数据）
    2 ingest            内置示例小说 -> 章节（证明输入契约）
    3 agent config      script.yaml 的关键参数 + 最坏耗时估算 + 提示词模板存在
    4 run script        真实调用一次（--offline 时用 mock），记录墙钟时间
    5 artifacts         Script 行 + events/dialogues/chapters 数量与字段完整性
    6 evidence          agent_runs / model_call_logs / 自动评估（可追溯性）
    7 schema guard      输出缺字段时是否被拦下；postprocess 是否兜底 events
    8 repair loop       模型先返回垃圾、再返回合法 JSON 时，是否产生"重试 + 修复"

用法（仓库根目录）：

    .\.venv\Scripts\python.exe scripts\checks\module2_script_agent.py
    .\.venv\Scripts\python.exe scripts\checks\module2_script_agent.py --offline   # 秒级，不连模型
    .\.venv\Scripts\python.exe scripts\checks\module2_script_agent.py --keep      # 保留临时目录便于翻数据库
    .\.venv\Scripts\python.exe scripts\checks\module2_script_agent.py --verbose
    .\.venv\Scripts\python.exe scripts\checks\module2_script_agent.py --max-tokens 1200 --timeout 300

最后一行是"预算实验"：只在内存里改 max_output_tokens / 超时，不动 YAML，
用来确认链路本身是通的（本机模型 ~7-17 tok/s，8192 tokens 根本跑不完 300s）。

退出码：0 = 全部通过；1 = 有失败项。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.agents.base import AgentContext  # noqa: E402
from app.agents.registry import create_agent  # noqa: E402
from app.core.settings import Settings, load_settings  # noqa: E402
from app.db.session import init_engine, init_schema, session_scope  # noqa: E402
from app.models.ops import AgentRun, ModelCallLog  # noqa: E402
from app.providers.base import LLMResult  # noqa: E402
from app.schemas.script import ScriptInput, ScriptOutput  # noqa: E402
from app.services import documents, pipeline, projects  # noqa: E402
from app.services.runtime import AppRuntime, build_runtime  # noqa: E402

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
USER_ID = "user_check"
# 模块 1 实测：本机 qwen 约 7 token/s（64 tokens / 9s）。这里只用来做耗时预估。
DECODE_TOKENS_PER_SEC = 7.0


@dataclass
class Report:
    rows: list[tuple[str, str, str]] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str = "") -> None:
        self.rows.append((name, status, detail))
        print(f"[{status}] {name:<30s} {detail}")

    @property
    def failed(self) -> list[tuple[str, str, str]]:
        return [row for row in self.rows if row[1] == FAIL]


def build_sandbox(keep: bool) -> tuple[Path, Settings, AppRuntime]:
    """第 1 步：隔离环境。临时目录 + 独立 SQLite，绝不碰 data/studio.db。"""
    data_dir = Path(tempfile.mkdtemp(prefix="studio_m2_"))
    settings = load_settings(data_dir=data_dir)
    init_engine(settings)
    init_schema()
    runtime = build_runtime(settings)
    print(f"  data dir : {data_dir}{'' if keep else ' (removed at the end)'}")
    print(f"  database : {settings.database_url}")
    return data_dir, settings, runtime


def check_ingest(db, runtime: AppRuntime) -> tuple[object, list[dict]]:
    """第 2 步：上传内置示例小说并取章节（下游一切依赖这里的输入契约）。"""
    project = projects.create_project(
        db,
        owner_id=USER_ID,
        name="模块2-剧本解析",
        description="module 2 check",
        genre="悬疑",
    )
    document = documents.ingest_sample(db, runtime, project=project, user_id=USER_ID)
    db.flush()
    chapters = documents.chapter_payloads(db, project.id)
    print(f"  project  : {project.id} status={project.status}")
    print(f"  document : {document.filename} chapters={len(chapters)}")
    for item in chapters[:3]:
        print(f"    - [{item.get('index')}] {item.get('title')} ({len(item.get('content') or '')} chars)")
    return project, chapters


def check_agent_config(store, report: Report, offline: bool = False) -> None:
    """第 3 步：智能体配置体检——参数是否合理，最坏耗时会是多少。"""
    try:
        config = store.agent("script")
        provider = store.provider("llm", config.model.provider)
        system_text = store.prompt_text(config.prompt.system)
        user_text = store.prompt_text(config.prompt.user_template)
    except Exception as exc:
        report.add("3 agent config", FAIL, f"{type(exc).__name__}: {exc}")
        return

    gen = config.generation
    structured = config.structured_output
    attempts = gen.max_retries + 1
    worst_case = (attempts + structured.repair_attempts) * gen.timeout_seconds
    decode_guess = (gen.max_output_tokens or 0) / DECODE_TOKENS_PER_SEC

    problems: list[str] = []
    if not system_text.strip() or not user_text.strip():
        problems.append("prompt template is empty")
    if not offline:
        # 离线模式把 provider 换成了 mock，它本来就没有 api key，不必检查。
        if not provider.enabled:
            problems.append(f"provider '{provider.name}' is disabled")
        if not provider.resolved_api_key():
            problems.append(f"provider '{provider.name}' has no api key")

    detail = (
        f"provider={config.model.provider}/{config.model.model_id} "
        f"max_tokens={gen.max_output_tokens} timeout={gen.timeout_seconds}s "
        f"retries={gen.max_retries} repairs={structured.repair_attempts} "
        f"worst_case={worst_case}s"
    )
    report.add("3 agent config", PASS if not problems else FAIL, detail)
    for item in problems:
        print(f"     error: {item}")

    print(f"  prompt: system {len(system_text)} chars, user {len(user_text)} chars")
    print(f"  provider timeout: {provider.timeout_seconds}s (config/providers/llm.yaml)")
    if decode_guess > provider.timeout_seconds:
        print(
            f"  WARN decode_guess={decode_guess:.0f}s ({gen.max_output_tokens} tokens @ "
            f"{DECODE_TOKENS_PER_SEC:.0f} tok/s) exceeds provider timeout "
            f"{provider.timeout_seconds}s -> long answers get cut off"
        )
        print("       fix: lower generation.max_output_tokens (e.g. 1200) in config/agents/script.yaml")
    if worst_case > 600:
        print(f"  WARN worst_case={worst_case}s: {attempts + structured.repair_attempts} failed "
              f"attempts in a row look like a hang in the UI")


async def _await_with_heartbeat(coro, label: str, every: float = 10.0):
    """等待长调用，每 10s 打一行心跳，避免"看着像卡死"。"""
    task = asyncio.ensure_future(coro)
    started = time.perf_counter()
    while True:
        done, _ = await asyncio.wait({task}, timeout=every)
        if done:
            return task.result()
        print(f"  ... {label} still running ({time.perf_counter() - started:.0f}s)")


def check_run(db, runtime: AppRuntime, project, report: Report, offline: bool) -> object | None:
    """第 4 步：真正跑一次剧本解析。"""
    started = time.perf_counter()
    try:
        script = asyncio.run(
            _await_with_heartbeat(
                pipeline.generate_script(db, runtime, project=project, user_id=USER_ID),
                label="script agent",
            )
        )
    except Exception as exc:
        detail = f"{type(exc).__name__}: {str(exc)[:200]}"
        report.add("4 run script", FAIL, detail)
        details = getattr(exc, "details", None) or {}
        for item in (details.get("failures") or [])[:3]:
            print(f"     failure: {str(item)[:200]}")
        if details.get("attempts"):
            print(f"     attempts={details['attempts']} latency_ms={details.get('latency_ms')}")
        print("     hint: if module 1 is green, look at the budget first:")
        print("           config/providers/llm.yaml request_defaults (enable_thinking=false)")
        print("           config/agents/script.yaml max_output_tokens / timeout_seconds")
        return None

    wall = time.perf_counter() - started
    mode = "mock (offline)" if offline else "live model"
    report.add("4 run script", PASS, f"wall={wall:.1f}s mode={mode} script={script.id}")
    return script


def check_artifacts(script, report: Report) -> None:
    """第 5 步：产物是否满足下游契约（人物提取/导演都依赖 events）。"""
    content = script.content or {}
    events = content.get("events") or []
    dialogues = content.get("dialogues") or []
    summaries = content.get("chapters") or []

    problems: list[str] = []
    if not (script.title or "").strip():
        problems.append("title is empty")
    if not events:
        problems.append("events is empty -> character/scene extraction has nothing to work with")
    for index, event in enumerate(events[:20], start=1):
        if not (event.get("title") or "").strip():
            problems.append(f"event #{index} has no title")
        if not (event.get("description") or "").strip():
            problems.append(f"event #{index} has no description")
        importance = event.get("importance")
        if importance is not None and not 0.0 <= float(importance) <= 1.0:
            problems.append(f"event #{index} importance out of range: {importance}")

    detail = (
        f"v{script.version} chapters={len(summaries)} events={len(events)} "
        f"dialogues={len(dialogues)} model={script.model_id}"
    )
    report.add("5 artifacts", PASS if not problems else FAIL, detail)
    for item in problems[:6]:
        print(f"     error: {item}")

    print(f"  title    : {script.title}")
    print(f"  logline  : {(script.logline or '-')[:90]}")
    print(f"  synopsis : {(script.synopsis or '-')[:90]}")
    print(f"  tone/genre: {script.tone or '-'} / {script.genre or '-'}")
    for index, event in enumerate(events[:3], start=1):
        print(
            f"  event{index}  : ch{event.get('chapter_index')} "
            f"{event.get('title')} | importance={event.get('importance')}"
        )


def check_evidence(project_id: str, report: Report) -> None:
    """第 6 步：可追溯性——每次调用都要能在 agent_runs / model_call_logs 里查到。"""
    with session_scope() as db:
        run = db.scalars(
            select(AgentRun)
            .where(AgentRun.project_id == project_id, AgentRun.agent_id == "script")
            .order_by(AgentRun.created_at.desc())
        ).first()
        call = db.scalars(
            select(ModelCallLog)
            .where(ModelCallLog.project_id == project_id)
            .order_by(ModelCallLog.created_at.desc())
        ).first()

    problems: list[str] = []
    if run is None:
        report.add("6 evidence", FAIL, "no agent_runs row")
        return
    if run.status != "succeeded":
        problems.append(f"agent_runs.status={run.status} error={run.error[:120]}")
    if not run.tokens_out:
        problems.append("tokens_out=0 (usage missing from provider response)")
    if call is None:
        problems.append("no model_call_logs row")
    meta = run.meta or {}
    evaluation = meta.get("evaluation") or {}

    detail = (
        f"run={run.status} provider={run.model_provider}/{run.model_id} "
        f"latency={run.latency_ms:.0f}ms in={run.tokens_in} out={run.tokens_out} "
        f"attempts={run.attempts} cost=${run.cost_usd:.4f}"
    )
    report.add("6 evidence", PASS if not problems else FAIL, detail)
    for item in problems:
        print(f"     error: {item}")
    print(f"  versions : prompt={run.prompt_version} config={run.config_version}")
    print(f"  meta     : repairs={meta.get('repairs')} degraded={meta.get('degraded')} "
          f"request_id={meta.get('request_id') or '-'}")
    if evaluation:
        print(f"  evaluation: completeness={evaluation.get('completeness')} "
              f"warnings={(evaluation.get('warnings') or [])[:3]}")


def check_schema_guard(store, report: Report) -> None:
    """第 7 步：字段契约。缺必填字段必须报错；空 events 必须被 postprocess 兜底。"""
    problems: list[str] = []
    try:
        ScriptOutput.model_validate({"logline": "missing title"})
        problems.append("ScriptOutput accepted a payload without 'title'")
    except Exception:
        pass

    agent = create_agent("script", store)
    inputs = ScriptInput(
        chapters=[{"title": "第一章", "content": "他走进雨夜的书店，柜台上放着一封没有署名的信。"}],
        language="zh",
        genre="悬疑",
        title_hint="雨夜书店",
    )
    ctx = AgentContext(project_id="proj_check")
    try:
        filled = agent.postprocess(ScriptOutput(title="t"), inputs, ctx)
    except Exception as exc:
        report.add("7 schema guard", FAIL, f"postprocess raised {type(exc).__name__}")
        return
    if len(filled.chapters) != 1:
        problems.append(f"postprocess should fill 1 chapter summary, got {len(filled.chapters)}")
    if len(filled.events) != 1:
        problems.append(f"postprocess should fill 1 event, got {len(filled.events)}")
    if filled.events and not 0.0 <= filled.events[0].importance <= 1.0:
        problems.append(f"postprocess left importance out of range: {filled.events[0].importance}")

    detail = "required field rejected, postprocess filled chapters+events"
    report.add("7 schema guard", PASS if not problems else FAIL, detail)
    for item in problems:
        print(f"     error: {item}")


class _StubProvider:
    """按脚本顺序返回预设文本的假 provider，用来验证重试/修复逻辑（不联网）。"""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.requests: list[object] = []

    async def generate(self, request) -> LLMResult:
        self.requests.append(request)
        text = self.replies.pop(0) if self.replies else ""
        return LLMResult(
            text=text,
            structured=None,
            provider="stub",
            model_id="stub-model",
            tokens_in=12,
            tokens_out=8,
            meta={},
        )


def check_repair_loop(store, report: Report) -> None:
    """第 8 步：第一次返回垃圾，第二次返回合法 JSON —— 应看到 attempts=2 / repairs=1。"""
    agent = create_agent("script", store)
    stub = _StubProvider(
        [
            "抱歉，我无法按要求输出。",  # 1) 不能解析成 JSON
            '{"title": "重试成功", "logline": "L", "synopsis": "S", '
            '"genre": "悬疑", "tone": "紧张", "chapters": [], "events": [], "dialogues": []}',
        ]
    )
    agent._provider_for = lambda model_ref: stub  # type: ignore[method-assign]  # 只替换取 provider 这一步

    variables = {
        "chapters": [{"title": "第一章", "content": "雨夜里，他推开了书店的门。"}],
        "chapter_count": 1,
        "title_hint": "雨夜书店",
        "genre": "悬疑",
        "language": "zh",
        "source_excerpt": "雨夜里，他推开了书店的门。",
    }
    try:
        result = asyncio.run(
            agent.invoke(
                variables=variables,
                ctx=AgentContext(project_id="proj_check"),
                schema_name="script",
                output_model=ScriptOutput,
            )
        )
    except Exception as exc:
        report.add("8 repair loop", FAIL, f"{type(exc).__name__}: {str(exc)[:160]}")
        return

    problems: list[str] = []
    if result.attempts != 2:
        problems.append(f"expected 2 attempts, got {result.attempts}")
    if (result.meta or {}).get("repairs") != 1:
        problems.append(f"expected repairs=1, got {(result.meta or {}).get('repairs')}")
    if len(stub.requests) != 2:
        problems.append(f"expected 2 provider calls, got {len(stub.requests)}")
    elif "结构化校验" not in (stub.requests[1].user or ""):
        problems.append("second request is missing the repair instruction")
    if getattr(result.output, "title", "") != "重试成功":
        problems.append(f"unexpected output: {result.output}")

    detail = f"attempts={result.attempts} repairs={(result.meta or {}).get('repairs')} " \
             f"calls={len(stub.requests)}"
    report.add("8 repair loop", PASS if not problems else FAIL, detail)
    for item in problems:
        print(f"     error: {item}")


def apply_overrides(store, max_tokens: int | None, timeout: int | None) -> None:
    """--max-tokens / --timeout：只在内存里改预算，不写 YAML。

    用途：你的模型如果只有 ~7 tok/s，8192 的 max_output_tokens 永远跑不完 300s，
    先用 --max-tokens 1200 验证整条链路是否通，再决定要不要改配置文件。
    """
    if not max_tokens and not timeout:
        return
    config = store.agent("script")
    update: dict[str, int] = {}
    if max_tokens:
        update["max_output_tokens"] = int(max_tokens)
    if timeout:
        update["timeout_seconds"] = int(timeout)
    config.generation = config.generation.model_copy(update=update)
    if timeout:
        store.provider("llm", config.model.provider).timeout_seconds = int(timeout)
    print(f"  override : generation{update} provider_timeout={timeout or '-'} (in-memory only)")


def run(
    offline: bool = False,
    keep: bool = False,
    verbose: bool = False,
    max_tokens: int | None = None,
    timeout: int | None = None,
) -> int:
    report = Report()
    print("=== Module 2: script agent (chapters -> structured script) ===")
    forced = os.environ.get("AGENT_MODEL_PROVIDER")
    if forced and not offline:
        print(f"  WARN AGENT_MODEL_PROVIDER={forced} is set: the run will NOT reach the real model")
    if offline:
        # 必须在 load_settings 之前设置：配置在加载时就按它改写了所有智能体。
        os.environ["AGENT_MODEL_PROVIDER"] = "mock"

    data_dir, settings, runtime = build_sandbox(keep)
    report.add("1 sandbox", PASS, f"data_dir={data_dir.name}")
    apply_overrides(runtime.config_store, max_tokens, timeout)

    try:
        with session_scope() as db:
            project, chapters = check_ingest(db, runtime)
            report.add(
                "2 ingest",
                PASS if chapters else FAIL,
                f"project={project.id} chapters={len(chapters)}",
            )
            if not chapters:
                return _summary(report)

            check_agent_config(runtime.config_store, report, offline=offline)
            script = check_run(db, runtime, project, report, offline=offline)
            if script is not None:
                check_artifacts(script, report)
            project_id = project.id

        if script is not None:
            check_evidence(project_id, report)
        else:
            report.add("6 evidence", SKIP, "no successful run")

        check_schema_guard(runtime.config_store, report)
        check_repair_loop(runtime.config_store, report)
        if verbose:
            print(f"  runtime config versions: {runtime.config_store.config_versions()}")
        return _summary(report)
    finally:
        if not keep:
            _cleanup(data_dir)


def _cleanup(path: Path) -> None:
    """只删除本脚本在系统临时目录里创建的沙箱，避免误删。"""
    try:
        if path.resolve().is_dir() and str(path.resolve()).startswith(
            str(Path(tempfile.gettempdir()).resolve())
        ):
            shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


def _summary(report: Report) -> int:
    total = len(report.rows)
    failed = report.failed
    print("\n" + "-" * 72)
    for name, status, _detail in report.rows:
        print(f"{status:<5s} {name}")
    if failed:
        print(f"RESULT: {len(failed)}/{total} FAILED -> fix the failures above before module 3")
        return 1
    print(f"RESULT: {total - sum(1 for row in report.rows if row[1] == SKIP)}/{total} passed")
    print("NEXT  : module 3 (characters + scenes, the first review gate)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Module 2 check: script agent")
    parser.add_argument("--offline", action="store_true", help="use the mock provider (no network)")
    parser.add_argument("--keep", action="store_true", help="keep the temp sandbox directory")
    parser.add_argument("--verbose", action="store_true", help="print extra runtime details")
    parser.add_argument("--max-tokens", type=int, default=None, help="override generation.max_output_tokens")
    parser.add_argument("--timeout", type=int, default=None, help="override generation/provider timeout (s)")
    args = parser.parse_args(argv)
    return run(
        offline=args.offline,
        keep=args.keep,
        verbose=args.verbose,
        max_tokens=args.max_tokens,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    raise SystemExit(main())
