"""Shared yt-dlp helpers used by audio/video download paths."""

from __future__ import annotations

from typing import Any, Optional

from ..logging_config import configure_logging
from ..platforms import (
    PLATFORM_BILIBILI,
    PLATFORM_DOUYIN,
    PLATFORM_KUAISHOU,
    PLATFORM_WEIBO,
    PLATFORM_XIAOHONGSHU,
    PLATFORM_YOUTUBE,
    detect_platform,
)
from ..text_utils import import_required
from .youtube import apply_youtube_extractor_options, extract_info_with_optional_auth_retry
from .youtube_auth import apply_youtube_po_token, apply_ytdlp_auth_options

logger = configure_logging()

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def platform_http_headers(platform: str) -> dict[str, str]:
    """HTTP headers that improve extraction success on Chinese platforms."""
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    if platform == PLATFORM_BILIBILI:
        headers["Referer"] = "https://www.bilibili.com"
        headers["Origin"] = "https://www.bilibili.com"
    elif platform == PLATFORM_DOUYIN:
        headers["Referer"] = "https://www.douyin.com"
    elif platform == PLATFORM_XIAOHONGSHU:
        headers["Referer"] = "https://www.xiaohongshu.com"
    elif platform == PLATFORM_WEIBO:
        headers["Referer"] = "https://weibo.com"
    elif platform == PLATFORM_KUAISHOU:
        headers["Referer"] = "https://www.kuaishou.com"
    return headers


def build_base_ydl_opts(
    *,
    quiet: bool = True,
    noplaylist: bool = True,
    socket_timeout: int = 60,
    retries: int = 10,
) -> dict[str, Any]:
    """Common yt-dlp options shared by audio/video downloads."""
    opts: dict[str, Any] = {
        "quiet": quiet,
        "no_warnings": quiet,
        "noplaylist": noplaylist,
        "socket_timeout": socket_timeout,
        "retries": retries,
        "fragment_retries": retries,
        "retry_sleep_functions": {"http": lambda n: min(2**n, 30)},
        "concurrent_fragment_downloads": 4,
    }
    try:
        from ..media.ffmpeg_tools import ensure_ffmpeg_on_path, ffmpeg_location_for_ytdlp

        ensure_ffmpeg_on_path()
        loc = ffmpeg_location_for_ytdlp()
        if loc:
            opts["ffmpeg_location"] = loc
    except Exception:
        pass
    return opts


def apply_platform_ydl_options(
    ydl_opts: dict[str, Any],
    platform: str,
    *,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    youtube_po_token: Optional[str] = None,
) -> dict[str, Any]:
    """Attach platform headers and auth options to yt-dlp opts."""
    headers = platform_http_headers(platform)
    existing = dict(ydl_opts.get("http_headers") or {})
    existing.update(headers)
    ydl_opts["http_headers"] = existing

    # YouTube keeps auto cookie discovery (default youtube.txt / browser env).
    # Other platforms only attach cookies when explicitly provided, so a YouTube
    # cookie file is not incorrectly forced onto Bilibili/Douyin/XHS.
    if platform == PLATFORM_YOUTUBE:
        apply_ytdlp_auth_options(ydl_opts, cookies_from_browser, cookies_file)
        apply_youtube_extractor_options(ydl_opts)
        apply_youtube_po_token(ydl_opts, youtube_po_token)
    elif cookies_from_browser or cookies_file:
        apply_ytdlp_auth_options(ydl_opts, cookies_from_browser, cookies_file)

    return ydl_opts


def extract_media_info(
    video_url: str,
    ydl_opts: dict[str, Any],
    *,
    download: bool = False,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
) -> dict:
    """Run yt-dlp extract_info with optional YouTube cookie retry."""
    yt_dlp = import_required("yt_dlp", "yt-dlp")
    platform = detect_platform(video_url)
    if platform == PLATFORM_YOUTUBE:
        return extract_info_with_optional_auth_retry(
            yt_dlp,
            video_url,
            ydl_opts,
            download,
            cookies_from_browser,
            cookies_file,
        )
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=download)
    if not info:
        raise RuntimeError(f"yt-dlp 未能解析媒体信息: {video_url}")
    return info


def build_media_metadata(info: dict, video_url: str, platform: Optional[str] = None) -> dict[str, Any]:
    """Normalize yt-dlp info into a shared metadata dict."""
    platform = platform or detect_platform(video_url)
    return {
        "title": info.get("title") or "未知标题",
        "id": info.get("id"),
        "webpage_url": info.get("webpage_url") or video_url,
        "channel": info.get("channel") or info.get("uploader") or info.get("creator"),
        "channel_url": info.get("channel_url") or info.get("uploader_url"),
        "upload_date": info.get("upload_date"),
        "duration": info.get("duration"),
        "description": info.get("description"),
        "thumbnail": info.get("thumbnail"),
        "platform": platform,
        "ext": info.get("ext"),
    }


def find_downloaded_file(directory, stem: str, preferred_exts: list[str]) -> Optional[str]:
    """Locate a downloaded media file by stem and preferred extensions."""
    from pathlib import Path

    directory = Path(directory)
    if not directory.exists():
        return None

    for ext in preferred_exts:
        candidate = directory / f"{stem}.{ext.lstrip('.')}"
        if candidate.exists():
            return str(candidate)

    matches = sorted(directory.glob(f"{stem}.*"))
    for path in matches:
        if path.suffix.lower().lstrip(".") in {e.lstrip(".").lower() for e in preferred_exts}:
            return str(path)
    if matches:
        # Prefer non-temp / non-json leftovers.
        for path in matches:
            if path.suffix.lower() not in {".json", ".part", ".ytdl", ".temp", ".tmp"}:
                return str(path)
    return None
