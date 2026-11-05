r"""模块 2：剧本解析（script agent）—— 小说章节 -> 结构化剧本。

与模块 1 的分工：

    模块 1  验证"配置 + 模型连接 + JSON 提取"这一层能不能用（纯技术通路）。
    模块 2  验证"业务编排 + 字段契约 + 失败修复"这一层能不能用（业务通路）。

模块边界（本文件覆盖的代码，按调用顺序）：

    1. app/modules/story/application/use_cases.py::generate_script     从章节取文本 -> 调智能体 -> 写 Script/StoryEvent
    2. app/modules/story/infrastructure/agents/script.py::ScriptAgent             变量组装（chapters/source_excerpt）与 postprocess 兜底
    3. app/modules/ai_runtime/base.py::StructuredLLMAgent.invoke  结构化调用：schema 校验 -> 修复重试 -> 兜底模型
    4. app/modules/ai_runtime/application/execution.py::run_agent        执行外壳：AgentRun / ModelCallLog / 预算 / 评估
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
    3 agent config      YAML/.env 的有效配置、HTTP 超时、重试/修复策略与提示词
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

最后一行只在内存里覆盖 max_output_tokens / 超时并更新有效配置指纹，不改 YAML。
不同供应商的吞吐不同，因此不使用历史本机 token/s 估计当前模型的必然耗时。
默认命令自动读取当前 YAML 供应商及项目 .env 的凭据；检查本身的 SQLite、
存储与配置副本始终隔离在临时目录。可用 --report-json PATH 输出脱敏报告。

退出码：0 = 八组全部 PASS；1 = 有 FAIL 或必要项 SKIP。
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]

import httpx  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.models.ops import AgentRun, ModelCallLog  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.story import Script, StoryEvent  # noqa: E402
from studio_ai_runtime.base import AgentContext  # noqa: E402
from studio_ai_runtime.providers import registry as provider_registry  # noqa: E402
from studio_ai_runtime.providers.base import LLMResult  # noqa: E402
from studio_ai_runtime.registry import create_agent  # noqa: E402
from studio_platform.configuration.config_store import stable_checksum  # noqa: E402
from studio_platform.configuration.settings import Settings, load_settings  # noqa: E402
from studio_platform.execution.runtime import AppRuntime, build_runtime  # noqa: E402
from studio_platform.execution.task_runner import reset_runner  # noqa: E402
from studio_platform.persistence.session import init_engine, init_schema, reset_engine, session_scope  # noqa: E402
from studio_projects import public as projects  # noqa: E402
from studio_story import public as story_module  # noqa: E402
from studio_story.contracts import ScriptInput, ScriptOutput  # noqa: E402

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
USER_ID = "user_check"
GROUPS = (
    "1 sandbox",
    "2 ingest",
    "3 agent config",
    "4 run script",
    "5 artifacts",
    "6 evidence",
    "7 schema guard",
    "8 repair loop",
)


class Redactor:
    """捕获供应商原始错误时也替换凭据；先脱敏字符串再编码 JSON。"""

    def __init__(self) -> None:
        self.secrets: set[str] = set()

    def remember_environment(self) -> None:
        for name, value in os.environ.items():
            if any(word in name.upper() for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")) and value:
                self.secrets.add(value)

    def text(self, value: Any) -> str:
        output = str(value)
        for secret in sorted(self.secrets, key=len, reverse=True):
            output = output.replace(secret, "[REDACTED]")
        return output

    def clean(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {self.text(key): self.clean(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [self.clean(item) for item in value]
        return value


class SafeStream:
    def __init__(self, original: Any, redactor: Redactor) -> None:
        self.original, self.redactor = original, redactor

    def write(self, text: str) -> int:
        self.original.write(self.redactor.text(text))
        return len(text)

    def flush(self) -> None:
        self.original.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.original, name)


@contextlib.contextmanager
def no_network():
    """offline及schema/stub机制检查不应触达真实接口或备用供应商。"""

    async def deny_async(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("模块2本地机制检查禁止 HTTP 请求")

    def deny_sync(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("模块2本地机制检查禁止 HTTP 请求")

    with patch.object(httpx.AsyncClient, "send", deny_async), patch.object(httpx.Client, "send", deny_sync):
        yield


@dataclass
class Report:
    rows: list[tuple[str, str, str]] = field(default_factory=list)
    redactor: Redactor = field(default_factory=Redactor)
    mode: str = "live"
    effective_config: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    sandbox_path: str | None = None
    sandbox_removed: bool = False
    paths: dict[str, str] = field(default_factory=dict)

    def add(self, name: str, status: str, detail: str = "") -> None:
        detail = self.redactor.text(detail)
        self.rows[:] = [row for row in self.rows if row[0] != name]
        self.rows.append((name, status, detail))
        print(f"[{status}] {name:<30s} {detail}", flush=True)

    @property
    def failed(self) -> list[tuple[str, str, str]]:
        return [row for row in self.rows if row[1] == FAIL]

    def payload(self) -> dict[str, Any]:
        known = {row[0]: row for row in self.rows}
        for name in GROUPS:
            if name not in known:
                self.add(name, SKIP, "前置检查未完成")
        known = {row[0]: row for row in self.rows}
        rows = [{"name": name, "status": known[name][1], "detail": known[name][2]} for name in GROUPS]
        return self.redactor.clean(
            {
                "mode": self.mode,
                "success": all(row["status"] == PASS for row in rows),
                "rows": rows,
                "effective_config": self.effective_config,
                "evidence": self.evidence,
                "sandbox_path": self.sandbox_path,
                "sandbox_removed": self.sandbox_removed,
                **self.paths,
            }
        )


def require(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def effective_fingerprint(store: Any) -> str:
    config = store.agent("script")
    providers = []
    for model in (config.model, config.model.fallback):
        if model is None:
            continue
        provider = store.provider("llm", model.provider)
        providers.append(
            {
                "provider": model.provider,
                "model": model.model_id,
                "protocol": provider.protocol_name(),
                "url": provider.resolved_url(),
                "api_key_env": provider.api_key_source(),
                "timeout_seconds": provider.timeout_seconds,
                "extra": provider.extra,
            }
        )
    return stable_checksum(
        {
            "agent": config.model_dump(mode="json", exclude={"config_version", "source_path"}),
            "effective_providers": providers,
        }
    )


def use_mock(store: Any) -> None:
    config = store.agent("script")
    config.model = config.model.model_copy(
        update={
            "provider": "mock",
            "model_id": "mock-llm",
            "fallback_provider": None,
            "fallback_model_id": None,
            "provider_options": {},
        }
    )
    config.config_version = effective_fingerprint(store)


def build_sandbox(
    keep: bool, offline: bool = False, report: Report | None = None
) -> tuple[Path, Settings, AppRuntime]:
    """先固定所有写入路径，再加载会自动读取项目 .env 的 settings。

    仅传 data_dir 不足以覆盖 DATABASE_URL、STORAGE_ROOT 和配置中的相对路径。
    环境中的模型强制覆盖必须置空而非删除，避免 .env 的 setdefault 再次注入。
    """
    from studio_api.bootstrap.composition import configure_application

    configure_application()
    sandbox = Path(tempfile.mkdtemp(prefix="studio_m2_")).resolve()
    if report is not None:
        report.sandbox_path = str(sandbox)
    config_dir, data_dir, storage_root = sandbox / "config", sandbox / "data", sandbox / "storage"
    shutil.copytree(ROOT / "config", config_dir)
    os.environ.update(
        {
            "APP_ENV": "test",
            # The checker runs against an isolated config/data sandbox but reads
            # credentials from the project root .env (never copies it into sandbox).
            "APP_ENV_FILE": str(ROOT / ".env"),
            "APP_CONFIG_DIR": str(config_dir),
            "APP_DATA_DIR": str(data_dir),
            "DATABASE_URL": f"sqlite:///{(sandbox / 'studio.db').as_posix()}",
            "STORAGE_ROOT": str(storage_root),
            "STORAGE_BACKEND": "local",
            "AGENT_MODEL_PROVIDER": "",
            "AGENT_MODEL_ID": "",
        }
    )
    settings = load_settings(config_dir=config_dir, data_dir=data_dir)
    database = make_url(settings.database_url)
    require(database.drivername == "sqlite", "模块2检查只允许独立SQLite")
    db_path = Path(str(database.database)).resolve()
    require(sandbox.is_relative_to(Path(tempfile.gettempdir()).resolve()), "沙箱不在系统临时目录")
    for path in (settings.config_dir, settings.data_dir, settings.storage_root, db_path):
        require(path.is_absolute() and path.resolve().is_relative_to(sandbox), f"路径逃离沙箱：{path}")
    require(settings.storage_backend == "local", "模块2检查必须用local storage")
    init_engine(settings)
    init_schema()
    runtime = build_runtime(settings)
    if offline:
        use_mock(runtime.config_store)
    if report is not None:
        report.paths = {
            "config_dir": str(settings.config_dir),
            "data_dir": str(settings.data_dir),
            "storage": str(settings.storage_root),
            "db": str(db_path),
            "database_url": settings.database_url,
        }
    print(f"  sandbox  : {sandbox}{'' if keep else ' (removed at the end)'}")
    print(f"  database : {settings.database_url}")
    return sandbox, settings, runtime


def check_ingest(db, runtime: AppRuntime) -> tuple[object, list[dict]]:
    """第 2 步：上传内置示例小说并取章节（下游一切依赖这里的输入契约）。"""
    project = projects.create_project(
        db,
        owner_id=USER_ID,
        name="模块2-剧本解析",
        description="module 2 check",
        genre="悬疑",
    )
    document = story_module.ingest_sample(db, runtime, project=project, user_id=USER_ID)
    db.flush()
    chapters = story_module.chapter_payloads(db, project.id)
    print(f"  project  : {project.id} status={project.status}")
    print(f"  document : {document.filename} chapters={len(chapters)}")
    for item in chapters[:3]:
        print(f"    - [{item.get('index')}] {item.get('title')} ({len(item.get('content') or '')} chars)")
    return project, chapters


def check_agent_config(store, report: Report, offline: bool = False) -> bool:
    """第3步：报告真实生效的参数；重试预算与修复预算不是简单相加。"""
    try:
        config = store.agent("script")
        provider = store.provider("llm", config.model.provider)
        system_text = store.prompt_text(config.prompt.system)
        user_text = store.prompt_text(config.prompt.user_template)
    except Exception as exc:
        report.add("3 agent config", FAIL, f"{type(exc).__name__}: {exc}")
        return False

    gen = config.generation
    structured = config.structured_output
    attempts = max(1, gen.max_retries + 1)
    problems: list[str] = []
    require(config.config_version, "配置版本为空")
    report.redactor.remember_environment()
    for item in store.providers().values():
        key = item.resolved_api_key()
        if key:
            report.redactor.secrets.add(key)
    if not system_text.strip() or not user_text.strip():
        problems.append("prompt template is empty")
    try:
        require(config.enabled, "script Agent未启用")
        provider_registry.validate_generation(store, "llm", config.model, gen)
        if not offline:
            require(provider.protocol_name() == "openai_chat", "真实检查需要openai_chat供应商，不能用mock")
            require(provider.resolved_url(), "真实供应商没有url")
            require(provider.resolved_api_key(), f"缺少凭据环境变量：{provider.api_key_source()}")
    except Exception as exc:
        problems.append(f"{type(exc).__name__}: {exc}")

    candidates = []
    for model in (config.model, config.model.fallback):
        if model is None:
            continue
        try:
            item = store.provider("llm", model.provider)
            candidates.append(
                {
                    "provider": model.provider,
                    "model": model.model_id,
                    "protocol": item.protocol_name(),
                    "endpoint": item.resolved_url(),
                    "api_key_env": item.api_key_source(),
                    "has_api_key": bool(item.resolved_api_key()),
                    "http_timeout_seconds": item.timeout_seconds,
                }
            )
        except Exception as exc:
            problems.append(f"fallback配置不可用：{type(exc).__name__}: {exc}")
    report.effective_config = {
        "provider": config.model.provider,
        "model": config.model.model_id,
        "endpoint": provider.resolved_url(),
        "api_key_env": provider.api_key_source(),
        "has_api_key": bool(provider.resolved_api_key()),
        "protocol": provider.protocol_name(),
        "max_tokens": gen.max_output_tokens,
        "agent_timeout_seconds": gen.timeout_seconds,
        "provider_timeout_seconds": provider.timeout_seconds,
        "max_retries": gen.max_retries,
        "attempts_per_candidate": attempts,
        "repair_attempts_within_budget": structured.repair_attempts,
        "candidates": candidates,
        "config_version": config.config_version,
    }

    detail = (
        f"provider={config.model.provider}/{config.model.model_id} "
        f"max_tokens={gen.max_output_tokens} timeout={gen.timeout_seconds}s "
        f"http_timeout={provider.timeout_seconds}s attempts_per_candidate<={attempts} "
        f"repairs_within_budget<={structured.repair_attempts} candidates={len(candidates)}"
    )
    report.add("3 agent config", PASS if not problems else FAIL, detail)
    for item in problems:
        print(f"     error: {item}")

    print(f"  prompt: system {len(system_text)} chars, user {len(user_text)} chars")
    print("  strategy: 修复使用同一候选的已有尝试预算；fallback是后续候选，不额外虚构墙钟上限。")
    print("  timeout : HTTP使用供应商超时；agent timeout字段不是本执行器的总墙钟截止时间。")
    return not problems


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
                story_module.generate_script(db, runtime, project=project, user_id=USER_ID),
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
        print("     hint: 检查有效供应商、HTTP超时、输出字段和本次错误；不把其他模型的专有参数套到当前接口。")
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
    for index, event in enumerate(events, start=1):
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


def check_evidence(
    project_id: str, report: Report, *, run_id: str, script_id: str, runtime: AppRuntime
) -> None:
    """按本次AgentRun.id关联日志、剧本和事件，不能拿项目的另一条成功记录顶替。"""
    with session_scope() as db:
        executed = db.scalars(
            select(AgentRun).where(
                AgentRun.id == run_id, AgentRun.project_id == project_id, AgentRun.agent_id == "script"
            )
        ).one_or_none()
        require(executed is not None and executed.status == "succeeded", "本次script调用没有成功记录")
        call = db.scalars(select(ModelCallLog).where(ModelCallLog.agent_run_id == run_id)).one_or_none()
        script = db.get(Script, script_id)
        require(script is not None and script.project_id == project_id, "剧本项目归属不正确")
        require(
            call is not None and call.project_id == project_id and call.status == "succeeded",
            "模型日志未关联本次run",
        )
        require(
            call.provider == executed.model_provider and call.model_id == executed.model_id,
            "日志供应商/模型不一致",
        )
        require(executed.tokens_out > 0, "供应商缺少输出usage信息")
        require(executed.prompt_version and executed.config_version, "调用缺少prompt/config版本")
        require(
            script.model_id == executed.model_id and script.config_version == executed.config_version,
            "剧本生成出处与调用记录不一致",
        )
        require(script.content == executed.output, "调用输出与持久化剧本内容不一致")
        event_count = db.scalar(
            select(func.count()).select_from(StoryEvent).where(StoryEvent.script_id == script.id)
        )
        require(event_count == len(script.content.get("events") or []), "StoryEvent数量与剧本events不一致")
        meta = executed.meta or {}
        require(meta.get("evaluation", {}).get("schema_valid"), "调用缺少结构化评估")
        if report.mode == "live":
            actual = runtime.config_store.provider("llm", executed.model_provider)
            require(actual.protocol_name() != "mock", "真实模式实际使用mock fallback，不能算真实通过")
            require(meta.get("provider_meta", {}).get("offline") is not True, "真实结果带offline标记")
        report.evidence = {
            "agent_run_id": executed.id,
            "script_id": script.id,
            "project_id": project_id,
            "provider": executed.model_provider,
            "model": executed.model_id,
            "tokens_in": executed.tokens_in,
            "tokens_out": executed.tokens_out,
            "latency_ms": executed.latency_ms,
            "attempts": executed.attempts,
            "cost_estimate_usd": executed.cost_usd,
            "prompt_version": executed.prompt_version,
            "config_version": executed.config_version,
            "request_id": meta.get("request_id"),
            "repairs": meta.get("repairs"),
            "degraded": meta.get("degraded"),
            "events": event_count,
            "evaluation": meta.get("evaluation"),
            "cost_note": "按供应商已配置费率估算；费率缺失导致0不代表免费。",
        }
    report.add(
        "6 evidence",
        PASS,
        f"run_id={run_id} provider={report.evidence['provider']}/"
        f"{report.evidence['model']} attempts={report.evidence['attempts']} "
        f"tokens_out={report.evidence['tokens_out']} events={report.evidence['events']}",
    )


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

    detail = (
        f"attempts={result.attempts} repairs={(result.meta or {}).get('repairs')} calls={len(stub.requests)}"
    )
    report.add("8 repair loop", PASS if not problems else FAIL, detail)
    for item in problems:
        print(f"     error: {item}")


def apply_overrides(store, max_tokens: int | None, timeout: int | None) -> None:
    """仅内存覆盖预算；同步变更实际HTTP超时和审计所用有效配置指纹。"""
    config = store.agent("script")
    update: dict[str, int] = {}
    if max_tokens:
        update["max_output_tokens"] = int(max_tokens)
    if timeout:
        update["timeout_seconds"] = int(timeout)
    config.generation = config.generation.model_copy(update=update)
    if timeout:
        store.provider("llm", config.model.provider).timeout_seconds = int(timeout)
        if config.model.fallback:
            store.provider("llm", config.model.fallback.provider).timeout_seconds = int(timeout)
    config.config_version = effective_fingerprint(store)
    if update:
        print(
            f"  override : generation{update} provider_timeout={timeout or '-'} "
            f"config_version={config.config_version} (in-memory only)"
        )


def run(
    offline: bool = False,
    keep: bool = False,
    verbose: bool = False,
    max_tokens: int | None = None,
    timeout: int | None = None,
    report_json: Path | str | None = None,
) -> int:
    saved_env = dict(os.environ)
    report = Report(mode="offline" if offline else "live")
    report.redactor.remember_environment()
    sandbox, runtime, local_runtime = None, None, None
    with (
        contextlib.redirect_stdout(SafeStream(sys.stdout, report.redactor)),
        contextlib.redirect_stderr(SafeStream(sys.stderr, report.redactor)),
    ):
        try:
            print(f"=== Module 2: script agent；mode={report.mode}；默认读取YAML/.env ===")
            sandbox, settings, runtime = build_sandbox(keep, offline=offline, report=report)
            report.redactor.remember_environment()
            report.add("1 sandbox", PASS, f"独立SQLite/config/data/local storage；{sandbox}")
            apply_overrides(runtime.config_store, max_tokens, timeout)
            ready = check_agent_config(runtime.config_store, report, offline=offline)
            with no_network(), session_scope() as db:
                project, chapters = check_ingest(db, runtime)
                project_id = project.id
                report.add(
                    "2 ingest", PASS if chapters else FAIL, f"project={project_id} chapters={len(chapters)}"
                )
            script_id, agent_run_id = None, None
            if ready and chapters:
                context = no_network() if offline else contextlib.nullcontext()
                with context, session_scope() as db:
                    project = db.get(Project, project_id)
                    script = check_run(db, runtime, project, report, offline=offline)
                    if script is not None:
                        script_id = script.id
                        check_artifacts(script, report)
                        actual = db.scalars(
                            select(AgentRun).where(
                                AgentRun.project_id == project_id, AgentRun.agent_id == "script"
                            )
                        ).one()
                        agent_run_id = actual.id
            else:
                report.add("4 run script", SKIP, "配置或章节前置条件未通过，未发送模型请求")
            if not script_id:
                report.add("5 artifacts", SKIP, "没有本次成功剧本")
                report.add("6 evidence", SKIP, "没有本次成功AgentRun，不能宣称真实证据通过")
            else:
                try:
                    check_evidence(
                        project_id, report, run_id=agent_run_id, script_id=script_id, runtime=runtime
                    )
                except Exception as exc:
                    report.add("6 evidence", FAIL, f"{type(exc).__name__}: {exc}")

            # 缺密钥时仍执行安全机制检查；它们采用独立mock配置，不走真实preflight。
            local_runtime = build_runtime(settings)
            use_mock(local_runtime.config_store)
            local_config = local_runtime.config_store.agent("script")
            local_config.generation = local_config.generation.model_copy(update={"max_retries": 1})
            local_config.structured_output = local_config.structured_output.model_copy(
                update={"repair_attempts": 1}
            )
            local_config.config_version = effective_fingerprint(local_runtime.config_store)
            with no_network():
                check_schema_guard(local_runtime.config_store, report)
                check_repair_loop(local_runtime.config_store, report)
            if verbose:
                print(
                    "  effective config:",
                    json.dumps(report.redactor.clean(report.effective_config), ensure_ascii=False),
                )
        except Exception as exc:
            known = {row[0] for row in report.rows}
            group = next((name for name in GROUPS if name not in known), "1 sandbox")
            report.add(group, FAIL, f"{type(exc).__name__}: {exc}")
        finally:
            try:
                for current in (local_runtime, runtime):
                    if current is not None:
                        reset_runner(current)
                reset_engine()
                if sandbox is None and report.sandbox_path:
                    sandbox = Path(report.sandbox_path)
                if sandbox is not None:
                    if not keep:
                        _cleanup(sandbox)
                    report.sandbox_removed = not sandbox.exists()
            except Exception as exc:
                report.add("1 sandbox", FAIL, f"释放/清理失败：{type(exc).__name__}: {exc}")
            finally:
                os.environ.clear()
                os.environ.update(saved_env)
        code = _summary(report)
        if report_json is not None:
            destination = Path(report_json).expanduser().absolute()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                json.dumps(report.payload(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(f"JSON报告：{destination}")
        return code


def _cleanup(path: Path) -> None:
    """只删除本脚本在系统临时目录里创建的沙箱，避免误删。"""
    resolved = path.resolve()
    require(
        resolved.is_relative_to(Path(tempfile.gettempdir()).resolve())
        and resolved.name.startswith("studio_m2_"),
        "拒绝清理不属于模块2本次运行的路径",
    )
    if resolved.is_dir():
        shutil.rmtree(resolved)


def _summary(report: Report) -> int:
    payload = report.payload()
    print("\n" + "-" * 72)
    for row in payload["rows"]:
        print(f"{row['status']:<5s} {row['name']}")
    passed = sum(row["status"] == PASS for row in payload["rows"])
    if not payload["success"]:
        print(f"RESULT: {passed}/8 passed；必要项SKIP也不算完整通过")
        return 1
    print("RESULT: 8/8 passed")
    print("NEXT  : module 3 (characters + scenes, the first review gate)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Module 2 check: script agent")
    parser.add_argument("--offline", action="store_true", help="use the mock provider (no network)")
    parser.add_argument("--keep", action="store_true", help="keep the temp sandbox directory")
    parser.add_argument("--verbose", action="store_true", help="print extra runtime details")
    parser.add_argument("--max-tokens", type=int, default=None, help="override generation.max_output_tokens")
    parser.add_argument("--timeout", type=int, default=None, help="override generation/provider timeout (s)")
    parser.add_argument(
        "--report-json", type=Path, default=None, help="write a redacted JSON report to this explicit path"
    )
    args = parser.parse_args(argv)
    if args.max_tokens is not None and args.max_tokens <= 0:
        parser.error("--max-tokens must be greater than zero")
    if args.timeout is not None and args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    return run(
        offline=args.offline,
        keep=args.keep,
        verbose=args.verbose,
        max_tokens=args.max_tokens,
        timeout=args.timeout,
        report_json=args.report_json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
