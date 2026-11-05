"""人物形象、镜头视频、语音、时间线、渲染与导出的应用协调。

调用方负责项目授权和传入实体的归属；现有兼容接口返回 ORM 或普通字典。
数据库仅 flush，由外层提交或回滚；模型请求、对象存储与 FFmpeg 不受数据库回滚保护。
批量生成允许部分失败或停止后返回；调用方必须读取计数、failures 和阶段状态，不能把函数返回当作全量成功。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.character import Character, CharacterAsset, CharacterVoice
from app.models.ops import Task
from app.models.project import Asset, Project
from app.modules.ai_runtime.public import run_agent
from app.modules.assets import public as asset_service
from app.modules.characters import public as character_module
from app.modules.characters.public import CharacterImageInput
from app.modules.platform.constants import (
    AssetKind,
    AudioKind,
    CharacterStatus,
    ProjectStatus,
    ShotStatus,
)
from app.modules.platform.exceptions import NotFoundError, ValidationAppError, WorkflowError
from app.modules.platform.execution.runtime import AppRuntime
from app.modules.platform.ids import new_id
from app.modules.platform.media import ffmpeg as ffmpeg_utils
from app.modules.platform.text import narrative
from app.modules.production.application import queries as production_queries
from app.modules.production.infrastructure.agents.audio import VoiceSynthesisInput
from app.modules.production.infrastructure.persistence.models import (
    AudioTrack,
    EditingProject,
    Shot,
    VideoGeneration,
)
from app.modules.projects.public import touch_status
from app.modules.story import public as story_module
from app.schemas.audio import AudioPlanInput
from app.schemas.editing import EditingPlanInput
from app.schemas.video import ShotVideoInput

logger = logging.getLogger(__name__)

CHARACTER_ASSET_KINDS = ("portrait", "full_body", "turnaround")

_RESOLUTIONS = {
    "16:9": (1280, 720),
    "9:16": (720, 1280),
    "1:1": (1024, 1024),
    "4:3": (1024, 768),
}


def _output_dims(project: Project) -> tuple[int, int]:
    """根据项目设置与宽高比计算输出尺寸；无 I/O，不验证模型是否支持该尺寸。"""
    if project.aspect_ratio in _RESOLUTIONS:
        return _RESOLUTIONS[project.aspect_ratio]
    settings = project.settings or {}
    width = int(settings.get("width") or 1280)
    height = int(settings.get("height") or 720)
    return width, height


def _asset_bytes(runtime: AppRuntime, asset_id: str, db: Session) -> bytes | None:
    """按资产 ID 读取媒体字节；记录不存在返回 None，实际存储读取错误向上传播。"""
    asset = db.get(Asset, asset_id) if asset_id else None
    if asset is None or not runtime.storage.exists(asset.storage_key):
        return None
    return runtime.read_media(asset.storage_key)


def character_asset_version(db: Session, character_id: str, kind: str) -> int:
    """读取人物某类形象资产的最大版本并建议下一个编号。

    仅查询，不预留编号或加锁；并发分配由调用方协调。
    """
    current = db.scalar(
        select(func.max(CharacterAsset.version)).where(
            CharacterAsset.character_id == character_id, CharacterAsset.kind == kind
        )
    )
    return int(current or 0) + 1


# --------------------------------------------------------- character assets
async def generate_character_assets(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    characters: list[Character] | None = None,
    kinds: tuple[str, ...] = CHARACTER_ASSET_KINDS,
    task: Task | None = None,
    workflow_run_id: str = "",
    user_id: str = "",
    stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """逐人物、逐种类生成形象资产，并保留单项失败明细。

    Args:
        db: 调用方拥有的 Session；本函数不提交。
        runtime: 提供图片执行和文件存储能力的运行上下文。
        project: 已授权项目；传入 characters 须属于该项目。
        characters: 候选列表；None 或空列表时读取项目全部人物。
        kinds: 每个人物顺序生成的形象种类。
        stop: 生成每个种类前检查的停止回调，不中断已发出的模型请求。

    Returns:
        含 characters、assets_created、failures、kinds 的字典；允许部分成功。

    Raises:
        WorkflowError: 没有可处理人物。
        Exception: 模型单项异常收集进 failures；后续资产保存或数据库错误仍可能传播。

    Notes:
        成功项写存储并追加资产版本；只 flush，不提交。失败或停止不撤销已完成项。
        重试可能再次生成与计费，不提供请求幂等或并发版本锁。
    """
    characters = characters or character_module.list_characters(db, project.id)
    if not characters:
        raise WorkflowError("还没有人物档案，无法生成角色形象")

    created = 0
    failures: list[dict[str, str]] = []
    for character in characters:
        profile = character_module.profile_of(db, character)
        profile_content = (profile.content if profile else {}) or {}
        reference_bytes: bytes | None = None
        parent_asset_id = ""
        for kind in kinds:
            if stop and stop():
                break
            inputs = CharacterImageInput(
                project_id=project.id,
                character_id=character.id,
                name=character.name,
                profile=profile_content,
                kind=kind,
                reference_image=reference_bytes,
                style_tokens=list(character.appearance_keywords or [])[:6],
                label=f"{character.name}_{kind}",
            )
            try:
                result = await run_agent(
                    db,
                    runtime,
                    project=project,
                    agent_id="character_image",
                    payload=inputs,
                    task=task,
                    workflow_run_id=workflow_run_id,
                    user_id=user_id,
                )
            except Exception as exc:
                logger.warning("character image failed for %s/%s: %s", character.id, kind, exc)
                failures.append({"character": character.name, "kind": kind, "error": str(exc)[:300]})
                continue

            output = result.output
            content = getattr(output, "content", None)
            if not content:
                failures.append({"character": character.name, "kind": kind, "error": "provider 未返回图片"})
                continue
            asset = asset_service.save_asset(
                db,
                runtime,
                project_id=project.id,
                kind=AssetKind.CHARACTER_IMAGE.value,
                content=content,
                extension=".png",
                mime_type=getattr(output, "mime", "image/png"),
                width=getattr(output, "width", None) or None,
                height=getattr(output, "height", None) or None,
                model_id=result.model_id,
                prompt_version=result.prompt_version,
                config_version=result.config_version,
                meta={"character_id": character.id, "kind": kind},
                created_by=user_id,
            )
            version = character_asset_version(db, character.id, kind)
            db.add(
                CharacterAsset(
                    id=new_id("casset"),
                    project_id=project.id,
                    character_id=character.id,
                    asset_id=asset.id,
                    kind=kind,
                    version=version,
                    approved=False,
                    parent_asset_id=parent_asset_id,
                    model_id=result.model_id,
                    prompt_version=result.prompt_version,
                    config_version=result.config_version,
                    meta={
                        "prompt": (result.meta or {}).get("prompt", ""),
                        "label": f"{character.name}_{kind}",
                    },
                )
            )
            asset_service.record_asset_version(
                db,
                project_id=project.id,
                asset_id=asset.id,
                entity_type="character_asset",
                entity_id=character.id,
                version=version,
                note=kind,
                is_active=kind == "portrait",
            )
            if kind == "portrait":
                reference_bytes = content
                parent_asset_id = asset.id
            created += 1
        db.flush()

    return {
        "characters": len(characters),
        "assets_created": created,
        "failures": failures,
        "kinds": list(kinds),
    }


def character_assets(db: Session, character_id: str) -> list[CharacterAsset]:
    """按创建时间降序读取人物的全部形象资产；人物归属由调用方核对，只读、不提交。"""
    return list(
        db.scalars(
            select(CharacterAsset)
            .where(CharacterAsset.character_id == character_id)
            .order_by(CharacterAsset.created_at.desc())
        )
    )


def character_asset_public(db: Session, row: CharacterAsset) -> dict:
    """读取关联 Asset 并投影形象资产信息；缺失资产时 URL 为空，不写入或提交。"""
    asset = db.get(Asset, row.asset_id)
    return {
        "id": row.id,
        "character_id": row.character_id,
        "asset_id": row.asset_id,
        "kind": row.kind,
        "version": row.version,
        "approved": row.approved,
        "parent_asset_id": row.parent_asset_id,
        "model_id": row.model_id,
        "prompt_version": row.prompt_version,
        "config_version": row.config_version,
        "url": asset_service.asset_url(asset) if asset else "",
        "meta": row.meta or {},
    }


# --------------------------------------------------------------- shot videos
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
        asset = asset_service.save_asset(
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
        generation.asset_id = asset.id
        generation.status = "succeeded"
        generation.duration_seconds = duration
        generation.cost_usd = float(result.cost_usd or 0.0)
        db.query(VideoGeneration).filter(
            VideoGeneration.shot_id == shot.id, VideoGeneration.id != generation.id
        ).update({"selected": False}, synchronize_session=False)
        generation.selected = True
        shot.selected_video_id = asset.id
        shot.status = ShotStatus.GENERATED.value
        asset_service.record_asset_version(
            db,
            project_id=project.id,
            asset_id=asset.id,
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


# --------------------------------------------------------------------- audio
def shot_start_times(shots: list[Shot]) -> dict[str, float]:
    """按传入镜头顺序累计预计开始时间；无 I/O，不根据媒体实际时长重新探测。"""
    starts: dict[str, float] = {}
    cursor = 0.0
    for shot in shots:
        starts[shot.id] = round(cursor, 3)
        cursor += float(shot.duration_seconds or 5.0)
    return starts


def _dialogue_lines_from_shots(shots: list[Shot]) -> list[dict[str, Any]]:
    """从镜头对白构造语音行并估算时长；过滤空文本，不代表原音轨识别结果。"""
    lines: list[dict[str, Any]] = []
    for shot in shots:
        for index, line in enumerate(shot.dialogue or [], start=1):
            text = str((line or {}).get("text") or "").strip()
            if not text:
                continue
            lines.append(
                {
                    "line_id": f"{shot.id}_{index:02d}",
                    "shot_id": shot.id,
                    "character_id": str(line.get("character_id") or ""),
                    "character_name": str(line.get("character_name") or ""),
                    "text": text,
                    "emotion": str(line.get("emotion") or ""),
                    "duration_seconds": narrative.estimate_speech_duration(text),
                }
            )
    return lines


def _voice_for(db: Session, character_id: str) -> CharacterVoice | None:
    """按人物 ID 读取一个已有语音设置；ID 为空或无记录返回 None，不写入。"""
    if not character_id:
        return None
    return db.scalar(select(CharacterVoice).where(CharacterVoice.character_id == character_id))


async def generate_audio(
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
    """生成音频计划、逐行语音及字幕，汇总单行失败。

    Args:
        db: 外层事务 Session，本函数只 flush。
        runtime: 文字计划、TTS、文件存储与配置能力。
        project: 已授权项目；传入 shots 须属于该项目。
        shots: None 或空列表时使用项目最新分镜镜头。
        stop: 每条语音前检查；已发出的请求不因此得到远端取消保证。

    Returns:
        voice_lines、voice_assets、failures、subtitle_asset_id；可有字幕而语音仅部分成功。

    Raises:
        WorkflowError: 没有镜头。
        Exception: 音频计划失败直接传播；单行 TTS 异常收集，后续存储等错误可能传播。

    Notes:
        计划无有效语音行时使用镜头对白。停止后仍处理已生成语音选择和字幕。
        成功项写音频资产与轨道版本；不提交，也不因部分失败撤销已完成外部请求。
        重放会再次规划、合成并可能新增轨道版本，调用方负责幂等和费用。
    """
    shots = shots or production_queries.list_shots(db, project.id)
    if not shots:
        raise WorkflowError("还没有分镜，无法生成配音")
    script = story_module.latest_script(db, project.id)
    plan = production_queries.latest_plan(db, project.id)
    shot_payloads = [production_queries.shot_payload(db, shot) for shot in shots]

    result = await run_agent(
        db,
        runtime,
        project=project,
        agent_id="audio",
        payload=AudioPlanInput(
            shots=shot_payloads,
            synopsis=(script.synopsis if script else "")[:1200],
            language=project.language,
            style=((plan.content or {}).get("visual_style") if plan else "") or "",
        ),
        task=task,
        workflow_run_id=workflow_run_id,
        user_id=user_id,
    )
    planned = result.output
    lines: list[dict[str, Any]] = []
    by_text = {(item["shot_id"], item["text"]): item for item in _dialogue_lines_from_shots(shots)}
    for index, line in enumerate(planned.voice_lines, start=1):
        text = (line.text or "").strip()
        if not text:
            continue
        match = by_text.get((line.shot_id, text))
        lines.append(
            {
                "line_id": line.line_id or f"line_{index:03d}",
                "shot_id": line.shot_id or (match or {}).get("shot_id", ""),
                "character_id": (match or {}).get("character_id", ""),
                "character_name": line.character_name,
                "text": text,
                "emotion": line.emotion,
                "duration_seconds": float(line.duration_seconds or 0)
                or narrative.estimate_speech_duration(text),
            }
        )
    if not lines:
        lines = _dialogue_lines_from_shots(shots)

    characters = {item.name: item for item in character_module.list_characters(db, project.id)}
    created = 0
    failures: list[dict[str, str]] = []
    shot_voice_asset: dict[str, str] = {}

    for line in lines:
        if stop and stop():
            break
        character = characters.get(line["character_name"])
        character_id = line["character_id"] or (character.id if character else "")
        voice = _voice_for(db, character_id)
        try:
            speech = await run_agent(
                db,
                runtime,
                project=project,
                agent_id="audio_voice",
                payload=VoiceSynthesisInput(
                    line_id=line["line_id"],
                    text=line["text"],
                    character_name=line["character_name"],
                    emotion=line["emotion"],
                    voice=(voice.voice_id if voice else ""),
                    language=project.language,
                ),
                task=task,
                workflow_run_id=workflow_run_id,
                user_id=user_id,
            )
        except Exception as exc:
            failures.append({"line_id": line["line_id"], "error": str(exc)[:300]})
            continue

        output = speech.output
        content = getattr(output, "content", None)
        if not content:
            failures.append({"line_id": line["line_id"], "error": "TTS 未返回音频"})
            continue
        duration = float(getattr(output, "duration_seconds", 0) or line["duration_seconds"])
        asset = asset_service.save_asset(
            db,
            runtime,
            project_id=project.id,
            kind=AssetKind.AUDIO.value,
            content=content,
            extension=".wav",
            mime_type=getattr(output, "mime", "audio/wav"),
            duration_seconds=duration,
            model_id=speech.model_id,
            config_version=speech.config_version,
            meta={"line_id": line["line_id"], "shot_id": line["shot_id"], "text": line["text"]},
            created_by=user_id,
        )
        version = 1
        if line["shot_id"]:
            current = db.scalar(
                select(func.max(AudioTrack.version)).where(
                    AudioTrack.shot_id == line["shot_id"], AudioTrack.kind == AudioKind.VOICE.value
                )
            )
            version = int(current or 0) + 1
        db.add(
            AudioTrack(
                id=new_id("audio"),
                project_id=project.id,
                shot_id=line["shot_id"],
                character_id=character_id,
                kind=AudioKind.VOICE.value,
                asset_id=asset.id,
                text=line["text"],
                voice_id=(voice.voice_id if voice else "default"),
                language=project.language,
                version=version,
                duration_seconds=duration,
                status="succeeded",
                provider=speech.provider,
                model_id=speech.model_id,
                config_version=speech.config_version,
                meta={"line_id": line["line_id"], "emotion": line["emotion"]},
            )
        )
        if line["shot_id"]:
            shot_voice_asset.setdefault(line["shot_id"], asset.id)
        created += 1
        db.flush()

    for shot_id, asset_id in shot_voice_asset.items():
        shot = db.get(Shot, shot_id)
        if shot is not None:
            shot.selected_audio_id = asset_id

    subtitle_asset = _write_subtitles(db, runtime, project=project, shots=shots, created_by=user_id)
    db.flush()
    return {
        "voice_lines": len(lines),
        "voice_assets": created,
        "failures": failures,
        "subtitle_asset_id": subtitle_asset.id if subtitle_asset else "",
    }


def _write_subtitles(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    shots: list[Shot],
    created_by: str = "",
) -> Asset | None:
    """根据已有语音轨道的时长顺序生成 SRT 并保存字幕资产。

    无可用轨道返回 None；不是语音识别或强制对齐。会写临时文件和存储，只 flush、不提交。
    """
    starts = shot_start_times(shots)
    cues: list[tuple[float, float, str]] = []
    for shot in shots:
        tracks = list(
            db.scalars(
                select(AudioTrack)
                .where(AudioTrack.shot_id == shot.id, AudioTrack.kind == AudioKind.VOICE.value)
                .order_by(AudioTrack.created_at)
            )
        )
        if not tracks:
            continue
        cursor = starts.get(shot.id, 0.0)
        for track in tracks:
            duration = max(0.6, float(track.duration_seconds or 1.0))
            cues.append((cursor, cursor + duration, track.text))
            cursor += duration
    if not cues:
        return None

    workdir = runtime.settings.storage_root / "_tmp" / project.id
    workdir.mkdir(parents=True, exist_ok=True)
    srt_path = workdir / f"subtitles_{len(cues)}.srt"
    ffmpeg_utils.write_srt(cues, srt_path)
    asset = asset_service.save_asset(
        db,
        runtime,
        project_id=project.id,
        kind=AssetKind.SUBTITLE.value,
        content=srt_path.read_bytes(),
        extension=".srt",
        mime_type="text/plain",
        meta={"cues": len(cues)},
        created_by=created_by,
    )
    srt_path.unlink(missing_ok=True)
    return asset


def audio_tracks(db: Session, project_id: str, *, shot_id: str | None = None) -> list[AudioTrack]:
    """读取项目音轨并可按镜头过滤；无匹配返回空列表，只读、不提交。"""
    statement = select(AudioTrack).where(AudioTrack.project_id == project_id)
    if shot_id:
        statement = statement.where(AudioTrack.shot_id == shot_id)
    return list(db.scalars(statement.order_by(AudioTrack.created_at)))


def audio_public(db: Session, track: AudioTrack) -> dict:
    """读取音轨关联资产后投影 API 字段；不写入或提交，不验证音频内容质量。"""
    asset = db.get(Asset, track.asset_id) if track.asset_id else None
    return {
        "id": track.id,
        "shot_id": track.shot_id,
        "character_id": track.character_id,
        "kind": track.kind,
        "asset_id": track.asset_id,
        "url": asset_service.asset_url(asset) if asset else "",
        "text": track.text,
        "voice_id": track.voice_id,
        "language": track.language,
        "version": track.version,
        "duration_seconds": track.duration_seconds,
        "start_seconds": track.start_seconds,
        "status": track.status,
        "provider": track.provider,
        "model_id": track.model_id,
        "error": track.error,
    }


# ------------------------------------------------------------ editing/render
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

    subtitle = db.scalar(
        select(Asset)
        .where(Asset.project_id == project.id, Asset.kind == AssetKind.SUBTITLE.value)
        .order_by(Asset.created_at.desc())
    )
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
        subtitle_asset_id=subtitle.id if subtitle else "",
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
    asset = db.get(Asset, asset_id) if asset_id else None
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
    asset = db.get(Asset, asset_id) if asset_id else None
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
    audio_asset = db.get(Asset, track.asset_id)
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
            subtitle_asset = db.get(Asset, editing.subtitle_asset_id)
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
    film = db.get(Asset, editing.output_asset_id)
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
    output = db.get(Asset, editing.output_asset_id) if editing.output_asset_id else None
    subtitle = db.get(Asset, editing.subtitle_asset_id) if editing.subtitle_asset_id else None
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
        return db.get(Asset, editing.output_asset_id)
    return db.scalar(
        select(Asset)
        .where(Asset.project_id == project_id, Asset.kind == AssetKind.FILM.value)
        .order_by(Asset.created_at.desc())
    )


def ensure_character_approved(db: Session, character: Character) -> None:
    """仅把所给人物实体 status 设为 approved 并 flush，不提交。

    此兼容辅助不核对项目，不批准档案版本或创建 Review；不能当成人物审核完整入口。
    """
    character.status = CharacterStatus.APPROVED.value
    db.flush()
