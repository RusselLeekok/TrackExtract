from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class MediaSource(str, Enum):
    upload = "upload"
    url = "url"


class MediaStatus(str, Enum):
    pending = "pending"
    ready = "ready"
    failed = "failed"


class TrackType(str, Enum):
    video = "video"
    audio = "audio"
    subtitle = "subtitle"


class TaskType(str, Enum):
    analyze_upload = "analyze_upload"
    import_url = "import_url"
    extract = "extract"
    transcribe = "transcribe"
    export_subtitle = "export_subtitle"


class TaskStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class ExportType(str, Enum):
    video = "video"
    audio = "audio"
    subtitle = "subtitle"
    cover = "cover"


class SubtitleKind(str, Enum):
    original = "original"
    edited = "edited"
    whisper = "whisper"
    uploaded = "uploaded"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class MediaItem(TimestampMixin, Base):
    __tablename__ = "media_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[MediaSource] = mapped_column(String(20), default=MediaSource.upload)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(String(255), default="Untitled media")
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    container_format: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cover_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[MediaStatus] = mapped_column(String(20), default=MediaStatus.pending)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    tracks: Mapped[list["MediaTrack"]] = relationship(back_populates="media", cascade="all, delete-orphan")
    tasks: Mapped[list["TaskRecord"]] = relationship(back_populates="media")
    exports: Mapped[list["ExportFile"]] = relationship(back_populates="media")
    subtitle_versions: Mapped[list["SubtitleVersion"]] = relationship(back_populates="media")


class MediaTrack(TimestampMixin, Base):
    __tablename__ = "media_tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    media_id: Mapped[int] = mapped_column(ForeignKey("media_items.id"), index=True)
    track_type: Mapped[TrackType] = mapped_column(String(20))
    stream_index: Mapped[int] = mapped_column(Integer)
    codec: Mapped[str | None] = mapped_column(String(80), nullable=True)
    language: Mapped[str | None] = mapped_column(String(40), nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bit_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_json: Mapped[dict] = mapped_column(JSON)

    media: Mapped[MediaItem] = relationship(back_populates="tracks")


class TaskRecord(TimestampMixin, Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    celery_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    media_id: Mapped[int | None] = mapped_column(ForeignKey("media_items.id"), nullable=True, index=True)
    task_type: Mapped[TaskType] = mapped_column(String(40))
    status: Mapped[TaskStatus] = mapped_column(String(20), default=TaskStatus.queued)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    media: Mapped[MediaItem | None] = relationship(back_populates="tasks")


class ExportFile(TimestampMixin, Base):
    __tablename__ = "export_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    media_id: Mapped[int] = mapped_column(ForeignKey("media_items.id"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    export_type: Mapped[ExportType] = mapped_column(String(20))
    format: Mapped[str] = mapped_column(String(20))
    file_name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(Text)
    is_original: Mapped[bool] = mapped_column(Boolean, default=False)

    media: Mapped[MediaItem] = relationship(back_populates="exports")


class SubtitleVersion(TimestampMixin, Base):
    __tablename__ = "subtitle_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    media_id: Mapped[int] = mapped_column(ForeignKey("media_items.id"), index=True)
    export_file_id: Mapped[int | None] = mapped_column(ForeignKey("export_files.id"), nullable=True)
    kind: Mapped[SubtitleKind] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(255), default="Subtitle")
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    media: Mapped[MediaItem] = relationship(back_populates="subtitle_versions")
    segments: Mapped[list["SubtitleSegment"]] = relationship(
        back_populates="version", cascade="all, delete-orphan", order_by="SubtitleSegment.sequence"
    )


class SubtitleSegment(TimestampMixin, Base):
    __tablename__ = "subtitle_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subtitle_version_id: Mapped[int] = mapped_column(ForeignKey("subtitle_versions.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    start_seconds: Mapped[float] = mapped_column(Float)
    end_seconds: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text)

    version: Mapped[SubtitleVersion] = relationship(back_populates="segments")

