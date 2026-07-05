export type TrackType = "video" | "audio" | "subtitle";

export interface Track {
  id: number;
  track_type: TrackType;
  stream_index: number;
  codec: string | null;
  language: string | null;
  duration: number | null;
  width: number | null;
  height: number | null;
  bit_rate: number | null;
}

export interface ExportFile {
  id: number;
  export_type: string;
  format: string;
  file_name: string;
  is_original: boolean;
  created_at: string;
}

export interface SubtitleVersion {
  id: number;
  export_file_id: number | null;
  kind: string;
  label: string;
  is_active: boolean;
  created_at: string;
}

export interface Media {
  id: number;
  source: string;
  source_url: string | null;
  title: string;
  duration: number | null;
  container_format: string | null;
  cover_path: string | null;
  status: string;
  error_message: string | null;
  metadata_json: Record<string, unknown> | null;
  tracks: Track[];
  exports: ExportFile[];
  subtitle_versions: SubtitleVersion[];
}

export interface Task {
  id: number;
  celery_id: string | null;
  media_id: number | null;
  task_type: string;
  status: "queued" | "running" | "completed" | "failed";
  progress: number;
  error_message: string | null;
  result_json: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface SubtitleSegment {
  id?: number | null;
  sequence: number;
  start_seconds: number;
  end_seconds: number;
  text: string;
}
