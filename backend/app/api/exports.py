from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ExportFile

router = APIRouter(prefix="/api/exports", tags=["exports"])


@router.get("/{export_id}/download")
def download_export(export_id: int, db: Session = Depends(get_db)) -> FileResponse:
    export = db.get(ExportFile, export_id)
    if not export:
        raise HTTPException(status_code=404, detail="Export not found")
    if not Path(export.file_path).exists():
        raise HTTPException(status_code=404, detail="Export file missing on disk")
    return FileResponse(export.file_path, filename=export.file_name)

