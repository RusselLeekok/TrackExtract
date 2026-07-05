from __future__ import annotations

import re
from pathlib import Path


def seconds_to_srt_time(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    ms = total_ms % 1000
    total_seconds = total_ms // 1000
    s = total_seconds % 60
    total_minutes = total_seconds // 60
    m = total_minutes % 60
    h = total_minutes // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def seconds_to_vtt_time(seconds: float) -> str:
    return seconds_to_srt_time(seconds).replace(",", ".")


def parse_timestamp(value: str) -> float:
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid subtitle timestamp: {value}")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds


def parse_subtitle_file(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"^WEBVTT.*?\n\n", "", text, flags=re.DOTALL)
    blocks = [block.strip() for block in re.split(r"\n{2,}", text) if block.strip()]
    segments: list[dict] = []
    sequence = 1
    for block in blocks:
        lines = block.split("\n")
        if lines and lines[0].strip().isdigit():
            lines = lines[1:]
        if not lines or "-->" not in lines[0]:
            continue
        start_raw, end_raw = [part.strip().split()[0] for part in lines[0].split("-->", 1)]
        segments.append(
            {
                "sequence": sequence,
                "start_seconds": parse_timestamp(start_raw),
                "end_seconds": parse_timestamp(end_raw),
                "text": "\n".join(lines[1:]).strip(),
            }
        )
        sequence += 1
    return segments


def write_srt(path: Path, segments: list[dict]) -> None:
    lines: list[str] = []
    for index, segment in enumerate(sorted(segments, key=lambda item: item["sequence"]), start=1):
        lines.append(str(index))
        lines.append(f"{seconds_to_srt_time(segment['start_seconds'])} --> {seconds_to_srt_time(segment['end_seconds'])}")
        lines.append(segment["text"].strip())
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_vtt(path: Path, segments: list[dict]) -> None:
    lines = ["WEBVTT", ""]
    for segment in sorted(segments, key=lambda item: item["sequence"]):
        lines.append(f"{seconds_to_vtt_time(segment['start_seconds'])} --> {seconds_to_vtt_time(segment['end_seconds'])}")
        lines.append(segment["text"].strip())
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")

