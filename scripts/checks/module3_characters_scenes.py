r"""模块 3：人物、场景及第一道人工作业审核的独立服务层检查。

本脚本从小说章节和一个 mock 剧本开始，只执行以下业务边界：
    characters（人物提取 + 逐人描述）-> scenes（场景提取 + 逐场景描述）
    -> characters_scenes 人工审核。
四个目标 Agent 可以使用真实模型；上游 script 始终使用 mock。离线模式、
关系/版本/隔离边界和 schema 修复检查都明确标为 mock 或 stub，不冒充真实调用。

十组检查：sandbox、fixture、config、characters、scenes、
references_versions_project_isolation、evidence、schema_guard_repair、
first_gate、review_decisions。完整通过要求十组都是 PASS；FAIL 或必要项 SKIP
均返回退出码 1。缺少真实凭据也会继续完成能安全执行的本地机制检查。

沙箱包含独立的 SQLite、data、storage 和 config 副本；不启动 HTTP 服务，
不创建第二个项目服务实例，不运行 FFmpeg，不进入导演/分镜/媒体阶段。
审核通过后只完成从生产 YAML 深拷贝的三节点检查子流程，不继续完整工作流。

用法（macOS/Linux；Windows 使用 .venv\Scripts\python.exe）：
    .venv/bin/python scripts/checks/module3_characters_scenes.py --offline
    .venv/bin/python scripts/checks/module3_characters_scenes.py --keep --verbose
    .venv/bin/python scripts/checks/module3_characters_scenes.py --max-tokens 1200 --timeout 300
    .venv/bin/python scripts/checks/module3_characters_scenes.py \
        --base-url https://gateway.example/v1 --model MODEL_ID \
        --api-key-env MODULE_CHECK_API_KEY --report-json /tmp/module3-report.json

base-url/model 必须成对传入；密钥只从指定环境变量读取，没有命令行密钥参数。
自定义供应商与预算覆盖只作用于内存，保留 YAML 文件。自定义供应商没有配置
费率时 cost_usd=0 仅表示本地估算未计费，不能据此声称模型免费。
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import json
import os
import re
import shutil
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.models.character import Character, CharacterProfile, CharacterRelationship  # noqa: E402
from app.models.ops import AgentRun, ModelCallLog, Review  # noqa: E402
from app.models.production import (  # noqa: E402
    AudioTrack,
    DirectingPlan,
    EditingProject,
    Shot,
    Storyboard,
    VideoGeneration,
)
from app.models.project import Asset, Project  # noqa: E402
from app.models.scene import Scene, SceneProfile  # noqa: E402
from app.models.story import StoryEvent  # noqa: E402
from app.modules.ai_runtime.base import AgentContext  # noqa: E402
from app.modules.ai_runtime.providers import registry as provider_registry  # noqa: E402
from app.modules.ai_runtime.providers.base import LLMResult  # noqa: E402
from app.modules.ai_runtime.public import execution as agent_runner  # noqa: E402
from app.modules.ai_runtime.registry import create_agent  # noqa: E402
from app.modules.characters import public as character_module  # noqa: E402
from app.modules.platform.configuration.config_models import ModelRef, ProviderConfig  # noqa: E402
from app.modules.platform.configuration.config_store import stable_checksum  # noqa: E402
from app.modules.platform.configuration.settings import load_settings  # noqa: E402
from app.modules.platform.exceptions import (  # noqa: E402
    AgentSchemaError,
    ConflictError,
    PermissionDeniedError,
    ValidationAppError,
    WorkflowError,
)
from app.modules.platform.execution.runtime import build_runtime  # noqa: E402
from app.modules.platform.execution.task_runner import reset_runner  # noqa: E402
from app.modules.platform.persistence.session import init_engine, init_schema, reset_engine, session_scope  # noqa: E402
from app.modules.projects import public as projects  # noqa: E402
from app.modules.reviews import public as reviews  # noqa: E402
from app.modules.scenes import public as scene_module  # noqa: E402
from app.modules.story import public as story_module  # noqa: E402
from app.modules.workflow.public import HandlerContext, WorkflowEngine, get_run, require_handler  # noqa: E402
from app.schemas.character import (  # noqa: E402
    CharacterDescriptionInput,
    CharacterExtractionInput,
    CharacterExtractionOutput,
    CharacterProfileOutput,
)
from app.schemas.scene import (  # noqa: E402
    SceneDescriptionInput,
    SceneExtractionInput,
    SceneExtractionOutput,
    SceneProfileOutput,
)

TARGETS = ("character_extraction", "character_description", "scene_extraction", "scene_description")
GROUPS = (
    "sandbox",
    "fixture",
    "config",
    "characters",
    "scenes",
    "references_versions_project_isolation",
    "evidence",
    "schema_guard_repair",
    "first_gate",
    "review_decisions",
)
PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
USER_ID = "module3_check"


def require(condition: Any, message: str) -> None:
    """业务断言使用明确异常，避免 python -O 删除 assert 后误报通过。"""
    if not condition:
        raise AssertionError(message)


class Redactor:
    """任何错误可能带供应商原始响应；输出前替换已知密钥，不写入报告。"""

    def __init__(self) -> None:
        self.secrets: set[str] = set()

    def add(self, value: str | None) -> None:
        if value:
            self.secrets.add(str(value))

    def text(self, value: Any) -> str:
        result = str(value)
        for secret in sorted(self.secrets, key=len, reverse=True):
            result = result.replace(secret, "[REDACTED]")
        return result

    def value(self, value: Any) -> Any:
        """先处理字符串再编码JSON，带换行/引号的密钥也不会以转义形式泄漏。"""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {self.text(key): self.value(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [self.value(item) for item in value]
        return value


class SafeStream:
    """同时覆盖生产代码日志和 traceback 的输出，报告层不依赖调用方守约。"""

    def __init__(self, stream: Any, redactor: Redactor) -> None:
        self.stream, self.redactor = stream, redactor

    def write(self, value: str) -> int:
        self.stream.write(self.redactor.text(value))
        return len(value)

    def flush(self) -> None:
        self.stream.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.stream, name)


@dataclass
class Report:
    redactor: Redactor
    mode: str
    rows: dict[str, dict[str, str]] = field(default_factory=dict)
    effective_config: dict[str, Any] = field(default_factory=dict)
    counts: dict[str, Any] = field(
        default_factory=lambda: {
            "primary": {
                "characters": 0,
                "scenes": 0,
                "expected_module3_calls": 0,
                "module3_agent_runs": 0,
                "other_agent_runs": 0,
            },
            "agents": {},
            "downstream_calls": 0,
        }
    )
    mechanisms: dict[str, Any] = field(default_factory=dict)
    sandbox_path: str | None = None
    paths: dict[str, str] = field(default_factory=dict)
    sandbox_removed: bool = False

    def add(self, name: str, status: str, detail: Any) -> None:
        require(name in GROUPS, f"未知检查组：{name}")
        clean = self.redactor.text(detail)
        self.rows[name] = {"name": name, "status": status, "detail": clean}
        print(f"[{status}] {name}: {clean}", flush=True)

    def attempt(self, name: str, callback: Any) -> Any:
        try:
            return callback()
        except Exception as exc:
            self.add(name, FAIL, f"{type(exc).__name__}: {exc}")
            return None

    def payload(self) -> dict[str, Any]:
        for name in GROUPS:
            if name not in self.rows:
                self.add(name, SKIP, "前置步骤未完成")
        rows = [self.rows[name] for name in GROUPS]
        return self.redactor.value(
            {
                "mode": self.mode,
                "upstream_script": "mock_fixture",
                "success": all(row["status"] == PASS for row in rows),
                "rows": rows,
                "effective_config": self.effective_config,
                "counts": self.counts,
                "mechanisms": self.mechanisms,
                "sandbox_path": self.sandbox_path,
                "sandbox_removed": self.sandbox_removed,
                **self.paths,
                "cost_note": "自定义供应商未配置费率时 cost_usd=0 表示未计入估算，不表示免费。",
            }
        )


@contextlib.contextmanager
def no_network():
    """本地机制检查连 HTTP 客户端都不允许发送，防止 fallback 触达真实供应商。"""

    async def deny_async(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("本地机制检查禁止 HTTP 请求")

    def deny_sync(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("本地机制检查禁止 HTTP 请求")

    with patch.object(httpx.AsyncClient, "send", deny_async), patch.object(httpx.Client, "send", deny_sync):
        yield


def effective_version(config: Any, store: Any) -> str:
    """内存预算/供应商变化也必须反映到审计版本；指纹从不包含明文密钥。"""
    payload = config.model_dump(mode="json", exclude={"config_version", "source_path"})
    provider = store.provider("llm", config.model.provider)
    payload["effective_provider"] = {
        "protocol": provider.protocol_name(),
        "url": provider.resolved_url(),
        "api_key_env": provider.api_key_source(),
        "timeout_seconds": provider.timeout_seconds,
        "extra": provider.extra,
    }
    return stable_checksum(payload)


def use_mock(store: Any, agent_ids: tuple[str, ...] = TARGETS) -> None:
    for agent_id in agent_ids:
        config = store.agent(agent_id)
        config.model = config.model.model_copy(
            update={
                "provider": "mock",
                "model_id": "mock-llm",
                "fallback_provider": None,
                "fallback_model_id": None,
                "provider_options": {},
            }
        )
        config.config_version = effective_version(config, store)


def build_sandbox(args: argparse.Namespace, report: Report) -> tuple[Path, Any, Any]:
    """先固定路径再调用 load_settings；不能让 .env 将测试指向正式数据库。

    load_settings(data_dir=...) 本身不足以隔离 DATABASE_URL/STORAGE_ROOT，
    而且函数末尾会立即建目录。因此环境覆盖必须发生在加载配置之前。
    """
    root = Path(tempfile.mkdtemp(prefix="studio_m3_")).resolve()
    report.sandbox_path = str(root)
    config_dir, data_dir, storage_root = root / "config", root / "data", root / "storage"
    shutil.copytree(ROOT / "config", config_dir)
    os.environ.update(
        {
            "APP_ENV": "test",
            "APP_CONFIG_DIR": str(config_dir),
            "APP_DATA_DIR": str(data_dir),
            "DATABASE_URL": f"sqlite:///{(root / 'studio.db').as_posix()}",
            "STORAGE_ROOT": str(storage_root),
            "STORAGE_BACKEND": "local",
        }
    )
    # 默认应忠实读取 YAML，不能继承调用 shell 的全局模型强制覆盖。
    # 必须保留空值占位：删除变量后，load_settings的.env setdefault会重新注入它。
    os.environ["AGENT_MODEL_PROVIDER"] = ""
    os.environ["AGENT_MODEL_ID"] = ""
    settings = load_settings(config_dir=config_dir, data_dir=data_dir)
    settings = dataclasses.replace(settings, storage_backend="local", inline_tasks=True, max_workers=1)
    db_path = Path(str(make_url(settings.database_url).database)).resolve()
    require(make_url(settings.database_url).drivername == "sqlite", "检查只允许 SQLite")
    for path in (root, settings.config_dir, settings.data_dir, settings.storage_root, db_path):
        require(path.is_absolute(), f"沙箱路径必须为绝对路径：{path}")
        require(path.resolve().is_relative_to(root), f"路径逃离本次沙箱：{path}")
    require(root.is_relative_to(Path(tempfile.gettempdir()).resolve()), "沙箱不在系统临时目录")
    init_engine(settings)
    init_schema()
    runtime = build_runtime(settings)
    report.paths = {
        "data_dir": str(settings.data_dir),
        "config_dir": str(settings.config_dir),
        "db": str(db_path),
        "database_url": settings.database_url,
        "storage": str(settings.storage_root),
    }
    report.add("sandbox", PASS, f"独立 SQLite/local storage/config；{root}")
    return root, settings, runtime


def configure_targets(runtime: Any, args: argparse.Namespace, report: Report) -> bool:
    store = runtime.config_store
    # 收集原始 YAML 供应商的凭据，仅用于输出脱敏；从不打印凭据本身。
    for provider in store.providers().values():
        report.redactor.add(provider.resolved_api_key())
    report.redactor.add(os.getenv(args.api_key_env))
    if args.offline:
        use_mock(store)
    elif args.base_url:
        store._providers.setdefault("llm", {})["module_check"] = ProviderConfig(
            name="module_check",
            capability="llm",
            enabled=True,
            protocol="openai_chat",
            url=args.base_url.rstrip("/"),
            api_key=f"env:{args.api_key_env}",
            models=[args.model],
            timeout_seconds=args.timeout or 120,
            max_concurrency=1,
            # 不继承 Qwen 的 reasoning_effort / chat_template_kwargs 等专有字段。
            # 此通用接口沿用 Agent 的 temperature/top_p/seed/max_tokens。
            extra={},
        )
        for agent_id in TARGETS:
            config = store.agent(agent_id)
            config.model = ModelRef(
                provider="module_check",
                model_id=args.model,
                capability=config.model.capability,
                fallback_provider=None,
                fallback_model_id=None,
                provider_options={},
            )
    problems = []
    for agent_id in TARGETS:
        config = store.agent(agent_id)
        provider = store.provider("llm", config.model.provider)
        changes = {}
        if args.max_tokens is not None:
            changes["max_output_tokens"] = args.max_tokens
        if args.timeout is not None:
            changes["timeout_seconds"] = args.timeout
            provider.timeout_seconds = args.timeout
        if changes:
            config.generation = config.generation.model_copy(update=changes)
        config.config_version = effective_version(config, store)
        report.effective_config[agent_id] = {
            "provider": config.model.provider,
            "protocol": provider.protocol_name(),
            "endpoint": provider.resolved_url(),
            "model": config.model.model_id,
            "api_key_env": provider.api_key_source(),
            "max_tokens": config.generation.max_output_tokens,
            "timeout": config.generation.timeout_seconds,
            "provider_timeout": provider.timeout_seconds,
            "max_retries": config.generation.max_retries,
            "repair_attempts": config.structured_output.repair_attempts,
            "fallback_provider": config.model.fallback_provider,
            "fallback_model": config.model.fallback_model_id,
            "provider_options": config.model.provider_options,
            "config_version": config.config_version,
        }
        try:
            require(config.enabled, f"{agent_id} 未启用")
            require(store.prompt_text(config.prompt.system).strip(), f"{agent_id} system prompt为空")
            require(store.prompt_text(config.prompt.user_template).strip(), f"{agent_id} user prompt为空")
            provider_registry.validate_generation(store, "llm", config.model, config.generation)
            if not args.offline:
                require(provider.protocol_name() != "mock", f"{agent_id} 真实模式不能使用 mock")
                require(provider.resolved_url(), f"{agent_id} 没有 endpoint")
        except Exception as exc:
            problems.append(f"{agent_id}: {type(exc).__name__}: {exc}")
        print(
            f"  effective {agent_id}: provider={config.model.provider} model={config.model.model_id} "
            f"max_tokens={config.generation.max_output_tokens} "
            f"timeout={config.generation.timeout_seconds}s provider_timeout={provider.timeout_seconds}s "
            f"version={config.config_version}",
            flush=True,
        )
    report.add(
        "config",
        FAIL if problems else PASS,
        "；".join(problems) if problems else f"四个目标 Agent 配置可用；mode={report.mode}；未改 YAML",
    )
    return not problems


async def heartbeat(coro: Any, label: str) -> Any:
    task = asyncio.ensure_future(coro)
    started = time.perf_counter()
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=10.0)
            if done:
                return task.result()
            print(f"  ... {label} 仍在执行，已等待 {time.perf_counter() - started:.0f}s", flush=True)
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


def fixture(runtime: Any, label: str, owner_id: str = USER_ID) -> str:
    """用户选择 mock 上游：只临时替换 script 配置，四个目标配置保持原样。"""
    store = runtime.config_store
    old = store._agents["script"]
    store._agents["script"] = old.model_copy(deep=True)
    use_mock(store, ("script",))
    try:
        with no_network(), session_scope() as db:
            project = projects.create_project(db, owner_id=owner_id, name=label, genre="悬疑")
            story_module.ingest_sample(db, runtime, project=project, user_id=owner_id)
            script = asyncio.run(story_module.generate_script(db, runtime, project=project, user_id=owner_id))
            require(story_module.chapter_payloads(db, project.id), "没有小说章节")
            require(script.content.get("events"), "mock 剧本没有 events")
            require(
                db.scalar(
                    select(func.count()).select_from(StoryEvent).where(StoryEvent.project_id == project.id)
                )
                > 0,
                "StoryEvent 未落库",
            )
            require(script.model_id == "mock-llm", "上游 script 并非 mock")
            return project.id
    finally:
        store._agents["script"] = old


def install_check_workflow(runtime: Any) -> Any:
    """仅复制生产定义的两个人物/场景 handler 和首 gate，禁止附加后续节点。"""
    store = runtime.config_store
    original = store.workflow(store.default_workflow_id())
    first_gate = next((node for node in original.nodes if node.type == "gate"), None)
    require(first_gate is not None and first_gate.review_stage == "characters_scenes", "首 gate 定义变化")
    required = []
    for name in ("characters", "scenes"):
        node = next((item for item in original.nodes if item.handler == name), None)
        require(node is not None, f"生产 YAML 缺少 {name} handler")
        required.append(node.model_copy(deep=True))
    config = original.model_copy(deep=True)
    config.id = "module3_check_only"
    config.name = "模块3检查子流程（不含导演与媒体）"
    config.nodes = [*required, first_gate.model_copy(deep=True)]
    config.config_version = stable_checksum(config.model_dump(mode="json", exclude={"config_version"}))
    store._workflows[config.id] = config
    return config


def count_rows(db: Any, model: Any, project_id: str) -> int:
    return int(db.scalar(select(func.count()).select_from(model).where(model.project_id == project_id)) or 0)


def usage_summary(runs: list[Any]) -> dict[str, Any]:
    """只汇总已记录的执行证据；时延为调用时延之和，不当作端到端墙钟时间。"""
    return {
        "tokens_in": sum(row.tokens_in or 0 for row in runs),
        "tokens_out": sum(row.tokens_out or 0 for row in runs),
        "agent_latency_ms": round(sum(row.latency_ms or 0.0 for row in runs), 3),
        "cost_estimate_usd": round(sum(row.cost_usd or 0.0 for row in runs), 6),
        "providers": sorted({row.model_provider for row in runs}),
        "models": sorted({row.model_id for row in runs}),
        "provider_models": [
            {"provider": provider, "model": model}
            for provider, model in sorted({(row.model_provider, row.model_id) for row in runs})
        ],
    }


def assert_characters(db: Any, project: Any) -> tuple[int, int]:
    characters = character_module.list_characters(db, project.id)
    require(characters, "人物列表为空")
    require(len({item.name.strip() for item in characters}) == len(characters), "人物名称去空白后不唯一")
    ids = {item.id for item in characters}
    for character in characters:
        profile = character_module.profile_of(db, character)
        require(character.project_id == project.id and character.name.strip(), "人物项目/姓名不正确")
        require(profile is not None, f"人物 {character.name} 没有 canonical profile")
        require(
            profile.character_id == character.id and profile.project_id == project.id, "人物档案引用跨项目"
        )
        require(
            profile.version >= 1 and profile.content.get("name") == character.name, "人物档案版本/名称不一致"
        )
        latest = db.scalar(
            select(func.max(CharacterProfile.version)).where(CharacterProfile.character_id == character.id)
        )
        require(profile.version == latest, "canonical人物档案不是最新版本")
        require(
            profile.model_id and profile.prompt_version and profile.config_version, "人物档案缺少生成出处"
        )
        require(
            character.appearance_keywords == profile.content.get("visual_keywords", []), "视觉关键词未同步"
        )
    relations = list(
        db.scalars(select(CharacterRelationship).where(CharacterRelationship.project_id == project.id))
    )
    for relation in relations:
        require(
            relation.source_character_id in ids and relation.target_character_id in ids,
            "人物关系存在悬空/跨项目端点",
        )
        require(relation.source_character_id != relation.target_character_id, "不应保存自身关系")
    return len(characters), len(relations)


def assert_scenes(db: Any, project: Any) -> int:
    scenes = scene_module.list_scenes(db, project.id)
    require(scenes, "场景列表为空")
    require(len({item.name.strip() for item in scenes}) == len(scenes), "场景名称去空白后不唯一")
    chapter_indexes = {item["index"] for item in story_module.chapter_payloads(db, project.id)}
    for scene in scenes:
        profile = scene_module.scene_profile_of(db, scene)
        require(scene.project_id == project.id and scene.name.strip(), "场景项目/姓名不正确")
        require(profile is not None, f"场景 {scene.name} 没有 canonical profile")
        require(profile.scene_id == scene.id and profile.project_id == project.id, "场景档案引用跨项目")
        require(profile.version >= 1, "场景档案版本不正确")
        require(profile.content.get("name") == scene.name, "场景描述的名称与实体身份不一致")
        latest = db.scalar(select(func.max(SceneProfile.version)).where(SceneProfile.scene_id == scene.id))
        require(profile.version == latest, "canonical场景档案不是最新版本")
        require(
            scene.chapter_index is None or scene.chapter_index in chapter_indexes,
            "场景chapter_index不属于本项目实际章节",
        )
        require(
            profile.content.get("description") and profile.content.get("visual_prompt"),
            "场景缺少描述/视觉提示词",
        )
        require(
            profile.model_id and profile.prompt_version and profile.config_version, "场景档案缺少生成出处"
        )
    return len(scenes)


def assert_no_downstream(db: Any) -> None:
    for model in (DirectingPlan, Storyboard, Shot, VideoGeneration, AudioTrack, EditingProject):
        require(not db.scalar(select(func.count()).select_from(model)), f"越界生成了 {model.__name__}")
    require(
        not db.scalar(select(func.count()).select_from(Asset).where(Asset.kind != "source_document")),
        "模块3不应生成图片、视频、语音或成片资产",
    )


def run_primary(runtime: Any, project_id: str, report: Report) -> str | None:
    """使用真实 handler 执行一次三节点子流程；第4/5组不重复真实模型调用。"""
    definition = install_check_workflow(runtime)

    async def scenario() -> str:
        with session_scope() as db:
            project = db.get(Project, project_id)
            engine = WorkflowEngine(runtime)
            for handler_name, group, checker in (
                ("characters", "characters", assert_characters),
                ("scenes", "scenes", assert_scenes),
            ):
                original = engine.handlers[handler_name]

                async def observed(
                    ctx: Any, original: Any = original, group: str = group, checker: Any = checker
                ) -> Any:
                    started = time.perf_counter()
                    try:
                        output = await original(ctx)
                        result = checker(ctx.db, ctx.project)
                        report.add(
                            group,
                            PASS,
                            f"mode={report.mode}；产物={result}；wall={time.perf_counter() - started:.1f}s",
                        )
                        return output
                    except Exception as exc:
                        report.add(group, FAIL, f"{type(exc).__name__}: {exc}")
                        raise

                engine.handlers[handler_name] = observed
            run = await engine.start(db, project=project, workflow_id=definition.id, user_id=USER_ID)
            assert_no_downstream(db)
            return run.id

    try:
        context = no_network() if report.mode == "offline" else contextlib.nullcontext()
        with context:
            return asyncio.run(heartbeat(scenario(), "模块3人物/场景子流程"))
    except Exception as exc:
        print(f"  主链路未完成：{type(exc).__name__}: {exc}", flush=True)
        for name in ("characters", "scenes"):
            if name not in report.rows:
                report.add(name, SKIP, "上一个业务阶段未完成")
        return None


def entity_snapshot(db: Any, project_id: str) -> dict[str, Any]:
    """比较项目隔离时保留完整业务值，不把关系重建后的随机 ID 当幂等条件。"""
    return {
        "characters": [
            (item.id, item.name, item.canonical_profile_id, item.status, item.approved_version)
            for item in character_module.list_characters(db, project_id)
        ],
        "scenes": [
            (item.id, item.name, item.canonical_profile_id, item.status, item.approved_version)
            for item in scene_module.list_scenes(db, project_id)
        ],
        "character_profiles": count_rows(db, CharacterProfile, project_id),
        "scene_profiles": count_rows(db, SceneProfile, project_id),
        "relations": sorted(
            (item.source_character_id, item.target_character_id, item.relation)
            for item in db.scalars(
                select(CharacterRelationship).where(CharacterRelationship.project_id == project_id)
            )
        ),
    }


def check_isolation(runtime: Any, report: Report) -> None:
    """使用完全独立的 mock runtime/项目，真实模型结果不参与边界断言。"""
    with no_network():
        project_a = fixture(runtime, "模块3隔离A", "module3_owner_a")
        project_b = fixture(runtime, "模块3隔离B", "module3_owner_b")

        async def scenario() -> None:
            with session_scope() as db:
                a, b = db.get(Project, project_a), db.get(Project, project_b)
                for project in (a, b):
                    for stage in ("characters", "scenes"):
                        await require_handler(stage)(
                            HandlerContext(
                                db=db,
                                runtime=runtime,
                                project=project,
                                task=None,
                                workflow_run=None,
                                node=install_check_workflow(runtime).nodes[0],
                                user_id=project.owner_id,
                            )
                        )
                    assert_characters(db, project)
                    assert_scenes(db, project)
                a_chars, b_chars = (
                    character_module.list_characters(db, a.id),
                    character_module.list_characters(db, b.id),
                )
                a_scenes, b_scenes = scene_module.list_scenes(db, a.id), scene_module.list_scenes(db, b.id)
                require({x.name for x in a_chars} == {x.name for x in b_chars}, "mock隔离夹具应有同名人物")
                require({x.id for x in a_chars}.isdisjoint(x.id for x in b_chars), "跨项目复用了人物ID")
                require({x.name for x in a_scenes} == {x.name for x in b_scenes}, "mock隔离夹具应有同名场景")
                require({x.id for x in a_scenes}.isdisjoint(x.id for x in b_scenes), "跨项目复用了场景ID")
                before_b = entity_snapshot(db, b.id)
                old_a = entity_snapshot(db, a.id)
                old_char_profiles = {x.id: x.canonical_profile_id for x in a_chars}
                old_scene_profiles = {x.id: x.canonical_profile_id for x in a_scenes}
                chars = await character_module.extract_characters(db, runtime, project=a)
                scenes = await scene_module.extract_scenes(db, runtime, project=a)
                require({x.id for x in chars} == {x.id for x in a_chars}, "重复提取新增了人物实体")
                require({x.id for x in scenes} == {x.id for x in a_scenes}, "重复提取新增了场景实体")
                require(entity_snapshot(db, b.id) == before_b, "重提取A改变了B")
                require(
                    entity_snapshot(db, a.id)["relations"] == old_a["relations"], "人物关系重建累积或丢失"
                )
                await character_module.describe_characters(db, runtime, project=a, characters=chars)
                await scene_module.describe_scenes(db, runtime, project=a, scenes=scenes)
                for item in chars:
                    old = db.get(CharacterProfile, old_char_profiles[item.id])
                    current = character_module.profile_of(db, item)
                    require(
                        old.version == 1 and current.version == 2 and old.id != current.id,
                        "人物档案版本未保留/递增",
                    )
                for item in scenes:
                    old = db.get(SceneProfile, old_scene_profiles[item.id])
                    current = scene_module.scene_profile_of(db, item)
                    require(
                        old.version == 1 and current.version == 2 and old.id != current.id,
                        "场景档案版本未保留/递增",
                    )
                require(entity_snapshot(db, b.id) == before_b, "A的新档案改变了B")
                try:
                    projects.get_project(db, a.id, b.owner_id)
                except PermissionDeniedError:
                    pass
                else:
                    raise AssertionError("B的所有者可越权访问A")
                # 无剧本时必须在调用模型之前失败，不能只检验错误字符串。
                empty = projects.create_project(db, owner_id=USER_ID, name="模块3无剧本边界")
                for action in (character_module.extract_characters, scene_module.extract_scenes):
                    try:
                        await action(db, runtime, project=empty)
                    except WorkflowError:
                        pass
                    else:
                        raise AssertionError("无剧本的提取没有被拒绝")
                require(count_rows(db, AgentRun, empty.id) == 0, "无剧本边界仍执行了模型")
                assert_no_downstream(db)

        asyncio.run(scenario())
    report.add(
        "references_versions_project_isolation",
        PASS,
        "独立mock：同名跨项目隔离、关系引用/重建、实体复用、profile 1→2、权限/无剧本边界",
    )


def check_evidence(runtime: Any, project_id: str, run_id: str | None, report: Report) -> None:
    with session_scope() as db:
        characters, scenes = count_rows(db, Character, project_id), count_rows(db, Scene, project_id)
        runs = list(db.scalars(select(AgentRun).where(AgentRun.project_id == project_id)))
        target_runs = [row for row in runs if row.agent_id in TARGETS]
        other_runs = [row for row in runs if row.agent_id not in (*TARGETS, "script")]
        expected = 2 + characters + scenes
        report.counts["primary"] = {
            "characters": characters,
            "scenes": scenes,
            "expected_module3_calls": expected,
            "module3_agent_runs": len(target_runs),
            "other_agent_runs": len(other_runs),
            "upstream_script_runs": sum(row.agent_id == "script" for row in runs),
            "model_attempts": sum(row.attempts for row in target_runs),
            **usage_summary(target_runs),
        }
        require(not other_runs, "出现模块3以外的Agent调用")
        require(run_id is not None and target_runs, "主链路未成功，不能核验成功调用证据")
        require(len(target_runs) == expected, f"预期2+人数+场景数={expected}次，实际{len(target_runs)}次")
        by_agent = Counter(row.agent_id for row in target_runs)
        require(
            by_agent
            == Counter(
                character_extraction=1,
                character_description=characters,
                scene_extraction=1,
                scene_description=scenes,
            ),
            "Agent调用分布不正确",
        )
        for row in target_runs:
            require(row.status == "succeeded" and row.workflow_run_id == run_id, "调用状态或工作流归属不正确")
            require(row.prompt_version and row.config_version and row.model_id, "调用缺少版本信息")
            call = db.scalars(select(ModelCallLog).where(ModelCallLog.agent_run_id == row.id)).one()
            require(call.project_id == project_id and call.status == "succeeded", "ModelCallLog不对应")
            require(
                call.provider == row.model_provider and call.model_id == row.model_id, "模型调用归属不一致"
            )
            require((row.meta or {}).get("evaluation", {}).get("schema_valid"), "没有结构化自动评估")
            if report.mode == "live":
                # YAML的主供应商是真实接口还不够：fallback可能偷偷换成mock。
                # 以实际执行记录和provider返回的offline标记核验每一次调用来源。
                actual = runtime.config_store.provider("llm", row.model_provider)
                require(actual.protocol_name() != "mock", f"{row.agent_id} 实际降级到mock，不能算真实通过")
                require(
                    (row.meta or {}).get("provider_meta", {}).get("offline") is not True,
                    f"{row.agent_id} 供应商标记为离线，不能算真实通过",
                )
        assert_no_downstream(db)
    report.add(
        "evidence",
        PASS,
        f"mode={report.mode}；调用数2+{characters}+{scenes}={expected}；每条均有日志/版本/评估",
    )


class StubProvider:
    """只为错误修复机制构造响应；不联网，不把它算成真实供应商验证。"""

    def __init__(self, replies: list[str]) -> None:
        self.replies, self.requests = list(replies), []

    async def generate(self, request: Any) -> LLMResult:
        self.requests.append(request)
        return LLMResult(
            text=self.replies.pop(0) if self.replies else "始终不返回 JSON",
            provider="stub",
            model_id="stub-module3",
            tokens_in=8,
            tokens_out=6,
        )


def check_schema_repair(runtime: Any, report: Report) -> None:
    cases = {
        "character_extraction": (
            CharacterExtractionInput(chapter_texts=[{"content": "林澈与许岚在旧书店交谈。"}]),
            {"characters": [{"name": "林澈", "evidence": "林澈在旧书店"}]},
            {"characters": [{}]},
        ),
        "character_description": (
            CharacterDescriptionInput(name="林澈", evidence=["林澈穿着蓝色外套"]),
            {"name": "林澈", "appearance": "蓝色外套", "source_facts": ["林澈穿着蓝色外套"]},
            {},
        ),
        "scene_extraction": (
            SceneExtractionInput(chapter_texts=[{"content": "两人走进旧书店。"}]),
            {"scenes": [{"name": "旧书店", "environment": "狭长书架"}]},
            {"scenes": [{}]},
        ),
        "scene_description": (
            SceneDescriptionInput(name="旧书店", evidence="书店里排着狭长书架"),
            {"name": "旧书店", "description": "狭长书架"},
            {"name": "旧书店"},
        ),
    }
    with no_network():
        for agent_id, (inputs, good, invalid) in cases.items():
            config = runtime.config_store.agent(agent_id)
            config.generation = config.generation.model_copy(update={"max_retries": 1})
            config.structured_output = config.structured_output.model_copy(update={"repair_attempts": 1})
            config.config_version = effective_version(config, runtime.config_store)
            agent = create_agent(agent_id, runtime.config_store)
            try:
                agent.validate_output(invalid)
            except Exception:
                pass
            else:
                raise AssertionError(f"{agent_id} 未拒绝缺少必填字段的输出")
            stub = StubProvider(["非JSON响应", json.dumps(good, ensure_ascii=False)])
            with patch.object(agent, "_provider_for", return_value=stub):
                result = asyncio.run(agent.execute(inputs, AgentContext(project_id="stub-only")))
            require(
                result.attempts == 2 and result.meta.get("repairs") == 1, f"{agent_id} 没有修复一次后成功"
            )
            require(len(stub.requests) == 2 and "校验错误" in stub.requests[1].user, "修复请求未包含错误信息")
            exhausted = StubProvider(["错误一", "错误二"])
            with patch.object(agent, "_provider_for", return_value=exhausted):
                try:
                    asyncio.run(agent.execute(inputs, AgentContext(project_id="stub-only")))
                except AgentSchemaError as exc:
                    require(exc.details.get("attempts") == 2, "耗尽后的真实尝试数不正确")
                else:
                    raise AssertionError(f"{agent_id} 额度耗尽仍报告成功")
            report.mechanisms[agent_id] = {
                "mode": "stub",
                "schema_guard": PASS,
                "repair_attempts": len(stub.requests),
                "exhaustion_attempts": len(exhausted.requests),
            }
        ctx = AgentContext(project_id="postprocess-only")
        agent = create_agent("character_extraction", runtime.config_store)
        filled = agent.postprocess(CharacterExtractionOutput(), cases["character_extraction"][0], ctx)
        require(
            filled.characters and all(item.name.strip() for item in filled.characters), "人物空输出未兜底"
        )
        agent = create_agent("scene_extraction", runtime.config_store)
        filled_scene = agent.postprocess(SceneExtractionOutput(), cases["scene_extraction"][0], ctx)
        require(len(filled_scene.scenes) == 1 and filled_scene.scenes[0].name == "主场景", "场景空输出未兜底")
        many = SceneExtractionOutput(scenes=[{"name": f"场景{i}"} for i in range(10)])
        require(
            len(agent.postprocess(many, cases["scene_extraction"][0], ctx).scenes) == 8, "场景数量上限不正确"
        )
        agent = create_agent("character_description", runtime.config_store)
        profile = agent.postprocess(
            CharacterProfileOutput(
                name="错误姓名",
                gender="invalid",
                visual_keywords=[str(i) for i in range(20)],
                source_facts=["这是一条根本不在输入证据内的伪造事实"],
                inferred_items=["推测项"],
            ),
            cases["character_description"][0],
            ctx,
        )
        require(profile.name == "林澈" and profile.gender == "unknown", "人物身份/性别后处理不正确")
        require(
            len(profile.visual_keywords) == 12 and profile.source_facts == ["林澈穿着蓝色外套"],
            "人物证据/关键词后处理不正确",
        )
        require(profile.inferred_items == ["推测项"], "事实与推断字段混合")
        agent = create_agent("scene_description", runtime.config_store)
        scene = agent.postprocess(
            SceneProfileOutput(name="", description=""), cases["scene_description"][0], ctx
        )
        require(
            scene.name == "旧书店" and scene.description and scene.visual_prompt and scene.negative_prompt,
            "场景描述/视觉提示词空值未补全",
        )
    report.add(
        "schema_guard_repair",
        PASS,
        "独立mock配置+stub：四Agent必填字段、坏→好修复、两次耗尽；人物/场景空输出和描述兜底",
    )


def check_gate(runtime: Any, project_id: str, run_id: str, report: Report, source: str) -> None:
    with session_scope() as db:
        run = get_run(db, project_id, run_id)
        definition = runtime.config_store.workflow(run.definition_id)
        review = db.get(Review, run.pending_review_id)
        require(len(definition.nodes) == 3 and definition.nodes[-1].type == "gate", "检查定义越界")
        require(run.status == "awaiting_review" and run.awaiting_stage == "characters_scenes", "未停在首gate")
        require(
            run.state.get("next_index") == 2 and run.current_node == definition.nodes[-1].id, "gate游标错误"
        )
        require(review is not None and review.status == "pending", "没有待审记录")
        require(review.workflow_run_id == run.id and review.project_id == project_id, "待审记录归属错误")
        require(review.target_id == definition.nodes[-1].id, "待审节点不正确")
        assert_no_downstream(db)
    report.add(
        "first_gate", PASS, f"{source}；三节点真实handler子流程停在人物/场景审核，next_index=2，无下游调用"
    )


def check_decisions(runtime: Any, project_id: str, run_id: str, report: Report, source: str) -> None:
    async def scenario() -> None:
        with session_scope() as db:
            project = db.get(Project, project_id)
            run = get_run(db, project_id, run_id)
            engine = WorkflowEngine(runtime)
            first_id = run.pending_review_id
            before_calls = count_rows(db, AgentRun, project_id)
            before_profiles = (
                count_rows(db, CharacterProfile, project_id),
                count_rows(db, SceneProfile, project_id),
            )
            # 没有结论时 resume 复用同一 pending；checkpoint 可以多一条等待记录。
            await engine.resume(db, run=run, project=project, user_id=USER_ID)
            require(run.pending_review_id == first_id and run.state["next_index"] == 2, "未决定时改变了gate")
            old = db.get(Review, first_id)
            reviews.decide(
                db,
                project=project,
                review=old,
                status="rejected",
                comment="需要补充证据",
                reviewer_id=USER_ID,
                decision={"reason": "fixture"},
            )
            db.commit()
            require(
                old.status == "rejected" and old.reviewer_id == USER_ID and old.reviewed_at, "拒绝结论未保存"
            )
            # reject只保存决定；显式resume才新建下一张pending，不重跑前面Agent。
            require(run.pending_review_id == first_id, "reject不应自动替换pending_review_id")
            await engine.resume(db, run=run, project=project, user_id=USER_ID)
            require(
                run.status == "awaiting_review" and run.pending_review_id != first_id, "拒绝后未打开新审核"
            )
            current = db.get(Review, run.pending_review_id)
            for status, expected_error, target in (
                ("approved", ConflictError, old),
                ("invalid", ValidationAppError, current),
            ):
                try:
                    reviews.decide(db, project=project, review=target, status=status, reviewer_id=USER_ID)
                except expected_error:
                    pass
                else:
                    raise AssertionError("重复/非法审核决定未被拒绝")
            # 历史run的approved不能解除本run的gate；仅作数据夹具，不调用_apply_approval。
            db.add(
                Review(
                    project_id=project_id,
                    workflow_run_id="historical_module3_run",
                    stage="characters_scenes",
                    status="approved",
                )
            )
            other = projects.create_project(db, owner_id=USER_ID, name="模块3审核隔离哨兵")
            db.add(
                Review(
                    project_id=other.id, workflow_run_id=run.id, stage="characters_scenes", status="approved"
                )
            )
            db.flush()
            require(
                reviews.approved_review(db, project_id, "characters_scenes", workflow_run_id=run.id) is None,
                "其他项目/历史run的审核泄漏",
            )
            chars, scenes = (
                character_module.list_characters(db, project_id),
                scene_module.list_scenes(db, project_id),
            )
            # 单个实体批准和整道人工作业审核是不同状态，前者不能推进gate。
            reviews.approve_character(db, project, chars[0])
            reviews.approve_scene(db, project, scenes[0])
            await engine.resume(db, run=run, project=project, user_id=USER_ID)
            require(
                run.status == "awaiting_review" and run.pending_review_id == current.id,
                "单实体批准错误地通过了gate",
            )
            reviews.decide(
                db,
                project=project,
                review=current,
                status="approved",
                comment="检查通过",
                reviewer_id=USER_ID,
            )
            for character in chars:
                profile = character_module.profile_of(db, character)
                require(
                    profile.approved
                    and character.approved_version == profile.version
                    and character.status == "approved",
                    "人物当前版本未批准",
                )
            for scene in scenes:
                profile = scene_module.scene_profile_of(db, scene)
                require(
                    profile.approved
                    and scene.approved_version == profile.version
                    and scene.status == "approved",
                    "场景当前版本未批准",
                )
            await engine.resume(db, run=run, project=project, user_id=USER_ID)
            require(run.status == "completed" and run.state["next_index"] == 3, "批准后未完成检查子流程")
            require(not run.pending_review_id and not run.awaiting_stage, "完成后仍带待审状态")
            require(count_rows(db, AgentRun, project_id) == before_calls, "审核恢复重跑了模型")
            require(
                (count_rows(db, CharacterProfile, project_id), count_rows(db, SceneProfile, project_id))
                == before_profiles,
                "审核恢复意外新增profile版本",
            )
            assert_no_downstream(db)

    with no_network():
        asyncio.run(scenario())
    report.add(
        "review_decisions",
        PASS,
        f"{source}；pending复用、reject/resume新审核、不重跑、审核隔离、重复/非法决定、approve后仅子流程completed",
    )


def summarize_counts(report: Report, primary_id: str | None, observed: list[str]) -> None:
    with session_scope() as db:
        counts = Counter(db.scalars(select(AgentRun.agent_id)))
        report.counts["agents"] = dict(sorted(counts.items()))
        report.counts["downstream_calls"] = sum(
            1 for agent_id in observed if agent_id not in (*TARGETS, "script")
        )
        if primary_id is not None:
            runs = list(db.scalars(select(AgentRun).where(AgentRun.project_id == primary_id)))
            characters, scenes = count_rows(db, Character, primary_id), count_rows(db, Scene, primary_id)
            report.counts["primary"].update(
                {
                    "characters": characters,
                    "scenes": scenes,
                    "expected_module3_calls": 2 + characters + scenes,
                    "module3_agent_runs": sum(row.agent_id in TARGETS for row in runs),
                    "other_agent_runs": sum(row.agent_id not in (*TARGETS, "script") for row in runs),
                    **usage_summary([row for row in runs if row.agent_id in TARGETS]),
                }
            )
        assert_no_downstream(db)


def run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    saved_env = dict(os.environ)
    redactor = Redactor()
    redactor.add(os.getenv(args.api_key_env))
    report = Report(redactor=redactor, mode="offline" if args.offline else "live")
    root = None
    runtimes = []
    observed: list[str] = []
    original_create = agent_runner.create_agent

    def guarded_create(agent_id: str, store: Any) -> Any:
        observed.append(agent_id)
        require(agent_id in (*TARGETS, "script"), f"禁止调用模块3下游Agent：{agent_id}")
        return original_create(agent_id, store)

    with (
        contextlib.redirect_stdout(SafeStream(sys.stdout, redactor)),
        contextlib.redirect_stderr(SafeStream(sys.stderr, redactor)),
        patch.object(agent_runner, "create_agent", guarded_create),
    ):
        try:
            print(f"=== 模块3：人物/场景/首个人工审核；mode={report.mode}；上游script=mock_fixture ===")
            root, settings, runtime = build_sandbox(args, report)
            runtimes.append(runtime)
            # load_settings可能读取了.env，此后刷新凭据脱敏集合。
            redactor.add(os.getenv(args.api_key_env))
            ready = configure_targets(runtime, args, report)
            primary_id = report.attempt("fixture", lambda: fixture(runtime, "模块3主要检查项目"))
            if primary_id is not None:
                report.add("fixture", PASS, f"导入示例小说+mock剧本/StoryEvent，project={primary_id}")
            primary_run_id = None
            if ready and primary_id:
                primary_run_id = run_primary(runtime, primary_id, report)
            else:
                for name in ("characters", "scenes"):
                    report.add(name, SKIP, "真实配置/上游预检未通过，未发送目标模型请求")
            # 这些边界检查始终使用独立runtime的mock配置，不能被真实凭据缺失阻断。
            local_runtime = build_runtime(settings)
            use_mock(local_runtime.config_store, (*TARGETS, "script"))
            runtimes.append(local_runtime)
            report.attempt(
                "references_versions_project_isolation", lambda: check_isolation(local_runtime, report)
            )
            if primary_run_id and primary_id:
                report.attempt(
                    "evidence", lambda: check_evidence(runtime, primary_id, primary_run_id, report)
                )
            else:
                report.add("evidence", SKIP, "主要四Agent链路未全部成功，不能宣称有完整真实证据")
            # schema组再建一份配置，重试预算调整不会影响主要调用或审核恢复。
            schema_runtime = build_runtime(settings)
            use_mock(schema_runtime.config_store)
            runtimes.append(schema_runtime)
            report.attempt("schema_guard_repair", lambda: check_schema_repair(schema_runtime, report))
            gate_runtime, gate_project, gate_run, source = (
                runtime,
                primary_id,
                primary_run_id,
                f"主要{report.mode}链路",
            )
            if not gate_run:
                # 主链路缺key/失败时，仍验证本地审核机制；该PASS不替代characters/scenes/evidence。
                gate_runtime = local_runtime
                with no_network():
                    gate_project = fixture(gate_runtime, "模块3独立mock审核项目")
                    definition = install_check_workflow(gate_runtime)

                    async def local_gate() -> str:
                        with session_scope() as db:
                            project = db.get(Project, gate_project)
                            run_row = await WorkflowEngine(gate_runtime).start(
                                db, project=project, workflow_id=definition.id, user_id=USER_ID
                            )
                            return run_row.id

                    gate_run = asyncio.run(local_gate())
                source = "独立mock机制（不替代主链路验证）"
            gate_passed = report.attempt(
                "first_gate",
                lambda: (check_gate(gate_runtime, gate_project, gate_run, report, source), True)[1],
            )
            if gate_passed:
                report.attempt(
                    "review_decisions",
                    lambda: check_decisions(gate_runtime, gate_project, gate_run, report, source),
                )
            else:
                report.add("review_decisions", SKIP, "首gate状态校验未通过")
            summarize_counts(report, primary_id, observed)
            if args.verbose:
                print("  counts:", json.dumps(report.counts, ensure_ascii=False))
                print("  mechanisms:", json.dumps(report.mechanisms, ensure_ascii=False))
        except Exception as exc:
            name = next((name for name in GROUPS if name not in report.rows), "sandbox")
            report.add(name, FAIL, f"未完成检查：{type(exc).__name__}: {exc}")
        finally:
            # 先关闭Session所用引擎与运行时，再删临时目录；不停止已有项目服务。
            for runtime in runtimes:
                reset_runner(runtime)
            reset_engine()
            if root is None and report.sandbox_path:
                root = Path(report.sandbox_path)
            if root is not None:
                if not args.keep:
                    if root.resolve().is_relative_to(
                        Path(tempfile.gettempdir()).resolve()
                    ) and root.name.startswith("studio_m3_"):
                        shutil.rmtree(root)
                report.sandbox_removed = not root.exists()
            os.environ.clear()
            os.environ.update(saved_env)
        payload = report.payload()
        print(
            f"=== {'PASS' if payload['success'] else 'FAIL'}："
            f"{sum(row['status'] == PASS for row in payload['rows'])}/10组通过；"
            f"sandbox_removed={report.sandbox_removed} ==="
        )
        if args.report_json is not None:
            # 只有显式请求的结果文件可写到沙箱之外；它不包含小说正文/模型原始响应/密钥。
            output = args.report_json.expanduser().absolute()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"  JSON报告：{output}")
    return (0 if payload["success"] else 1), payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--offline", action="store_true", help="四个目标Agent使用mock；禁止真实HTTP")
    parser.add_argument("--keep", action="store_true", help="保留本次临时沙箱用于核对数据库")
    parser.add_argument("--verbose", action="store_true", help="显示额外计数/机制明细")
    parser.add_argument("--max-tokens", type=int, help="仅在内存覆盖四个目标Agent输出token上限")
    parser.add_argument("--timeout", type=int, help="仅在内存覆盖四个目标Agent及供应商超时秒数")
    parser.add_argument("--base-url", help="OpenAI兼容Chat Completions基地址，与--model成对使用")
    parser.add_argument("--model", help="检查使用的模型ID，不写入YAML")
    parser.add_argument("--api-key-env", default="MODULE_CHECK_API_KEY", help="只读的凭据环境变量名称")
    parser.add_argument("--report-json", type=Path, help="将脱敏检查报告写到明确指定的位置")
    args = parser.parse_args(argv)
    if bool(args.base_url) != bool(args.model):
        parser.error("--base-url 与 --model 必须同时提供")
    for name in ("max_tokens", "timeout"):
        if getattr(args, name) is not None and getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} 必须大于0")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.api_key_env):
        parser.error("--api-key-env 必须是有效环境变量名称，不可直接传入密钥")
    if args.base_url:
        url = urlsplit(args.base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            parser.error("--base-url 必须是无凭据、查询参数或fragment的http/https绝对地址")
    return args


if __name__ == "__main__":
    raise SystemExit(run(parse_args())[0])
