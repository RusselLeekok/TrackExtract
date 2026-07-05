from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models import (
    ExportFile,
    ExportType,
    MediaItem,
    MediaStatus,
    MediaTrack,
    SubtitleKind,
    SubtitleSegment,
    SubtitleVersion,
    TaskRecord,
    TaskStatus,
    TrackType,
)
from app.services.media_tools import (
    CommandError,
    download_url,
    extract_audio_for_transcription,
    extract_cover,
    extract_track,
    get_ytdlp_info,
    media_summary,
    normalize_tracks,
    probe_media,
    transcribe_audio,
)
from app.services.subtitles import parse_subtitle_file
from app.services.task_logger import TaskLogger


def _set_task(db: Session, task: TaskRecord, status: TaskStatus, progress: int, error: str | None = None, result: dict | None = None) -> None:
    task.status = status
    task.progress = progress
    task.error_message = error
    if result is not None:
        task.result_json = result
    db.commit()


def _fail(db: Session, task: TaskRecord, media: MediaItem | None, logger: TaskLogger, exc: Exception) -> None:
    message = str(exc)
    if isinstance(exc, CommandError):
        message = "\n".join(part for part in [message, exc.stderr.strip()] if part)
    logger.write("ERROR: " + message)
    task.log_path = str(logger.path)
    task.status = TaskStatus.failed
    task.progress = 100
    task.error_message = message
    if media:
        media.status = MediaStatus.failed
        media.error_message = message
    db.commit()


def _replace_tracks(db: Session, media: MediaItem, probe: dict) -> None:
    for track in list(media.tracks):
        db.delete(track)
    db.flush()
    for item in normalize_tracks(probe):
        db.add(MediaTrack(media_id=media.id, **item))


def _analyze_existing_media(db: Session, media: MediaItem, logger: TaskLogger) -> None:
    if not media.original_path:
        raise RuntimeError("Media file path is missing")
    probe = probe_media(Path(media.original_path), logger)
    summary = media_summary(probe)
    media.duration = summary["duration"]
    media.container_format = summary["container_format"]
    media.metadata_json = summary["metadata_json"]
    _replace_tracks(db, media, probe)
    try:
        media.cover_path = str(extract_cover(Path(media.original_path), media.id, logger))
    except Exception as exc:  # Some audio-only or damaged files cannot produce covers.
        logger.write(f"Cover extraction skipped: {exc}")
    media.status = MediaStatus.ready
    media.error_message = None


@celery_app.task(name="analyze_upload")
def analyze_upload_task(task_id: int, media_id: int) -> None:
    db = SessionLocal()
    logger = TaskLogger(task_id)
    try:
        task = db.get(TaskRecord, task_id)
        media = db.get(MediaItem, media_id)
        if not task or not media:
            raise RuntimeError("Task or media record not found")
        task.log_path = str(logger.path)
        _set_task(db, task, TaskStatus.running, 10)
        _analyze_existing_media(db, media, logger)
        _set_task(db, task, TaskStatus.completed, 100, result={"media_id": media.id})
    except Exception as exc:
        task = db.get(TaskRecord, task_id)
        media = db.get(MediaItem, media_id)
        if task:
            _fail(db, task, media, logger, exc)
    finally:
        db.close()


@celery_app.task(name="import_url")
def import_url_task(task_id: int, media_id: int, url: str) -> None:
    db = SessionLocal()
    logger = TaskLogger(task_id)
    try:
        task = db.get(TaskRecord, task_id)
        media = db.get(MediaItem, media_id)
        if not task or not media:
            raise RuntimeError("Task or media record not found")
        task.log_path = str(logger.path)
        _set_task(db, task, TaskStatus.running, 5)
        info = get_ytdlp_info(url, logger)
        media.title = info.get("title") or media.title
        media.metadata_json = {"yt_dlp": info}
        _set_task(db, task, TaskStatus.running, 35)
        media.original_path = str(download_url(url, media.id, logger))
        _set_task(db, task, TaskStatus.running, 75)
        _analyze_existing_media(db, media, logger)
        media.metadata_json = {"ffprobe": media.metadata_json, "yt_dlp": info}
        _set_task(db, task, TaskStatus.completed, 100, result={"media_id": media.id})
    except Exception as exc:
        task = db.get(TaskRecord, task_id)
        media = db.get(MediaItem, media_id)
        if task:
            _fail(db, task, media, logger, exc)
    finally:
        db.close()


@celery_app.task(name="extract_track")
def extract_track_task(task_id: int, media_id: int, track_id: int, output_format: str, file_name: str | None) -> None:
    db = SessionLocal()
    logger = TaskLogger(task_id)
    try:
        task = db.get(TaskRecord, task_id)
        media = db.get(MediaItem, media_id)
        track = db.get(MediaTrack, track_id)
        if not task or not media or not track:
            raise RuntimeError("Task, media, or track record not found")
        if not media.original_path:
            raise RuntimeError("Media file path is missing")
        task.log_path = str(logger.path)
        _set_task(db, task, TaskStatus.running, 15)
        output_path = extract_track(Path(media.original_path), track.stream_index, TrackType(track.track_type), output_format, file_name, logger)
        export = ExportFile(
            media_id=media.id,
            task_id=task.id,
            export_type=ExportType(track.track_type),
            format=output_format,
            file_name=file_name or output_path.name,
            file_path=str(output_path),
            is_original=True,
        )
        db.add(export)
        db.flush()
        if TrackType(track.track_type) == TrackType.subtitle:
            version = SubtitleVersion(
                media_id=media.id,
                export_file_id=export.id,
                kind=SubtitleKind.original,
                label=f"Original subtitle stream {track.stream_index}",
                source_path=str(output_path),
            )
            db.add(version)
            db.flush()
            for segment in parse_subtitle_file(output_path):
                db.add(SubtitleSegment(subtitle_version_id=version.id, **segment))
        _set_task(db, task, TaskStatus.completed, 100, result={"export_id": export.id})
    except Exception as exc:
        task = db.get(TaskRecord, task_id)
        media = db.get(MediaItem, media_id)
        if task:
            _fail(db, task, media, logger, exc)
    finally:
        db.close()


@celery_app.task(name="transcribe_media")
def transcribe_media_task(
    task_id: int,
    media_id: int,
    audio_track_id: int | None,
    external_audio_export_id: int | None,
    output_format: str,
    language: str | None,
    split_enabled: bool = False,
    max_chars: int = 42,
    max_seconds: float = 5.0,
) -> None:
    db = SessionLocal()
    logger = TaskLogger(task_id)
    try:
        task = db.get(TaskRecord, task_id)
        media = db.get(MediaItem, media_id)
        if not task or not media:
            raise RuntimeError("Task or media record not found")
        task.log_path = str(logger.path)
        _set_task(db, task, TaskStatus.running, 10)

        if external_audio_export_id:
            export = db.get(ExportFile, external_audio_export_id)
            if not export:
                raise RuntimeError("External audio file not found")
            audio_path = Path(export.file_path)
        else:
            if not media.original_path:
                raise RuntimeError("Media file path is missing")
            track = db.get(MediaTrack, audio_track_id) if audio_track_id else None
            if not track:
                track = next((item for item in media.tracks if TrackType(item.track_type) == TrackType.audio), None)
            if not track:
                raise RuntimeError("No audio track detected. Upload an external audio file or subtitle file for this media.")
            audio_path = extract_audio_for_transcription(Path(media.original_path), track.stream_index, logger)

        _set_task(db, task, TaskStatus.running, 45)
        subtitle_index = (
            db.execute(
                select(func.count(SubtitleVersion.id)).where(
                    SubtitleVersion.media_id == media.id,
                    SubtitleVersion.kind == SubtitleKind.whisper,
                )
            ).scalar_one()
            + 1
        )
        subtitle_stem = Path(media.title or "subtitle").stem or "subtitle"
        subtitle_file_name = f"{subtitle_stem}.{output_format}"
        subtitle_label = f"{subtitle_index}. {subtitle_file_name}"
        subtitle_path, segments = transcribe_audio(
            audio_path,
            language,
            output_format,
            logger,
            split_enabled,
            max_chars,
            max_seconds,
            subtitle_stem,
        )
        export = ExportFile(
            media_id=media.id,
            task_id=task.id,
            export_type=ExportType.subtitle,
            format=output_format,
            file_name=subtitle_file_name,
            file_path=str(subtitle_path),
            is_original=False,
        )
        db.add(export)
        db.flush()
        version = SubtitleVersion(
            media_id=media.id,
            export_file_id=export.id,
            kind=SubtitleKind.whisper,
            label=subtitle_label,
            source_path=str(subtitle_path),
        )
        db.add(version)
        db.flush()
        for segment in segments:
            db.add(SubtitleSegment(subtitle_version_id=version.id, **segment))
        _set_task(db, task, TaskStatus.completed, 100, result={"export_id": export.id, "subtitle_version_id": version.id})
    except Exception as exc:
        task = db.get(TaskRecord, task_id)
        media = db.get(MediaItem, media_id)
        if task:
            _fail(db, task, media, logger, exc)
    finally:
        db.close()
