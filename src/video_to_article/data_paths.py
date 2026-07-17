"""Resolve data/ cache directories for local, YouTube, and other online platforms.

Layout (aligned across platforms):

  data/
    youtube/
      YouTube-{channel}/
        audio/
        video/
    bilibili/
      Bilibili-{uploader}/
        audio/
        video/
    douyin/
      Douyin-{author}/
        audio/
        video/
    local/
      {batch_name}/
        audio/
    online/   # legacy flat layout only (read fallback)
      Bilibili/audio|video
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .paths import DATA_DIR
from .platforms import (
    PLATFORM_BILIBILI,
    PLATFORM_DOUYIN,
    PLATFORM_KUAISHOU,
    PLATFORM_UNKNOWN,
    PLATFORM_WEIBO,
    PLATFORM_XIAOHONGSHU,
    PLATFORM_YOUTUBE,
    platform_slug,
)
from .text_utils import sanitize_path_component


AUTO_PATH_VALUES = {"", "auto", "default"}


def split_virtual_path(value: str) -> list[str]:
    return [part for part in re.split(r"[\\/]+", value or "") if part]


def local_batch_name(batch_root: Optional[str] = None, source_path: Optional[str] = None) -> str:
    """Return the readable local batch name used under data/local."""
    if batch_root:
        return sanitize_path_component(Path(batch_root).name)
    if source_path:
        parent = Path(source_path).parent
        if parent.name:
            return sanitize_path_component(parent.name)
    return "single"


def youtube_batch_name(batch_root: Optional[str] = None, metadata: Optional[dict] = None) -> str:
    """Return the readable YouTube batch name used under data/youtube."""
    name = ""
    if batch_root:
        parts = split_virtual_path(batch_root)
        if parts:
            name = parts[-1]
    if not name and metadata:
        name = str(metadata.get("channel") or metadata.get("uploader") or metadata.get("title") or "")
    name = sanitize_path_component(name or "YouTube")
    return name if name.lower().startswith("youtube-") else f"YouTube-{name}"


def online_batch_name(
    platform: str,
    batch_root: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> str:
    """Channel/uploader folder under data/{platform}/, e.g. Bilibili-老师长.

    Mirrors youtube_batch_name: ``{Platform}-{channel}``.
    """
    label = (platform or "Online").strip() or "Online"
    name = ""
    if batch_root:
        parts = split_virtual_path(batch_root)
        if parts:
            name = parts[-1]
    if not name and metadata:
        name = str(
            metadata.get("channel")
            or metadata.get("uploader")
            or metadata.get("creator")
            or metadata.get("uploader_id")
            or ""
        )
    if not name and metadata:
        # Last resort: video id keeps single downloads out of a giant "unknown" bucket
        name = str(metadata.get("id") or metadata.get("title") or "unknown")
    if not name:
        name = "unknown"
    name = sanitize_path_component(name)
    prefix = f"{label}-"
    if name.lower().startswith(prefix.lower()):
        return name
    # batch_root may already be "Bilibili-xxx" from output planner
    return f"{label}-{name}"


def local_data_dir(batch_root: Optional[str] = None, source_path: Optional[str] = None) -> Path:
    return DATA_DIR / "local" / local_batch_name(batch_root, source_path)


def youtube_data_dir(batch_root: Optional[str] = None, metadata: Optional[dict] = None) -> Path:
    return DATA_DIR / "youtube" / youtube_batch_name(batch_root, metadata)


def online_data_dir(
    platform: str,
    batch_root: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> Path:
    """Canonical online cache root: data/{slug}/{Platform-Channel}/."""
    slug = platform_slug(platform)
    batch = online_batch_name(platform, batch_root=batch_root, metadata=metadata)
    if slug in {"unknown"}:
        return DATA_DIR / "online" / "unknown" / batch
    return DATA_DIR / slug / batch


def legacy_online_data_dir(platform: str) -> Path:
    """Pre-migration flat layout: data/online/{Platform}/audio|video."""
    return DATA_DIR / "online" / sanitize_path_component(platform or "online")


def local_audio_dir(source_path: str, batch_root: Optional[str] = None) -> Path:
    return local_data_dir(batch_root=batch_root, source_path=source_path) / "audio"


def youtube_audio_dir(batch_root: Optional[str] = None, metadata: Optional[dict] = None) -> Path:
    return youtube_data_dir(batch_root=batch_root, metadata=metadata) / "audio"


def online_audio_dir(
    platform: str,
    batch_root: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> Path:
    return online_data_dir(platform, batch_root=batch_root, metadata=metadata) / "audio"


def online_video_dir(
    platform: str,
    batch_root: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> Path:
    return online_data_dir(platform, batch_root=batch_root, metadata=metadata) / "video"


def online_subs_dir(
    platform: str,
    batch_root: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> Path:
    """Sidecar subtitles for online platforms (not mixed into video/)."""
    return online_data_dir(platform, batch_root=batch_root, metadata=metadata) / "subs"


def youtube_video_dir(batch_root: Optional[str] = None, metadata: Optional[dict] = None) -> Path:
    return youtube_data_dir(batch_root=batch_root, metadata=metadata) / "video"


def youtube_subs_dir(batch_root: Optional[str] = None, metadata: Optional[dict] = None) -> Path:
    return youtube_data_dir(batch_root=batch_root, metadata=metadata) / "subs"


def legacy_online_audio_dir(platform: str) -> Path:
    return legacy_online_data_dir(platform) / "audio"


def legacy_online_video_dir(platform: str) -> Path:
    return legacy_online_data_dir(platform) / "video"


def media_audio_search_dirs(
    platform: str,
    *,
    batch_root: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> list[Path]:
    """Primary + legacy dirs to look for cached audio."""
    if platform == PLATFORM_YOUTUBE:
        return [youtube_audio_dir(batch_root=batch_root, metadata=metadata)]
    dirs = [online_audio_dir(platform, batch_root=batch_root, metadata=metadata)]
    legacy = legacy_online_audio_dir(platform)
    if legacy not in dirs:
        dirs.append(legacy)
    return dirs


def media_video_search_dirs(
    platform: str,
    *,
    batch_root: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> list[Path]:
    """Primary + legacy dirs to look for cached video."""
    if platform == PLATFORM_YOUTUBE:
        return [youtube_video_dir(batch_root=batch_root, metadata=metadata)]
    dirs = [online_video_dir(platform, batch_root=batch_root, metadata=metadata)]
    legacy = legacy_online_video_dir(platform)
    if legacy not in dirs:
        dirs.append(legacy)
    return dirs


def media_subs_search_dirs(
    platform: str,
    *,
    batch_root: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> list[Path]:
    """Primary subs/ + legacy places (beside video/audio) for cache reuse."""
    if platform == PLATFORM_YOUTUBE:
        primary = youtube_subs_dir(batch_root=batch_root, metadata=metadata)
        legacy_video = youtube_video_dir(batch_root=batch_root, metadata=metadata)
        legacy_audio = youtube_audio_dir(batch_root=batch_root, metadata=metadata)
        return [primary, legacy_video, legacy_audio]
    primary = online_subs_dir(platform, batch_root=batch_root, metadata=metadata)
    return [
        primary,
        online_video_dir(platform, batch_root=batch_root, metadata=metadata),
        online_audio_dir(platform, batch_root=batch_root, metadata=metadata),
        legacy_online_video_dir(platform),
        legacy_online_audio_dir(platform),
    ]


def batch_list_path(kind: str, batch_root: Optional[str] = None, explicit_path: Optional[str] = None) -> Path:
    """Resolve where a batch list should be written.

    Explicit paths are respected. Passing "auto" / "default" chooses the
    source-specific data directory.
    """
    if explicit_path is not None and explicit_path.strip().lower() not in AUTO_PATH_VALUES:
        return Path(explicit_path)

    if kind == "youtube":
        return youtube_data_dir(batch_root=batch_root) / "videos.txt"
    if kind == "local":
        return local_data_dir(batch_root=batch_root) / "videos.txt"
    if kind in {
        "bilibili",
        PLATFORM_BILIBILI.lower(),
        PLATFORM_BILIBILI,
    }:
        return online_data_dir(PLATFORM_BILIBILI, batch_root=batch_root) / "videos.txt"
    # Generic: treat kind as platform label when it looks like one
    kind_map = {
        "douyin": PLATFORM_DOUYIN,
        "xiaohongshu": PLATFORM_XIAOHONGSHU,
        "weibo": PLATFORM_WEIBO,
        "kuaishou": PLATFORM_KUAISHOU,
    }
    plat = kind_map.get((kind or "").lower())
    if plat:
        return online_data_dir(plat, batch_root=batch_root) / "videos.txt"
    return DATA_DIR / sanitize_path_component(kind or "batch") / "videos.txt"
