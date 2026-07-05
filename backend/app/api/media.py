from pathlib import Path
from shutil import copyfileobj

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import ExportFile, ExportType, MediaItem, MediaSource, MediaStatus, MediaTrack, SubtitleKind, SubtitleSegment, SubtitleVersion, TaskRecord, TaskStatus, TaskType
from app.schemas import MediaRead, MediaUpdateRequest, TaskCreated, UrlImportRequest
from app.services.storage import storage_root, unique_path
from app.services.subtitles import parse_subtitle_file
from app.tasks import analyze_upload_task, import_url_task

router = APIRouter(prefix="/api/media", tags=["media"])


def _get_media(db: Session, media_id: int) -> MediaItem:
    media = db.execute(
        select(MediaItem)
        .where(MediaItem.id == media_id)
        .options(
            selectinload(MediaItem.tracks),
            selectinload(MediaItem.exports),
            selectinload(MediaItem.subtitle_versions),
        )
    ).scalar_one_or_none()
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")
    return media


def _is_inside_storage(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _delete_storage_files(paths: set[str]) -> None:
    root = storage_root()
    for raw_path in paths:
        if not raw_path:
            continue
        path = Path(raw_path)
        if not _is_inside_storage(path, root):
            continue
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass


@router.post("/upload", response_model=TaskCreated)
def upload_media(file: UploadFile = File(...), db: Session = Depends(get_db)) -> TaskCreated:
    suffix = Path(file.filename or "media.bin").suffix or ".bin"
    target = unique_path("uploads", suffix, Path(file.filename or "media").stem)
    with target.open("wb") as handle:
        copyfileobj(file.file, handle)

    media = MediaItem(
        source=MediaSource.upload,
        title=Path(file.filename or target.name).stem,
        original_path=str(target),
        status=MediaStatus.pending,
    )
    db.add(media)
    db.flush()
    task = TaskRecord(media_id=media.id, task_type=TaskType.analyze_upload, status=TaskStatus.queued)
    db.add(task)
    db.flush()
    task_id = task.id
    media_id = media.id
    db.commit()
    result = analyze_upload_task.delay(task_id, media_id)
    task = db.get(TaskRecord, task_id)
    task.celery_id = result.id
    db.commit()
    return TaskCreated(task_id=task_id, media_id=media_id)


@router.post("/import-url", response_model=TaskCreated)
def import_url(payload: UrlImportRequest, db: Session = Depends(get_db)) -> TaskCreated:
    media = MediaItem(source=MediaSource.url, source_url=payload.url, title=payload.url, status=MediaStatus.pending)
    db.add(media)
    db.flush()
    task = TaskRecord(media_id=media.id, task_type=TaskType.import_url, status=TaskStatus.queued)
    db.add(task)
    db.flush()
    task_id = task.id
    media_id = media.id
    db.commit()
    result = import_url_task.delay(task_id, media_id, payload.url)
    task = db.get(TaskRecord, task_id)
    task.celery_id = result.id
    db.commit()
    return TaskCreated(task_id=task_id, media_id=media_id)


@router.get("", response_model=list[MediaRead])
def list_media(db: Session = Depends(get_db)) -> list[MediaItem]:
    return list(
        db.execute(
            select(MediaItem)
            .order_by(MediaItem.created_at.desc())
            .options(
                selectinload(MediaItem.tracks),
                selectinload(MediaItem.exports),
                selectinload(MediaItem.subtitle_versions),
            )
        ).scalars()
    )


@router.get("/{media_id}", response_model=MediaRead)
def read_media(media_id: int, db: Session = Depends(get_db)) -> MediaItem:
    return _get_media(db, media_id)


@router.patch("/{media_id}", response_model=MediaRead)
def update_media(media_id: int, payload: MediaUpdateRequest, db: Session = Depends(get_db)) -> MediaItem:
    media = _get_media(db, media_id)
    if payload.title is not None:
        media.title = payload.title
    db.commit()
    db.refresh(media)
    return _get_media(db, media_id)


@router.delete("/{media_id}")
def delete_media(media_id: int, db: Session = Depends(get_db)) -> dict:
    media = db.get(MediaItem, media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")
    active_task = db.execute(
        select(TaskRecord).where(
            TaskRecord.media_id == media_id,
            TaskRecord.status.in_([TaskStatus.queued, TaskStatus.running]),
        ).limit(1)
    ).scalar_one_or_none()
    if active_task:
        raise HTTPException(status_code=409, detail="素材正在处理中，请等待任务结束后删除")

    file_paths = {media.original_path or "", media.cover_path or ""}
    versions = list(db.execute(select(SubtitleVersion).where(SubtitleVersion.media_id == media_id)).scalars())
    exports = list(db.execute(select(ExportFile).where(ExportFile.media_id == media_id)).scalars())
    tasks = list(db.execute(select(TaskRecord).where(TaskRecord.media_id == media_id)).scalars())

    version_ids = [version.id for version in versions]
    for version in versions:
        if version.source_path:
            file_paths.add(version.source_path)

    for export in exports:
        if export.file_path:
            file_paths.add(export.file_path)

    for task in tasks:
        if task.log_path:
            file_paths.add(task.log_path)

    if version_ids:
        db.execute(
            delete(SubtitleSegment)
            .where(SubtitleSegment.subtitle_version_id.in_(version_ids))
            .execution_options(synchronize_session=False)
        )
    db.execute(
        delete(SubtitleVersion)
        .where(SubtitleVersion.media_id == media_id)
        .execution_options(synchronize_session=False)
    )
    db.flush()
    db.execute(
        delete(ExportFile)
        .where(ExportFile.media_id == media_id)
        .execution_options(synchronize_session=False)
    )
    db.execute(
        delete(MediaTrack)
        .where(MediaTrack.media_id == media_id)
        .execution_options(synchronize_session=False)
    )
    db.execute(
        delete(TaskRecord)
        .where(TaskRecord.media_id == media_id)
        .execution_options(synchronize_session=False)
    )
    db.execute(
        delete(MediaItem)
        .where(MediaItem.id == media_id)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    _delete_storage_files(file_paths)
    return {"deleted": True, "media_id": media_id}


@router.get("/{media_id}/tracks")
def read_tracks(media_id: int, db: Session = Depends(get_db)) -> dict:
    media = _get_media(db, media_id)
    grouped = {"video": [], "audio": [], "subtitle": []}
    for track in media.tracks:
        key = getattr(track.track_type, "value", track.track_type)
        grouped[key].append(track)
    return grouped


@router.get("/{media_id}/source")
def media_source(media_id: int, db: Session = Depends(get_db)) -> FileResponse:
    media = _get_media(db, media_id)
    if not media.original_path or not Path(media.original_path).exists():
        raise HTTPException(status_code=404, detail="Source file not found")
    return FileResponse(media.original_path, filename=Path(media.original_path).name)


@router.get("/{media_id}/cover")
def media_cover(media_id: int, db: Session = Depends(get_db)) -> FileResponse:
    media = _get_media(db, media_id)
    if not media.cover_path or not Path(media.cover_path).exists():
        raise HTTPException(status_code=404, detail="Cover not found")
    return FileResponse(media.cover_path, media_type="image/jpeg", filename=Path(media.cover_path).name)


@router.post("/{media_id}/cover", response_model=MediaRead)
def upload_cover(media_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)) -> MediaItem:
    media = _get_media(db, media_id)
    suffix = Path(file.filename or "cover.jpg").suffix or ".jpg"
    target = unique_path("covers", suffix, f"media_{media_id}_custom")
    with target.open("wb") as handle:
        copyfileobj(file.file, handle)
    media.cover_path = str(target)
    db.commit()
    return _get_media(db, media_id)


@router.post("/{media_id}/external-audio")
def upload_external_audio(media_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    media = _get_media(db, media_id)
    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    target = unique_path("external_audio", suffix, Path(file.filename or "audio").stem)
    with target.open("wb") as handle:
        copyfileobj(file.file, handle)
    export = ExportFile(
        media_id=media.id,
        export_type=ExportType.audio,
        format=suffix.lstrip("."),
        file_name=file.filename or target.name,
        file_path=str(target),
        is_original=False,
    )
    db.add(export)
    db.commit()
    return {"export_id": export.id}


@router.post("/{media_id}/subtitles/upload")
def upload_subtitle(media_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    media = _get_media(db, media_id)
    suffix = Path(file.filename or "subtitle.srt").suffix.lower()
    if suffix not in {".srt", ".vtt"}:
        raise HTTPException(status_code=400, detail="Only .srt and .vtt subtitle files are supported")
    target = unique_path("external_subtitles", suffix, Path(file.filename or "subtitle").stem)
    with target.open("wb") as handle:
        copyfileobj(file.file, handle)
    export = ExportFile(
        media_id=media.id,
        export_type=ExportType.subtitle,
        format=suffix.lstrip("."),
        file_name=file.filename or target.name,
        file_path=str(target),
        is_original=False,
    )
    db.add(export)
    db.flush()
    version = SubtitleVersion(media_id=media.id, export_file_id=export.id, kind=SubtitleKind.uploaded, label=file.filename or "Uploaded subtitle", source_path=str(target))
    db.add(version)
    db.flush()
    for segment in parse_subtitle_file(target):
        db.add(SubtitleSegment(subtitle_version_id=version.id, **segment))
    db.commit()
    return {"export_id": export.id, "subtitle_version_id": version.id}
