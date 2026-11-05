"""Dialogue audio, subtitle and audio track application flows."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.character import CharacterVoice
from app.models.ops import Task
from app.models.project import Asset, Project
from app.modules.ai_runtime.public import run_agent
from app.modules.assets import public as asset_service
from app.modules.characters import public as character_module
from app.modules.platform.constants import (
    AssetKind,
    AudioKind,
)
from app.modules.platform.exceptions import WorkflowError
from app.modules.platform.execution.runtime import AppRuntime
from app.modules.platform.ids import new_id
from app.modules.platform.media import ffmpeg as ffmpeg_utils
from app.modules.platform.text import narrative
from app.modules.production.application import queries as production_queries
from app.modules.production.infrastructure.agents.audio import VoiceSynthesisInput
from app.modules.production.infrastructure.persistence.models import (
    AudioTrack,
    Shot,
)
from app.modules.story import public as story_module
from app.schemas.audio import AudioPlanInput

logger = logging.getLogger(__name__)


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
