import {
  Captions,
  Check,
  Copy,
  Download,
  Edit3,
  FileText,
  Film,
  Home,
  Link,
  ListMusic,
  Loader2,
  Music,
  Play,
  Plus,
  RefreshCcw,
  Save,
  Scissors,
  Search,
  Settings2,
  Trash2,
  Upload,
  Wand2,
  X
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  createExtractTask,
  createTranscribeTask,
  deleteMedia,
  deleteSubtitle,
  downloadUrl,
  exportSubtitle,
  getMedia,
  getSegments,
  getTask,
  getTaskLogs,
  importUrl,
  listMedia,
  mediaSourceUrl,
  saveSegments,
  updateMedia,
  uploadExternalAudio,
  uploadMedia,
  uploadSubtitle
} from "./api";
import type { Media, SubtitleSegment, Task, Track, TrackType } from "./types";

type ViewMode = "history" | "workspace";

const trackLabels: Record<TrackType, string> = {
  video: "视频轨",
  audio: "音频轨",
  subtitle: "字幕轨"
};

const sourceLabels: Record<string, string> = {
  upload: "本地上传",
  url: "在线链接"
};

const statusLabels: Record<string, string> = {
  queued: "排队中",
  pending: "等待中",
  running: "处理中",
  completed: "已完成",
  ready: "可用",
  failed: "失败"
};

const taskLabels: Record<string, string> = {
  analyze_upload: "分析上传文件",
  import_url: "导入在线视频",
  extract: "导出轨道",
  transcribe: "生成字幕",
  export_subtitle: "导出字幕"
};

const versionKindLabels: Record<string, string> = {
  original: "原始字幕",
  edited: "编辑版本",
  whisper: "Whisper 生成",
  uploaded: "手动上传"
};

const LOCKED_RETURN_DELAY_MS = 1800;

const time = (seconds: number | null | undefined) => {
  if (seconds == null) return "-";
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
};

const defaultFormat = (track: Track) => {
  if (track.track_type === "video") return "mp4";
  if (track.track_type === "audio") return "wav";
  return "srt";
};

const formatOptions = (track: Track) => {
  if (track.track_type === "video") return ["mp4", "mkv"];
  if (track.track_type === "audio") return ["wav", "mp3"];
  return ["srt", "vtt"];
};

const initialMediaId = () => {
  const value = new URLSearchParams(window.location.search).get("mediaId");
  const id = value ? Number(value) : NaN;
  return Number.isFinite(id) && id > 0 ? id : null;
};

const displayVersionLabel = (label: string, kind: string) => {
  const normalized = label
    .replace("Whisper generated subtitle", "Whisper 生成字幕")
    .replace("Original subtitle stream", "原始字幕轨");
  return `${normalized} · ${versionKindLabels[kind] || kind}`;
};

export default function App() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const clipRefs = useRef<Array<HTMLDivElement | null>>([]);
  const lockedReturnTimerRef = useRef<number | null>(null);
  const subtitleLockedRef = useRef(false);
  const autoReturningRef = useRef(false);
  const firstMediaId = initialMediaId();
  const [viewMode, setViewMode] = useState<ViewMode>(firstMediaId ? "workspace" : "history");
  const [mediaItems, setMediaItems] = useState<Media[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(firstMediaId);
  const [media, setMedia] = useState<Media | null>(null);
  const [activeTaskId, setActiveTaskId] = useState<number | null>(null);
  const [task, setTask] = useState<Task | null>(null);
  const [logs, setLogs] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [formats, setFormats] = useState<Record<number, string>>({});
  const [fileNames, setFileNames] = useState<Record<number, string>>({});
  const [subtitleId, setSubtitleId] = useState<number | null>(null);
  const [subtitleDeleteId, setSubtitleDeleteId] = useState<number | null>(null);
  const [showSubtitleDeletePicker, setShowSubtitleDeletePicker] = useState(false);
  const [segments, setSegments] = useState<SubtitleSegment[]>([]);
  const [activeRow, setActiveRow] = useState(0);
  const [playbackRow, setPlaybackRow] = useState(-1);
  const [subtitleLocked, setSubtitleLocked] = useState(false);
  const [captionTime, setCaptionTime] = useState(0);
  const [transcribeFormat, setTranscribeFormat] = useState<"srt" | "vtt">("srt");
  const [externalAudioExportId, setExternalAudioExportId] = useState<number | null>(null);
  const [externalAudioReady, setExternalAudioReady] = useState(false);
  const [splitEnabled, setSplitEnabled] = useState(false);
  const [maxChars, setMaxChars] = useState(42);
  const [maxSeconds, setMaxSeconds] = useState(5);
  const [historyQuery, setHistoryQuery] = useState("");
  const [importMode, setImportMode] = useState<"upload" | "url">("upload");
  const [urlInput, setUrlInput] = useState("");
  const [showLogModal, setShowLogModal] = useState(false);
  const [showSettingsPanel, setShowSettingsPanel] = useState(false);

  const showError = (error: unknown) => {
    setErrorMessage(error instanceof Error ? error.message : String(error));
  };

  const mediaSubtitleVersionIds = (media?.subtitle_versions || []).map((version) => version.id).join(",");

  const refreshList = async () => {
    const items = await listMedia();
    setMediaItems(items);
    if (!selectedId && items.length > 0 && viewMode === "workspace") setSelectedId(items[0].id);
  };

  const refreshMedia = async (id = selectedId) => {
    if (!id) {
      setMedia(null);
      return;
    }
    const next = await getMedia(id);
    setMedia(next);
    setMediaItems((items) => items.map((item) => (item.id === next.id ? next : item)));
  };

  useEffect(() => {
    refreshList().catch(showError);
  }, []);

  useEffect(() => {
    return () => {
      if (lockedReturnTimerRef.current) window.clearTimeout(lockedReturnTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (viewMode === "workspace") {
      refreshMedia(selectedId).catch(showError);
    }
  }, [selectedId, viewMode]);

  useEffect(() => {
    if (!activeTaskId) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const nextTask = await getTask(activeTaskId);
        const nextLogs = await getTaskLogs(activeTaskId);
        setTask(nextTask);
        setLogs(nextLogs);
        if (nextTask.status === "completed" || nextTask.status === "failed") {
          window.clearInterval(timer);
          setActiveTaskId(null);
          await refreshList();
          if (nextTask.media_id && nextTask.media_id === selectedId) {
            setSelectedId(nextTask.media_id);
            if (viewMode === "workspace") await refreshMedia(nextTask.media_id);
          }
          if (nextTask.status === "failed") {
            setErrorMessage(nextTask.error_message || "任务执行失败");
          }
        }
      } catch (error) {
        window.clearInterval(timer);
        setActiveTaskId(null);
        showError(error);
      }
    }, 1400);
    return () => window.clearInterval(timer);
  }, [activeTaskId, selectedId, viewMode]);

  useEffect(() => {
    if (!media) {
      setSubtitleId(null);
      setSegments([]);
      return;
    }
    const versions = media.subtitle_versions || [];
    if (versions.length === 0) {
      setSubtitleId(null);
      setSegments([]);
      return;
    }
    if (!subtitleId || !versions.some((version) => version.id === subtitleId)) {
      setSubtitleId(versions[0].id);
    }
  }, [media?.id, mediaSubtitleVersionIds, subtitleId]);

  useEffect(() => {
    const versions = media?.subtitle_versions || [];
    if (versions.length === 0) {
      setSubtitleDeleteId(null);
      setShowSubtitleDeletePicker(false);
      return;
    }
    if (!subtitleDeleteId || !versions.some((version) => version.id === subtitleDeleteId)) {
      setSubtitleDeleteId(subtitleId || versions[0].id);
    }
  }, [media?.id, mediaSubtitleVersionIds, subtitleDeleteId, subtitleId]);

  useEffect(() => {
    if (!subtitleId) {
      setSegments([]);
      return;
    }
    if (media && !media.subtitle_versions.some((version) => version.id === subtitleId)) {
      setSegments([]);
      return;
    }
    let cancelled = false;
    setActiveRow(0);
    setPlaybackRow(-1);
    setSubtitleLock(false);
    setSegments([]);
    getSegments(subtitleId)
      .then((items) => {
        if (!cancelled) setSegments(items);
      })
      .catch((error) => {
        if (!cancelled) showError(error);
      });
    return () => {
      cancelled = true;
    };
  }, [subtitleId, mediaSubtitleVersionIds]);

  useEffect(() => {
    clipRefs.current = clipRefs.current.slice(0, segments.length);
  }, [segments.length]);

  const grouped = useMemo(() => {
    const base: Record<TrackType, Track[]> = { video: [], audio: [], subtitle: [] };
    for (const track of media?.tracks || []) base[track.track_type].push(track);
    return base;
  }, [media]);

  const filteredMedia = useMemo(() => {
    const keyword = historyQuery.trim().toLowerCase();
    if (!keyword) return mediaItems;
    return mediaItems.filter((item) => {
      return `${item.title} ${item.source_url || ""} ${item.status}`.toLowerCase().includes(keyword);
    });
  }, [historyQuery, mediaItems]);

  const currentCaption = useMemo(() => {
    return segments.find((segment) => captionTime >= segment.start_seconds && captionTime <= segment.end_seconds)?.text || "";
  }, [captionTime, segments]);

  const subtitleExportById = useMemo(() => {
    const byId = new Map<number, NonNullable<Media["exports"]>[number]>();
    for (const item of media?.exports || []) byId.set(item.id, item);
    return byId;
  }, [media]);

  const subtitleFiles = useMemo(() => {
    const versions = [...(media?.subtitle_versions || [])].sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    );
    return versions.map((version, index) => {
      const exportFile = version.export_file_id ? subtitleExportById.get(version.export_file_id) : undefined;
      const rawName = exportFile?.file_name || version.label || `${media?.title || "subtitle"}.${transcribeFormat}`;
      const cleanName = rawName.replace(/^\d+\.\s*/, "");
      return { version, exportFile, index, displayName: `${index + 1}. ${cleanName}` };
    });
  }, [media, subtitleExportById, transcribeFormat]);

  const activeTaskIsTranscribe = task?.task_type.toLowerCase().includes("transcribe") || task?.task_type.toLowerCase().includes("subtitle");
  const activeTaskIsExtract = task?.task_type.toLowerCase().includes("extract");

  const openMedia = (id: number) => {
    setSelectedId(id);
    setViewMode("workspace");
    window.history.replaceState(null, "", `?mediaId=${id}`);
  };

  const goHistory = () => {
    setViewMode("history");
    window.history.replaceState(null, "", window.location.pathname);
    refreshList().catch(showError);
  };

  const scrollToRow = (index: number) => {
    window.requestAnimationFrame(() => {
      clipRefs.current[index]?.scrollIntoView({ block: "center", behavior: "smooth" });
    });
  };

  const scrollToRowAnchor = (index: number, behavior: ScrollBehavior = "smooth") => {
    const container = timelineRef.current;
    const item = clipRefs.current[index];
    if (!container || !item) return;
    const containerRect = container.getBoundingClientRect();
    const itemRect = item.getBoundingClientRect();
    const anchor = container.clientHeight * 0.34;
    const nextTop = container.scrollTop + itemRect.top - containerRect.top - anchor;
    autoReturningRef.current = true;
    container.scrollTo({ top: Math.max(0, nextTop), behavior });
    window.setTimeout(() => {
      autoReturningRef.current = false;
    }, behavior === "smooth" ? 900 : 120);
  };

  const clearLockedReturnTimer = () => {
    if (lockedReturnTimerRef.current) {
      window.clearTimeout(lockedReturnTimerRef.current);
      lockedReturnTimerRef.current = null;
    }
  };

  const setSubtitleLock = (locked: boolean) => {
    subtitleLockedRef.current = locked;
    setSubtitleLocked(locked);
    if (!locked) clearLockedReturnTimer();
  };

  const scrollToCurrentPlayback = () => {
    const currentTime = videoRef.current?.currentTime ?? captionTime;
    const nextPlayback = segments.findIndex((segment) => currentTime >= segment.start_seconds && currentTime <= segment.end_seconds);
    if (nextPlayback >= 0) {
      setPlaybackRow(nextPlayback);
      setActiveRow(nextPlayback);
      scrollToRowAnchor(nextPlayback);
    }
  };

  const scheduleLockedReturn = () => {
    clearLockedReturnTimer();
    if (!subtitleLockedRef.current) return;
    lockedReturnTimerRef.current = window.setTimeout(() => {
      lockedReturnTimerRef.current = null;
      if (!subtitleLockedRef.current) return;
      scrollToCurrentPlayback();
    }, LOCKED_RETURN_DELAY_MS);
  };

  const beginEditingSegment = (index: number) => {
    setActiveRow(index);
    clearLockedReturnTimer();
  };

  const toggleFollowLock = () => {
    if (subtitleLockedRef.current) {
      setSubtitleLock(false);
      return;
    }
    setSubtitleLock(true);
  };

  const handleDeleteMedia = async (id: number) => {
    const target = mediaItems.find((item) => item.id === id) || media;
    const title = target?.title || "当前素材";
    if (!window.confirm(`确定要删除“${title}”吗？原始文件、导出文件和字幕版本都会一并删除。`)) return;
    try {
      await deleteMedia(id);
      setMediaItems((items) => items.filter((item) => item.id !== id));
      if (selectedId === id) {
        setSelectedId(null);
        setMedia(null);
        setSubtitleId(null);
        setSegments([]);
        setTask(null);
        setLogs("");
        setActiveTaskId(null);
        setViewMode("history");
        window.history.replaceState(null, "", window.location.pathname);
      }
      await refreshList();
    } catch (error) {
      showError(error);
    }
  };

  const startTask = (created: { task_id: number; media_id?: number | null }, openWorkspace = true) => {
    setActiveTaskId(created.task_id);
    setTask(null);
    setLogs("");
    if (created.media_id) setSelectedId(created.media_id);
    if (openWorkspace && created.media_id) {
      setViewMode("workspace");
      window.history.replaceState(null, "", `?mediaId=${created.media_id}`);
    }
  };

  const handleUpload = async (file: File | undefined) => {
    if (!file) return;
    try {
      startTask(await uploadMedia(file));
    } catch (error) {
      showError(error);
    }
  };

  const handleImportUrl = async () => {
    if (!urlInput.trim()) return;
    try {
      startTask(await importUrl(urlInput.trim()));
      setUrlInput("");
    } catch (error) {
      showError(error);
    }
  };

  const updateSegment = (index: number, patch: Partial<SubtitleSegment>) => {
    setSegments((items) => items.map((item, itemIndex) => (itemIndex === index ? { ...item, ...patch } : item)));
  };

  const resequence = (items: SubtitleSegment[]) => items.map((item, index) => ({ ...item, sequence: index + 1 }));

  const addSegment = () => {
    const pivot = segments[activeRow];
    const start = pivot ? pivot.end_seconds : 0;
    const next = { id: null, sequence: activeRow + 2, start_seconds: start, end_seconds: start + 2, text: "" };
    const items = [...segments];
    items.splice(activeRow + 1, 0, next);
    setSegments(resequence(items));
    setActiveRow(Math.min(activeRow + 1, items.length - 1));
  };

  const duplicateSegment = (index: number) => {
    const source = segments[index];
    if (!source) return;
    const copy = { ...source, id: null, sequence: source.sequence + 1 };
    const items = [...segments];
    items.splice(index + 1, 0, copy);
    setSegments(resequence(items));
    setActiveRow(index + 1);
  };

  const deleteSegment = () => {
    setSegments(resequence(segments.filter((_, index) => index !== activeRow)));
    setActiveRow(Math.max(0, activeRow - 1));
  };

  const mergeSegment = () => {
    if (activeRow >= segments.length - 1) return;
    const current = segments[activeRow];
    const next = segments[activeRow + 1];
    const mergedText = `${current.text.trim()} ${next.text.trim()}`.replace(/\s+/g, " ").trim();
    const merged = { ...current, end_seconds: next.end_seconds, text: mergedText };
    const items = [...segments];
    items.splice(activeRow, 2, merged);
    setSegments(resequence(items));
  };

  const splitSegment = () => {
    const current = segments[activeRow];
    if (!current) return;
    const midpoint = (current.start_seconds + current.end_seconds) / 2;
    const cut = Math.max(1, Math.floor(current.text.length / 2));
    const first = { ...current, end_seconds: midpoint, text: current.text.slice(0, cut).trim() };
    const second = { id: null, sequence: current.sequence + 1, start_seconds: midpoint, end_seconds: current.end_seconds, text: current.text.slice(cut).trim() };
    const items = [...segments];
    items.splice(activeRow, 1, first, second);
    setSegments(resequence(items));
  };

  const handleVideoTimeUpdate = (nextTime: number) => {
    setCaptionTime(nextTime);
    const nextPlayback = segments.findIndex((segment) => nextTime >= segment.start_seconds && nextTime <= segment.end_seconds);
    setPlaybackRow(nextPlayback);
    if (nextPlayback < 0) return;
    if (subtitleLockedRef.current && !lockedReturnTimerRef.current && !autoReturningRef.current) {
      scrollToRowAnchor(nextPlayback);
    }
  };

  const seekToSegment = (segment: SubtitleSegment, index: number, shouldPlay = true) => {
    setActiveRow(index);
    setPlaybackRow(index);
    setCaptionTime(segment.start_seconds);
    if (!videoRef.current) return;
    videoRef.current.currentTime = segment.start_seconds;
    if (shouldPlay) {
      void videoRef.current.play().catch(() => undefined);
      if (subtitleLockedRef.current) scrollToRowAnchor(index);
    } else {
      setSubtitleLock(true);
      scheduleLockedReturn();
      videoRef.current.pause();
    }
  };

  const focusSegment = (index: number) => {
    beginEditingSegment(index);
    window.setTimeout(() => {
      document.querySelector<HTMLTextAreaElement>(`[data-subtitle-index="${index}"] textarea`)?.focus();
    }, 0);
  };

  const copySegmentText = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch (error) {
      showError(error);
    }
  };

  const handleSaveSegments = async () => {
    if (!subtitleId) return;
    try {
      const result = await saveSegments(subtitleId, "编辑字幕", resequence(segments));
      setSubtitleId(result.subtitle_version_id);
      await refreshMedia();
    } catch (error) {
      showError(error);
    }
  };

  const handleDeleteSubtitle = async (targetId = subtitleDeleteId) => {
    if (!targetId || !media) return;
    const current = media.subtitle_versions.find((version) => version.id === targetId);
    const label = current ? displayVersionLabel(current.label, current.kind) : "选中的字幕";
    if (!window.confirm(`确定要删除“${label}”吗？对应字幕段和未被其它版本引用的字幕文件都会一并删除。`)) return;
    try {
      await deleteSubtitle(targetId);
      const nextMedia = await getMedia(media.id);
      setMedia(nextMedia);
      setMediaItems((items) => items.map((item) => (item.id === nextMedia.id ? nextMedia : item)));
      const currentStillExists = subtitleId ? nextMedia.subtitle_versions.some((version) => version.id === subtitleId) : false;
      const nextVersion = currentStillExists
        ? nextMedia.subtitle_versions.find((version) => version.id === subtitleId)
        : nextMedia.subtitle_versions[0];
      setSubtitleId(nextVersion?.id || null);
      setSubtitleDeleteId(nextVersion?.id || null);
      setShowSubtitleDeletePicker(false);
      if (!nextVersion) setSegments([]);
    } catch (error) {
      showError(error);
    }
  };

  const handleSubtitleExport = async (format: "srt" | "vtt") => {
    if (!subtitleId) return;
    try {
      const result = await exportSubtitle(subtitleId, format);
      await refreshMedia();
      window.open(downloadUrl(result.export_id), "_blank");
    } catch (error) {
      showError(error);
    }
  };

  const renderTaskProgress = (visible: boolean) => {
    if (!visible || !task) return null;
    return (
      <div className="inlineTask">
        <div className="taskHead">
          <span>{taskLabels[task.task_type] || task.task_type}</span>
          <strong>{task.progress}%</strong>
        </div>
        <div className="progress"><span style={{ width: `${task.progress}%` }} /></div>
        <div className={`status ${task.status}`}>{statusLabels[task.status] || task.status}</div>
        {task.error_message && <p className="error">{task.error_message}</p>}
        <button className="logButton" onClick={() => setShowLogModal(true)} disabled={!logs}>
          查看命令行日志
        </button>
      </div>
    );
  };

  const renderTopbar = () => (
    <header className="topbar">
      <div className="topbarBrand">
        {viewMode === "workspace" && (
          <button className="iconButton" onClick={goHistory} title="返回历史记录">
            <Home size={18} />
          </button>
        )}
        <div className="brandMark"><Film size={18} /></div>
        <div>
          <strong>{viewMode === "history" ? "媒体历史记录" : "媒体轨道处理台"}</strong>
          <span>{viewMode === "history" ? "管理导入记录，也可以新建导入任务" : "视频、音频、字幕提取与编辑"}</span>
        </div>
      </div>
      <nav className="topbarNav">
        <button className={viewMode === "history" ? "activeNav" : ""} onClick={goHistory}><Home size={16} />历史记录</button>
        <button disabled={viewMode !== "workspace"} onClick={() => setShowSettingsPanel(true)}><Settings2 size={16} />扩展设置</button>
      </nav>
      <div className="topbarActions">
        {viewMode === "workspace" && media ? (
          <button className="dangerButton" onClick={() => handleDeleteMedia(media.id)}><Trash2 size={16} />删除素材</button>
        ) : (
          <button className="primaryButton" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}><Upload size={16} />新导入</button>
        )}
      </div>
    </header>
  );

  const renderHistory = () => (
    <div className="historyPage">
      {errorMessage && (
        <div className="toast">
          <span>{errorMessage}</span>
          <button onClick={() => setErrorMessage("")}>关闭</button>
        </div>
      )}
      <section className="importCard">
        <div className="importTabs">
          <button className={importMode === "upload" ? "activeTab" : ""} onClick={() => setImportMode("upload")}>上传文件</button>
          <button className={importMode === "url" ? "activeTab" : ""} onClick={() => setImportMode("url")}>粘贴链接</button>
        </div>
        {importMode === "upload" ? (
          <label className="dropZone">
            <Upload size={28} />
            <strong>将音频或视频文件拖到此处上传</strong>
            <span>支持 mp4、mkv、mov、webm、mp3、wav、m4a 等格式</span>
            <input type="file" accept="video/*,audio/*,.mkv,.mp4,.mov,.webm,.mp3,.wav,.m4a" onChange={(event) => handleUpload(event.target.files?.[0])} />
          </label>
        ) : (
          <div className="urlImportBox">
            <Link size={28} />
            <strong>粘贴在线视频链接</strong>
            <div className="urlImportRow">
              <input value={urlInput} onChange={(event) => setUrlInput(event.target.value)} placeholder="https://..." />
              <button className="primaryButton" onClick={handleImportUrl}>开始导入</button>
            </div>
          </div>
        )}
        {task && !selectedId && renderTaskProgress(true)}
      </section>

      <section className="historyCard">
        <div className="historyHeader">
          <div>
            <h2>历史记录</h2>
            <p>查看已导入媒体，点击任意记录进入轨道处理页面。</p>
          </div>
          <button onClick={() => refreshList().catch(showError)}><RefreshCcw size={16} />刷新</button>
        </div>
        <div className="searchBar">
          <Search size={16} />
          <input value={historyQuery} onChange={(event) => setHistoryQuery(event.target.value)} placeholder="搜索标题、链接或状态" />
        </div>
        <div className="historyList">
          {filteredMedia.map((item) => (
            <div className="historyItem" key={item.id} role="button" tabIndex={0} onClick={() => openMedia(item.id)} onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                openMedia(item.id);
              }
            }}>
              <div className="historyIcon">
                {item.tracks.some((track) => track.track_type === "video") ? <Film size={18} /> : <Music size={18} />}
              </div>
              <div>
                <strong>{item.title}</strong>
                <span>{sourceLabels[item.source] || item.source} · {time(item.duration)} · {item.tracks.length} 条轨道</span>
                {item.source_url && <small>{item.source_url}</small>}
              </div>
              <em className={`historyStatus ${item.status}`}>{statusLabels[item.status] || item.status}</em>
              <button
                className="iconButton dangerIcon"
                title="删除素材"
                onClick={(event) => {
                  event.stopPropagation();
                  void handleDeleteMedia(item.id);
                }}
              >
                <Trash2 size={16} />
              </button>
            </div>
          ))}
          {filteredMedia.length === 0 && <div className="emptyHistory">暂无匹配记录</div>}
        </div>
      </section>
    </div>
  );

  const renderWorkspace = () => (
    <div className="shell">
      <main className="workspace">
        {errorMessage && (
          <div className="toast">
            <span>{errorMessage}</span>
            <button onClick={() => setErrorMessage("")}>关闭</button>
          </div>
        )}

        {media ? (
          <>
            <section className="mediaHeader">
              <div>
                <label className="fieldLabel">媒体标题</label>
                <input
                  className="titleInput"
                  value={media.title}
                  onChange={(event) => setMedia({ ...media, title: event.target.value })}
                  onBlur={async () => {
                    try {
                      setMedia(await updateMedia(media.id, media.title));
                    } catch (error) {
                      showError(error);
                    }
                  }}
                />
              </div>
              <dl>
                <div><dt>状态</dt><dd>{statusLabels[media.status] || media.status}</dd></div>
                <div><dt>时长</dt><dd>{time(media.duration)}</dd></div>
                <div><dt>来源</dt><dd>{sourceLabels[media.source] || media.source}</dd></div>
              </dl>
            </section>

            <section className="hero">
              <div className="videoWrap">
                <video
                  ref={videoRef}
                  src={mediaSourceUrl(media.id)}
                  controls
                  onTimeUpdate={(event) => handleVideoTimeUpdate(event.currentTarget.currentTime)}
                />
                {currentCaption && <div className="captionPreview">{currentCaption}</div>}
              </div>
            </section>

            <section className="tracks">
              <div className="sectionHead">
                <h2><ListMusic size={20} />轨道列表</h2>
                <button onClick={() => refreshMedia().catch(showError)}><RefreshCcw size={16} />刷新</button>
              </div>
              {renderTaskProgress(Boolean(activeTaskIsExtract))}
              {(["video", "audio", "subtitle"] as const).map((kind) => (
                <div className="trackGroup" key={kind}>
                  <h3>{trackLabels[kind]}</h3>
                  {grouped[kind].length === 0 ? <p className="muted">未检测到{trackLabels[kind]}</p> : grouped[kind].map((track) => (
                    <div className="trackRow" key={track.id}>
                      <div>
                        <strong>#{track.stream_index} {track.codec || "未知编码"}</strong>
                        <span>{track.language || "未知语言"} · {track.width && track.height ? `${track.width}×${track.height}` : time(track.duration)}</span>
                      </div>
                      <input placeholder="导出文件名" value={fileNames[track.id] || ""} onChange={(event) => setFileNames({ ...fileNames, [track.id]: event.target.value })} />
                      <select value={formats[track.id] || defaultFormat(track)} onChange={(event) => setFormats({ ...formats, [track.id]: event.target.value })}>
                        {formatOptions(track).map((option) => <option key={option}>{option}</option>)}
                      </select>
                      <button
                        onClick={async () => {
                          try {
                            startTask(await createExtractTask(media.id, track.id, formats[track.id] || defaultFormat(track), fileNames[track.id]), false);
                          } catch (error) {
                            showError(error);
                          }
                        }}
                      >
                        <Download size={16} />导出
                      </button>
                    </div>
                  ))}
                </div>
              ))}
            </section>

            <section className="fallbacks">
              <div className="sectionHead">
                <h2><Wand2 size={20} />Whisper 字幕生成</h2>
                <span className="sectionHint">没有字幕轨时，可从音频自动生成字幕</span>
              </div>
              <div className="whisperGrid">
                <label>
                  <span>字幕格式</span>
                  <select value={transcribeFormat} onChange={(event) => setTranscribeFormat(event.target.value as "srt" | "vtt")}>
                    <option value="srt">SRT</option>
                    <option value="vtt">VTT</option>
                  </select>
                </label>
                <label>
                  <span>生成规则</span>
                  <select value={splitEnabled ? "short" : "original"} onChange={(event) => setSplitEnabled(event.target.value === "short")}>
                    <option value="original">Whisper 原始分段</option>
                    <option value="short">自动短句分段</option>
                  </select>
                </label>
                <label>
                  <span>每行最多字符</span>
                  <input type="number" min={12} max={120} value={maxChars} disabled={!splitEnabled} onChange={(event) => setMaxChars(Number(event.target.value))} />
                </label>
                <label>
                  <span>每行最长秒数</span>
                  <input type="number" min={1} max={15} step={0.5} value={maxSeconds} disabled={!splitEnabled} onChange={(event) => setMaxSeconds(Number(event.target.value))} />
                </label>
              </div>
              <div className="fallbackGrid">
                <button
                  className="primaryButton"
                  onClick={async () => {
                    try {
                      startTask(await createTranscribeTask(media.id, grouped.audio[0]?.id || null, transcribeFormat, externalAudioExportId, {
                        split_enabled: splitEnabled,
                        max_chars: maxChars,
                        max_seconds: maxSeconds
                      }), false);
                    } catch (error) {
                      showError(error);
                    }
                  }}
                >
                  <Captions size={16} />生成字幕
                </button>
                <label className="smallUpload">
                  <Music size={16} />
                  上传外部音频
                  <input type="file" accept="audio/*" onChange={async (event) => {
                    const file = event.target.files?.[0];
                    if (!file) return;
                    try {
                      const result = await uploadExternalAudio(media.id, file);
                      setExternalAudioExportId(result.export_id);
                      setExternalAudioReady(true);
                    } catch (error) {
                      showError(error);
                    }
                  }} />
                </label>
                <label className="smallUpload">
                  <FileText size={16} />
                  上传已有字幕
                  <input type="file" accept=".srt,.vtt" onChange={async (event) => {
                    const file = event.target.files?.[0];
                    if (!file) return;
                    try {
                      const result = await uploadSubtitle(media.id, file);
                      setSubtitleId(result.subtitle_version_id);
                      await refreshMedia();
                    } catch (error) {
                      showError(error);
                    }
                  }} />
                </label>
              </div>
              {externalAudioReady && <p className="inlineNote">外部音频已绑定，将优先用于生成字幕。</p>}
              <div className="subtitleOutputPanel">
                <div className="miniSectionHead">
                  <strong>输出字幕轨文件</strong>
                  <span>{subtitleFiles.length} 个</span>
                </div>
                <div className="subtitleFileList">
                  {subtitleFiles.length ? subtitleFiles.map((file) => {
                    const exportId = file.exportFile?.id;
                    return (
                      <div
                        className={subtitleId === file.version.id ? "subtitleFile active" : "subtitleFile"}
                        key={file.version.id}
                        onClick={() => setSubtitleId(file.version.id)}
                      >
                        <FileText size={16} />
                        <div>
                          <strong>{file.displayName}</strong>
                          <span>{versionKindLabels[file.version.kind] || file.version.kind}</span>
                        </div>
                        {exportId && (
                          <button
                            title="下载字幕文件"
                            onClick={(event) => {
                              event.stopPropagation();
                              window.open(downloadUrl(exportId), "_blank");
                            }}
                          >
                            <Download size={14} />下载
                          </button>
                        )}
                        <button
                          className="subtitleFileDelete"
                          title="删除字幕文件"
                          onClick={(event) => {
                            event.stopPropagation();
                            void handleDeleteSubtitle(file.version.id);
                          }}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    );
                  }) : <p className="muted emptySubtitleFiles">暂无输出字幕文件</p>}
                </div>
              </div>
              {renderTaskProgress(Boolean(activeTaskIsTranscribe))}
            </section>
          </>
        ) : (
          <div className="empty">请选择一个媒体文件进入处理页面。</div>
        )}
      </main>

      <aside className="editor">
        <div className="sectionHead">
          <h2><Captions size={20} />字幕编辑器</h2>
          {task?.status === "running" && activeTaskIsTranscribe && <Loader2 className="spin" size={18} />}
        </div>
        {media?.subtitle_versions?.length ? (
          <>
            <div className="subtitleVersionRow">
              <select className="full" value={subtitleId || ""} onChange={(event) => setSubtitleId(Number(event.target.value))}>
                {media.subtitle_versions.map((version) => (
                  <option value={version.id} key={version.id}>{displayVersionLabel(version.label, version.kind)}</option>
                ))}
              </select>
              <button
                className="iconButton dangerIcon"
                onClick={() => {
                  setSubtitleDeleteId(subtitleId || media.subtitle_versions[0]?.id || null);
                  setShowSubtitleDeletePicker((visible) => !visible);
                }}
                title="选择要删除的字幕文件"
              >
                <Trash2 size={16} />
              </button>
            </div>
            {showSubtitleDeletePicker && (
              <div className="subtitleDeletePicker">
                <label>
                  <span>选择要删除的字幕</span>
                  <select value={subtitleDeleteId || ""} onChange={(event) => setSubtitleDeleteId(Number(event.target.value))}>
                    {media.subtitle_versions.map((version) => (
                      <option value={version.id} key={version.id}>{displayVersionLabel(version.label, version.kind)}</option>
                    ))}
                  </select>
                </label>
                <button className="dangerButton" onClick={() => handleDeleteSubtitle()} disabled={!subtitleDeleteId}>
                  <Trash2 size={16} />确认删除
                </button>
                <button onClick={() => setShowSubtitleDeletePicker(false)}>取消</button>
              </div>
            )}
            <div className="editorToolbar">
              <button onClick={addSegment} title="新增"><Plus size={15} /></button>
              <button onClick={mergeSegment} title="合并"><Check size={15} />合并</button>
              <button onClick={splitSegment} title="拆分"><Scissors size={15} />拆分</button>
              <button onClick={deleteSegment} title="删除"><Trash2 size={15} /></button>
              <button onClick={handleSaveSegments} title="保存"><Save size={15} />保存</button>
              <button className={subtitleLocked ? "lockButton locked" : "lockButton"} onClick={toggleFollowLock} title={subtitleLocked ? "取消锁定，停止固定播放字幕位置" : "锁定字幕列表，让当前播放字幕固定在同一位置切换"}>
                <Play size={15} />{subtitleLocked ? "取消锁定" : "锁定"}
              </button>
            </div>
            <div
              className="subtitleTimeline"
              ref={timelineRef}
              onScroll={() => {
                if (!subtitleLockedRef.current || autoReturningRef.current) return;
                scheduleLockedReturn();
              }}
            >
              {segments.map((segment, index) => (
                <div
                  key={`${segment.id || "new"}-${index}`}
                  ref={(node) => { clipRefs.current[index] = node; }}
                  data-subtitle-index={index}
                  className={[
                    "subtitleClip",
                    activeRow === index ? "active" : "",
                    playbackRow === index ? "playing" : ""
                  ].filter(Boolean).join(" ")}
                  onClick={() => seekToSegment(segment, index, true)}
                >
                  <div className="clipTime">
                    <span>{time(segment.start_seconds)}</span>
                    <small>{time(segment.end_seconds)}</small>
                  </div>
                  <div className="clipBody">
                    <div className="clipActions" onClick={(event) => event.stopPropagation()}>
                      <button title="播放" onClick={() => seekToSegment(segment, index, true)}><Play size={14} /></button>
                      <button title="复制文本" onClick={() => copySegmentText(segment.text)}><Copy size={14} /></button>
                      <button title="复制片段" onClick={() => duplicateSegment(index)}><Plus size={14} /></button>
                      <button title="编辑" onClick={() => focusSegment(index)}><Edit3 size={14} /></button>
                    </div>
                    <div className="clipFields" onClick={(event) => event.stopPropagation()}>
                      <input type="number" step="0.01" value={segment.start_seconds} onFocus={() => beginEditingSegment(index)} onChange={(event) => updateSegment(index, { start_seconds: Number(event.target.value) })} />
                      <input type="number" step="0.01" value={segment.end_seconds} onFocus={() => beginEditingSegment(index)} onChange={(event) => updateSegment(index, { end_seconds: Number(event.target.value) })} />
                    </div>
                    <textarea value={segment.text} onFocus={() => beginEditingSegment(index)} onClick={(event) => event.stopPropagation()} onChange={(event) => updateSegment(index, { text: event.target.value })} />
                  </div>
                </div>
              ))}
            </div>
            <div className="exportButtons">
              <button onClick={() => handleSubtitleExport("srt")}><Download size={16} />导出 SRT</button>
              <button onClick={() => handleSubtitleExport("vtt")}><Download size={16} />导出 VTT</button>
            </div>
          </>
        ) : (
          <p className="muted">检测或生成字幕后，可在这里逐行编辑字幕、调整时间轴并重新导出。</p>
        )}
      </aside>
    </div>
  );

  return (
    <>
      <div className="appShell">
        {renderTopbar()}
        {viewMode === "history" ? renderHistory() : renderWorkspace()}
      </div>
      {showLogModal && (
        <div className="modalBackdrop" onClick={() => setShowLogModal(false)}>
          <div className="modalPanel logModal" onClick={(event) => event.stopPropagation()}>
            <div className="modalHead">
              <div>
                <strong>命令行输出日志</strong>
                <span>{task ? taskLabels[task.task_type] || task.task_type : "当前任务"}</span>
              </div>
              <button className="iconButton" onClick={() => setShowLogModal(false)}><X size={16} /></button>
            </div>
            <pre className="logs modalLogs">{logs || "暂无日志"}</pre>
          </div>
        </div>
      )}
      {showSettingsPanel && (
        <div className="modalBackdrop" onClick={() => setShowSettingsPanel(false)}>
          <div className="modalPanel settingsModal" onClick={(event) => event.stopPropagation()}>
            <div className="modalHead">
              <div>
                <strong>扩展设置</strong>
                <span>这些设置会影响下一次 Whisper 字幕生成</span>
              </div>
              <button className="iconButton" onClick={() => setShowSettingsPanel(false)}><X size={16} /></button>
            </div>
            <div className="settingsGrid">
              <label>
                <span>默认字幕格式</span>
                <select value={transcribeFormat} onChange={(event) => setTranscribeFormat(event.target.value as "srt" | "vtt")}>
                  <option value="srt">SRT</option>
                  <option value="vtt">VTT</option>
                </select>
              </label>
              <label>
                <span>Whisper 生成规则</span>
                <select value={splitEnabled ? "short" : "original"} onChange={(event) => setSplitEnabled(event.target.value === "short")}>
                  <option value="original">Whisper 原始分段</option>
                  <option value="short">自动短句分段</option>
                </select>
              </label>
              <label>
                <span>每行最多字符</span>
                <input type="number" min={12} max={120} value={maxChars} disabled={!splitEnabled} onChange={(event) => setMaxChars(Number(event.target.value))} />
              </label>
              <label>
                <span>每行最长秒数</span>
                <input type="number" min={1} max={15} step={0.5} value={maxSeconds} disabled={!splitEnabled} onChange={(event) => setMaxSeconds(Number(event.target.value))} />
              </label>
            </div>
            <div className="settingsNotes">
              <p><strong>字幕命名：</strong>Whisper 生成文件按视频标题命名，列表按 1、2、3 自动编号。</p>
              <p><strong>日志查看：</strong>任务进度区只显示状态，完整命令行输出可通过“查看命令行日志”打开。</p>
              <p><strong>删除策略：</strong>删除字幕文件时会删除字幕段和未被其它版本引用的导出文件，不会删除原视频。</p>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
