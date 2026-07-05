from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MediaTrack, TaskRecord, TaskStatus, TaskType
from app.schemas import ExtractRequest, TaskCreated, TaskRead, TranscribeRequest
from app.tasks import extract_track_task, transcribe_media_task

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("/extract", response_model=TaskCreated)
def create_extract_task(payload: ExtractRequest, db: Session = Depends(get_db)) -> TaskCreated:
    track = db.get(MediaTrack, payload.track_id)
    if not track or track.media_id != payload.media_id:
        raise HTTPException(status_code=404, detail="Track not found for media")
    task = TaskRecord(media_id=payload.media_id, task_type=TaskType.extract, status=TaskStatus.queued)
    db.add(task)
    db.flush()
    task_id = task.id
    db.commit()
    result = extract_track_task.delay(task_id, payload.media_id, payload.track_id, payload.export_format, payload.file_name)
    task = db.get(TaskRecord, task_id)
    task.celery_id = result.id
    db.commit()
    return TaskCreated(task_id=task_id, media_id=payload.media_id)


@router.post("/transcribe", response_model=TaskCreated)
def create_transcribe_task(payload: TranscribeRequest, db: Session = Depends(get_db)) -> TaskCreated:
    task = TaskRecord(media_id=payload.media_id, task_type=TaskType.transcribe, status=TaskStatus.queued)
    db.add(task)
    db.flush()
    task_id = task.id
    db.commit()
    result = transcribe_media_task.delay(
        task_id,
        payload.media_id,
        payload.audio_track_id,
        payload.external_audio_export_id,
        payload.output_format,
        payload.language,
        payload.split_enabled,
        payload.max_chars,
        payload.max_seconds,
    )
    task = db.get(TaskRecord, task_id)
    task.celery_id = result.id
    db.commit()
    return TaskCreated(task_id=task_id, media_id=payload.media_id)


@router.get("/{task_id}", response_model=TaskRead)
def read_task(task_id: int, db: Session = Depends(get_db)) -> TaskRecord:
    task = db.get(TaskRecord, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/{task_id}/logs", response_class=PlainTextResponse)
def read_task_logs(task_id: int, db: Session = Depends(get_db)) -> str:
    task = db.get(TaskRecord, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.log_path or not Path(task.log_path).exists():
        return ""
    return Path(task.log_path).read_text(encoding="utf-8", errors="replace")
