"""Unified audio/video download via yt-dlp."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..data_paths import (
    media_audio_search_dirs,
    media_subs_search_dirs,
    media_video_search_dirs,
    online_audio_dir,
    online_subs_dir,
    online_video_dir,
    youtube_audio_dir,
    youtube_subs_dir,
    youtube_video_dir,
)
from ..logging_config import configure_logging
from ..platforms import (
    PLATFORM_KUAISHOU,
    PLATFORM_LOCAL,
    PLATFORM_YOUTUBE,
    detect_platform,
    platform_download_hint,
)
from ..providers.youtube import build_youtube_metadata, get_youtube_info
from ..providers.ytdlp_common import (
    apply_platform_ydl_options,
    build_base_ydl_opts,
    build_media_metadata,
    extract_media_info,
    find_downloaded_file,
)
from ..text_utils import format_time, sanitize_filename

logger = configure_logging()

AUDIO_EXTS = ["mp3", "m4a", "webm", "opus", "aac", "wav"]
VIDEO_EXTS = ["mp4", "mkv", "webm", "flv", "mov"]
SUBTITLE_EXTS = ["srt", "vtt", "json3", "ttml", "ass", "ssa"]

# Prefer merged DASH (HD) then progressive; needs ffmpeg for non-progressive.
# Prefer H.264 when available for broader player compatibility after merge to mp4.
VIDEO_FORMAT = (
    "bv*[vcodec^=avc1]+ba/"
    "bv*+ba/"
    "b/"
    "bestvideo*+bestaudio/"
    "best"
)
# Progressive-only fallback when DASH streams return HTTP 403 mid-download.
VIDEO_FORMAT_PROGRESSIVE_FALLBACK = (
    "best[acodec!=none][vcodec!=none]/"
    "b/"
    "best"
)

# Prefer user-facing subtitle languages; yt-dlp also accepts "all".
DEFAULT_SUBTITLE_LANGS = [
    "zh",
    "zh-Hans",
    "zh-CN",
    "zh-Hant",
    "zh-TW",
    "en",
    "en-US",
    "en-GB",
]


def _probe_video_resolution(path: str | Path) -> Optional[tuple[int, int]]:
    """Return (width, height) via ffprobe, or None if unavailable."""
    from .ffmpeg_tools import ensure_ffmpeg_on_path, resolve_ffprobe

    ensure_ffmpeg_on_path()
    ffprobe = resolve_ffprobe() or shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        proc = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout:
            return None
        data = json.loads(proc.stdout)
        streams = data.get("streams") or []
        if not streams:
            return None
        w = streams[0].get("width")
        h = streams[0].get("height")
        if w and h:
            return int(w), int(h)
    except Exception as e:
        logger.debug(f"ffprobe 分辨率探测失败: {e}")
    return None


def _height_from_ydl_info(info: Optional[dict]) -> Optional[int]:
    """Best-effort height from yt-dlp extract_info result."""
    if not info:
        return None
    req = info.get("requested_formats")
    if isinstance(req, list) and req:
        heights = [f.get("height") for f in req if isinstance(f, dict) and f.get("height")]
        if heights:
            return max(int(h) for h in heights)
    h = info.get("height")
    return int(h) if h else None


def _log_video_resolution(
    video_path: Optional[str],
    *,
    info: Optional[dict] = None,
    reused: bool = False,
    metadata: Optional[dict] = None,
) -> None:
    """Log and optionally record actual/selected video resolution."""
    if not video_path:
        return
    selected = _height_from_ydl_info(info)
    probed = _probe_video_resolution(video_path)
    if probed:
        w, h = probed
        if metadata is not None:
            metadata["download_width"] = w
            metadata["download_height"] = h
        tag = "复用缓存" if reused else "已下载"
        extra = f"（yt-dlp 选择约 {selected}p）" if selected and selected != h else ""
        logger.info(f"视频分辨率 [{tag}]: {w}x{h}{extra} -> {video_path}")
        if h <= 360:
            logger.warning(
                "当前视频仅约 360p。若期望更高清晰度：删除该缓存后重下，"
                "并确认已登录 cookies；YouTube 高清需 DASH+ffmpeg。"
            )
    elif selected:
        if metadata is not None:
            metadata["download_height"] = selected
        tag = "复用缓存" if reused else "已下载"
        logger.info(f"视频分辨率 [{tag}]: yt-dlp 选择约 {selected}p -> {video_path}")


@dataclass
class DownloadResult:
    """Result of an online media download."""

    title: str
    platform: str
    audio_path: Optional[str] = None
    video_path: Optional[str] = None
    subtitle_paths: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


def _resolve_output_dirs(
    platform: str,
    *,
    batch_root: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> tuple[Path, Path]:
    """Return (audio_dir, video_dir) for downloads.

    YouTube and other online platforms both use:
      data/{platform}/{Platform-Channel}/audio|video
    """
    if platform == PLATFORM_YOUTUBE:
        return (
            youtube_audio_dir(batch_root=batch_root, metadata=metadata),
            youtube_video_dir(batch_root=batch_root, metadata=metadata),
        )
    return (
        online_audio_dir(platform, batch_root=batch_root, metadata=metadata),
        online_video_dir(platform, batch_root=batch_root, metadata=metadata),
    )


def _find_in_dirs(dirs: list[Path], stem: str, exts: list[str]) -> Optional[str]:
    for d in dirs:
        found = find_downloaded_file(d, stem, exts)
        if found:
            return found
    return None


def _media_id_stem(metadata: Optional[dict] = None, info: Optional[dict] = None) -> str:
    """Legacy / lookup stem: bare platform video id."""
    video_id = (metadata or {}).get("id") or (info or {}).get("id")
    if not video_id:
        return ""
    return sanitize_filename(str(video_id), 48)


def _media_stem(metadata: dict, info: Optional[dict] = None) -> str:
    """Filename stem for audio/video/subs: ``标题_视频ID`` (readable + unique).

    Falls back to id-only or title-only when one side is missing. Old caches
    that used bare id remain findable via :func:`_media_lookup_stems`.
    """
    raw_id = str((metadata or {}).get("id") or (info or {}).get("id") or "").strip()
    raw_title = str((metadata or {}).get("title") or (info or {}).get("title") or "").strip()
    vid = sanitize_filename(raw_id, 48) if raw_id else ""
    title = sanitize_filename(raw_title, 50) if raw_title else ""

    if title and vid:
        # Avoid "BV1xxx_BV1xxx" if title was already the id
        if title == vid or title.endswith(f"_{vid}"):
            return title[:100] or vid
        return sanitize_filename(f"{title}_{vid}", 100)
    return vid or title or "media"


def _media_lookup_stems(metadata: Optional[dict] = None, info: Optional[dict] = None) -> list[str]:
    """Stems to try when reusing cache (new title_id + legacy id-only)."""
    stems: list[str] = []
    primary = _media_stem(metadata or {}, info)
    legacy = _media_id_stem(metadata, info)
    for s in (primary, legacy):
        if s and s not in stems:
            stems.append(s)
    return stems


def download_audio(
    video_url: str,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    youtube_po_token: Optional[str] = None,
    batch_root: Optional[str] = None,
    youtube_metadata: Optional[dict] = None,
) -> tuple[str, str]:
    """Download video audio as mp3. Backward-compatible wrapper."""
    result = download_media(
        video_url,
        media_type="audio",
        cookies_from_browser=cookies_from_browser,
        cookies_file=cookies_file,
        youtube_po_token=youtube_po_token,
        batch_root=batch_root,
        metadata=youtube_metadata,
    )
    if not result.audio_path:
        raise RuntimeError(f"音频下载失败: {video_url}")
    # Keep caller-visible metadata in place for YouTube pipeline.
    if youtube_metadata is not None and result.metadata:
        youtube_metadata.update(result.metadata)
    return result.audio_path, result.title


def download_video(
    video_url: str,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    youtube_po_token: Optional[str] = None,
    batch_root: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> tuple[str, str, dict]:
    """Download best available video (merged to mp4 when possible)."""
    result = download_media(
        video_url,
        media_type="video",
        cookies_from_browser=cookies_from_browser,
        cookies_file=cookies_file,
        youtube_po_token=youtube_po_token,
        batch_root=batch_root,
        metadata=metadata,
    )
    if not result.video_path:
        raise RuntimeError(f"视频下载失败: {video_url}")
    return result.video_path, result.title, result.metadata


def _subtitle_out_dir(
    platform: str,
    *,
    batch_root: Optional[str] = None,
    metadata: Optional[dict] = None,
    video_dir: Optional[Path] = None,
    audio_dir: Optional[Path] = None,
) -> Path:
    """Dedicated ``subs/`` next to audio/video (YouTube + other online platforms)."""
    if platform == PLATFORM_YOUTUBE:
        return youtube_subs_dir(batch_root=batch_root, metadata=metadata)
    if platform != PLATFORM_LOCAL:
        return online_subs_dir(platform, batch_root=batch_root, metadata=metadata)
    # Local: keep beside media
    if video_dir is not None:
        return Path(video_dir).parent / "subs"
    if audio_dir is not None:
        return Path(audio_dir).parent / "subs"
    return Path("subs")


def _normalize_subtitle_paths(paths: list[str], *, dest_dir: Path) -> list[str]:
    """Keep SRT/VTT only; move files into dest_dir (subs/) when needed."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out: list[str] = []
    for p in paths:
        src = Path(p)
        if not src.is_file():
            continue
        ext = src.suffix.lstrip(".").lower()
        if ext not in {"srt", "vtt"}:
            # Drop legacy json sidecars from result list (optional delete left to user)
            continue
        if src.parent.resolve() == dest_dir.resolve():
            out.append(str(src))
            continue
        dest = dest_dir / src.name
        try:
            if not dest.exists():
                src.replace(dest)
                out.append(str(dest))
            else:
                out.append(str(dest))
        except OSError:
            out.append(str(src))
    # unique preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def _collect_subtitle_paths(
    directory: Path,
    video_id: Optional[str] = None,
    *,
    stems: Optional[list[str]] = None,
) -> list[str]:
    """List subtitle files that belong to this video only.

    Matching (any one is enough):
      - filename contains video_id (e.g. BV1xxx / youtube id)
      - filename starts with one of ``stems`` (title_id)

    Never return *other* videos' sidecars from the same channel folder.
    """
    if not directory.exists():
        return []
    vid = (video_id or "").strip()
    stem_list = [s for s in (stems or []) if s]
    files: list[Path] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lstrip(".").lower() not in SUBTITLE_EXTS:
            continue
        name = path.name
        # Primary: id token must appear (unique per video)
        if vid and vid in name:
            files.append(path)
            continue
        # Secondary: exact stem prefix (title_id.xx.srt)
        if stem_list and any(
            name == s
            or name.startswith(s + ".")
            or name.startswith(s + "-")
            for s in stem_list
        ):
            files.append(path)
            continue
        # No id and no stems: do not grab random files in a shared folder
    return [str(p) for p in files]


def _apply_subtitle_ydl_opts(
    ydl_opts: dict,
    *,
    out_dir: Path,
    subtitle_langs: Optional[list[str]] = None,
) -> None:
    langs = subtitle_langs or list(DEFAULT_SUBTITLE_LANGS)
    ydl_opts.update(
        {
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": langs,
            "subtitlesformat": "srt/vtt/best",
        }
    )
    # Keep outtmpl if already set for media; for subs-only set template.
    if "outtmpl" not in ydl_opts:
        ydl_opts["outtmpl"] = str(out_dir / "%(id)s.%(ext)s")


def download_media(
    video_url: str,
    media_type: str = "audio",
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    youtube_po_token: Optional[str] = None,
    batch_root: Optional[str] = None,
    metadata: Optional[dict] = None,
    download_subs: bool = False,
    subtitle_langs: Optional[list[str]] = None,
) -> DownloadResult:
    """Download audio, video, both, and/or subtitles for an online URL.

    media_type: "audio" | "video" | "both" | "none"
      - "none" is for subtitle-only downloads (requires download_subs=True).
    download_subs: also write subtitle files (srt/vtt preferred).
    Default media_type "audio" preserves the existing transcription pipeline.
    """
    media_type = (media_type or "audio").strip().lower()
    if media_type not in {"audio", "video", "both", "none"}:
        raise ValueError(f"不支持的 media_type: {media_type}（可选: audio/video/both/none）")
    if media_type == "none" and not download_subs:
        raise ValueError("media_type=none 时必须启用 download_subs（仅下载字幕）")

    start_time = time.time()
    platform = detect_platform(video_url)
    meta = dict(metadata or {})
    # Seed id early from URL so we never reuse another video's sidecars.
    if not meta.get("id") and platform == "Bilibili":
        try:
            from ..providers.bilibili import extract_bvid

            bvid = extract_bvid(video_url)
            if bvid:
                meta["id"] = bvid
        except Exception:
            pass
    logger.info(
        f"开始下载媒体 (type={media_type}, subs={download_subs}): {video_url} [{platform}]"
    )

    if platform == PLATFORM_KUAISHOU:
        logger.warning(platform_download_hint(platform))

    # Prefetch metadata for stable channel directories and cache reuse.
    need_channel_meta = not (
        meta.get("channel") or meta.get("uploader") or meta.get("creator")
    )
    if platform == PLATFORM_YOUTUBE and need_channel_meta:
        try:
            info_for_dir = get_youtube_info(
                video_url,
                download=False,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
                youtube_po_token=youtube_po_token,
            )
            meta.update(build_youtube_metadata(info_for_dir, video_url))
        except Exception as e:
            logger.warning(f"YouTube 频道信息预取失败，将使用默认目录: {e}")
    elif platform != PLATFORM_LOCAL and (need_channel_meta or not meta.get("id")):
        try:
            probe_opts = build_base_ydl_opts()
            apply_platform_ydl_options(
                probe_opts,
                platform,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
                youtube_po_token=youtube_po_token,
            )
            probe_opts["skip_download"] = True
            probe_info = extract_media_info(
                video_url,
                probe_opts,
                download=False,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
            )
            meta.update(build_media_metadata(probe_info, video_url, platform))
        except Exception as e:
            logger.warning(f"媒体元数据预取失败，将直接下载: {e}")

    audio_dir, video_dir = _resolve_output_dirs(platform, batch_root=batch_root, metadata=meta)
    audio_search = media_audio_search_dirs(platform, batch_root=batch_root, metadata=meta)
    video_search = media_video_search_dirs(platform, batch_root=batch_root, metadata=meta)
    subs_search = media_subs_search_dirs(platform, batch_root=batch_root, metadata=meta)
    need_audio = media_type in {"audio", "both"}
    need_video = media_type in {"video", "both"}
    need_media = need_audio or need_video
    subs_dir = _subtitle_out_dir(
        platform,
        batch_root=batch_root,
        metadata=meta,
        video_dir=video_dir,
        audio_dir=audio_dir,
    )
    if need_audio:
        audio_dir.mkdir(parents=True, exist_ok=True)
    if need_video:
        video_dir.mkdir(parents=True, exist_ok=True)
    if download_subs:
        subs_dir.mkdir(parents=True, exist_ok=True)

    # Reuse existing media files (title_id names + legacy bare id).
    lookup_stems = _media_lookup_stems(meta)
    stem_guess = lookup_stems[0] if lookup_stems else _media_stem(meta)
    existing_audio = None
    existing_video = None
    existing_subs: list[str] = []
    if meta.get("id") or meta.get("title"):
        if need_audio:
            for s in lookup_stems:
                existing_audio = _find_in_dirs(audio_search, s, AUDIO_EXTS)
                if existing_audio:
                    break
        if need_video:
            for s in lookup_stems:
                existing_video = _find_in_dirs(video_search, s, VIDEO_EXTS)
                if existing_video:
                    break
        if download_subs:
            vid_key = str(meta.get("id") or "")
            # Require id (or stem) match — never treat sibling videos' .srt as ours
            if vid_key or lookup_stems:
                existing_subs = _collect_subtitle_paths(
                    subs_dir, video_id=vid_key or None, stems=lookup_stems
                )
                if not existing_subs:
                    for d in subs_search:
                        existing_subs = _collect_subtitle_paths(
                            d, video_id=vid_key or None, stems=lookup_stems
                        )
                        if existing_subs:
                            break
                # Prefer srt; migrate legacy video/audio sidecars into subs/
                if existing_subs:
                    existing_subs = _normalize_subtitle_paths(
                        existing_subs, dest_dir=subs_dir
                    )

    media_ready = (not need_audio or existing_audio) and (not need_video or existing_video)
    subs_ready = (not download_subs) or bool(existing_subs)
    if media_ready and subs_ready and (need_media or download_subs):
        title = str(meta.get("title") or "未知标题")
        logger.info(
            f"复用已下载: audio={existing_audio} video={existing_video} "
            f"subs={len(existing_subs)} id={meta.get('id')}"
        )
        if existing_video:
            _log_video_resolution(existing_video, reused=True, metadata=meta)
        return DownloadResult(
            title=title,
            platform=platform,
            audio_path=existing_audio,
            video_path=existing_video,
            subtitle_paths=existing_subs,
            metadata=meta,
        )

    ydl_opts = build_base_ydl_opts()
    apply_platform_ydl_options(
        ydl_opts,
        platform,
        cookies_from_browser=cookies_from_browser,
        cookies_file=cookies_file,
        youtube_po_token=youtube_po_token,
    )

    info: dict = {}
    # Prefer readable title_id stem; if title still missing, id-only (same as before).
    out_stem = _media_stem(meta)
    if need_media and not media_ready:
        if media_type == "audio":
            # Progressive A+V first (itag 18 etc.) is more reliable than pure-audio
            # itags that often return HTTP 403 under current YouTube restrictions.
            ydl_opts.update(
                {
                    "format": "best[acodec!=none][vcodec!=none]/bestaudio/best",
                    "outtmpl": str(audio_dir / f"{out_stem}.%(ext)s"),
                    "postprocessors": [
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": "64",
                        }
                    ],
                }
            )
        elif media_type == "video":
            ydl_opts.update(
                {
                    "format": VIDEO_FORMAT,
                    "outtmpl": str(video_dir / f"{out_stem}.%(ext)s"),
                    "merge_output_format": "mp4",
                }
            )
        else:  # both
            ydl_opts.update(
                {
                    "format": VIDEO_FORMAT,
                    "outtmpl": str(video_dir / f"{out_stem}.%(ext)s"),
                    "merge_output_format": "mp4",
                    "keepvideo": True,
                    "postprocessors": [
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": "64",
                        }
                    ],
                }
            )
        if download_subs and not existing_subs:
            _apply_subtitle_ydl_opts(ydl_opts, out_dir=subs_dir, subtitle_langs=subtitle_langs)

        try:
            info = extract_media_info(
                video_url,
                ydl_opts,
                download=True,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
            )
        except Exception as e:
            # YouTube DASH often lists HD then 403s on media GET without PO token.
            # Retry once with progressive-only so download still succeeds (often 360p).
            err_text = str(e).lower()
            is_yt = platform == PLATFORM_YOUTUBE
            is_video = media_type in {"video", "both"}
            is_403 = "403" in err_text or "forbidden" in err_text
            if not (is_yt and is_video and is_403):
                raise
            logger.warning(
                "YouTube 高清流下载 403，改用渐进式格式重试（可能降至 360p）: %s",
                e,
            )
            ydl_opts = dict(ydl_opts)
            ydl_opts["format"] = VIDEO_FORMAT_PROGRESSIVE_FALLBACK
            info = extract_media_info(
                video_url,
                ydl_opts,
                download=True,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
            )
    elif download_subs and not existing_subs:
        # Subtitle-only (or media already cached)
        ydl_opts.update(
            {
                "skip_download": True,
                "outtmpl": str(subs_dir / f"{out_stem}.%(ext)s"),
                "noplaylist": True,
            }
        )
        _apply_subtitle_ydl_opts(ydl_opts, out_dir=subs_dir, subtitle_langs=subtitle_langs)
        try:
            info = extract_media_info(
                video_url,
                ydl_opts,
                download=True,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
            )
        except Exception as e:
            # Bilibili may fail yt-dlp subtitle write even when media info works
            logger.warning(f"yt-dlp 字幕下载未成功，将尝试平台专用通道: {e}")
            info = {}
            try:
                probe_opts = build_base_ydl_opts()
                apply_platform_ydl_options(
                    probe_opts,
                    platform,
                    cookies_from_browser=cookies_from_browser,
                    cookies_file=cookies_file,
                    youtube_po_token=youtube_po_token,
                )
                probe_opts["skip_download"] = True
                probe_opts["ignore_no_formats_error"] = True
                info = extract_media_info(
                    video_url,
                    probe_opts,
                    download=False,
                    cookies_from_browser=cookies_from_browser,
                    cookies_file=cookies_file,
                )
            except Exception:
                info = {}
    else:
        info = {}

    if info:
        if platform == PLATFORM_YOUTUBE:
            meta.update(build_youtube_metadata(info, video_url))
        else:
            meta.update(build_media_metadata(info, video_url, platform))

    stem = _media_stem(meta, info or None)
    audio_path = existing_audio
    video_path = existing_video
    subtitle_paths = list(existing_subs)

    # Recompute stem after info/metadata merge (title may arrive late).
    stem = _media_stem(meta, info or None)
    lookup_stems = _media_lookup_stems(meta, info or None)
    search_audio_dirs = [audio_dir] + [d for d in audio_search if d != audio_dir]
    search_video_dirs = [video_dir] + [d for d in video_search if d != video_dir]

    if need_audio and not audio_path:
        # Audio-only writes into audio_dir; both writes mp3 next to video then we relocate.
        if media_type == "audio":
            for s in lookup_stems:
                audio_path = _find_in_dirs(search_audio_dirs, s, AUDIO_EXTS)
                if audio_path:
                    break
        else:
            # FFmpegExtractAudio leaves mp3 in video_dir when keepvideo=True
            found = None
            for s in lookup_stems:
                found = (
                    find_downloaded_file(video_dir, s, AUDIO_EXTS)
                    or _find_in_dirs(search_audio_dirs, s, AUDIO_EXTS)
                )
                if found:
                    break
            if found:
                audio_dir.mkdir(parents=True, exist_ok=True)
                target = audio_dir / f"{stem}.mp3"
                found_path = Path(found)
                if found_path.resolve() != target.resolve():
                    if target.exists():
                        audio_path = str(target)
                    else:
                        # Prefer new title_id name when relocating from bare id
                        found_path.replace(target)
                        audio_path = str(target)
                else:
                    audio_path = str(target)
            if not audio_path:
                for s in lookup_stems:
                    audio_path = _find_in_dirs(search_audio_dirs, s, AUDIO_EXTS)
                    if audio_path:
                        break

    if need_video and not video_path:
        for s in lookup_stems:
            video_path = _find_in_dirs(search_video_dirs, s, VIDEO_EXTS)
            if video_path:
                break
        # Optionally rename bare-id file to title_id for consistency
        if video_path and stem:
            vp = Path(video_path)
            desired = vp.parent / f"{stem}{vp.suffix}"
            if vp.name != desired.name and not desired.exists() and vp.exists():
                try:
                    vp.rename(desired)
                    video_path = str(desired)
                except OSError:
                    pass

    # Relocate into channel-specific folders if metadata arrived late (all online platforms).
    if platform != PLATFORM_LOCAL and (audio_path or video_path):
        desired_audio_dir, desired_video_dir = _resolve_output_dirs(
            platform, batch_root=batch_root, metadata=meta
        )
        if audio_path and desired_audio_dir != Path(audio_path).parent:
            desired_audio_dir.mkdir(parents=True, exist_ok=True)
            src = Path(audio_path)
            dest = desired_audio_dir / src.name
            if src.exists() and not dest.exists():
                src.rename(dest)
                audio_path = str(dest)
            elif dest.exists():
                audio_path = str(dest)
            audio_dir = desired_audio_dir
        if need_video and video_path and desired_video_dir != Path(video_path).parent:
            desired_video_dir.mkdir(parents=True, exist_ok=True)
            src = Path(video_path)
            dest = desired_video_dir / src.name
            if src.exists() and not dest.exists():
                src.rename(dest)
                video_path = str(dest)
            elif dest.exists():
                video_path = str(dest)
            # Move legacy/new subs into the channel's subs/ folder
            desired_subs = _subtitle_out_dir(
                platform,
                batch_root=batch_root,
                metadata=meta,
                video_dir=desired_video_dir,
                audio_dir=desired_audio_dir,
            )
            desired_subs.mkdir(parents=True, exist_ok=True)
            for d in (video_dir, Path(video_dir).parent / "subs"):
                old_subs = _collect_subtitle_paths(
                    d,
                    video_id=str(meta.get("id") or ""),
                    stems=_media_lookup_stems(meta),
                )
                for sp in old_subs:
                    spath = Path(sp)
                    target = desired_subs / spath.name
                    if spath.exists() and not target.exists():
                        try:
                            spath.rename(target)
                        except OSError:
                            pass
            video_dir = desired_video_dir

    if download_subs:
        final_subs_dir = _subtitle_out_dir(
            platform,
            batch_root=batch_root,
            metadata=meta,
            video_dir=video_dir,
            audio_dir=audio_dir,
        )
        final_subs_dir.mkdir(parents=True, exist_ok=True)
        video_id = str(meta.get("id") or (info or {}).get("id") or "")
        final_stems = _media_lookup_stems(meta, info or None)
        subtitle_paths = _collect_subtitle_paths(
            final_subs_dir, video_id=video_id or None, stems=final_stems
        )
        if not subtitle_paths:
            for d in media_subs_search_dirs(platform, batch_root=batch_root, metadata=meta):
                subtitle_paths = _collect_subtitle_paths(
                    d, video_id=video_id or None, stems=final_stems
                )
                if subtitle_paths:
                    break
        if subtitle_paths:
            subtitle_paths = _normalize_subtitle_paths(subtitle_paths, dest_dir=final_subs_dir)
        # Bilibili: yt-dlp usually misses AI/CC tracks; use player API with cookies.
        if not subtitle_paths and platform == "Bilibili":
            try:
                from ..providers.bilibili import download_bilibili_subtitles_to_dir

                stem = _media_stem(meta, info or None)
                saved, bili_meta = download_bilibili_subtitles_to_dir(
                    video_url,
                    final_subs_dir,
                    stem=stem,
                    cookies_from_browser=cookies_from_browser,
                    cookies_file=cookies_file,
                    preferred_langs=subtitle_langs,
                    all_langs=False,
                )
                if bili_meta:
                    meta.update({k: v for k, v in bili_meta.items() if v is not None})
                subtitle_paths = [p for p in saved if p.lower().endswith((".srt", ".vtt"))]
            except Exception as e:
                logger.warning(f"B站 API 字幕下载失败: {e}")
        if not subtitle_paths:
            logger.warning(
                "已请求下载字幕，但未找到落盘的字幕文件"
                "（B站 AI/CC 字幕需登录 cookies；其它平台请检查是否有软字幕轨）"
            )

    title = str(meta.get("title") or (info or {}).get("title") or "未知标题")
    if need_audio and not audio_path:
        raise RuntimeError(f"音频文件未找到（下载可能已完成但扩展名不匹配）: {audio_dir}")
    if need_video and not video_path:
        raise RuntimeError(f"视频文件未找到（下载可能已完成但扩展名不匹配）: {video_dir}")
    if not need_media and download_subs and not subtitle_paths:
        raise RuntimeError("字幕下载失败：未找到可用字幕文件（可检查 cookies / 语言 / 平台支持）")

    if video_path:
        _log_video_resolution(video_path, info=info or None, reused=False, metadata=meta)

    elapsed = time.time() - start_time
    res_note = ""
    if meta.get("download_width") and meta.get("download_height"):
        res_note = f", {meta['download_width']}x{meta['download_height']}"
    elif meta.get("download_height"):
        res_note = f", ~{meta['download_height']}p"
    logger.info(
        f"媒体下载完成: {title} "
        f"(audio={bool(audio_path)}, video={bool(video_path)}, "
        f"subs={len(subtitle_paths)}{res_note}, 耗时: {format_time(elapsed)})"
    )
    return DownloadResult(
        title=title,
        platform=platform,
        audio_path=audio_path,
        video_path=video_path,
        subtitle_paths=subtitle_paths,
        metadata=meta,
    )
