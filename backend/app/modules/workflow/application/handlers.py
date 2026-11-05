"""Workflow node handlers.

Workflow YAML nodes reference a handler *name*; this module is the only place
that maps those names to service functions.  Adding a stage therefore means:
write a handler here, add it to ``HANDLERS``, and reference it from YAML.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models.ops import Task, WorkflowRun
from app.models.project import Project
from app.modules.characters import public as character_module
from app.modules.platform.configuration.config_models import WorkflowNodeConfig
from app.modules.platform.exceptions import AgentSchemaError, ConflictError, WorkflowError
from app.modules.platform.execution.runtime import AppRuntime
from app.modules.production import public as production_module
from app.modules.scenes import public as scene_module
from app.modules.story import public as story_module

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class HandlerContext:
    db: Session
    runtime: AppRuntime
    project: Project
    task: Task | None
    workflow_run: WorkflowRun | None
    node: WorkflowNodeConfig
    user_id: str = ""
    stop: Callable[[], bool] | None = None

    @property
    def run_id(self) -> str:
        return self.workflow_run.id if self.workflow_run else ""

    def cancelled(self) -> bool:
        return bool(self.stop and self.stop())


Handler = Callable[[HandlerContext], Awaitable[dict[str, Any]]]


async def handle_script(ctx: HandlerContext) -> dict[str, Any]:
    # 手写/导入/修订稿已经是剧本输入。启动完整流程时复用该版本，不能再强制
    # 要求小说章节或悄悄重写正文；独立“解析小说”任务仍执行原有生成用例。
    current = story_module.latest_script(ctx.db, ctx.project.id)
    meta = (current.content or {}).get("workspace_meta", {}) if current is not None else {}
    if (
        ctx.workflow_run is not None
        and current is not None
        and meta.get("source") in {"manual", "import", "polish", "continue", "restore"}
        and story_module.script_text_of(current).strip()
    ):
        return {
            "script_id": current.id,
            "script_fingerprint": story_module.script_fingerprint(current),
            "version": current.version,
            "title": current.title,
            "events": len((current.content or {}).get("events") or []),
            "reused_saved_script": True,
        }
    script = await story_module.generate_script(
        ctx.db,
        ctx.runtime,
        project=ctx.project,
        task=ctx.task,
        workflow_run_id=ctx.run_id,
        user_id=ctx.user_id,
    )
    return {
        "script_id": script.id,
        "script_fingerprint": story_module.script_fingerprint(script),
        "version": script.version,
        "title": script.title,
        "events": len((script.content or {}).get("events") or []),
    }


async def handle_characters(ctx: HandlerContext) -> dict[str, Any]:
    # 一个工作流节点内先提取人物，再为本次候选逐个追加档案版本；返回节点摘要，
    # 不在这里审批人物或生成形象图片。人物/场景都完成后由后续 gate 等待人工审核。
    characters = await character_module.extract_characters(
        ctx.db,
        ctx.runtime,
        project=ctx.project,
        task=ctx.task,
        workflow_run_id=ctx.run_id,
        user_id=ctx.user_id,
    )
    profiles = await character_module.describe_characters(
        ctx.db,
        ctx.runtime,
        project=ctx.project,
        characters=characters,
        task=ctx.task,
        workflow_run_id=ctx.run_id,
        user_id=ctx.user_id,
    )
    return {
        "characters": len(characters),
        "profiles": len(profiles),
        "names": [character.name for character in characters],
    }


async def handle_scenes(ctx: HandlerContext) -> dict[str, Any]:
    # 场景节点负责提取与文字档案生成；第一审核关卡检查的是这些设定。
    # 本节点不生成图片，也不调用导演规划或分镜。
    scenes = await scene_module.extract_scenes(
        ctx.db,
        ctx.runtime,
        project=ctx.project,
        task=ctx.task,
        workflow_run_id=ctx.run_id,
        user_id=ctx.user_id,
    )
    profiles = await scene_module.describe_scenes(
        ctx.db,
        ctx.runtime,
        project=ctx.project,
        scenes=scenes,
        task=ctx.task,
        workflow_run_id=ctx.run_id,
        user_id=ctx.user_id,
    )
    return {
        "scenes": len(scenes),
        "profiles": len(profiles),
        "names": [scene.name for scene in scenes],
    }


async def handle_directing(ctx: HandlerContext) -> dict[str, Any]:
    # 独立任务的参数来自已校验payload；工作流仍使用项目默认创作设置。
    options = (ctx.task.payload or {}) if ctx.task is not None and ctx.workflow_run is None else {}
    try:
        plan = await production_module.build_directing_plan(
            ctx.db,
            ctx.runtime,
            project=ctx.project,
            task=ctx.task,
            workflow_run_id=ctx.run_id,
            user_id=ctx.user_id,
            base_script_id=options.get("base_script_id"),
            base_script_fingerprint=options.get("base_script_fingerprint"),
            instruction=options.get("instruction", ""),
            shots_target=options.get("shots_target"),
        )
    except ConflictError as exc:
        # 与剧本编辑保持一致：仅模型完成后的来源冲突保留既成审计和用量。
        # 完整工作流已有失败边界提交；这里只处理独立stage，未写入任何新计划。
        if ctx.workflow_run is None and exc.details.get("generation_completed") is True:
            ctx.db.commit()
        raise
    return {
        "plan_id": plan.id,
        "version": plan.version,
        "visual_style": (plan.content or {}).get("visual_style", ""),
    }


async def handle_storyboard(ctx: HandlerContext) -> dict[str, Any]:
    options = (ctx.task.payload or {}) if ctx.task is not None and ctx.workflow_run is None else {}
    try:
        board = await production_module.build_storyboard(
            ctx.db,
            ctx.runtime,
            project=ctx.project,
            task=ctx.task,
            workflow_run_id=ctx.run_id,
            user_id=ctx.user_id,
            base_script_id=options.get("base_script_id"),
            base_plan_id=options.get("base_plan_id"),
            base_script_fingerprint=options.get("base_script_fingerprint"),
            base_plan_fingerprint=options.get("base_plan_fingerprint"),
            refine_prompts=options.get("refine_prompts", True),
        )
    except (ConflictError, AgentSchemaError) as exc:
        # 语义引用检查在保存分镜之前；深化后的冲突会先删除候选行，再保留模型审计。
        if ctx.workflow_run is None and exc.details.get("generation_completed") is True:
            ctx.db.commit()
        raise
    shots = production_module.list_shots(ctx.db, ctx.project.id, board=board)
    return {
        "storyboard_id": board.id,
        "version": board.version,
        "shots": len(shots),
        "shot_ids": [shot.id for shot in shots],
    }


async def handle_character_assets(ctx: HandlerContext) -> dict[str, Any]:
    return await production_module.generate_character_assets(
        ctx.db,
        ctx.runtime,
        project=ctx.project,
        task=ctx.task,
        workflow_run_id=ctx.run_id,
        user_id=ctx.user_id,
        stop=ctx.stop,
    )


async def handle_video(ctx: HandlerContext) -> dict[str, Any]:
    return await production_module.generate_shot_videos(
        ctx.db,
        ctx.runtime,
        project=ctx.project,
        task=ctx.task,
        workflow_run_id=ctx.run_id,
        user_id=ctx.user_id,
        stop=ctx.stop,
    )


async def handle_audio(ctx: HandlerContext) -> dict[str, Any]:
    return await production_module.generate_audio(
        ctx.db,
        ctx.runtime,
        project=ctx.project,
        task=ctx.task,
        workflow_run_id=ctx.run_id,
        user_id=ctx.user_id,
        stop=ctx.stop,
    )


async def handle_editing(ctx: HandlerContext) -> dict[str, Any]:
    editing = await production_module.build_editing_plan(
        ctx.db,
        ctx.runtime,
        project=ctx.project,
        task=ctx.task,
        workflow_run_id=ctx.run_id,
        user_id=ctx.user_id,
    )
    return {
        "editing_id": editing.id,
        "version": editing.version,
        "duration_seconds": editing.duration_seconds,
        "clips": len((editing.timeline or {}).get("clips") or []),
    }


async def handle_render(ctx: HandlerContext) -> dict[str, Any]:
    asset = production_module.render_film(ctx.db, ctx.runtime, project=ctx.project, user_id=ctx.user_id)
    if asset is None:
        editing = production_module.latest_editing(ctx.db, ctx.project.id)
        return {
            "rendered": False,
            "status": editing.status if editing else "unknown",
            "error": editing.error if editing else "",
        }
    return {"rendered": True, "asset_id": asset.id, "duration_seconds": asset.duration_seconds}


async def handle_evaluation(ctx: HandlerContext) -> dict[str, Any]:
    run = await production_module.evaluate_project(
        ctx.db,
        ctx.runtime,
        project=ctx.project,
        stage="final",
        task=ctx.task,
        workflow_run_id=ctx.run_id,
        user_id=ctx.user_id,
    )
    return {
        "evaluation_id": run.id,
        "overall_score": run.overall_score,
        "recommendation": run.recommendation,
    }


async def handle_export(ctx: HandlerContext) -> dict[str, Any]:
    asset = production_module.export_film(ctx.db, ctx.runtime, project=ctx.project, user_id=ctx.user_id)
    return {
        "asset_id": asset.id,
        "url": f"/media/{asset.storage_key}",
        "size_bytes": asset.size_bytes,
        "duration_seconds": asset.duration_seconds,
    }


HANDLERS: dict[str, Handler] = {
    "script": handle_script,
    "characters": handle_characters,
    "scenes": handle_scenes,
    "directing": handle_directing,
    "storyboard": handle_storyboard,
    "character_assets": handle_character_assets,
    "video": handle_video,
    "audio": handle_audio,
    "editing": handle_editing,
    "render": handle_render,
    "evaluation": handle_evaluation,
    "export": handle_export,
}


def build_handlers() -> dict[str, Handler]:
    return dict(HANDLERS)


def handler_names() -> list[str]:
    return sorted(HANDLERS)


def require_handler(name: str) -> Handler:
    handler = HANDLERS.get(name)
    if handler is None:
        raise WorkflowError(f"未注册的工作流 handler '{name}'，可用: {', '.join(handler_names())}")
    return handler
