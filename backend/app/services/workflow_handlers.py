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

from app.core.config_models import WorkflowNodeConfig
from app.core.exceptions import WorkflowError
from app.models.ops import Task, WorkflowRun
from app.models.project import Project
from app.services import media, pipeline, quality
from app.services.runtime import AppRuntime

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
    script = await pipeline.generate_script(
        ctx.db,
        ctx.runtime,
        project=ctx.project,
        task=ctx.task,
        workflow_run_id=ctx.run_id,
        user_id=ctx.user_id,
    )
    return {
        "script_id": script.id,
        "version": script.version,
        "title": script.title,
        "events": len((script.content or {}).get("events") or []),
    }


async def handle_characters(ctx: HandlerContext) -> dict[str, Any]:
    characters = await pipeline.extract_characters(
        ctx.db,
        ctx.runtime,
        project=ctx.project,
        task=ctx.task,
        workflow_run_id=ctx.run_id,
        user_id=ctx.user_id,
    )
    profiles = await pipeline.describe_characters(
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
    scenes = await pipeline.extract_scenes(
        ctx.db,
        ctx.runtime,
        project=ctx.project,
        task=ctx.task,
        workflow_run_id=ctx.run_id,
        user_id=ctx.user_id,
    )
    profiles = await pipeline.describe_scenes(
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
    plan = await pipeline.build_directing_plan(
        ctx.db,
        ctx.runtime,
        project=ctx.project,
        task=ctx.task,
        workflow_run_id=ctx.run_id,
        user_id=ctx.user_id,
    )
    return {
        "plan_id": plan.id,
        "version": plan.version,
        "visual_style": (plan.content or {}).get("visual_style", ""),
    }


async def handle_storyboard(ctx: HandlerContext) -> dict[str, Any]:
    board = await pipeline.build_storyboard(
        ctx.db,
        ctx.runtime,
        project=ctx.project,
        task=ctx.task,
        workflow_run_id=ctx.run_id,
        user_id=ctx.user_id,
    )
    shots = pipeline.list_shots(ctx.db, ctx.project.id, board=board)
    return {
        "storyboard_id": board.id,
        "version": board.version,
        "shots": len(shots),
        "shot_ids": [shot.id for shot in shots],
    }


async def handle_character_assets(ctx: HandlerContext) -> dict[str, Any]:
    return await media.generate_character_assets(
        ctx.db,
        ctx.runtime,
        project=ctx.project,
        task=ctx.task,
        workflow_run_id=ctx.run_id,
        user_id=ctx.user_id,
        stop=ctx.stop,
    )


async def handle_video(ctx: HandlerContext) -> dict[str, Any]:
    return await media.generate_shot_videos(
        ctx.db,
        ctx.runtime,
        project=ctx.project,
        task=ctx.task,
        workflow_run_id=ctx.run_id,
        user_id=ctx.user_id,
        stop=ctx.stop,
    )


async def handle_audio(ctx: HandlerContext) -> dict[str, Any]:
    return await media.generate_audio(
        ctx.db,
        ctx.runtime,
        project=ctx.project,
        task=ctx.task,
        workflow_run_id=ctx.run_id,
        user_id=ctx.user_id,
        stop=ctx.stop,
    )


async def handle_editing(ctx: HandlerContext) -> dict[str, Any]:
    editing = await media.build_editing_plan(
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
    asset = media.render_film(
        ctx.db, ctx.runtime, project=ctx.project, user_id=ctx.user_id
    )
    if asset is None:
        editing = media.latest_editing(ctx.db, ctx.project.id)
        return {
            "rendered": False,
            "status": editing.status if editing else "unknown",
            "error": editing.error if editing else "",
        }
    return {"rendered": True, "asset_id": asset.id, "duration_seconds": asset.duration_seconds}


async def handle_evaluation(ctx: HandlerContext) -> dict[str, Any]:
    run = await quality.evaluate_project(
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
    asset = media.export_film(
        ctx.db, ctx.runtime, project=ctx.project, user_id=ctx.user_id
    )
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
        raise WorkflowError(
            f"未注册的工作流 handler '{name}'，可用: {', '.join(handler_names())}"
        )
    return handler
