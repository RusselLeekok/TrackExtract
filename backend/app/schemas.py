from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class UrlImportRequest(BaseModel):
    url: str


class MediaUpdateRequest(BaseModel):
    title: str | None = None


class TrackRead(BaseModel):
    id: int
    track_type: str
    stream_index: int
    codec: str | None
    language: str | None
    duration: float | None
    width: int | None
    height: int | None
    bit_rate: int | None

    model_config = {"from_attributes": True}


class ExportFileRead(BaseModel):
    id: int
    export_type: str
    format: str
    file_name: str
    is_original: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SubtitleVersionRead(BaseModel):
    id: int
    export_file_id: int | None
    kind: str
    label: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class MediaRead(BaseModel):
    id: int
    source: str
    source_url: str | None
    title: str
    duration: float | None
    container_format: str | None
    cover_path: str | None
    status: str
    error_message: str | None
    metadata_json: dict | None
    tracks: list[TrackRead] = []
    exports: list[ExportFileRead] = []
    subtitle_versions: list[SubtitleVersionRead] = []

    model_config = {"from_attributes": True}


class TaskRead(BaseModel):
    id: int
    celery_id: str | None
    media_id: int | None
    task_type: str
    status: str
    progress: int
    error_message: str | None
    result_json: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskCreated(BaseModel):
    task_id: int
    media_id: int | None = None


class ExtractRequest(BaseModel):
    media_id: int
    track_id: int
    export_format: Literal["mp4", "mkv", "wav", "mp3", "srt", "vtt"]
    file_name: str | None = None


class TranscribeRequest(BaseModel):
    media_id: int
    audio_track_id: int | None = None
    external_audio_export_id: int | None = None
    output_format: Literal["srt", "vtt"] = "srt"
    language: str | None = None
    split_enabled: bool = False
    max_chars: int = Field(default=42, ge=12, le=120)
    max_seconds: float = Field(default=5.0, ge=1.0, le=15.0)


class SubtitleSegmentIn(BaseModel):
    id: int | None = None
    sequence: int
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    text: str
    alignment_json: dict | None = None


class SubtitleSegmentRead(SubtitleSegmentIn):
    id: int

    model_config = {"from_attributes": True}


class SubtitleSaveRequest(BaseModel):
    label: str | None = None
    segments: list[SubtitleSegmentIn]


class SubtitleExportRequest(BaseModel):
    format: Literal["srt", "vtt"]
    file_name: str | None = None
