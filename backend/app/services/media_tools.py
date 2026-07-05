from __future__ import annotations

import json
import subprocess
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from app.config import get_settings
from app.models import TrackType
from app.services.storage import ensure_dir, unique_path
from app.services.subtitles import write_srt, write_vtt
from app.services.task_logger import TaskLogger


class CommandError(RuntimeError):
    def __init__(self, message: str, stdout: str = "", stderr: str = ""):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


YOUTUBE_EXTRACTOR_ARG_ATTEMPTS: tuple[str | None, ...] = (
    None,
    "youtube:player_client=default,-android_vr",
    "youtube:player_client=web_embedded,web,ios,mweb",
    "youtube:player_client=tv,web_embedded,ios",
)

def run_command(args: list[str], logger: TaskLogger | None = None, timeout: int | None = None) -> subprocess.CompletedProcess:
    if logger:
        logger.command(args)
    completed = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if logger and completed.stdout:
        logger.write(completed.stdout)
    if logger and completed.stderr:
        logger.write(completed.stderr)
    if completed.returncode != 0:
        raise CommandError(f"Command failed with exit code {completed.returncode}", completed.stdout, completed.stderr)
    return completed


def run_ytdlp_with_fallbacks(base_args: list[str], logger: TaskLogger | None, timeout: int | None) -> subprocess.CompletedProcess:
    errors: list[str] = []
    for extractor_args in YOUTUBE_EXTRACTOR_ARG_ATTEMPTS:
        args = ["yt-dlp", "--js-runtimes", "node"]
        if extractor_args:
            args += ["--extractor-args", extractor_args]
        args += base_args
        if logger:
            label = extractor_args or "yt-dlp default extractor clients"
            logger.write(f"yt-dlp attempt using {label}")
        try:
            return run_command(args, logger=logger, timeout=timeout)
        except CommandError as exc:
            errors.append("\n".join(part for part in [str(exc), exc.stderr.strip()] if part))
            if logger:
                logger.write("yt-dlp attempt failed; trying next extractor client set")
    raise CommandError("All yt-dlp extractor client attempts failed", stderr="\n\n".join(errors))


def probe_media(path: Path, logger: TaskLogger | None = None) -> dict:
    completed = run_command(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        logger=logger,
    )
    return json.loads(completed.stdout)


def normalize_tracks(probe: dict) -> list[dict]:
    tracks: list[dict] = []
    for stream in probe.get("streams", []):
        codec_type = stream.get("codec_type")
        if codec_type not in {"video", "audio", "subtitle"}:
            continue
        tags = stream.get("tags") or {}
        duration = stream.get("duration") or (probe.get("format") or {}).get("duration")
        bit_rate = stream.get("bit_rate")
        tracks.append(
            {
                "track_type": TrackType(codec_type),
                "stream_index": int(stream["index"]),
                "codec": stream.get("codec_name"),
                "language": tags.get("language"),
                "duration": float(duration) if duration else None,
                "width": stream.get("width"),
                "height": stream.get("height"),
                "bit_rate": int(bit_rate) if bit_rate and str(bit_rate).isdigit() else None,
                "raw_json": stream,
            }
        )
    return tracks


def media_summary(probe: dict) -> dict:
    fmt = probe.get("format") or {}
    duration = fmt.get("duration")
    return {
        "duration": float(duration) if duration else None,
        "container_format": fmt.get("format_name"),
        "metadata_json": probe,
    }


def get_ytdlp_info(url: str, logger: TaskLogger | None = None) -> dict:
    completed = run_ytdlp_with_fallbacks(["--dump-single-json", "--no-playlist", url], logger=logger, timeout=180)
    return json.loads(completed.stdout)


def download_url(url: str, media_id: int, logger: TaskLogger | None = None) -> Path:
    imports_dir = ensure_dir("imports")
    prefix = f"url_{media_id}_{uuid4().hex[:8]}"
    template = imports_dir / f"{prefix}.%(ext)s"
    run_ytdlp_with_fallbacks(
        [
            "--no-playlist",
            "-f",
            "bv*[ext=mp4][vcodec^=avc1]+ba[ext=m4a]/bv*[vcodec^=avc1]+ba[acodec^=mp4a]/b[ext=mp4]/bv*+ba/best",
            "--merge-output-format",
            "mp4",
            "-o",
            str(template),
            url,
        ],
        logger=logger,
        timeout=None,
    )
    candidates = sorted(imports_dir.glob(f"{prefix}.*"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not candidates:
        raise CommandError("yt-dlp finished but no output file was created")
    return candidates[0]


def extract_cover(media_path: Path, media_id: int, logger: TaskLogger | None = None) -> Path:
    cover_path = unique_path("covers", "jpg", f"media_{media_id}")
    run_command(
        ["ffmpeg", "-y", "-ss", "00:00:01", "-i", str(media_path), "-frames:v", "1", str(cover_path)],
        logger=logger,
    )
    return cover_path


def extract_track(media_path: Path, stream_index: int, track_type: TrackType, output_format: str, file_name: str | None, logger: TaskLogger | None = None) -> Path:
    safe_name = Path(file_name).stem if file_name else f"stream_{stream_index}"
    output_path = unique_path("exports", output_format, safe_name)
    base = ["ffmpeg", "-y", "-i", str(media_path), "-map", f"0:{stream_index}"]
    if track_type == TrackType.audio:
        if output_format == "mp3":
            args = base + ["-vn", "-c:a", "libmp3lame", "-q:a", "2", str(output_path)]
        elif output_format == "wav":
            args = base + ["-vn", "-c:a", "pcm_s16le", str(output_path)]
        else:
            raise HTTPException(status_code=400, detail="Audio tracks can only export to wav or mp3")
    elif track_type == TrackType.video:
        if output_format not in {"mp4", "mkv"}:
            raise HTTPException(status_code=400, detail="Video tracks can only export to mp4 or mkv")
        args = base + ["-an", "-sn", "-c:v", "copy", str(output_path)]
    elif track_type == TrackType.subtitle:
        if output_format == "srt":
            args = base + ["-c:s", "srt", str(output_path)]
        elif output_format == "vtt":
            args = base + ["-c:s", "webvtt", str(output_path)]
        else:
            raise HTTPException(status_code=400, detail="Subtitle tracks can only export to srt or vtt")
    else:
        raise HTTPException(status_code=400, detail="Unsupported track type")
    run_command(args, logger=logger)
    return output_path


def extract_audio_for_transcription(media_path: Path, stream_index: int, logger: TaskLogger | None = None) -> Path:
    output_path = unique_path("transcription_audio", "wav", f"stream_{stream_index}")
    run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(media_path),
            "-map",
            f"0:{stream_index}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ],
        logger=logger,
    )
    return output_path


def clean_subtitle_text(text: str) -> str:
    return " ".join(text.replace("\n", " ").split()).strip()


def subtitle_text_len(text: str) -> int:
    return len(clean_subtitle_text(text).replace(" ", ""))


def split_whisper_segment_words(segment: object, sequence: int, max_chars: int, max_seconds: float) -> tuple[list[dict], int]:
    words = [
        {
            "text": str(getattr(word, "word", "") or ""),
            "start": float(getattr(word, "start", 0.0) or 0.0),
            "end": float(getattr(word, "end", 0.0) or 0.0),
        }
        for word in (getattr(segment, "words", None) or [])
    ]
    if not words:
        return [
            {
                "sequence": sequence,
                "start_seconds": float(getattr(segment, "start", 0.0)),
                "end_seconds": float(getattr(segment, "end", 0.0)),
                "text": clean_subtitle_text(getattr(segment, "text", "")),
            }
        ], sequence + 1

    rows: list[dict] = []
    chunk: list[dict] = []
    hard_breaks = set(".!?;:。！？；：")
    soft_breaks = set(",，、")

    def flush() -> None:
        nonlocal sequence, chunk
        text = clean_subtitle_text("".join(item["text"] for item in chunk))
        if text:
            rows.append(
                {
                    "sequence": sequence,
                    "start_seconds": chunk[0]["start"],
                    "end_seconds": max(chunk[-1]["end"], chunk[0]["start"] + 0.15),
                    "text": text,
                }
            )
            sequence += 1
        chunk = []

    for word in words:
        if not word["text"]:
            continue
        projected = chunk + [word]
        projected_text = clean_subtitle_text("".join(item["text"] for item in projected))
        projected_duration = projected[-1]["end"] - projected[0]["start"]
        if chunk and (subtitle_text_len(projected_text) > max_chars or projected_duration > max_seconds):
            flush()
        chunk.append(word)
        current_text = clean_subtitle_text("".join(item["text"] for item in chunk))
        last_char = clean_subtitle_text(word["text"])[-1:] if clean_subtitle_text(word["text"]) else ""
        current_duration = chunk[-1]["end"] - chunk[0]["start"]
        if last_char in hard_breaks or (
            last_char in soft_breaks and (subtitle_text_len(current_text) >= max_chars * 0.75 or current_duration >= max_seconds * 0.75)
        ):
            flush()
    if chunk:
        flush()
    return rows, sequence


def transcribe_audio(
    audio_path: Path,
    language: str | None,
    output_format: str,
    logger: TaskLogger | None = None,
    split_enabled: bool = False,
    max_chars: int = 42,
    max_seconds: float = 5.0,
    output_stem: str | None = None,
) -> tuple[Path, list[dict]]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise CommandError(f"faster-whisper import failed: {exc}") from exc

    settings = get_settings()
    if logger:
        logger.write(
            f"Loading faster-whisper model={settings.whisper_model_size} device={settings.whisper_device} compute={settings.whisper_compute_type}"
        )
    model = WhisperModel(settings.whisper_model_size, device=settings.whisper_device, compute_type=settings.whisper_compute_type)
    segments_iter, info = model.transcribe(str(audio_path), language=language, vad_filter=True, word_timestamps=split_enabled)
    if logger:
        logger.write(f"Detected language={info.language} probability={info.language_probability}")
    segments: list[dict] = []
    if split_enabled and logger:
        logger.write(f"Whisper split rule enabled: max_chars={max_chars}, max_seconds={max_seconds}")
    sequence = 1
    for index, segment in enumerate(segments_iter, start=1):
        if split_enabled:
            rows, sequence = split_whisper_segment_words(segment, sequence, max_chars, max_seconds)
            segments.extend(rows)
        else:
            segments.append(
                {
                    "sequence": index,
                    "start_seconds": float(segment.start),
                    "end_seconds": float(segment.end),
                    "text": segment.text.strip(),
                }
            )
    subtitle_path = unique_path("exports", output_format, output_stem or "whisper_subtitle")
    if output_format == "srt":
        write_srt(subtitle_path, segments)
    else:
        write_vtt(subtitle_path, segments)
    return subtitle_path, segments
