from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ExportFile, ExportType, SubtitleKind, SubtitleSegment, SubtitleVersion
from app.schemas import SubtitleExportRequest, SubtitleSaveRequest, SubtitleSegmentRead
from app.services.storage import storage_root, unique_path
from app.services.subtitles import write_srt, write_vtt

router = APIRouter(prefix="/api/subtitles", tags=["subtitles"])


def _get_version(db: Session, subtitle_id: int) -> SubtitleVersion:
    version = db.get(SubtitleVersion, subtitle_id)
    if not version:
        raise HTTPException(status_code=404, detail="Subtitle version not found")
    return version


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


def _path_is_referenced(db: Session, path: str) -> bool:
    if not path:
        return False
    version_id = db.execute(
        select(SubtitleVersion.id)
        .where(SubtitleVersion.source_path == path)
        .limit(1)
    ).scalar_one_or_none()
    if version_id is not None:
        return True
    export_id = db.execute(
        select(ExportFile.id)
        .where(ExportFile.file_path == path)
        .limit(1)
    ).scalar_one_or_none()
    return export_id is not None


@router.get("/{subtitle_id}/segments", response_model=list[SubtitleSegmentRead])
def read_segments(subtitle_id: int, db: Session = Depends(get_db)) -> list[SubtitleSegment]:
    version = _get_version(db, subtitle_id)
    return sorted(version.segments, key=lambda item: item.sequence)


@router.put("/{subtitle_id}/segments")
def save_segments(subtitle_id: int, payload: SubtitleSaveRequest, db: Session = Depends(get_db)) -> dict:
    source = _get_version(db, subtitle_id)
    target = source
    if SubtitleKind(source.kind) != SubtitleKind.edited:
        target = SubtitleVersion(
            media_id=source.media_id,
            export_file_id=source.export_file_id,
            kind=SubtitleKind.edited,
            label=payload.label or f"Edited from {source.label}",
            source_path=source.source_path,
        )
        db.add(target)
        db.flush()
    else:
        target.label = payload.label or target.label
        for segment in list(target.segments):
            db.delete(segment)
        db.flush()

    previous_end = 0.0
    for item in sorted(payload.segments, key=lambda segment: segment.sequence):
        if item.end_seconds <= item.start_seconds:
            raise HTTPException(status_code=400, detail="Subtitle segment end time must be after start time")
        if item.start_seconds < previous_end:
            raise HTTPException(status_code=400, detail="Subtitle segments cannot overlap")
        previous_end = item.end_seconds
        db.add(
            SubtitleSegment(
                subtitle_version_id=target.id,
                sequence=item.sequence,
                start_seconds=item.start_seconds,
                end_seconds=item.end_seconds,
                text=item.text,
                alignment_json=item.alignment_json,
            )
        )
    db.commit()
    return {"subtitle_version_id": target.id}


@router.delete("/{subtitle_id}")
def delete_subtitle(subtitle_id: int, db: Session = Depends(get_db)) -> dict:
    version = _get_version(db, subtitle_id)
    media_id = version.media_id
    export_file_id = version.export_file_id
    candidate_paths = {version.source_path or ""}
    if export_file_id:
        export = db.get(ExportFile, export_file_id)
        if export and export.file_path:
            candidate_paths.add(export.file_path)

    db.execute(
        delete(SubtitleSegment)
        .where(SubtitleSegment.subtitle_version_id == subtitle_id)
        .execution_options(synchronize_session=False)
    )
    db.execute(
        delete(SubtitleVersion)
        .where(SubtitleVersion.id == subtitle_id)
        .execution_options(synchronize_session=False)
    )
    db.flush()

    if export_file_id:
        still_used = db.execute(
            select(SubtitleVersion.id)
            .where(SubtitleVersion.export_file_id == export_file_id)
            .limit(1)
        ).scalar_one_or_none()
        if still_used is None:
            db.execute(
                delete(ExportFile)
                .where(ExportFile.id == export_file_id)
                .execution_options(synchronize_session=False)
            )
            db.flush()

    removable_paths = {path for path in candidate_paths if path and not _path_is_referenced(db, path)}
    db.commit()
    _delete_storage_files(removable_paths)
    return {"deleted": True, "subtitle_id": subtitle_id, "media_id": media_id}


@router.post("/{subtitle_id}/export")
def export_subtitle(subtitle_id: int, payload: SubtitleExportRequest, db: Session = Depends(get_db)) -> dict:
    version = _get_version(db, subtitle_id)
    segments = [
        {
            "sequence": segment.sequence,
            "start_seconds": segment.start_seconds,
            "end_seconds": segment.end_seconds,
            "text": segment.text,
        }
        for segment in sorted(version.segments, key=lambda item: item.sequence)
    ]
    output = unique_path("exports", payload.format, Path(payload.file_name or version.label).stem)
    if payload.format == "srt":
        write_srt(output, segments)
    else:
        write_vtt(output, segments)
    export = ExportFile(
        media_id=version.media_id,
        export_type=ExportType.subtitle,
        format=payload.format,
        file_name=payload.file_name or output.name,
        file_path=str(output),
        is_original=False,
    )
    db.add(export)
    db.flush()
    version.export_file_id = export.id
    db.commit()
    return {"export_id": export.id}
