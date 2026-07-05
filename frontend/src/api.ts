import type { Media, SubtitleSegment, Task } from "./types";

export const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json() as Promise<T>;
}

export async function listMedia(): Promise<Media[]> {
  return request<Media[]>("/api/media");
}

export async function getMedia(id: number): Promise<Media> {
  return request<Media>(`/api/media/${id}`);
}

export async function updateMedia(id: number, title: string): Promise<Media> {
  return request<Media>(`/api/media/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title })
  });
}

export async function deleteMedia(id: number): Promise<{ deleted: boolean; media_id: number }> {
  return request<{ deleted: boolean; media_id: number }>(`/api/media/${id}`, {
    method: "DELETE"
  });
}

export async function uploadMedia(file: File): Promise<{ task_id: number; media_id: number }> {
  const body = new FormData();
  body.append("file", file);
  return request("/api/media/upload", { method: "POST", body });
}

export async function importUrl(url: string): Promise<{ task_id: number; media_id: number }> {
  return request("/api/media/import-url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url })
  });
}

export async function uploadCover(mediaId: number, file: File): Promise<Media> {
  const body = new FormData();
  body.append("file", file);
  return request<Media>(`/api/media/${mediaId}/cover`, { method: "POST", body });
}

export async function uploadExternalAudio(mediaId: number, file: File): Promise<{ export_id: number }> {
  const body = new FormData();
  body.append("file", file);
  return request(`/api/media/${mediaId}/external-audio`, { method: "POST", body });
}

export async function uploadSubtitle(mediaId: number, file: File): Promise<{ export_id: number; subtitle_version_id: number }> {
  const body = new FormData();
  body.append("file", file);
  return request(`/api/media/${mediaId}/subtitles/upload`, { method: "POST", body });
}

export async function createExtractTask(mediaId: number, trackId: number, exportFormat: string, fileName?: string): Promise<{ task_id: number; media_id: number }> {
  return request("/api/tasks/extract", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ media_id: mediaId, track_id: trackId, export_format: exportFormat, file_name: fileName || null })
  });
}

export interface WhisperRuleOptions {
  split_enabled: boolean;
  max_chars: number;
  max_seconds: number;
}

export async function createTranscribeTask(
  mediaId: number,
  audioTrackId: number | null,
  outputFormat: "srt" | "vtt",
  externalAudioExportId?: number | null,
  rules?: WhisperRuleOptions
): Promise<{ task_id: number; media_id: number }> {
  return request("/api/tasks/transcribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      media_id: mediaId,
      audio_track_id: audioTrackId,
      external_audio_export_id: externalAudioExportId || null,
      output_format: outputFormat,
      split_enabled: rules?.split_enabled ?? false,
      max_chars: rules?.max_chars ?? 42,
      max_seconds: rules?.max_seconds ?? 5
    })
  });
}

export async function getTask(id: number): Promise<Task> {
  return request<Task>(`/api/tasks/${id}`);
}

export async function getTaskLogs(id: number): Promise<string> {
  const response = await fetch(`${API_BASE}/api/tasks/${id}/logs`);
  return response.text();
}

export async function getSegments(subtitleId: number): Promise<SubtitleSegment[]> {
  return request<SubtitleSegment[]>(`/api/subtitles/${subtitleId}/segments`);
}

export async function saveSegments(subtitleId: number, label: string, segments: SubtitleSegment[]): Promise<{ subtitle_version_id: number }> {
  return request(`/api/subtitles/${subtitleId}/segments`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label, segments })
  });
}

export async function deleteSubtitle(subtitleId: number): Promise<{ deleted: boolean; subtitle_id: number; media_id: number }> {
  return request<{ deleted: boolean; subtitle_id: number; media_id: number }>(`/api/subtitles/${subtitleId}`, {
    method: "DELETE"
  });
}

export async function exportSubtitle(subtitleId: number, format: "srt" | "vtt", fileName?: string): Promise<{ export_id: number }> {
  return request(`/api/subtitles/${subtitleId}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ format, file_name: fileName || null })
  });
}

export function downloadUrl(exportId: number): string {
  return `${API_BASE}/api/exports/${exportId}/download`;
}

export function mediaSourceUrl(mediaId: number): string {
  return `${API_BASE}/api/media/${mediaId}/source`;
}

export function mediaCoverUrl(mediaId: number): string {
  return `${API_BASE}/api/media/${mediaId}/cover`;
}
