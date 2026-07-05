from pathlib import Path
from uuid import uuid4

from app.config import get_settings


def storage_root() -> Path:
    root = get_settings().storage_root
    root.mkdir(parents=True, exist_ok=True)
    return root


def ensure_dir(name: str) -> Path:
    path = storage_root() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def unique_path(folder: str, suffix: str, stem: str | None = None) -> Path:
    safe_stem = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in (stem or uuid4().hex))
    return ensure_dir(folder) / f"{safe_stem}_{uuid4().hex[:10]}.{suffix.lstrip('.')}"

