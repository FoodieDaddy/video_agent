"""模块4：导演规划、分镜创作与第二审核的独立服务层验收。

默认读取项目 YAML/.env，仅 director/storyboard 目标调用可以访问真实供应商；
--offline 使用 mock 并禁止 HTTP。上游是手写剧本和合成人物／场景档案夹具，
不把它们描述为真实模块2/3生成。版本、冲突及 Schema 修复使用单独 mock/stub。

复用模块2的隔离沙箱与脱敏工具：临时 SQLite/config/storage，不启动网页服务，
不写正式数据，不生成图片、视频、音频，也不调用 FFmpeg。
分镜提示词精化在检查中显式关闭，明确不算作真实prompt Agent验证。
每次主检查限制一个候选、一次尝试、无结构修复，最多4096输出token。
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import copy
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from module2_script_agent import Redactor, SafeStream, _cleanup, build_sandbox, no_network  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from studio_ai_runtime.base import AgentContext  # noqa: E402
from studio_ai_runtime.providers import registry as provider_registry  # noqa: E402
from studio_ai_runtime.providers.base import LLMResult  # noqa: E402
from studio_ai_runtime.registry import create_agent  # noqa: E402
from studio_api.bootstrap.model_catalog import (  # noqa: E402  # noqa: E402  # noqa: E402  # noqa: E402
    AgentRun,
    Asset,  # noqa: E402
    AudioTrack,
    Character,
    CharacterAsset,
    CharacterProfile,
    DirectingPlan,
    EditingProject,
    ModelCallLog,
    Review,
    Scene,
    SceneAsset,
    SceneProfile,
    Storyboard,
    VideoGeneration,
    WorkflowRun,
)
from studio_platform.configuration.config_models import ModelRef, ProviderConfig  # noqa: E402
from studio_platform.configuration.config_store import stable_checksum  # noqa: E402
from studio_platform.exceptions import (  # noqa: E402
    AgentSchemaError,
    ConflictError,
    PermissionDeniedError,
    WorkflowError,
)
from studio_platform.execution.runtime import build_runtime  # noqa: E402
from studio_platform.execution.task_runner import reset_runner  # noqa: E402
from studio_platform.persistence.session import reset_engine, session_scope  # noqa: E402
from studio_production import public as production  # noqa: E402
from studio_production.application import use_cases as production_cases  # noqa: E402
from studio_production.contracts import (  # noqa: E402
    DirectingPlanInput,  # noqa: E402
    StoryboardInput,  # noqa: E402
)
from studio_projects import public as projects  # noqa: E402
from studio_reviews import public as reviews  # noqa: E402
from studio_story import public as story  # noqa: E402
from studio_workflow import public as workflow  # noqa: E402

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
TARGETS = ("director", "storyboard")
GROUPS = (
    "sandbox",
    "config",
    "fixture",
    "directing",
    "storyboard",
    "versions_source",
    "shot_edit",
    "baseline_guard",
    "schema_guard_repair",
    "second_gate",
    "call_evidence",
    "project_isolation_no_downstream",
    "cleanup",
)
USER_ID = "module4_check"
SCRIPT_TEXT = (
    "第一场 内景·旧书店·雨夜\n林简把一封旧信放在柜台上。\n"
    "苏晚：等雨停了，我们一起把信送到。\n林简点头，将门边的灯重新点亮。\n"
    "第二场 外景·书店门口·雨后\n两人并肩走向街口，橱窗里的暖光留在身后。\n"
    "【模块4完整正文末尾标记】"
)
DOWNSTREAM = (
    VideoGeneration,
    AudioTrack,
    EditingProject,
    Asset,
    CharacterAsset,
    SceneAsset,
)


def require(condition: Any, detail: str) -> None:
    """不能使用会被 python -O 删除的 assert 作为公开验收条件。"""
    if not condition:
        raise AssertionError(detail)


@dataclass
class Report:
    mode: str
    redactor: Redactor = field(default_factory=Redactor)
    rows: dict[str, dict[str, Any]] = field(default_factory=dict)
    sandbox_path: str | None = None
    sandbox_removed: bool = False
    paths: dict[str, str] = field(default_factory=dict)
    effective_config: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    mechanisms: dict[str, Any] = field(default_factory=dict)

    def add(self, name: str, status: str, detail: str) -> None:
        self.rows[name] = {"name": name, "status": status, "detail": self.redactor.text(detail)}
        print(f"[{status}] {name}: {self.rows[name]['detail']}", flush=True)

    def payload(self) -> dict[str, Any]:
        rows = [
            self.rows.get(name, {"name": name, "status": SKIP, "detail": "前置检查未完成"}) for name in GROUPS
        ]
        return self.redactor.clean(
            {
                "mode": self.mode,
                "upstream": "saved_manual_and_synthetic_profiles",
                "targets": list(TARGETS),
                "success": all(row["status"] == PASS for row in rows),
                "rows": rows,
                "effective_config": self.effective_config,
                "evidence": self.evidence,
                "mechanisms": self.mechanisms,
                "sandbox_path": self.sandbox_path,
                "sandbox_removed": self.sandbox_removed,
                **self.paths,
            }
        )


def config_version(store: Any, agent_id: str = "director") -> str:
    """内存上限也进入审计指纹；供应商凭据仅保留引用名，不写明文。"""
    config = store.agent(agent_id)
    provider = store.provider("llm", config.model.provider)
    return stable_checksum(
        {
            "agent": config.model_dump(mode="json", exclude={"config_version", "source_path"}),
            "provider": {
                "name": config.model.provider,
                "protocol": provider.protocol_name(),
                "url": provider.resolved_url(),
                "api_key_env": provider.api_key_source(),
                "timeout": provider.timeout_seconds,
            },
        }
    )


def mock_targets(runtime: Any, *, repair: bool = False) -> None:
    for agent_id in TARGETS:
        config = runtime.config_store.agent(agent_id)
        config.model = config.model.model_copy(
            update={
                "provider": "mock",
                "model_id": "mock-llm",
                "fallback_provider": None,
                "fallback_model_id": None,
                "provider_options": {},
            }
        )
        config.generation = config.generation.model_copy(update={"max_retries": 1 if repair else 0})
        config.structured_output = config.structured_output.model_copy(
            update={"repair_attempts": 1 if repair else 0}
        )
        config.config_version = config_version(runtime.config_store, agent_id)


def configure(runtime: Any, args: argparse.Namespace, report: Report) -> bool:
    store = runtime.config_store
    for provider in store.providers().values():
        report.redactor.secrets.add(provider.resolved_api_key() or "")
    report.redactor.secrets.discard("")
    if args.offline:
        mock_targets(runtime)
    elif args.base_url:
        store._providers.setdefault("llm", {})["module4_check"] = ProviderConfig(
            name="module4_check",
            capability="llm",
            enabled=True,
            protocol="openai_chat",
            url=args.base_url.rstrip("/"),
            api_key=f"env:{args.api_key_env}",
            models=[args.model],
            timeout_seconds=args.timeout,
            max_concurrency=1,
            extra={},
        )
        for agent_id in TARGETS:
            config = store.agent(agent_id)
            config.model = ModelRef(
                provider="module4_check", model_id=args.model, capability=config.model.capability
            )
    problems = []
    for agent_id in TARGETS:
        config = store.agent(agent_id)
        config.model = config.model.model_copy(update={"fallback_provider": None, "fallback_model_id": None})
        config.generation = config.generation.model_copy(
            update={
                "max_output_tokens": args.max_tokens,
                "max_retries": 0,
                "timeout_seconds": args.timeout,
            }
        )
        config.structured_output = config.structured_output.model_copy(update={"repair_attempts": 0})
        provider = store.provider("llm", config.model.provider)
        provider.timeout_seconds = args.timeout
        report.redactor.secrets.add(provider.resolved_api_key() or "")
        report.redactor.secrets.discard("")
        config.config_version = config_version(store, agent_id)
        report.effective_config[agent_id] = {
            "provider": config.model.provider,
            "model": config.model.model_id,
            "protocol": provider.protocol_name(),
            "api_key_env": provider.api_key_source(),
            "has_api_key": bool(provider.resolved_api_key()),
            "max_tokens": args.max_tokens,
            "timeout": args.timeout,
            "max_retries": 0,
            "repair_attempts": 0,
            "fallback_provider": None,
            "config_version": config.config_version,
        }
        try:
            require(config.enabled, f"{agent_id} 未启用")
            require(store.prompt_text(config.prompt.system).strip(), f"{agent_id} system prompt 为空")
            require(store.prompt_text(config.prompt.user_template).strip(), f"{agent_id} user prompt 为空")
            provider_registry.validate_generation(store, "llm", config.model, config.generation)
            if not args.offline:
                require(provider.protocol_name() != "mock", "真实检查不能采用 mock Provider")
                require(provider.resolved_url(), "真实 Provider 没有接口地址")
        except Exception as exc:
            problems.append(f"{agent_id}: {type(exc).__name__}: {exc}")
    report.add(
        "config",
        FAIL if problems else PASS,
        "；".join(problems)
        if problems
        else f"director/storyboard 使用既有 YAML/.env；{json.dumps(report.effective_config)}",
    )
    return not problems


def fixture(runtime: Any, *, label: str, profiles: bool = True) -> tuple[str, str]:
    """合成上游只用于导演输入，不调用 script、人物或场景 Agent。"""
    with session_scope() as db:
        project = projects.create_project(db, owner_id=USER_ID, name=label)
        script = story.create_script_version(db, project=project, title="雨后旧书店", script_text=SCRIPT_TEXT)
        if profiles:
            for name in ("林简", "苏晚"):
                character = Character(
                    project_id=project.id, name=name, source="manual", summary="合成夹具人物"
                )
                db.add(character)
                db.flush()
                profile = CharacterProfile(
                    project_id=project.id,
                    character_id=character.id,
                    source="manual",
                    approved=True,
                    status="approved",
                    content={"name": name, "appearance": "朴素深色外套", "source_facts": ["两人送信"]},
                )
                db.add(profile)
                db.flush()
                character.canonical_profile_id = profile.id
                character.approved_version = 1
                character.status = "approved"
            scene = Scene(project_id=project.id, name="旧书店", summary="雨夜暖光", status="approved")
            db.add(scene)
            db.flush()
            profile = SceneProfile(
                project_id=project.id,
                scene_id=scene.id,
                approved=True,
                content={"name": "旧书店", "description": "柜台、橱窗和暖灯", "visual_prompt": "雨夜旧书店"},
            )
            db.add(profile)
            db.flush()
            scene.canonical_profile_id = profile.id
            scene.approved_version = 1
        return project.id, script.id


async def heartbeat(coro: Any) -> Any:
    task = asyncio.create_task(coro)
    start = time.monotonic()
    try:
        while not task.done():
            done, _ = await asyncio.wait({task}, timeout=10)
            if not done:
                print(f"  模块4目标调用等待中：{time.monotonic() - start:.0f}s", flush=True)
        return await task
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


def validate_plan(db: Any, plan: Any, source_id: str) -> None:
    content = plan.content or {}
    require(bool(str(content.get("visual_style", "")).strip()), "导演视觉风格为空")
    strategy = content.get("shot_strategy", {})
    shots, duration = strategy.get("total_shots"), strategy.get("avg_duration_seconds")
    require(isinstance(shots, int) and 1 <= shots <= 120, "镜头数量不合法")
    require(isinstance(duration, (int, float)) and math.isfinite(duration) and duration > 0, "时长不合法")
    source = content.get("source_script", {})
    script = story.get_project_script(db, plan.project_id, source_id)
    require(source.get("id") == source_id and source.get("version") == script.version, "来源版本不一致")
    require(source.get("fingerprint") == story.script_fingerprint(script), "来源指纹不一致")
    require(
        production.directing_source_status(db, plan)["source_status"] == "current", "新方案来源不是current"
    )
    require(not plan.approved, "生成不应自动完成分镜审核")


def shot_snapshot(db: Any, board: Any) -> list[dict[str, Any]]:
    return [
        copy.deepcopy(production.shot_payload(db, shot))
        for shot in production.list_shots(db, board.project_id, board=board)
    ]


def validate_board(db: Any, board: Any, plan_id: str, source_id: str) -> None:
    require(board.directing_plan_id == plan_id, "分镜关联了错误导演版本")
    status = production.storyboard_source_status(db, board)
    require(
        status["source_status"] == "current" and status["source_script"]["id"] == source_id,
        "分镜来源不是本次已保存稿",
    )
    shots = production.list_shots(db, board.project_id, board=board)
    require(
        shots and [shot.order_index for shot in shots] == list(range(1, len(shots) + 1)),
        "镜头为空或序号不连续",
    )
    known_characters = set(db.scalars(select(Character.id).where(Character.project_id == board.project_id)))
    known_scenes = set(db.scalars(select(Scene.id).where(Scene.project_id == board.project_id)))
    require(any(shot.scene_id for shot in shots), "镜头没有引用给定场景")
    require(any(shot.characters for shot in shots), "镜头没有引用给定人物")
    for shot in shots:
        require(shot.description.strip() and shot.visual_prompt.strip(), "镜头描述/提示词为空")
        require(math.isfinite(shot.duration_seconds) and shot.duration_seconds > 0, "镜头时长不是正有限值")
        require(not shot.scene_id or shot.scene_id in known_scenes, "分镜混入跨项目场景")
        for ref in (shot.characters or []) + (shot.dialogue or []):
            require(
                not ref.get("character_id") or ref["character_id"] in known_characters, "分镜混入跨项目人物"
            )
    require(not board.approved and all(not shot.approved for shot in shots), "生成不应自动完成第二审核")


def primary(runtime: Any, pid: str, sid: str, offline: bool, report: Report) -> None:
    saved_plan = saved_board = None
    for index in range(2):
        instruction = (
            "采用克制写实风格，严格依据原稿，不增加人物；简短回答。"
            if index == 0
            else "保留原稿，节奏更从容；简短回答。"
        )
        with session_scope() as db:
            project = projects.get_project(db, pid, USER_ID)
            with no_network() if offline else contextlib.nullcontext():
                plan = asyncio.run(
                    heartbeat(
                        production.build_directing_plan(
                            db,
                            runtime,
                            project=project,
                            base_script_id=sid,
                            instruction=instruction,
                            shots_target=3,
                            user_id=USER_ID,
                        )
                    )
                )
            validate_plan(db, plan, sid)
            require(plan.version == index + 1, "追加导演版本号不连续")
            require(
                plan.content.get("generation_request") == {"instruction": instruction, "shots_target": 3},
                "创作参数未持久化",
            )
            plan_id = plan.id
            if saved_plan is None:
                saved_plan = {"id": plan.id, "content": copy.deepcopy(plan.content)}
                report.add("directing", PASS, f"导演生成V1；source={sid}；上游为合成夹具")
            else:
                require(
                    production.get_directing_plan(db, saved_plan["id"]).content == saved_plan["content"],
                    "再次生成覆盖了旧导演方案",
                )
        with session_scope() as db:
            project = projects.get_project(db, pid, USER_ID)
            with no_network() if offline else contextlib.nullcontext():
                board = asyncio.run(
                    heartbeat(
                        production.build_storyboard(
                            db,
                            runtime,
                            project=project,
                            base_script_id=sid,
                            base_plan_id=plan_id,
                            refine_prompts=False,
                            user_id=USER_ID,
                        )
                    )
                )
            validate_board(db, board, plan_id, sid)
            require(board.version == index + 1, "追加分镜版本号不连续")
            if saved_board is None:
                saved_board = {
                    "id": board.id,
                    "plan_id": board.directing_plan_id,
                    "title": board.title,
                    "notes": board.notes,
                    "shots": shot_snapshot(db, board),
                }
                report.add(
                    "storyboard",
                    PASS,
                    f"分镜V1；shots={len(saved_board['shots'])}；关闭prompt精化，不进入媒体",
                )
            else:
                original = production.get_storyboard(db, saved_board["id"])
                require(
                    original.directing_plan_id == saved_board["plan_id"]
                    and original.title == saved_board["title"]
                    and original.notes == saved_board["notes"],
                    "历史分镜被覆盖",
                )
                require(shot_snapshot(db, original) == saved_board["shots"], "历史镜头内容被改写")
                require(
                    story.script_text_of(story.get_project_script(db, pid, sid)) == SCRIPT_TEXT,
                    "上游正文被改写",
                )
                report.add(
                    "versions_source", PASS, "导演/分镜V1、V2及旧镜头保留；正文未变；来源版本与指纹完整"
                )
    report.mechanisms["prompt_refinement"] = {"mode": "disabled", "real_prompt_calls": 0}


def edit_shot(pid: str, report: Report) -> None:
    with no_network(), session_scope() as db:
        board = production.latest_board(db, pid)
        require(board is not None, "缺少本次分镜")
        shot = production.list_shots(db, pid, board=board)[0]
        old_fingerprint = production.shot_edit_fingerprint(shot)
        production.update_shot(
            db,
            shot=shot,
            description="验收修订：柜台上的信与两人关系",
            base_storyboard_id=board.id,
            base_shot_fingerprint=old_fingerprint,
        )
        require(not shot.approved and shot.description.startswith("验收修订"), "镜头编辑未保存或错误批准")
        try:
            production.update_shot(
                db,
                shot=shot,
                description="不能覆盖",
                base_storyboard_id=board.id,
                base_shot_fingerprint=old_fingerprint,
            )
        except ConflictError:
            pass
        else:
            raise AssertionError("镜头过期编辑未被拒绝")
        old_board = db.scalar(select(Storyboard).where(Storyboard.project_id == pid, Storyboard.version == 1))
        old_shot = production.list_shots(db, pid, board=old_board)[0]
        try:
            production.update_shot(
                db, shot=old_shot, description="不得改历史", base_storyboard_id=old_board.id
            )
        except ConflictError:
            pass
        else:
            raise AssertionError("历史分镜镜头仍可写入")
    report.add("shot_edit", PASS, "手动服务调用：当前镜头可改、过期编辑409语义、历史镜头只读；不调用模型")


def baseline_guard(runtime: Any, report: Report) -> None:
    pid, sid = fixture(runtime, label="模块4本地基线机制", profiles=False)
    with no_network(), session_scope() as db:
        project = projects.get_project(db, pid, USER_ID)
        old = story.get_project_script(db, pid, sid)
        old_source = {
            "id": old.id,
            "version": old.version,
            "title": old.title,
            "fingerprint": story.script_fingerprint(old),
        }
        current = story.create_script_version(
            db, project=project, title="后续手稿", script_text=SCRIPT_TEXT + "\n修订。", base_script_id=sid
        )
        with patch.object(
            production_cases, "run_agent", side_effect=AssertionError("过期基线不应调用模型")
        ) as spy:
            try:
                asyncio.run(production.build_directing_plan(db, runtime, project=project, base_script_id=sid))
            except ConflictError:
                pass
            else:
                raise AssertionError("过期基线未被拒绝")
            require(spy.call_count == 0, "过期请求产生模型调用")
        stale = DirectingPlan(
            project_id=pid, version=1, content={"visual_style": "本地旧稿", "source_script": old_source}
        )
        legacy = DirectingPlan(project_id=pid, version=2, content={"visual_style": "没有来源的历史稿"})
        db.add_all([stale, legacy])
        db.flush()
        require(
            production.directing_source_status(db, stale)["source_status"] == "stale", "旧来源未标记stale"
        )
        require(
            production.directing_source_status(db, legacy)["source_status"] == "unknown",
            "旧计划被伪造为已知来源",
        )
        original_run = production_cases.run_agent

        async def change_during_generation(*args: Any, **kwargs: Any) -> Any:
            result = await original_run(*args, **kwargs)
            story.create_script_version(
                db,
                project=project,
                title="调用期间的新稿",
                script_text=SCRIPT_TEXT + "\n再次修订。",
                base_script_id=current.id,
            )
            return result

        with patch.object(production_cases, "run_agent", side_effect=change_during_generation):
            try:
                asyncio.run(
                    production.build_directing_plan(db, runtime, project=project, base_script_id=current.id)
                )
            except ConflictError as exc:
                require(exc.details.get("generation_completed") is True, "缺少已完成模型审计标记")
            else:
                raise AssertionError("调用期间改稿仍保存了过期导演方案")
        require(
            db.scalar(select(func.count()).select_from(DirectingPlan).where(DirectingPlan.project_id == pid))
            == 2,
            "冲突新增了导演方案",
        )
        latest = story.latest_script(db, pid)
        plan = asyncio.run(
            production.build_directing_plan(db, runtime, project=project, base_script_id=latest.id)
        )
        with patch.object(
            production_cases, "run_agent", side_effect=AssertionError("过期导演不应调用模型")
        ) as spy:
            try:
                asyncio.run(
                    production.build_storyboard(
                        db,
                        runtime,
                        project=project,
                        base_script_id=latest.id,
                        base_plan_id=stale.id,
                        refine_prompts=False,
                    )
                )
            except ConflictError:
                pass
            else:
                raise AssertionError("分镜过期导演基线未被拒绝")
            require(spy.call_count == 0, "分镜过期基线仍调用模型")

        async def change_plan_during_board(*args: Any, **kwargs: Any) -> Any:
            result = await original_run(*args, **kwargs)
            db.add(
                DirectingPlan(
                    project_id=pid,
                    version=plan.version + 1,
                    content=copy.deepcopy(plan.content),
                    agent_id="fixture_only",
                )
            )
            db.flush()
            return result

        with patch.object(production_cases, "run_agent", side_effect=change_plan_during_board):
            try:
                asyncio.run(
                    production.build_storyboard(
                        db,
                        runtime,
                        project=project,
                        base_script_id=latest.id,
                        base_plan_id=plan.id,
                        refine_prompts=False,
                    )
                )
            except ConflictError as exc:
                require(exc.details.get("generation_completed") is True, "分镜冲突缺少已完成调用标记")
            else:
                raise AssertionError("分镜生成期间导演变化仍落库")
        require(
            db.scalar(select(func.count()).select_from(Storyboard).where(Storyboard.project_id == pid)) == 0,
            "分镜冲突新增了产物",
        )
        empty = projects.create_project(db, owner_id=USER_ID, name="无剧本夹具")
        with patch.object(production_cases, "run_agent", side_effect=AssertionError("无剧本不应调用模型")):
            try:
                asyncio.run(production.build_directing_plan(db, runtime, project=empty))
            except WorkflowError:
                pass
            else:
                raise AssertionError("无剧本未拒绝")
    report.mechanisms["baseline_guard"] = {
        "mode": "mock",
        "stale_before_call": True,
        "change_during_call": True,
        "legacy_unknown": True,
        "storyboard_stale_plan_before_call": True,
        "storyboard_plan_change_during_call": True,
    }
    report.add(
        "baseline_guard",
        PASS,
        "本地mock：导演/分镜过期请求零调用，调用期间基线变化不落库，旧来源stale/unknown及无剧本拒绝",
    )


def second_gate(runtime: Any, pid: str, report: Report) -> None:
    """真实审核用例＋仅含生产第二gate的子流程，批准后也无法进入媒体节点。"""
    store = runtime.config_store
    original = store.workflow(store.default_workflow_id())
    gate = next(
        (node for node in original.nodes if node.type == "gate" and node.review_stage == "storyboard"), None
    )
    require(gate is not None, "生产工作流缺少第二审核")
    definition = original.model_copy(deep=True)
    definition.id = "module4_second_gate_only"
    definition.name = "模块4第二审核边界（不含媒体）"
    definition.nodes = [gate.model_copy(deep=True)]
    definition.config_version = stable_checksum(
        definition.model_dump(mode="json", exclude={"config_version"})
    )
    store._workflows[definition.id] = definition
    for scenario in ("reject", "stale", "approve"):
        with no_network(), session_scope() as db:
            project = projects.get_project(db, pid, USER_ID)
            board = production.latest_board(db, pid)
            plan = production.latest_plan(db, pid)
            before_calls = int(
                db.scalar(select(func.count()).select_from(AgentRun).where(AgentRun.project_id == pid)) or 0
            )
            engine = workflow.WorkflowEngine(runtime)
            run = asyncio.run(engine.start(db, project=project, workflow_id=definition.id, user_id=USER_ID))
            review = db.get(Review, run.pending_review_id)
            require(run.status == "awaiting_review" and run.awaiting_stage == "storyboard", "未停在第二审核")
            require(review is not None and review.status == "pending", "第二审核未创建pending")
            snapshot = (review.decision or {}).get("storyboard_snapshot", {})
            shots = production.list_shots(db, pid, board=board)
            require(
                snapshot.get("storyboard_id") == board.id and snapshot.get("directing_plan_id") == plan.id,
                "待审版本没有冻结",
            )
            require(
                set(snapshot.get("shot_fingerprints", {})) == {shot.id for shot in shots},
                "待审镜头指纹不完整",
            )
            if scenario == "stale":
                first = shots[0]
                production.update_shot(
                    db,
                    shot=first,
                    description="提审后的新修订",
                    base_storyboard_id=board.id,
                    base_shot_fingerprint=production.shot_edit_fingerprint(first),
                )
                try:
                    reviews.decide(db, project=project, review=review, status="approved", reviewer_id=USER_ID)
                except ConflictError:
                    pass
                else:
                    raise AssertionError("提审后变化仍能批准旧快照")
                require(
                    review.status == "pending" and not board.approved and not plan.approved,
                    "过期批准改变了审批状态",
                )
                reviews.decide(
                    db,
                    project=project,
                    review=review,
                    status="rejected",
                    comment="基线已变更，重新提审",
                    reviewer_id=USER_ID,
                )
                workflow.cancel(db, run, "本地机制：驳回后重新提审")
            elif scenario == "reject":
                reviews.decide(
                    db,
                    project=project,
                    review=review,
                    status="rejected",
                    comment="需要调整节奏",
                    reviewer_id=USER_ID,
                )
                require(not board.approved and not plan.approved, "驳回却批准产物")
                try:
                    reviews.decide(db, project=project, review=review, status="approved", reviewer_id=USER_ID)
                except ConflictError:
                    pass
                else:
                    raise AssertionError("重复决定未冲突")
                workflow.cancel(db, run, "本地机制：驳回后重新提审")
            else:
                reviews.decide(
                    db,
                    project=project,
                    review=review,
                    status="approved",
                    comment="快照核对通过",
                    reviewer_id=USER_ID,
                )
                require(
                    board.approved and plan.approved and all(shot.approved for shot in shots),
                    "第二审核未批准冻结产物",
                )
                old_board = db.scalar(
                    select(Storyboard).where(Storyboard.project_id == pid, Storyboard.version == 1)
                )
                old_plan = db.scalar(
                    select(DirectingPlan).where(DirectingPlan.project_id == pid, DirectingPlan.version == 1)
                )
                require(not old_board.approved and not old_plan.approved, "第二审核误批准历史版本")
                run = asyncio.run(engine.resume(db, run=run, project=project, user_id=USER_ID))
                require(run.status == "completed", "第二审核通过后子流程未正常结束")
            after_calls = int(
                db.scalar(select(func.count()).select_from(AgentRun).where(AgentRun.project_id == pid)) or 0
            )
            require(before_calls == after_calls, "审核边界意外运行下游Agent")
    report.mechanisms["second_gate"] = {
        "mode": "local_service",
        "workflow_nodes": 1,
        "rejected": True,
        "stale_approval_rejected": True,
        "frozen_version_approved": True,
        "media_calls": 0,
    }
    report.add(
        "second_gate",
        PASS,
        "仅第二gate子流程：驳回、过期快照拒绝且保持pending、重新提审批准冻结版本；通过后无媒体",
    )


class StubProvider:
    """只验证结构修复机制，不联网，不作为真实模型质量证据。"""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.requests: list[Any] = []

    async def generate(self, request: Any) -> LLMResult:
        self.requests.append(request)
        return LLMResult(
            text=self.replies.pop(0),
            provider="stub",
            model_id="module4-schema-stub",
            tokens_in=8,
            tokens_out=8,
        )


def schema_guard(runtime: Any, report: Report) -> None:
    mock_targets(runtime, repair=True)
    cases = {
        "director": (
            DirectingPlanInput(script={"script_text": SCRIPT_TEXT}, shots_target=3),
            {"visual_style": "克制写实", "shot_strategy": {"total_shots": 3, "avg_duration_seconds": 5.0}},
            [{}, {"visual_style": "   "}, {"visual_style": "写实", "shot_strategy": {"total_shots": -1}}],
        ),
        "storyboard": (
            StoryboardInput(
                script={"script_text": SCRIPT_TEXT}, plan={"visual_style": "克制写实"}, shots_target=3
            ),
            {
                "title": "书店分镜",
                "shots": [
                    {
                        "description": "两人在书店送信",
                        "visual_prompt": "写实雨夜旧书店",
                        "duration_seconds": 5.0,
                    }
                ],
            },
            [{}, {"shots": []}, {"shots": [{"description": "书店", "duration_seconds": -1}]}],
        ),
    }
    evidence = {}
    with no_network():
        for agent_id, (inputs, good, invalid_cases) in cases.items():
            agent = create_agent(agent_id, runtime.config_store)
            for invalid in invalid_cases:
                try:
                    agent.validate_output(invalid)
                except Exception:
                    pass
                else:
                    raise AssertionError(f"{agent_id} 坏结构未被拒绝")
            stub = StubProvider(["不是JSON", json.dumps(good, ensure_ascii=False)])
            with patch.object(agent, "_provider_for", return_value=stub):
                result = asyncio.run(agent.execute(inputs, AgentContext(project_id="module4-stub-only")))
            require(result.attempts == 2 and result.meta.get("repairs") == 1, f"{agent_id} 修复次数不正确")
            require("校验错误" in stub.requests[1].user, "修复提示缺少结构错误")
            bad = StubProvider(["仍然错误", "继续错误"])
            with patch.object(agent, "_provider_for", return_value=bad):
                try:
                    asyncio.run(agent.execute(inputs, AgentContext(project_id="module4-stub-only")))
                except AgentSchemaError as exc:
                    require(exc.details.get("attempts") == 2, "耗尽次数不正确")
                else:
                    raise AssertionError(f"{agent_id} 修复耗尽仍报告成功")
            evidence[agent_id] = {"mode": "stub", "repair_requests": 2, "exhaustion_requests": 2}
    report.mechanisms["schema_guard_repair"] = evidence
    report.add(
        "schema_guard_repair", PASS, "独立stub：导演空风格/负镜头数、分镜空镜头/负时长拒绝；坏→好与耗尽"
    )


def evidence_and_isolation(runtime: Any, pid: str, ready: bool, report: Report) -> None:
    with session_scope() as db:
        runs = list(db.scalars(select(AgentRun).where(AgentRun.project_id == pid)))
        logs = list(db.scalars(select(ModelCallLog).where(ModelCallLog.project_id == pid)))
        if ready:
            require(len(runs) == len(logs) == 4, "主检查的审计数不是四次")
            require(
                all(
                    row.agent_id in TARGETS and row.status == "succeeded" and row.attempts == 1
                    for row in runs
                ),
                "主检查混入其他Agent/失败/重试",
            )
            require(
                all(sum(row.agent_id == name for row in runs) == 2 for name in TARGETS),
                "主检查不是两次导演和两次分镜",
            )
            require(
                all(row.input.get("script", {}).get("script_text") == SCRIPT_TEXT for row in runs),
                "输入正文被截断或替换",
            )
            for row in runs:
                config = runtime.config_store.agent(row.agent_id)
                require(
                    row.model_provider == config.model.provider and row.model_id == config.model.model_id,
                    "实际调用出处与配置不符",
                )
            if report.mode == "live":
                require(
                    all((row.meta or {}).get("provider_meta", {}).get("offline") is not True for row in runs),
                    "真实证据混入offline",
                )
            report.evidence["primary"] = {
                "project_id": pid,
                "plans": 2,
                "storyboards": 2,
                "agent_runs": len(runs),
                "model_logs": len(logs),
                "agent_ids": sorted({row.agent_id for row in runs}),
                "by_agent": {
                    name: {
                        "provider": runtime.config_store.agent(name).model.provider,
                        "model": runtime.config_store.agent(name).model.model_id,
                    }
                    for name in TARGETS
                },
                "attempts": sum(row.attempts for row in runs),
                "tokens_in": sum(row.tokens_in for row in runs),
                "tokens_out": sum(row.tokens_out for row in runs),
                "agent_run_ids": [row.id for row in runs],
                "model_log_ids": [row.id for row in logs],
            }
            report.add(
                "call_evidence",
                PASS,
                "导演/分镜各两次、一候选/一次尝试；全文输入与四条AgentRun/ModelCallLog可追踪；无prompt请求",
            )
        else:
            report.add("call_evidence", SKIP, "主模型配置或生成未成功，不宣称目标调用通过")
        try:
            projects.get_project(db, pid, "module4_intruder")
        except PermissionDeniedError:
            pass
        else:
            raise AssertionError("项目访问隔离未生效")
        downstream = {
            model.__tablename__: int(db.scalar(select(func.count()).select_from(model)) or 0)
            for model in DOWNSTREAM
        }
        require(not any(downstream.values()), f"产生了媒体下游记录：{downstream}")
        all_ids = sorted(set(db.scalars(select(AgentRun.agent_id))))
        require(set(all_ids).issubset(set(TARGETS)), f"检查混入其他Agent：{all_ids}")
        stages = set(db.scalars(select(Review.stage)))
        require(stages.issubset({"storyboard"}), f"审核越出第二关：{stages}")
        definitions = set(db.scalars(select(WorkflowRun.definition_id)))
        require(definitions.issubset({"module4_second_gate_only"}), "检查启动了未截断的生产工作流")
        report.evidence["downstream_counts"] = downstream
        report.add(
            "project_isolation_no_downstream",
            PASS,
            "项目访问隔离；审核仅storyboard、子流程仅第二gate；无图片/视频/音频/剪辑",
        )


def run(args: argparse.Namespace) -> int:
    saved_environment = os.environ.copy()
    report = Report(mode="offline" if args.offline else "live")
    report.redactor.remember_environment()
    sandbox = runtime = local_runtime = None
    with (
        contextlib.redirect_stdout(SafeStream(sys.stdout, report.redactor)),
        contextlib.redirect_stderr(SafeStream(sys.stderr, report.redactor)),
    ):
        try:
            sandbox, settings, runtime = build_sandbox(keep=args.keep, report=report)
            report.redactor.remember_environment()
            report.add("sandbox", PASS, "独立临时SQLite/config/local storage；复用已验证隔离工具，不启动服务")
            ready = configure(runtime, args, report)
            pid, sid = fixture(runtime, label="模块4导演与分镜主检查")
            report.add("fixture", PASS, "手写全文+合成两个人物、一处场景；未调用上游Agent")
            completed = False
            if ready:
                try:
                    primary(runtime, pid, sid, args.offline, report)
                    completed = True
                except Exception as exc:
                    group = next(
                        name
                        for name in ("directing", "storyboard", "versions_source")
                        if name not in report.rows
                    )
                    report.add(group, FAIL, f"{type(exc).__name__}: {exc}")
            else:
                report.add("directing", SKIP, "配置未通过，未发送真实请求")
                report.add("storyboard", SKIP, "没有本次导演与分镜结果")
                report.add("versions_source", SKIP, "没有两次目标生成结果")
            for name, operation in (("shot_edit", edit_shot), ("second_gate", second_gate)):
                if not completed:
                    report.add(name, SKIP, "缺少本次完整导演／分镜结果")
                    continue
                try:
                    if name == "shot_edit":
                        operation(pid, report)
                    else:
                        operation(runtime, pid, report)
                except Exception as exc:
                    report.add(name, FAIL, f"{type(exc).__name__}: {exc}")
            local_runtime = build_runtime(settings)
            mock_targets(local_runtime)
            for name, operation in (
                ("baseline_guard", baseline_guard),
                ("schema_guard_repair", schema_guard),
            ):
                try:
                    operation(local_runtime, report)
                except Exception as exc:
                    report.add(name, FAIL, f"{type(exc).__name__}: {exc}")
            evidence_and_isolation(runtime, pid, completed, report)
        except Exception as exc:
            group = next((name for name in GROUPS if name not in report.rows), "sandbox")
            report.add(group, FAIL, f"{type(exc).__name__}: {exc}")
        finally:
            try:
                for current in (runtime, local_runtime):
                    if current is not None:
                        reset_runner(current)
                reset_engine()
                if sandbox is None and report.sandbox_path:
                    sandbox = Path(report.sandbox_path)
                if sandbox is not None and not args.keep:
                    _cleanup(sandbox)
                report.sandbox_removed = sandbox is not None and not sandbox.exists()
                report.add("cleanup", PASS, "保留本次沙箱" if args.keep else "已释放并删除本次沙箱")
            except Exception as exc:
                report.add("cleanup", FAIL, f"{type(exc).__name__}: {exc}")
            os.environ.clear()
            os.environ.update(saved_environment)
        payload = report.payload()
        if args.report_json:
            destination = args.report_json.expanduser().absolute()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"JSON报告：{destination}")
        passed = sum(row["status"] == PASS for row in payload["rows"])
        print(f"RESULT: {passed}/{len(GROUPS)} passed；必要项SKIP不算完整通过")
        return 0 if payload["success"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="模块4：导演＋分镜＋第二审核隔离验收，目标默认使用真实YAML/.env"
    )
    parser.add_argument("--offline", action="store_true", help="显式使用mock并禁止目标HTTP请求")
    parser.add_argument("--keep", action="store_true", help="保留本次临时沙箱")
    parser.add_argument("--verbose", action="store_true", help="兼容检查入口；报告始终保留脱敏配置")
    parser.add_argument("--max-tokens", type=int, default=2048, help="每次目标调用输出上限，1..4096")
    parser.add_argument("--timeout", type=int, default=150, help="每次目标调用超时秒数，1..600")
    parser.add_argument("--base-url", help="可选临时模型商接口地址，必须与--model成对使用")
    parser.add_argument("--model", help="可选临时模型名")
    parser.add_argument("--api-key-env", default="MODULE_CHECK_API_KEY", help="临时接口密钥的环境变量名")
    parser.add_argument("--report-json", type=Path, help="保存脱敏JSON报告")
    args = parser.parse_args(argv)
    if bool(args.base_url) != bool(args.model):
        parser.error("--base-url 与 --model 必须成对提供")
    if not 1 <= args.max_tokens <= 4096 or not 1 <= args.timeout <= 600:
        parser.error("--max-tokens应为1..4096，--timeout应为1..600")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
