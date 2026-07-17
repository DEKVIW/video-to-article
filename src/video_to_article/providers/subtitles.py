"""Platform subtitle extraction via yt-dlp (manual first, then automatic).

Uses yt-dlp's own subtitle downloader so cookies / PO token / headers stay
consistent with media download. Falls back to ASR when no usable text is found.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence

from ..logging_config import configure_logging
from ..platforms import PLATFORM_BILIBILI, PLATFORM_YOUTUBE, detect_platform
from ..text_utils import clean_caption_text, import_required
from .ytdlp_common import (
    apply_platform_ydl_options,
    build_base_ydl_opts,
    build_media_metadata,
    extract_media_info,
)

logger = configure_logging()

# Preference order for Chinese cooking content; English as last resort.
DEFAULT_PREFERRED_LANGS: List[str] = [
    "zh-Hans",
    "zh-CN",
    "zh",
    "zh-Hant",
    "zh-TW",
    "zh-HK",
    "en",
    "en-US",
    "en-GB",
]

# Ignore caption payloads shorter than this after cleaning.
MIN_SUBTITLE_CHARS = 20

# Platforms worth attempting yt-dlp subtitle extraction on.
SUBTITLE_CAPABLE_PLATFORMS = {
    PLATFORM_YOUTUBE,
    PLATFORM_BILIBILI,
}


def supports_platform_subtitles(platform: Optional[str] = None, video_url: Optional[str] = None) -> bool:
    """Return True when we should try platform subtitles before ASR."""
    plat = platform or (detect_platform(video_url) if video_url else None)
    return plat in SUBTITLE_CAPABLE_PLATFORMS


def lang_matches(available: str, preferred: str) -> bool:
    """Match yt-dlp language codes against a preference entry."""
    a = (available or "").lower()
    p = (preferred or "").lower()
    if not a or not p:
        return False
    if p.endswith(".*"):
        base = p[:-2]
        return a == base or a.startswith(base + "-") or a.startswith(base + ".")
    if p.endswith("*"):
        return a.startswith(p[:-1])
    return a == p or a.startswith(p + "-") or a.startswith(p + ".")


def pick_caption_lang(
    captions: dict,
    preferred_langs: Sequence[str],
) -> tuple[Optional[str], Optional[dict]]:
    """Pick the best caption language entry from a yt-dlp captions dict."""
    if not captions:
        return None, None

    for preferred in preferred_langs:
        for lang, entries in captions.items():
            if lang_matches(lang, preferred) and entries:
                return lang, entries[0] if isinstance(entries, list) else entries

    for lang, entries in captions.items():
        if entries:
            return lang, entries[0] if isinstance(entries, list) else entries

    return None, None


def is_probable_html_payload(text: str) -> bool:
    """Return true when a caption payload looks like an HTML/JS page, not subtitles."""
    head = (text or "")[:20000].lower()
    markers = [
        "<!doctype html",
        "<html",
        "window.wiz_global_data",
        "var ytcfg",
        "ytcfg.set",
        "ytinitialdata",
        "youtube_web",
        "engagement-panel-searchable-transcript",
        "/youtubei/v1/get_transcript",
    ]
    return any(marker in head for marker in markers)


def parse_json3_caption(text: str) -> str:
    """Parse YouTube/Bilibili-style json3 captions into plain text."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return ""

    lines: list[str] = []
    for event in data.get("events") or []:
        if not isinstance(event, dict):
            continue
        parts = event.get("segs") or []
        line = "".join(part.get("utf8", "") for part in parts if isinstance(part, dict))
        line = line.replace("\n", " ").replace("\xa0", " ").strip()
        if line:
            lines.append(line)

    return clean_caption_text("\n".join(lines))


def parse_caption_payload(text: str, ext: str = "") -> str:
    """Convert a subtitle file payload into plain transcript text."""
    if not text or not text.strip():
        return ""
    if is_probable_html_payload(text):
        return ""

    ext = (ext or "").lower().lstrip(".")
    if ext == "json3" or text.lstrip().startswith("{"):
        parsed = parse_json3_caption(text)
        if parsed:
            return parsed
        if ext == "json3":
            return ""

    return clean_caption_text(text)


def _read_subtitle_file(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    return parse_caption_payload(raw, path.suffix.lstrip("."))


def _collect_subtitle_files(directory: Path, video_id: Optional[str] = None) -> list[Path]:
    """List subtitle files written by yt-dlp under directory."""
    if not directory.exists():
        return []
    exts = {".vtt", ".srt", ".json3", ".srv1", ".srv2", ".srv3", ".ttml", ".ass", ".ssa"}
    files: list[Path] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in exts:
            continue
        if video_id and video_id not in path.name:
            # Still accept if only one subtitle-like file exists later.
            pass
        files.append(path)
    if video_id:
        preferred = [p for p in files if video_id in p.name]
        if preferred:
            return preferred
    return files


def _subtitle_file_lang(path: Path, video_id: Optional[str] = None) -> str:
    """Best-effort language code from yt-dlp filename stem."""
    stem = path.stem  # e.g. id.zh-Hans or id.zh-Hans.vtt already stripped once
    # Handle double extensions like file.zh-Hans.vtt -> stem file.zh-Hans
    name = path.name
    if video_id and name.startswith(video_id + "."):
        rest = name[len(video_id) + 1 :]
        # rest: zh-Hans.vtt / zh-Hans.json3
        lang = rest.rsplit(".", 1)[0]
        return lang or "unknown"
    parts = stem.split(".")
    if len(parts) >= 2:
        return parts[-1]
    return "unknown"


def _apply_subtitle_youtube_clients(ydl_opts: dict) -> dict:
    """Prefer player clients that expose caption tracks more reliably.

    Subtitle listing benefits from web/tv/mweb; media download uses yt-dlp
    defaults + player_js_version=actual (see apply_youtube_extractor_options).
    Does not remove existing po_token / other extractor args.
    """
    extractor_args = ydl_opts.setdefault("extractor_args", {})
    youtube_args = extractor_args.setdefault("youtube", {})
    youtube_args["player_client"] = ["web", "mweb", "tv"]
    youtube_args.setdefault("player_js_version", ["actual"])
    return ydl_opts


def _build_subtitle_ydl_opts(
    out_dir: Path,
    *,
    platform: str,
    write_manual: bool,
    write_auto: bool,
    langs: Sequence[str],
    cookies_from_browser: Optional[str],
    cookies_file: Optional[str],
    youtube_po_token: Optional[str],
) -> dict:
    ydl_opts = build_base_ydl_opts(quiet=True)
    ydl_opts.update(
        {
            "skip_download": True,
            "writesubtitles": write_manual,
            "writeautomaticsub": write_auto,
            "subtitleslangs": list(langs),
            "subtitlesformat": "json3/vtt/srt/best",
            "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
            "ignoreerrors": False,
            # Avoid playlist expansion when a watch URL is ambiguous.
            "noplaylist": True,
        }
    )
    apply_platform_ydl_options(
        ydl_opts,
        platform,
        cookies_from_browser=cookies_from_browser,
        cookies_file=cookies_file,
        youtube_po_token=youtube_po_token,
    )
    if platform == PLATFORM_YOUTUBE:
        _apply_subtitle_youtube_clients(ydl_opts)
    return ydl_opts


def _download_caption_url_with_ytdlp(
    caption_url: str,
    *,
    platform: str,
    cookies_from_browser: Optional[str],
    cookies_file: Optional[str],
    youtube_po_token: Optional[str],
    ext: str,
) -> str:
    """Fetch a caption URL through yt-dlp's downloader (keeps cookies/headers)."""
    yt_dlp = import_required("yt_dlp", "yt-dlp")
    ydl_opts = build_base_ydl_opts(quiet=True)
    ydl_opts.update({"skip_download": True, "noplaylist": True})
    apply_platform_ydl_options(
        ydl_opts,
        platform,
        cookies_from_browser=cookies_from_browser,
        cookies_file=cookies_file,
        youtube_po_token=youtube_po_token,
    )
    if platform == PLATFORM_YOUTUBE:
        _apply_subtitle_youtube_clients(ydl_opts)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        payload = ydl.urlopen(caption_url).read()
    text = payload.decode("utf-8", errors="replace")
    return parse_caption_payload(text, ext)


def _pick_caption_entry(captions: dict, lang: str) -> Optional[dict]:
    entries = captions.get(lang) if captions else None
    if not entries:
        return None
    if isinstance(entries, list):
        # Prefer json3, then vtt, then anything with a url.
        def score(item: dict) -> tuple:
            ext = (item.get("ext") or "").lower()
            return (
                0 if ext == "json3" else 1 if ext == "vtt" else 2 if ext == "srt" else 3,
                0 if item.get("url") else 1,
            )

        ranked = sorted((e for e in entries if isinstance(e, dict)), key=score)
        return ranked[0] if ranked else None
    return entries if isinstance(entries, dict) else None


def _download_one_subtitle_track(
    video_url: str,
    *,
    platform: str,
    source_type: str,
    lang: str,
    caption_entry: Optional[dict],
    cookies_from_browser: Optional[str],
    cookies_file: Optional[str],
    youtube_po_token: Optional[str],
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Download a single subtitle track via yt-dlp. Returns (text, lang, ext)."""
    write_manual = source_type == "manual"
    write_auto = source_type == "automatic"

    with tempfile.TemporaryDirectory(prefix="vqe-subs-") as tmp:
        out_dir = Path(tmp)
        ydl_opts = _build_subtitle_ydl_opts(
            out_dir,
            platform=platform,
            write_manual=write_manual,
            write_auto=write_auto,
            langs=[lang],
            cookies_from_browser=cookies_from_browser,
            cookies_file=cookies_file,
            youtube_po_token=youtube_po_token,
        )
        info = None
        try:
            info = extract_media_info(
                video_url,
                ydl_opts,
                download=True,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
            )
        except Exception as e:
            logger.warning(f"yt-dlp 字幕写盘失败 ({source_type}/{lang}): {e}")

        video_id = (info or {}).get("id")
        files = _collect_subtitle_files(out_dir, video_id=video_id)
        if files:
            files_sorted = sorted(
                files,
                key=lambda p: (
                    0 if p.suffix.lower() == ".json3" else 1 if p.suffix.lower() == ".vtt" else 2,
                    p.name,
                ),
            )
            for path in files_sorted:
                try:
                    text = _read_subtitle_file(path)
                except OSError as e:
                    logger.warning(f"读取字幕文件失败 {path.name}: {e}")
                    continue
                if text and len(text) >= MIN_SUBTITLE_CHARS:
                    ext = path.suffix.lstrip(".").lower()
                    file_lang = _subtitle_file_lang(path, video_id=video_id) or lang
                    return text, file_lang, ext
                logger.warning(
                    f"字幕文件内容不可用 ({source_type}/{lang}, {path.name}, "
                    f"{len(text or '')} chars)"
                )
        else:
            logger.warning(f"字幕已请求但未落盘 ({source_type}/{lang})")

    # Fallback: fetch caption URL via yt-dlp session (cookies/headers intact).
    entry = caption_entry or {}
    caption_url = entry.get("url")
    ext = (entry.get("ext") or "vtt").lower()
    if caption_url:
        try:
            text = _download_caption_url_with_ytdlp(
                caption_url,
                platform=platform,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
                youtube_po_token=youtube_po_token,
                ext=ext,
            )
            if text and len(text) >= MIN_SUBTITLE_CHARS:
                logger.info(f"字幕 URL 回退下载成功 ({source_type}/{lang})")
                return text, lang, ext
            logger.warning(f"字幕 URL 回退内容不可用 ({source_type}/{lang})")
        except Exception as e:
            logger.warning(f"字幕 URL 回退失败 ({source_type}/{lang}): {e}")

    return None, lang, None


def _list_caption_summary(captions: dict, limit: int = 12) -> str:
    keys = sorted((captions or {}).keys())
    if not keys:
        return "无"
    if len(keys) <= limit:
        return ", ".join(keys)
    return ", ".join(keys[:limit]) + f" …共{len(keys)}种"


def extract_platform_subtitle_text(
    video_url: str,
    preferred_langs: Optional[List[str]] = None,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    youtube_po_token: Optional[str] = None,
    platform: Optional[str] = None,
) -> tuple[Optional[str], dict]:
    """Extract platform subtitles via yt-dlp; return (text_or_None, metadata).

    Order: manual preferred languages → automatic preferred languages.
    Metadata always includes title/id when extract_info succeeds, plus
    caption diagnostics when available.
    """
    preferred_langs = list(preferred_langs or DEFAULT_PREFERRED_LANGS)
    platform = platform or detect_platform(video_url)
    metadata: dict = {
        "platform": platform,
        "caption_attempted": True,
        "caption_available_manual": [],
        "caption_available_automatic": [],
        "caption_failure_reason": None,
    }

    # Metadata-only probe (shared auth / extractor settings).
    ydl_opts = build_base_ydl_opts(quiet=True)
    ydl_opts.update(
        {
            "skip_download": True,
            "noplaylist": True,
            # Listing captions must not fail the whole extract when formats are gated.
            "ignore_no_formats_error": True,
        }
    )
    apply_platform_ydl_options(
        ydl_opts,
        platform,
        cookies_from_browser=cookies_from_browser,
        cookies_file=cookies_file,
        youtube_po_token=youtube_po_token,
    )
    if platform == PLATFORM_YOUTUBE:
        _apply_subtitle_youtube_clients(ydl_opts)

    try:
        info = extract_media_info(
            video_url,
            ydl_opts,
            download=False,
            cookies_from_browser=cookies_from_browser,
            cookies_file=cookies_file,
        )
    except Exception as e:
        metadata["caption_failure_reason"] = f"metadata_error: {e}"
        raise

    metadata.update(build_media_metadata(info, video_url, platform=platform))
    title = metadata.get("title") or "未知标题"

    manual = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {}
    # Normalize: some extractors put empty lists; keep only non-empty tracks.
    manual = {k: v for k, v in manual.items() if v}
    automatic = {k: v for k, v in automatic.items() if v}

    metadata["caption_available_manual"] = sorted(manual.keys())
    metadata["caption_available_automatic"] = sorted(automatic.keys())

    if not manual and not automatic:
        formats = info.get("formats") or []
        # Bot-gate often yields title + empty formats/captions.
        if platform == PLATFORM_YOUTUBE and not formats:
            metadata["caption_failure_reason"] = "auth_or_bot_check"
            logger.warning(
                f"未发现字幕轨且无可用媒体格式（可能触发 YouTube 风控）: {title}。"
                f"请更新 cookies（config.youtube / --cookies-from-browser）"
                f"或配置 --youtube-po-token 后重试。"
            )
            return None, metadata
        # Bilibili AI/CC subtitles are often invisible to yt-dlp; use player API.
        if platform == PLATFORM_BILIBILI:
            from .bilibili import fetch_bilibili_subtitle_text

            text, bili_meta = fetch_bilibili_subtitle_text(
                video_url,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
                preferred_langs=preferred_langs,
            )
            metadata.update({k: v for k, v in bili_meta.items() if v is not None})
            if text:
                return text, metadata
            logger.info(
                f"未发现平台字幕轨: {title}"
                f"（B站 API: {metadata.get('caption_failure_reason') or 'empty'}）"
            )
            metadata.setdefault("caption_failure_reason", "no_caption_tracks")
            return None, metadata
        metadata["caption_failure_reason"] = "no_caption_tracks"
        logger.info(f"未发现平台字幕轨: {title}")
        return None, metadata

    logger.info(
        f"发现字幕轨: {title} | 人工=[{_list_caption_summary(manual)}] | "
        f"自动=[{_list_caption_summary(automatic)}]"
    )

    attempts: list[tuple[str, str, dict]] = []
    for source_type, captions in (("manual", manual), ("automatic", automatic)):
        if not captions:
            continue
        # Build ordered unique language attempts for this source.
        seen: set[str] = set()
        ordered_langs: list[str] = []
        for preferred in preferred_langs:
            for lang in captions:
                if lang in seen:
                    continue
                if lang_matches(lang, preferred):
                    seen.add(lang)
                    ordered_langs.append(lang)
        for lang in captions:
            if lang not in seen:
                seen.add(lang)
                ordered_langs.append(lang)
        # Cap auto attempts: automatic captions can have 100+ machine languages.
        if source_type == "automatic":
            ordered_langs = ordered_langs[:8]
        else:
            ordered_langs = ordered_langs[:6]
        for lang in ordered_langs:
            entry = _pick_caption_entry(captions, lang) or {}
            attempts.append((source_type, lang, entry))

    last_errors: list[str] = []
    for source_type, lang, entry in attempts:
        text, file_lang, ext = _download_one_subtitle_track(
            video_url,
            platform=platform,
            source_type=source_type,
            lang=lang,
            caption_entry=entry,
            cookies_from_browser=cookies_from_browser,
            cookies_file=cookies_file,
            youtube_po_token=youtube_po_token,
        )
        if not text:
            last_errors.append(f"{source_type}/{lang}")
            continue

        metadata.update(
            {
                "caption_source": source_type,
                "caption_language": file_lang or lang,
                "caption_ext": ext,
                "caption_failure_reason": None,
            }
        )
        logger.info(
            f"已提取平台字幕: {title} ({source_type}/{metadata['caption_language']}, {ext})"
        )
        return text, metadata

    metadata["caption_failure_reason"] = "download_or_parse_failed"
    logger.warning(
        f"字幕轨存在但未能取得可用文本: {title} | "
        f"人工=[{_list_caption_summary(manual)}] 自动=[{_list_caption_summary(automatic)}] | "
        f"已尝试: {', '.join(last_errors[:12]) or '无'}。"
        f"可检查 cookies / --youtube-po-token 后重试。"
    )
    return None, metadata


def extract_youtube_subtitle_text(
    video_url: str,
    preferred_langs: Optional[List[str]] = None,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    youtube_po_token: Optional[str] = None,
) -> tuple[Optional[str], Optional[dict]]:
    """YouTube-oriented wrapper kept for existing imports/call sites."""
    text, metadata = extract_platform_subtitle_text(
        video_url,
        preferred_langs=preferred_langs,
        cookies_from_browser=cookies_from_browser,
        cookies_file=cookies_file,
        youtube_po_token=youtube_po_token,
        platform=PLATFORM_YOUTUBE,
    )
    return text, metadata
