import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..logging_config import configure_logging
from ..text_utils import import_required, sanitize_path_component
from .youtube_auth import (
    apply_youtube_po_token,
    apply_ytdlp_auth_options,
    diagnose_ytdlp_error,
    is_youtube_auth_error,
    resolve_youtube_auth,
)

logger = configure_logging()


def apply_youtube_extractor_options(ydl_opts: dict) -> dict:
    """Use robust YouTube extractor settings for current yt-dlp releases.

    Notes (verified with yt-dlp 2026.07 + Firefox cookies):
    - Do **not** force ``player_client=tv,web,mweb`` for media download: those
      clients list HD DASH, but media GETs often mid-fail with HTTP 403 without
      a GVS PO Token.
    - yt-dlp **default clients** + ``player_js_version=actual`` can complete a
      real 1080p ``bv*+ba`` merge (avc1 137 + audio).
    - mweb alone is reliable only for progressive itag 18 (~360p).
    - ``remote_components`` ejs helps nsig / player JS challenges.
    """
    youtube_args = ydl_opts.setdefault("extractor_args", {}).setdefault("youtube", {})
    # Prefer working download URLs over clients that only *list* HD formats.
    youtube_args.setdefault("player_js_version", ["actual"])
    # Leave player_client unset so yt-dlp uses its current default set.
    ydl_opts["remote_components"] = ["ejs:github"]
    return ydl_opts


def extract_info_with_optional_auth_retry(
    yt_dlp,
    video_url: str,
    ydl_opts: dict,
    download: bool,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
):
    """Extract info and retry once without cookies if the cookie auth is rejected."""
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(video_url, download=download)
    except Exception as e:
        auth = resolve_youtube_auth(cookies_from_browser, cookies_file)
        auth_was_used = bool(auth.cookies_file or auth.cookies_from_browser)
        if not auth_was_used or not is_youtube_auth_error(e):
            raise

        hint = diagnose_ytdlp_error(e)
        retry_opts = dict(ydl_opts)
        retry_opts.pop("cookiefile", None)
        retry_opts.pop("cookiesfrombrowser", None)
        logger.warning(f"YouTube cookie 认证失败，尝试不带 cookies 重试。{hint}")
        try:
            with yt_dlp.YoutubeDL(retry_opts) as ydl:
                return ydl.extract_info(video_url, download=download)
        except Exception:
            raise e




# Caption parsing / language picking live in providers.subtitles (shared).
# Keep thin re-exports so older imports and tests keep working.
def parse_json3_caption(text: str) -> str:
    """Parse YouTube json3 captions into plain text."""
    from .subtitles import parse_json3_caption as _parse

    return _parse(text)


def is_probable_youtube_page_payload(text: str) -> bool:
    """Return true when a caption URL returned a YouTube HTML/JS page."""
    from .subtitles import is_probable_html_payload

    return is_probable_html_payload(text)


def parse_caption_payload(text: str, ext: str) -> str:
    """Convert caption payload into plain text."""
    from .subtitles import parse_caption_payload as _parse

    return _parse(text, ext)


def pick_caption(captions: dict, preferred_langs: List[str]) -> tuple[Optional[str], Optional[dict]]:
    """Pick the best caption entry from yt-dlp captions."""
    from .subtitles import pick_caption_lang

    return pick_caption_lang(captions, preferred_langs)


def fetch_text_url(url: str) -> str:
    """Download text URL content (legacy helper; subtitle path uses yt-dlp)."""
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def download_binary_url(url: str, output_path: Path) -> None:
    """Download binary URL content (delegates to shared thumbnail helper)."""
    from ..media.thumbnails import download_binary_url as _download

    _download(url, output_path, platform="YouTube")


def get_youtube_info(
    video_url: str,
    download: bool = False,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    youtube_po_token: Optional[str] = None,
) -> dict:
    """Fetch YouTube metadata using yt-dlp."""
    yt_dlp = import_required("yt_dlp", "yt-dlp")
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": not download,
        "format": None if not download else "bestaudio/best",
        "ignore_no_formats_error": not download,
    }
    apply_youtube_extractor_options(ydl_opts)
    apply_youtube_po_token(ydl_opts, youtube_po_token)
    apply_ytdlp_auth_options(ydl_opts, cookies_from_browser, cookies_file)
    return extract_info_with_optional_auth_retry(
        yt_dlp,
        video_url,
        ydl_opts,
        download,
        cookies_from_browser,
        cookies_file,
    )


def get_youtube_collection_urls(
    collection_url: str,
    limit: Optional[int] = None,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    youtube_po_token: Optional[str] = None,
) -> List[str]:
    """Expand a YouTube channel/playlist into video URLs."""
    yt_dlp = import_required("yt_dlp", "yt-dlp")
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "ignoreerrors": True,
    }
    apply_youtube_extractor_options(ydl_opts)
    apply_youtube_po_token(ydl_opts, youtube_po_token)
    if limit and limit > 0:
        ydl_opts["playlistend"] = limit
    apply_ytdlp_auth_options(ydl_opts, cookies_from_browser, cookies_file)

    info = extract_info_with_optional_auth_retry(
        yt_dlp,
        collection_url,
        ydl_opts,
        False,
        cookies_from_browser,
        cookies_file,
    )

    if not info:
        return []

    entries = info.get("entries") or []
    urls = []
    for entry in entries:
        if not entry:
            continue
        video_id = entry.get("id")
        url = entry.get("url") or entry.get("webpage_url")
        if video_id:
            urls.append(f"https://www.youtube.com/watch?v={video_id}")
        elif url:
            urls.append(url)

    return urls


def make_youtube_batch_root(
    collection_url: str,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    youtube_po_token: Optional[str] = None,
) -> str:
    """Build a virtual batch root for YouTube collections."""
    try:
        yt_dlp = import_required("yt_dlp", "yt-dlp")
        ydl_opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True}
        apply_youtube_extractor_options(ydl_opts)
        apply_youtube_po_token(ydl_opts, youtube_po_token)
        apply_ytdlp_auth_options(ydl_opts, cookies_from_browser, cookies_file)
        info = extract_info_with_optional_auth_retry(
            yt_dlp,
            collection_url,
            ydl_opts,
            False,
            cookies_from_browser,
            cookies_file,
        )
        title = info.get("channel") or info.get("uploader") or info.get("title") or "YouTube"
    except Exception:
        title = "YouTube"
    return f"YouTube\\{sanitize_path_component(title)}"


def extract_youtube_subtitle_text(
    video_url: str,
    preferred_langs: Optional[List[str]] = None,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    youtube_po_token: Optional[str] = None,
) -> tuple[Optional[str], Optional[dict]]:
    """Extract YouTube subtitles via yt-dlp write-subs path; return text and metadata.

    Implementation lives in providers.subtitles so auth (cookies / PO token)
    matches media download. Prefer manual tracks, then automatic captions.
    """
    from .subtitles import extract_platform_subtitle_text

    text, metadata = extract_platform_subtitle_text(
        video_url,
        preferred_langs=preferred_langs,
        cookies_from_browser=cookies_from_browser,
        cookies_file=cookies_file,
        youtube_po_token=youtube_po_token,
        platform="YouTube",
    )
    # Preserve historical YouTube metadata shape for downstream output paths.
    if metadata is None:
        return None, None
    youtube_meta = {
        "title": metadata.get("title", "未知标题"),
        "id": metadata.get("id"),
        "webpage_url": metadata.get("webpage_url") or video_url,
        "channel": metadata.get("channel"),
        "channel_url": metadata.get("channel_url"),
        "upload_date": metadata.get("upload_date"),
        "duration": metadata.get("duration"),
        "description": metadata.get("description"),
        "thumbnail": metadata.get("thumbnail"),
    }
    for key in (
        "caption_source",
        "caption_language",
        "caption_ext",
        "caption_failure_reason",
        "caption_available_manual",
        "caption_available_automatic",
        "caption_attempted",
        "platform",
    ):
        if key in metadata:
            youtube_meta[key] = metadata[key]
    return text, youtube_meta


def build_youtube_metadata(info: dict, video_url: str) -> dict:
    """Build normalized YouTube metadata."""
    return {
        "title": info.get("title", "未知标题"),
        "id": info.get("id"),
        "webpage_url": info.get("webpage_url") or video_url,
        "channel": info.get("channel") or info.get("uploader"),
        "channel_url": info.get("channel_url") or info.get("uploader_url"),
        "upload_date": info.get("upload_date"),
        "duration": info.get("duration"),
        "description": info.get("description"),
        "thumbnail": info.get("thumbnail"),
    }


def save_youtube_assets(raw_file: Path, metadata: dict, transcript_text: str) -> dict:
    """Save metadata, subtitle text, and thumbnail next to raw output."""
    from ..media.thumbnails import save_source_assets

    return save_source_assets(
        raw_file,
        metadata,
        transcript_text,
        platform="YouTube",
    )


def search_youtube_videos(
    keyword: str,
    count: int = 5,
    order: str = "relevance",
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    youtube_po_token: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Search YouTube via yt-dlp flat extract (ytsearchN / ytsearchdateN)."""
    keyword = (keyword or "").strip()
    if not keyword:
        logger.warning("YouTube 搜索关键词为空")
        return []
    count = max(1, min(50, int(count or 5)))
    order = (order or "relevance").strip().lower()
    prefix = "ytsearchdate" if order in {"date", "pubdate", "upload_date"} else "ytsearch"
    query = f"{prefix}{count}:{keyword}"
    yt_dlp = import_required("yt_dlp", "yt-dlp")
    ydl_opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "ignoreerrors": True,
    }
    apply_youtube_extractor_options(ydl_opts)
    apply_youtube_po_token(ydl_opts, youtube_po_token)
    apply_ytdlp_auth_options(ydl_opts, cookies_from_browser, cookies_file)
    try:
        info = extract_info_with_optional_auth_retry(
            yt_dlp,
            query,
            ydl_opts,
            False,
            cookies_from_browser,
            cookies_file,
        )
    except Exception as e:
        logger.error(f"YouTube 搜索失败: {e}")
        raise

    entries = (info or {}).get("entries") or []
    results: List[Dict[str, Any]] = []
    for entry in entries:
        if not entry:
            continue
        vid = entry.get("id") or ""
        url = (
            entry.get("webpage_url")
            or entry.get("url")
            or (f"https://www.youtube.com/watch?v={vid}" if vid else "")
        )
        if not url:
            continue
        if not str(url).startswith("http") and vid:
            url = f"https://www.youtube.com/watch?v={vid}"
        results.append(
            {
                "title": entry.get("title") or "未知标题",
                "author": entry.get("channel") or entry.get("uploader") or "",
                "url": url,
                "duration": entry.get("duration"),
                "play": entry.get("view_count"),
                "platform": "youtube",
                "id": vid,
            }
        )
        if len(results) >= count:
            break
    return results
