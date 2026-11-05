"""Thin, testable FFmpeg helpers used by media providers and the editor.

Every helper raises :class:`FFmpegError` with the tail of stderr so failures are
diagnosable from task events.  Callers decide whether a missing binary is fatal
(the editor degrades to a manifest in that case).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def binary_available(binary: str) -> bool:
    if not binary:
        return False
    if Path(binary).is_file():
        return True
    return shutil.which(binary) is not None


def run(args: list[str], *, timeout: int = 600) -> str:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - environment specific
        raise FFmpegError(f"Executable not found: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:  # pragma: no cover
        raise FFmpegError(f"Command timed out after {timeout}s: {' '.join(args[:3])}") from exc
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "").strip().splitlines()[-6:]
        raise FFmpegError(f"{args[0]} failed ({completed.returncode}): {' | '.join(tail)}")
    return completed.stdout


def probe_duration(path: Path, ffprobe_bin: str = "ffprobe") -> float:
    if not path.exists() or not binary_available(ffprobe_bin):
        return 0.0
    try:
        output = run(
            [
                ffprobe_bin,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            timeout=60,
        )
        payload = json.loads(output or "{}")
        duration = payload.get("format", {}).get("duration")
        if duration is not None:
            return round(float(duration), 3)
        for stream in payload.get("streams", []):
            if stream.get("duration"):
                return round(float(stream["duration"]), 3)
    except (FFmpegError, ValueError, json.JSONDecodeError):
        return 0.0
    return 0.0


def make_color_clip(
    output: Path,
    *,
    duration: float,
    width: int,
    height: int,
    color: str = "0x1b2a41",
    fps: int = 25,
    ffmpeg_bin: str = "ffmpeg",
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            ffmpeg_bin,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s={width}x{height}:r={fps}",
            "-t",
            f"{max(0.5, duration):.2f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output),
        ],
        timeout=180,
    )
    return output


def normalize_clip(
    source: Path,
    output: Path,
    *,
    duration: float,
    width: int,
    height: int,
    fps: int = 25,
    voice_wav: Path | None = None,
    ffmpeg_bin: str = "ffmpeg",
) -> Path:
    """Re-encode a clip to a uniform format so the concat demuxer can stream copy."""
    output.parent.mkdir(parents=True, exist_ok=True)
    filter_video = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps},setsar=1[v]"
    )
    if voice_wav and voice_wav.exists():
        args = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(source),
            "-i",
            str(voice_wav),
            "-f",
            "lavfi",
            "-t",
            f"{duration:.2f}",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-filter_complex",
            f"{filter_video};[1:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[va];"
            f"[va][2:a]amix=inputs=2:duration=longest:dropout_transition=0[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
        ]
    else:
        args = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(source),
            "-f",
            "lavfi",
            "-t",
            f"{duration:.2f}",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-filter_complex",
            filter_video,
            "-map",
            "[v]",
            "-map",
            "1:a",
        ]
    args += [
        "-t",
        f"{max(0.5, duration):.2f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(output),
    ]
    run(args, timeout=300)
    return output


def concat_clips(clips: Iterable[Path], output: Path, *, ffmpeg_bin: str = "ffmpeg") -> Path:
    clip_list = [clip for clip in clips if clip.exists()]
    if not clip_list:
        raise FFmpegError("No clips to concatenate")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
        for clip in clip_list:
            escaped = str(clip.resolve()).replace("'", "'\\''")
            handle.write(f"file '{escaped}'\n")
        list_path = Path(handle.name)
    try:
        run(
            [
                ffmpeg_bin,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(output),
            ],
            timeout=600,
        )
    finally:
        list_path.unlink(missing_ok=True)
    return output


def to_wav(source: Path, output: Path, *, ffmpeg_bin: str = "ffmpeg", sample_rate: int = 22050) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(source),
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            str(output),
        ],
        timeout=180,
    )
    return output


def concat_audio(sources: list[Path], output: Path, *, ffmpeg_bin: str = "ffmpeg") -> Path:
    if not sources:
        raise FFmpegError("No audio sources to concatenate")
    if len(sources) == 1:
        shutil.copyfile(sources[0], output)
        return output
    args = [ffmpeg_bin, "-y"]
    for source in sources:
        args += ["-i", str(source)]
    joined = "".join(f"[{index}:a]" for index in range(len(sources)))
    args += [
        "-filter_complex",
        f"{joined}concat=n={len(sources)}:v=0:a=1[a]",
        "-map",
        "[a]",
        "-ac",
        "1",
        "-ar",
        "22050",
        "-c:a",
        "pcm_s16le",
        str(output),
    ]
    run(args, timeout=300)
    return output


def attach_subtitles(
    video: Path,
    subtitles: Path,
    output: Path,
    *,
    ffmpeg_bin: str = "ffmpeg",
) -> Path:
    run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(video),
            "-i",
            str(subtitles),
            "-map",
            "0",
            "-map",
            "1:0",
            "-c",
            "copy",
            "-c:s",
            "mov_text",
            "-metadata:s:s:0",
            "language=chi",
            "-movflags",
            "+faststart",
            str(output),
        ],
        timeout=300,
    )
    return output


def format_srt_timestamp(seconds: float) -> str:
    milliseconds = int(round(max(0.0, seconds) * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(cues: list[tuple[float, float, str]], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for index, (start, end, text) in enumerate(cues, start=1):
        end = max(end, start + 0.3)
        lines.append(str(index))
        lines.append(f"{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}")
        lines.append(text.strip() or " ")
        lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")
    return output
