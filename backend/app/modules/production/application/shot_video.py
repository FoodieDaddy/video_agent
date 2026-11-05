"""Shot video generation, selection and version queries."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.character import CharacterAsset
from app.models.ops import Task
from app.models.project import Asset, Project
from app.modules.ai_runtime.public import run_agent
from app.modules.assets import public as asset_service
from app.modules.platform.constants import (
    AssetKind,
    ProjectStatus,
    ShotStatus,
)
from app.modules.platform.exceptions import NotFoundError, ValidationAppError, WorkflowError
from app.modules.platform.execution.runtime import AppRuntime
from app.modules.platform.ids import new_id
from app.modules.production.application import queries as production_queries
from app.modules.production.application.media_support import _asset_bytes, _output_dims
from app.modules.production.infrastructure.persistence.models import (
    Shot,
    VideoGeneration,
)
from app.modules.projects.public import touch_status
from app.schemas.video import ShotVideoInput

logger = logging.getLogger(__name__)


def _video_version(db: Session, shot_id: str) -> int:
    """读取镜头候选视频的最大版本并建议下一个编号；不预留或加锁。"""
    current = db.scalar(select(func.max(VideoGeneration.version)).where(VideoGeneration.shot_id == shot_id))
    return int(current or 0) + 1


def _shot_reference(db: Session, runtime: AppRuntime, shot: Shot) -> tuple[bytes | None, list[str]]:
    """按镜头人物读取头像引用，返回第一项字节和全部找到的资产 ID。

    每个人物按 approved 优先、版本降序选择，不强制必须已批准；没有引用返回空值。
    仅第一项用于读取内容，后续引用不会作为首项读取失败后的自动兜底。
    """
    references: list[str] = []
    for ref in shot.characters or []:
        character_id = str((ref or {}).get("character_id") or "")
        if not character_id:
            continue
        row = db.scalar(
            select(CharacterAsset)
            .where(
                CharacterAsset.character_id == character_id,
                CharacterAsset.kind == "portrait",
            )
            .order_by(CharacterAsset.approved.desc(), CharacterAsset.version.desc())
        )
        if row is not None:
            references.append(row.asset_id)
    content = _asset_bytes(runtime, references[0], db) if references else None
    return content, references


async def generate_shot_videos(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    shots: list[Shot] | None = None,
    task: Task | None = None,
    workflow_run_id: str = "",
    user_id: str = "",
    stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """逐镜头提交视频生成并保存可用结果，允许部分成功返回。

    Args:
        db: 调用方 Session，负责本次写入的提交或回滚。
        runtime: 视频 Provider、存储和有效配置的运行上下文。
        project: 已授权项目；显式 shots 的项目归属由调用方保证。
        shots: 镜头列表；None 或空列表时读取最新分镜镜头。
        stop: 每个镜头前检查，不能保证取消正在运行的远端作业。

    Returns:
        shots、videos_created 与 failures；停止后也返回该结构，不产生独立取消终态。

    Raises:
        WorkflowError: 没有镜头。
        Exception: 模型调用异常逐项收集；资产写入及未捕获的数据库/存储异常传播。

    Notes:
        每项先写 generating，再等待模型；远端 task_ref 目前在调用返回后记录。
        有任意成功项就沿用设置 video_ready 的行为，不代表镜头已全部完成。
        仅 flush、不提交；重试可能新增版本与远端费用，调用方应处理重复提交。
    """
    shots = shots or production_queries.list_shots(db, project.id)
    if not shots:
        raise WorkflowError("还没有分镜，无法生成镜头视频")
    width, height = _output_dims(project)
    created = 0
    failures: list[dict[str, str]] = []

    for shot in shots:
        if stop and stop():
            break
        reference, reference_ids = _shot_reference(db, runtime, shot)
        payload = ShotVideoInput(
            shot_id=shot.id,
            prompt=shot.visual_prompt or shot.description,
            negative_prompt=shot.negative_prompt,
            duration_seconds=float(shot.duration_seconds or 5.0),
            width=width,
            height=height,
            aspect_ratio=project.aspect_ratio,
            reference_image=reference,
            extra={"scene_id": shot.scene_id},
        )
        version = _video_version(db, shot.id)
        generation = VideoGeneration(
            id=new_id("video"),
            project_id=project.id,
            shot_id=shot.id,
            version=version,
            status="generating",
            prompt=shot.visual_prompt,
            prompt_version=shot.prompt_version,
            config_version=shot.config_version,
            reference_asset_ids=reference_ids,
            params={"width": width, "height": height, "fps": int((project.settings or {}).get("fps", 25))},
        )
        db.add(generation)
        db.flush()
        shot.status = ShotStatus.GENERATING.value

        try:
            result = await run_agent(
                db,
                runtime,
                project=project,
                agent_id="video",
                payload=payload,
                task=task,
                workflow_run_id=workflow_run_id,
                user_id=user_id,
            )
        except Exception as exc:
            generation.status = "failed"
            generation.error = f"{type(exc).__name__}: {exc}"[:2000]
            shot.status = ShotStatus.FAILED.value
            db.flush()
            failures.append({"shot_id": shot.id, "error": str(exc)[:300]})
            logger.warning("video generation failed for shot %s: %s", shot.id, exc)
            continue

        output = result.output
        content = getattr(output, "content", None)
        generation.provider = result.provider
        generation.model_id = result.model_id
        generation.task_ref = str(getattr(output, "task_ref", "") or "")
        if not content:
            generation.status = "submitted"
            shot.status = ShotStatus.QUEUED.value
            failures.append({"shot_id": shot.id, "error": "provider 返回异步任务，等待回调/轮询"})
            db.flush()
            continue

        duration = float(getattr(output, "duration_seconds", 0) or shot.duration_seconds or 5.0)
        asset = asset_service.save_asset_reference(
            db,
            runtime,
            project_id=project.id,
            kind=AssetKind.VIDEO.value,
            content=content,
            extension=".mp4",
            mime_type=getattr(output, "mime", "video/mp4"),
            width=width,
            height=height,
            duration_seconds=duration,
            model_id=result.model_id,
            prompt_version=shot.prompt_version,
            config_version=result.config_version,
            meta={
                "shot_id": shot.id,
                "version": version,
                "placeholder": bool(result.meta.get("placeholder")),
            },
            created_by=user_id,
        )
        generation.asset_id = asset.asset_id
        generation.status = "succeeded"
        generation.duration_seconds = duration
        generation.cost_usd = float(result.cost_usd or 0.0)
        db.query(VideoGeneration).filter(
            VideoGeneration.shot_id == shot.id, VideoGeneration.id != generation.id
        ).update({"selected": False}, synchronize_session=False)
        generation.selected = True
        shot.selected_video_id = asset.asset_id
        shot.status = ShotStatus.GENERATED.value
        asset_service.record_asset_version(
            db,
            project_id=project.id,
            asset_id=asset.asset_id,
            entity_type="shot_video",
            entity_id=shot.id,
            version=version,
            note="video",
        )
        db.flush()
        created += 1

    if created:
        touch_status(db, project, ProjectStatus.VIDEO_READY)
    db.flush()
    return {"shots": len(shots), "videos_created": created, "failures": failures}


def video_generations(db: Session, shot_id: str) -> list[VideoGeneration]:
    """按版本降序读取镜头的全部视频候选；只读、不提交，访问权限由调用方确认。"""
    return list(
        db.scalars(
            select(VideoGeneration)
            .where(VideoGeneration.shot_id == shot_id)
            .order_by(VideoGeneration.version.desc())
        )
    )


def video_public(db: Session, row: VideoGeneration) -> dict:
    """读取候选关联资产并投影视频状态和地址；无资产时保留空 URL，只读、不提交。"""
    asset = db.get(Asset, row.asset_id) if row.asset_id else None
    return {
        "id": row.id,
        "shot_id": row.shot_id,
        "version": row.version,
        "status": row.status,
        "provider": row.provider,
        "model_id": row.model_id,
        "task_ref": row.task_ref,
        "asset_id": row.asset_id,
        "url": asset_service.asset_url(asset) if asset else "",
        "prompt": row.prompt,
        "duration_seconds": row.duration_seconds,
        "cost_usd": row.cost_usd,
        "selected": row.selected,
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def select_video(db: Session, *, project: Project, shot: Shot, generation: VideoGeneration) -> Shot:
    """选择属于当前镜头的已完成候选，返回原 Shot。

    Args:
        db: 调用方 Session；只 flush，不提交。
        project: 已授权项目。
        shot: 目标镜头，调用方保证其项目归属。
        generation: 待选候选，必须属于 project 和 shot，且已有资产并生成成功。

    Raises:
        NotFoundError: 候选不属于项目或镜头。
        ValidationAppError: 候选尚未生成完成。

    Notes:
        更新所有候选 selected 标记，并按当前实现将 generation.id 写入 selected_video_id。
        自动生成路径写入该字段的标识不同，调用方不能在此假定一定是 Asset ID。
        不创建审核记录或新增视频，重复选择仍会 flush。
    """
    if generation.project_id != project.id or generation.shot_id != shot.id:
        raise NotFoundError("视频版本不属于该镜头", details={"video_id": generation.id})
    if not generation.asset_id or generation.status not in {"succeeded", "generated"}:
        raise ValidationAppError("该候选视频尚未生成完成", details={"video_id": generation.id})
    for row in video_generations(db, shot.id):
        row.selected = row.id == generation.id
    shot.selected_video_id = generation.id
    shot.status = ShotStatus.GENERATED.value
    db.flush()
    return shot
