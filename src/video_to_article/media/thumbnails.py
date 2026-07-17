"""Download platform thumbnails for local AI-cover reference."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..logging_config import configure_logging
from ..platforms import PLATFORM_BILIBILI, PLATFORM_YOUTUBE

logger = configure_logging()

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def thumbnail_http_headers(url: str, *, platform: str = "", referer: str = "") -> dict[str, str]:
    headers = {"User-Agent": DEFAULT_UA}
    host = (urlparse(url).netloc or "").lower()
    plat = (platform or "").lower()
    if referer:
        headers["Referer"] = referer
    elif plat == PLATFORM_BILIBILI.lower() or "bilibili" in plat or "hdslb.com" in host or "bili" in host:
        headers["Referer"] = "https://www.bilibili.com"
    elif plat == PLATFORM_YOUTUBE.lower() or "youtu" in host:
        headers["Referer"] = "https://www.youtube.com"
    return headers


def download_binary_url(
    url: str,
    output_path: Path,
    *,
    platform: str = "",
    referer: str = "",
    timeout: int = 60,
) -> None:
    """Download a binary URL (thumbnail/image) to disk."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    request = Request(
        url,
        headers=thumbnail_http_headers(url, platform=platform, referer=referer),
    )
    with urlopen(request, timeout=timeout) as response:
        output_path.write_bytes(response.read())


def download_thumbnail_to_dir(
    thumbnail_url: str,
    output_dir: Path,
    *,
    platform: str = "",
    filename_stem: str = "thumbnail",
) -> Optional[str]:
    """Save thumbnail next to article outputs. Returns local path or None."""
    if not thumbnail_url:
        return None
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(urlparse(thumbnail_url).path).suffix or ".jpg"
    if len(suffix) > 5 or not suffix.startswith("."):
        suffix = ".jpg"
    thumbnail_file = output_dir / f"{filename_stem}{suffix}"
    try:
        download_binary_url(thumbnail_url, thumbnail_file, platform=platform)
        if thumbnail_file.stat().st_size < 32:
            logger.warning(f"封面文件过小，可能下载失败: {thumbnail_file}")
            return None
        logger.info(f"封面已保存: {thumbnail_file}")
        return str(thumbnail_file)
    except Exception as e:
        logger.warning(f"封面下载失败: {e}")
        return None


def save_source_assets(
    raw_file: Path,
    metadata: Optional[dict[str, Any]],
    transcript_text: str,
    *,
    platform: str = "",
) -> dict[str, str]:
    """Save metadata.json, transcript text, and thumbnail beside raw.md.

    Used for YouTube, Bilibili, and other online sources so AI cover can use a
    local reference image.
    """
    output_dir = Path(raw_file).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: dict[str, str] = {}
    metadata = dict(metadata or {})
    platform = platform or str(metadata.get("platform") or "")

    metadata_file = output_dir / "metadata.json"
    with open(metadata_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    saved["metadata"] = str(metadata_file)

    transcript_source = str(metadata.get("transcript_source") or "")
    if transcript_source.startswith("youtube_subtitle:") or transcript_source.startswith(
        "platform_subtitle:"
    ):
        transcript_name = "platform_subtitle.txt"
        if transcript_source.startswith("youtube_subtitle:"):
            transcript_name = "youtube_subtitle.txt"
    else:
        transcript_name = "asr_transcript.txt"
    transcript_file = output_dir / transcript_name
    with open(transcript_file, "w", encoding="utf-8") as f:
        f.write(transcript_text or "")
    saved["transcript_text"] = str(transcript_file)

    thumbnail_url = metadata.get("thumbnail") or ""
    if thumbnail_url:
        local = download_thumbnail_to_dir(
            str(thumbnail_url),
            output_dir,
            platform=platform,
        )
        if local:
            saved["thumbnail"] = local
            print(f"   封面已下载到本地: {local}")

    return saved
