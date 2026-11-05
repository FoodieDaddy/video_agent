"""Editing plans, film rendering and export application flows."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.ai_runtime.public import run_agent
from app.modules.assets import public as asset_service
from app.modules.assets.contracts import AssetReference
from app.modules.assets.contracts import LegacyAssetRecord as Asset
from app.modules.platform.constants import (
    AssetKind,
    ProjectStatus,
)
from app.modules.platform.exceptions import NotFoundError, WorkflowError
from app.modules.platform.execution.runtime import AppRuntime
from app.modules.platform.ids import new_id
from app.modules.platform.media import ffmpeg as ffmpeg_utils
from app.modules.platform.persistence.models import Task
from app.modules.production.application import queries as production_queries
from app.modules.production.application.media_support import _output_dims
from app.modules.production.infrastructure.persistence.models import (
    AudioTrack,
    EditingProject,
)
from app.modules.production.schemas.editing import EditingPlanInput
from app.modules.projects.contracts import ProjectContext as Project
from app.modules.projects.public import touch_status

logger = logging.getLogger(__name__)


def latest_editing(db: Session, project_id: str) -> EditingProject | None:
    """按版本降序读取项目最新剪辑工程，无记录返回 None；只读，不限制批准状态。"""
    return db.scalar(
        select(EditingProject)
        .where(EditingProject.project_id == project_id)
        .order_by(EditingProject.version.desc())
    )


async def build_editing_plan(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    task: Task | None = None,
    workflow_run_id: str = "",
    user_id: str = "",
) -> EditingProject:
    """调用 Editing Agent，为最新分镜追加 draft 剪辑工程。

    Args:
        db: 调用方 Session，不在本函数提交。
        runtime: Agent 执行与配置上下文。
        project: 已授权且具有镜头的项目。

    Returns:
        新 EditingProject，含时间线、输出尺寸、最近字幕引用与生成出处。

    Raises:
        WorkflowError: 项目没有镜头。
        Exception: 模型、契约和持久化错误向上传播。

    Notes:
        不在此验证全部视频/音频资产就绪，也不执行 FFmpeg；每次成功新增版本。
        模型请求可能产生费用，仅 flush；重复提交不是幂等操作。
    """
    shots = production_queries.list_shots(db, project.id)
    if not shots:
        raise WorkflowError("还没有分镜，无法编排时间线")
    plan = production_queries.latest_plan(db, project.id)
    width, height = _output_dims(project)
    fps = int((project.settings or {}).get("fps") or 25)

    result = await run_agent(
        db,
        runtime,
        project=project,
        agent_id="editing",
        payload=EditingPlanInput(
            shots=[production_queries.shot_payload(db, shot) for shot in shots],
            visual_style=((plan.content or {}).get("visual_style") if plan else "") or "",
            width=width,
            height=height,
            fps=fps,
        ),
        task=task,
        workflow_run_id=workflow_run_id,
        user_id=user_id,
    )
    output = result.output
    version = (
        int(
            db.scalar(select(func.max(EditingProject.version)).where(EditingProject.project_id == project.id))
            or 0
        )
        + 1
    )

    subtitle = asset_service.latest_asset_reference(db, project.id, AssetKind.SUBTITLE.value)
    editing = EditingProject(
        id=new_id("edit"),
        project_id=project.id,
        version=version,
        status="draft",
        timeline={
            "fps": fps,
            "width": width,
            "height": height,
            "total_duration": output.total_duration,
            "clips": [clip.model_dump(mode="json") for clip in output.timeline],
            "subtitles": output.subtitles,
        },
        subtitle_asset_id=subtitle.asset_id if subtitle else "",
        duration_seconds=output.total_duration,
        agent_id="editing",
        model_id=result.model_id,
        config_version=result.config_version,
        prompt_version=result.prompt_version,
        manifest={"notes": output.notes},
    )
    db.add(editing)
    db.flush()
    return editing


def _clip_source(db: Session, runtime: AppRuntime, clip: dict[str, Any], workdir: Path, index: int) -> Path:
    """读取时间线的视频资产；缺失时合成色卡占位片段。

    本函数有文件和 FFmpeg 副作用，返回可渲染路径不代表真实视频生成成功。
    """
    asset_id = str(clip.get("video_asset_id") or "")
    asset = asset_service.asset_reference(db, asset_id)
    if asset is not None and runtime.storage.exists(asset.storage_key):
        return runtime.media_path(asset.storage_key)
    # Degraded mode: no clip from the provider, synthesize a colour card.
    output = workdir / f"placeholder_{index:03d}.mp4"
    return ffmpeg_utils.make_color_clip(
        output,
        duration=float(clip.get("duration") or 2.0),
        width=int(clip.get("width") or 1280),
        height=int(clip.get("height") or 720),
        color="0x101820",
        ffmpeg_bin=runtime.settings.ffmpeg_bin,
    )


def _clip_audio(db: Session, runtime: AppRuntime, clip: dict[str, Any], workdir: Path) -> Path | None:
    """优先读取时间线指定音频，否则尝试镜头已有轨道；无可用资产返回 None，可继续无该音轨渲染。"""
    asset_id = str(clip.get("audio_asset_id") or "")
    asset = asset_service.asset_reference(db, asset_id)
    if asset is not None and runtime.storage.exists(asset.storage_key):
        return runtime.media_path(asset.storage_key)
    shot_id = str(clip.get("shot_id") or "")
    track = db.scalar(
        select(AudioTrack)
        .where(AudioTrack.shot_id == shot_id, AudioTrack.asset_id != "")
        .order_by(AudioTrack.created_at)
    )
    if track is None:
        return None
    audio_asset = asset_service.asset_reference(db, track.asset_id)
    if audio_asset is None or not runtime.storage.exists(audio_asset.storage_key):
        return None
    return runtime.media_path(audio_asset.storage_key)


def render_film(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    editing: EditingProject | None = None,
    user_id: str = "",
) -> Asset | None:
    """执行 FFmpeg 合成并保存成片资产，按现有降级策略返回结果。

    Args:
        db: 调用方事务，只 flush、不提交。
        runtime: 本地媒体路径、存储和 FFmpeg 能力。
        project: 已授权项目；显式 editing 的归属由调用方核对。
        editing: None 时使用最新剪辑工程，要求时间线非空。

    Returns:
        成功为新 Asset；FFmpeg 不可用或捕获到 FFmpegError 时返回 None，并写工程状态和错误。

    Raises:
        WorkflowError: 没有剪辑工程或时间线为空。
        Exception: 未捕获的文件、数据库、存储错误继续传播。

    Notes:
        缺视频可用色卡，字幕挂载失败保留原影片；rendered 不保证真实素材完整或终审通过。
        成功更新 output_asset_id 和项目 edited 状态，重复渲染会产生新资产。
        文件/子进程不受数据库回滚保护；finally 仅清理已记录的标准化片段，其它工作文件可保留。
    """
    editing = editing or latest_editing(db, project.id)
    if editing is None:
        raise WorkflowError("还没有时间线，无法合成成片")
    timeline = (editing.timeline or {}).get("clips") or []
    if not timeline:
        raise WorkflowError("时间线为空，无法合成成片")
    if not ffmpeg_utils.binary_available(runtime.settings.ffmpeg_bin):
        editing.status = "pending_render"
        editing.error = "FFmpeg 不可用，已保留时间线清单，安装后可重新合成"
        db.flush()
        logger.warning("ffmpeg unavailable, render skipped for project %s", project.id)
        return None

    width = int((editing.timeline or {}).get("width") or 1280)
    height = int((editing.timeline or {}).get("height") or 720)
    fps = int((editing.timeline or {}).get("fps") or 25)
    workdir = runtime.settings.storage_root / "_tmp" / project.id / f"render_{editing.version}"
    workdir.mkdir(parents=True, exist_ok=True)

    clips: list[Path] = []
    try:
        for index, clip in enumerate(sorted(timeline, key=lambda item: item.get("order", 0)), start=1):
            clip["width"] = clip.get("width") or width
            clip["height"] = clip.get("height") or height
            duration = float(clip.get("duration") or 2.0)
            source = _clip_source(db, runtime, clip, workdir, index)
            voice = _clip_audio(db, runtime, clip, workdir)
            target = workdir / f"normalized_{index:03d}.mp4"
            ffmpeg_utils.normalize_clip(
                source,
                target,
                duration=duration,
                width=width,
                height=height,
                fps=fps,
                voice_wav=voice,
                ffmpeg_bin=runtime.settings.ffmpeg_bin,
            )
            clip["normalized"] = target.name
            clips.append(target)

        film_path = workdir / "film.mp4"
        ffmpeg_utils.concat_clips(clips, film_path, ffmpeg_bin=runtime.settings.ffmpeg_bin)

        subtitle_path: Path | None = None
        if editing.subtitle_asset_id:
            subtitle_asset = asset_service.asset_reference(db, editing.subtitle_asset_id)
            if subtitle_asset is not None and runtime.storage.exists(subtitle_asset.storage_key):
                subtitle_path = runtime.media_path(subtitle_asset.storage_key)
        if subtitle_path is not None:
            subtitled = workdir / "film_subtitled.mp4"
            try:
                ffmpeg_utils.attach_subtitles(
                    film_path, subtitle_path, subtitled, ffmpeg_bin=runtime.settings.ffmpeg_bin
                )
                film_path = subtitled
            except ffmpeg_utils.FFmpegError as exc:
                logger.warning("subtitle mux failed, keeping silent film: %s", exc)

        content = film_path.read_bytes()
        asset = asset_service.save_asset(
            db,
            runtime,
            project_id=project.id,
            kind=AssetKind.FILM.value,
            content=content,
            extension=".mp4",
            mime_type="video/mp4",
            width=width,
            height=height,
            duration_seconds=editing.duration_seconds,
            config_version=editing.config_version,
            prompt_version=editing.prompt_version,
            meta={"editing_version": editing.version, "clips": len(clips)},
            created_by=user_id,
        )
        asset_service.record_asset_version(
            db,
            project_id=project.id,
            asset_id=asset.id,
            entity_type="editing_project",
            entity_id=editing.id,
            version=editing.version,
            note="render",
        )
        editing.output_asset_id = asset.id
        editing.status = "rendered"
        editing.error = ""
        editing.manifest = {
            **(editing.manifest or {}),
            "rendered_clips": len(clips),
            "subtitles": bool(subtitle_path),
            "ffmpeg": runtime.settings.ffmpeg_bin,
        }
        touch_status(db, project, ProjectStatus.EDITED)
        db.flush()
        return asset
    except ffmpeg_utils.FFmpegError as exc:
        editing.status = "failed"
        editing.error = str(exc)[:2000]
        db.flush()
        logger.warning("render failed for project %s: %s", project.id, exc)
        return None
    finally:
        for path in clips:
            path.unlink(missing_ok=True)


def export_film(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    editing: EditingProject | None = None,
    user_id: str = "",
) -> Asset:
    """复制已有成片为导出资产并更新工程和项目状态。

    Args:
        db: 外层事务 Session，仅 flush、不提交。
        runtime: 成片读取与导出存储能力。
        project: 已授权项目；审核与导出资格由上游决定。
        editing: None 时读取最新工程，必须已引用输出成片。

    Returns:
        新 export Asset，同时将工程置 exported、项目置 completed。

    Raises:
        NotFoundError: 没有输出引用或关联成片资产不存在。
        Exception: 文件读取、存储和数据库异常传播。

    Notes:
        本函数不额外校验终审决定或占位比例；重复导出新增资产，不提供请求幂等。
        外部文件写入不能由数据库回滚自动撤销。
    """
    editing = editing or latest_editing(db, project.id)
    if editing is None or not editing.output_asset_id:
        raise NotFoundError("还没有可导出的成片，请先完成合成")
    film = asset_service.asset_reference(db, editing.output_asset_id)
    if film is None:
        raise NotFoundError("成片资产不存在")
    content = runtime.read_media(film.storage_key)
    asset = asset_service.save_asset(
        db,
        runtime,
        project_id=project.id,
        kind=AssetKind.EXPORT.value,
        content=content,
        extension=".mp4",
        mime_type="video/mp4",
        width=film.width,
        height=film.height,
        duration_seconds=film.duration_seconds,
        config_version=editing.config_version,
        meta={"editing_version": editing.version, "filename": f"{project.name}.mp4"},
        created_by=user_id,
    )
    editing.status = "exported"
    touch_status(db, project, ProjectStatus.COMPLETED)
    db.flush()
    return asset


def editing_public(db: Session, editing: EditingProject) -> dict:
    """读取剪辑工程关联成片并投影时间线、状态、错误与地址；只读，不进行重新合成。"""
    output = asset_service.asset_reference(db, editing.output_asset_id)
    subtitle = asset_service.asset_reference(db, editing.subtitle_asset_id)
    return {
        "id": editing.id,
        "version": editing.version,
        "status": editing.status,
        "timeline": editing.timeline or {},
        "manifest": editing.manifest or {},
        "duration_seconds": editing.duration_seconds,
        "output_asset_id": editing.output_asset_id,
        "output_url": asset_service.asset_url(output) if output else "",
        "subtitle_asset_id": editing.subtitle_asset_id,
        "subtitle_url": asset_service.asset_url(subtitle) if subtitle else "",
        "error": editing.error,
        "config_version": editing.config_version,
    }


def latest_film_asset(db: Session, project_id: str) -> Asset | None:
    """优先读取最新剪辑工程引用的输出资产；无输出引用时才查询最近 film 资产。

    已有引用但资产丢失时返回 None；只读，不证明文件存在或内容合格。
    """
    editing = latest_editing(db, project_id)
    if editing and editing.output_asset_id:
        return asset_service.get_legacy_asset(db, editing.output_asset_id)
    return asset_service.latest_legacy_asset(db, project_id, AssetKind.FILM.value)


def latest_film_reference(db: Session, project_id: str) -> AssetReference | None:
    """读取当前成片的稳定资产引用，保留旧工程优先与缺失引用语义。"""
    editing = latest_editing(db, project_id)
    if editing and editing.output_asset_id:
        return asset_service.asset_reference(db, editing.output_asset_id)
    return asset_service.latest_asset_reference(db, project_id, AssetKind.FILM.value)
