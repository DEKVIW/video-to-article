"""Bilibili search, metadata, and CC/AI subtitle helpers."""

from __future__ import annotations

import html
import json
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import quote

from ..logging_config import configure_logging
from ..text_utils import import_required

logger = configure_logging()

BILIBILI_SEARCH_API = "https://api.bilibili.com/x/web-interface/search/type"
BILIBILI_SPI_API = "https://api.bilibili.com/x/frontend/finger/spi"
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

ORDER_MAP = {
    "totalrank": "totalrank",
    "pubdate": "pubdate",
    "click": "click",
    "dm": "dm",
}


def clean_bilibili_title(title: str) -> str:
    """Strip Bilibili search highlight tags and decode HTML entities."""
    if not title:
        return "未知标题"
    text = html.unescape(str(title))
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip() or "未知标题"


def extract_bvid(url_or_id: str) -> str:
    """Extract a BVid from a URL or bare id."""
    if not url_or_id:
        return ""
    text = str(url_or_id).strip()
    match = re.search(r"(BV[\w]+)", text, re.IGNORECASE)
    if match:
        return match.group(1)
    return ""


def extract_aid(url_or_id: str) -> str:
    """Extract a numeric aid from av URLs / bare ids."""
    if not url_or_id:
        return ""
    text = str(url_or_id).strip()
    match = re.search(r"(?:av|/video/av)?(\d{5,})", text, re.IGNORECASE)
    if match:
        return match.group(1)
    if text.isdigit() and len(text) >= 5:
        return text
    return ""


def search_bilibili_videos(keyword: str, count: int = 5, order: str = "totalrank") -> List[Dict[str, Any]]:
    """Search Bilibili videos.

    Strategy (in order):
    1. bilibili-api-python if installed
    2. Public HTTP API with SPI cookies (no extra dependency)
    3. yt-dlp bilisearch fallback
    """
    keyword = (keyword or "").strip()
    if not keyword:
        logger.warning("搜索关键词为空")
        return []

    count = max(1, int(count or 5))
    order = ORDER_MAP.get(order, "totalrank")
    logger.info(f"搜索B站视频: 关键词='{keyword}', 数量={count}, 排序={order}")

    for name, fn in (
        ("bilibili-api", lambda: _search_via_bilibili_api(keyword, count, order)),
        ("HTTP API", lambda: _search_via_http_api(keyword, count, order)),
        ("yt-dlp bilisearch", lambda: _search_via_ytdlp(keyword, count)),
    ):
        try:
            videos = fn()
        except Exception as e:
            logger.warning(f"{name} 搜索异常: {e}")
            videos = []
        if videos:
            logger.info(f"搜索完成（{name}），找到 {len(videos)} 个视频")
            return videos

    logger.error("B站搜索失败：所有搜索通道均不可用")
    return []


def _search_via_bilibili_api(keyword: str, count: int, order: str) -> List[Dict[str, Any]]:
    try:
        from bilibili_api import search, sync
    except ImportError:
        logger.info("未安装 bilibili-api-python，跳过该通道")
        return []

    try:
        order_map = {
            "totalrank": search.OrderVideo.TOTALRANK,
            "pubdate": search.OrderVideo.PUBDATE,
            "click": search.OrderVideo.CLICK,
            "dm": search.OrderVideo.DM,
        }
        order_type = order_map.get(order, search.OrderVideo.TOTALRANK)

        async def _search():
            return await search.search_by_type(
                keyword=keyword,
                search_type=search.SearchObjectType.VIDEO,
                order_type=order_type,
                page=1,
            )

        result = sync(_search())
        raw_items = (result or {}).get("result") or []
        return _normalize_search_items(raw_items, count)
    except Exception as e:
        logger.warning(f"bilibili-api 搜索失败: {e}")
        return []


def _build_bilibili_session(
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
):
    """Create a requests session; attach browser/file cookies when provided.

    AI/CC subtitles often require login (``need_login_subtitle``). Anonymous
    SPI cookies are enough for search but not for subtitle listing.
    """
    requests = import_required("requests", "requests")
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": DEFAULT_UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Origin": "https://www.bilibili.com",
            "Referer": "https://www.bilibili.com",
        }
    )

    _attach_auth_cookies(session, cookies_from_browser, cookies_file)

    # Always ensure buvid exists for API hygiene
    if not session.cookies.get("buvid3", domain=".bilibili.com"):
        buvid3 = str(uuid.uuid4()).upper() + "infoc"
        try:
            spi = session.get(BILIBILI_SPI_API, timeout=15)
            spi.raise_for_status()
            payload = spi.json() if spi.content else {}
            data = (payload or {}).get("data") or {}
            if data.get("b_3"):
                buvid3 = data["b_3"]
            if data.get("b_4"):
                session.cookies.set("buvid4", data["b_4"], domain=".bilibili.com")
        except Exception as e:
            logger.warning(f"获取 B站 SPI 指纹失败，将使用本地 buvid3: {e}")
        session.cookies.set("buvid3", buvid3, domain=".bilibili.com")
    return session


def _attach_auth_cookies(
    session,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
) -> None:
    """Load Bilibili cookies from Netscape file and/or browser via yt-dlp."""
    from http.cookiejar import MozillaCookieJar

    if cookies_file:
        try:
            jar = MozillaCookieJar(str(cookies_file))
            jar.load(ignore_discard=True, ignore_expires=True)
            session.cookies.update(jar)
            logger.info(f"已加载 cookies 文件: {cookies_file}")
        except Exception as e:
            logger.warning(f"加载 cookie 文件失败 ({cookies_file}): {e}")

    if cookies_from_browser:
        try:
            yt_dlp = import_required("yt_dlp", "yt-dlp")
            from .youtube_auth import parse_browser_spec

            # YoutubeDL loads browser cookies into its cookiejar on init.
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "cookiesfrombrowser": parse_browser_spec(cookies_from_browser),
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                jar = getattr(ydl, "cookiejar", None)
                if jar is None:
                    raise RuntimeError("yt-dlp 未提供 cookiejar")
                count = 0
                for c in jar:
                    domain = (c.domain or "").lstrip(".")
                    if "bili" not in domain and "hdslb" not in domain:
                        # Keep SESSDATA / bili-related only to avoid bloating
                        name = c.name or ""
                        if name not in {
                            "SESSDATA",
                            "bili_jct",
                            "DedeUserID",
                            "DedeUserID__ckMd5",
                            "sid",
                            "buvid3",
                            "buvid4",
                        }:
                            continue
                    try:
                        session.cookies.set(
                            c.name,
                            c.value,
                            domain=c.domain or ".bilibili.com",
                            path=c.path or "/",
                        )
                        count += 1
                    except Exception:
                        continue
                logger.info(
                    f"已从浏览器导入 B站相关 cookies: {cookies_from_browser} ({count} 条)"
                )
                if count == 0:
                    # Fallback: import all cookies (some builds domain-filter too strict)
                    for c in jar:
                        try:
                            session.cookies.set(
                                c.name,
                                c.value,
                                domain=c.domain or ".bilibili.com",
                                path=c.path or "/",
                            )
                            count += 1
                        except Exception:
                            pass
                    if count:
                        logger.info(f"已回退导入全部 cookies 中的 {count} 条")
        except Exception as e:
            logger.warning(f"从浏览器读取 B站 cookies 失败: {e}")


def bilibili_json_to_srt(payload: dict) -> str:
    """Convert Bilibili CC/AI subtitle JSON to SRT text."""
    body = payload.get("body") if isinstance(payload, dict) else None
    if not isinstance(body, list) or not body:
        return ""

    def _ts(sec: float) -> str:
        if sec < 0:
            sec = 0.0
        ms = int(round(sec * 1000))
        h, rem = divmod(ms, 3600_000)
        m, rem = divmod(rem, 60_000)
        s, milli = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"

    lines: list[str] = []
    idx = 1
    for item in body:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        start = float(item.get("from") or 0)
        end = float(item.get("to") or start)
        if end <= start:
            end = start + 0.5
        lines.append(str(idx))
        lines.append(f"{_ts(start)} --> {_ts(end)}")
        lines.append(content)
        lines.append("")
        idx += 1
    return "\n".join(lines).strip() + ("\n" if lines else "")


def bilibili_json_to_plain(payload: dict) -> str:
    """Flatten subtitle JSON to plain transcript text."""
    body = payload.get("body") if isinstance(payload, dict) else None
    if not isinstance(body, list):
        return ""
    parts = []
    for item in body:
        if isinstance(item, dict):
            c = str(item.get("content") or "").strip()
            if c:
                parts.append(c)
    return "\n".join(parts)


def list_bilibili_subtitle_tracks(
    video_url: str,
    *,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
) -> tuple[list[dict], dict]:
    """List CC/AI subtitle tracks via Bilibili player API.

    Returns (tracks, meta) where each track has lan, lan_doc, subtitle_url.
    """
    bvid = extract_bvid(video_url)
    meta: dict[str, Any] = {"platform": "Bilibili", "bvid": bvid}
    if not bvid:
        meta["caption_failure_reason"] = "invalid_bvid"
        return [], meta

    session = _build_bilibili_session(cookies_from_browser, cookies_file)
    view = session.get(
        f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
        timeout=20,
    ).json()
    if view.get("code") != 0:
        meta["caption_failure_reason"] = f"view_api:{view.get('message') or view.get('code')}"
        return [], meta

    data = view.get("data") or {}
    meta["title"] = data.get("title") or "未知标题"
    meta["id"] = bvid
    meta["thumbnail"] = data.get("pic") or data.get("banner") or ""
    meta["channel"] = (
        (data.get("owner") or {}).get("name")
        or data.get("owner_name")
        or ""
    )
    meta["uploader"] = meta["channel"]
    pages = data.get("pages") or []
    if not pages:
        meta["caption_failure_reason"] = "no_pages"
        return [], meta
    cid = pages[0].get("cid")
    meta["cid"] = cid

    player = session.get(
        f"https://api.bilibili.com/x/player/v2?bvid={bvid}&cid={cid}",
        timeout=20,
    ).json()
    if player.get("code") != 0:
        meta["caption_failure_reason"] = f"player_api:{player.get('message') or player.get('code')}"
        return [], meta

    pdata = player.get("data") or {}
    meta["need_login_subtitle"] = bool(pdata.get("need_login_subtitle"))
    meta["login_mid"] = pdata.get("login_mid")
    tracks = ((pdata.get("subtitle") or {}).get("subtitles") or [])
    # Normalize URL
    for t in tracks:
        url = t.get("subtitle_url") or ""
        if url.startswith("//"):
            t["subtitle_url"] = "https:" + url
    meta["caption_available_manual"] = [
        str(t.get("lan") or "") for t in tracks if t.get("subtitle_url")
    ]
    if not tracks:
        if meta.get("need_login_subtitle") and not meta.get("login_mid"):
            meta["caption_failure_reason"] = "auth_or_bot_check"
            logger.warning(
                "B站字幕需登录后可见，请使用 --cookies-from-browser 或 cookies 文件（已登录 bilibili.com）"
            )
        else:
            meta["caption_failure_reason"] = "no_caption_tracks"
    return tracks, meta


def pick_bilibili_subtitle_track(
    tracks: Sequence[dict],
    preferred_langs: Optional[Sequence[str]] = None,
) -> Optional[dict]:
    """Pick best track: zh AI/manual first, then preferred list, then first."""
    if not tracks:
        return None
    preferred = [str(p).lower() for p in (preferred_langs or [])]

    def score(t: dict) -> tuple:
        lan = str(t.get("lan") or "").lower()
        doc = str(t.get("lan_doc") or "")
        # Prefer Chinese
        zh = 0
        if lan in {"zh-cn", "zh", "ai-zh", "zh-hans"} or "中文" in doc:
            zh = 0
        elif lan.startswith("ai-zh") or "zh" in lan:
            zh = 1
        else:
            zh = 10
        # Prefer preferred lang match
        pref = 50
        for i, p in enumerate(preferred):
            if p in lan or lan in p or (p.startswith("zh") and "zh" in lan):
                pref = i
                break
        # Prefer non-ai slightly? Actually AI is fine; manual often empty lan
        ai = 1 if lan.startswith("ai-") else 0
        return (zh, pref, ai)

    ranked = sorted([t for t in tracks if t.get("subtitle_url")], key=score)
    return ranked[0] if ranked else None


def fetch_bilibili_subtitle_text(
    video_url: str,
    *,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    preferred_langs: Optional[Sequence[str]] = None,
) -> tuple[Optional[str], dict]:
    """Download best Bilibili CC/AI subtitle as plain text + metadata."""
    tracks, meta = list_bilibili_subtitle_tracks(
        video_url,
        cookies_from_browser=cookies_from_browser,
        cookies_file=cookies_file,
    )
    if not tracks:
        return None, meta

    track = pick_bilibili_subtitle_track(tracks, preferred_langs)
    if not track:
        meta["caption_failure_reason"] = "no_caption_tracks"
        return None, meta

    session = _build_bilibili_session(cookies_from_browser, cookies_file)
    url = track.get("subtitle_url") or ""
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        meta["caption_failure_reason"] = f"subtitle_download_failed:{e}"
        return None, meta

    plain = bilibili_json_to_plain(payload)
    if len(plain.strip()) < 8:
        meta["caption_failure_reason"] = "subtitle_empty"
        return None, meta

    meta.update(
        {
            "caption_source": "ai" if str(track.get("lan") or "").startswith("ai-") else "manual",
            "caption_language": track.get("lan") or track.get("lan_doc") or "unknown",
            "caption_ext": "json",
            "caption_failure_reason": None,
            "thumbnail": meta.get("thumbnail"),  # may be filled by caller
        }
    )
    # thumbnail from view already? not set — optional
    logger.info(
        f"已通过 B站 API 提取字幕: {meta.get('title')} "
        f"({meta.get('caption_source')}/{meta.get('caption_language')})"
    )
    return plain, meta


def download_bilibili_subtitles_to_dir(
    video_url: str,
    out_dir: Path,
    *,
    stem: str,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    preferred_langs: Optional[Sequence[str]] = None,
    all_langs: bool = False,
) -> tuple[list[str], dict]:
    """Write Bilibili subtitle files (srt + optional json) under out_dir.

    Returns (paths, meta).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tracks, meta = list_bilibili_subtitle_tracks(
        video_url,
        cookies_from_browser=cookies_from_browser,
        cookies_file=cookies_file,
    )
    if not tracks:
        return [], meta

    session = _build_bilibili_session(cookies_from_browser, cookies_file)
    if all_langs:
        chosen = [t for t in tracks if t.get("subtitle_url")]
    else:
        one = pick_bilibili_subtitle_track(tracks, preferred_langs)
        chosen = [one] if one else []

    saved: list[str] = []
    for track in chosen:
        lan = re.sub(r"[^\w\-]+", "_", str(track.get("lan") or "und"))[:20]
        url = track.get("subtitle_url") or ""
        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            logger.warning(f"下载 B站字幕失败 ({lan}): {e}")
            continue
        srt = bilibili_json_to_srt(payload)
        if not srt.strip():
            continue
        # SRT only — common format for players / tools; no need for raw JSON by default
        srt_path = out_dir / f"{stem}.{lan}.srt"
        srt_path.write_text(srt, encoding="utf-8")
        saved.append(str(srt_path))
        logger.info(f"B站字幕已保存: {srt_path}")

    if saved:
        meta["caption_failure_reason"] = None
        meta["caption_files"] = saved
        best = pick_bilibili_subtitle_track(tracks, preferred_langs) or tracks[0]
        meta["caption_source"] = (
            "ai" if str(best.get("lan") or "").startswith("ai-") else "manual"
        )
        meta["caption_language"] = best.get("lan") or "unknown"
    else:
        meta["caption_failure_reason"] = meta.get("caption_failure_reason") or "download_or_parse_failed"
    return saved, meta


def _search_via_http_api(keyword: str, count: int, order: str) -> List[Dict[str, Any]]:
    """Search via Bilibili public web API (no extra package)."""
    try:
        session = _build_bilibili_session()
    except RuntimeError as e:
        logger.error(str(e))
        return []

    page_size = min(max(count, 1), 50)
    params = {
        "search_type": "video",
        "keyword": keyword,
        "order": order,
        "page": 1,
        "page_size": page_size,
    }
    headers = {
        "Referer": f"https://search.bilibili.com/all?keyword={quote(keyword)}",
        "Origin": "https://search.bilibili.com",
    }

    try:
        response = session.get(BILIBILI_SEARCH_API, params=params, headers=headers, timeout=20)
        response.raise_for_status()
        # Some anti-bot responses return HTML with 200.
        content_type = (response.headers.get("content-type") or "").lower()
        if "json" not in content_type and not response.text.lstrip().startswith("{"):
            logger.error("B站 HTTP 搜索返回非 JSON（可能触发风控）")
            return []
        payload = response.json()
    except Exception as e:
        logger.error(f"B站 HTTP 搜索请求失败: {e}")
        return []

    if not isinstance(payload, dict):
        logger.error("B站 HTTP 搜索返回格式异常")
        return []

    code = payload.get("code")
    if code not in (0, None):
        logger.error(f"B站 HTTP 搜索业务错误: code={code}, message={payload.get('message')}")
        return []

    data = payload.get("data") or {}
    raw_items = data.get("result") or data.get("items") or []
    if not raw_items:
        logger.warning(f"搜索无结果: {keyword}")
        return []

    return _normalize_search_items(raw_items, count)


def _search_via_ytdlp(keyword: str, count: int) -> List[Dict[str, Any]]:
    """Fallback search using yt-dlp's bilisearch extractor."""
    try:
        yt_dlp = import_required("yt_dlp", "yt-dlp")
    except RuntimeError as e:
        logger.error(str(e))
        return []

    query = f"bilisearch{count}:{keyword}"
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "playlistend": count,
        "http_headers": {
            "User-Agent": DEFAULT_UA,
            "Referer": "https://www.bilibili.com",
        },
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)
    except Exception as e:
        logger.warning(f"yt-dlp bilisearch 失败: {e}")
        return []

    entries = (info or {}).get("entries") or []
    videos: List[Dict[str, Any]] = []
    for entry in entries:
        if not entry:
            continue
        url = entry.get("url") or entry.get("webpage_url") or ""
        bvid = extract_bvid(url) or extract_bvid(str(entry.get("id") or ""))
        aid = extract_aid(url) or extract_aid(str(entry.get("id") or ""))
        if bvid:
            final_url = f"https://www.bilibili.com/video/{bvid}"
            media_id = bvid
        elif aid:
            final_url = f"https://www.bilibili.com/video/av{aid}"
            media_id = f"av{aid}"
        else:
            continue
        title = clean_bilibili_title(str(entry.get("title") or media_id))
        videos.append(
            {
                "url": final_url,
                "title": title,
                "bvid": bvid or media_id,
                "duration": int(entry.get("duration") or 0),
                "play": int(entry.get("view_count") or entry.get("play") or 0),
                "author": str(entry.get("uploader") or entry.get("channel") or "未知UP主"),
            }
        )
        if len(videos) >= count:
            break
    return videos


def _normalize_search_items(raw_items: list, count: int) -> List[Dict[str, Any]]:
    video_list: List[Dict[str, Any]] = []
    for video in raw_items:
        if not isinstance(video, dict):
            continue
        # Some payloads interleave tips / media cards.
        item_type = video.get("type")
        if item_type not in (None, "video", "bili_video") and not video.get("bvid"):
            continue
        bvid = video.get("bvid") or extract_bvid(str(video.get("arcurl") or video.get("url") or ""))
        aid = video.get("aid") or video.get("id")
        if not bvid and aid:
            bvid = ""
            url = f"https://www.bilibili.com/video/av{aid}"
        elif bvid:
            url = f"https://www.bilibili.com/video/{bvid}"
        else:
            continue

        title = clean_bilibili_title(str(video.get("title") or "未知标题"))
        duration_raw = video.get("duration") or video.get("length") or "0:00"
        play = video.get("play") or video.get("view") or video.get("video_review") or 0
        try:
            play = int(play)
        except (TypeError, ValueError):
            play = 0
        author = video.get("author") or video.get("uname") or video.get("owner") or "未知UP主"
        if isinstance(author, dict):
            author = author.get("name") or author.get("uname") or "未知UP主"

        video_list.append(
            {
                "url": url,
                "title": title,
                "bvid": bvid or f"av{aid}",
                "duration": _parse_duration(str(duration_raw)),
                "play": play,
                "author": str(author),
            }
        )
        if len(video_list) >= count:
            break

    if not video_list:
        logger.warning("搜索结果解析后为空")
    return video_list


def _parse_duration(duration_str: str) -> int:
    """Parse duration string into seconds."""
    try:
        text = str(duration_str).strip()
        if text.isdigit():
            return int(text)
        parts = text.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        return 0
    except Exception:
        return 0


def format_duration(seconds: int) -> str:
    """Format seconds as duration text."""
    try:
        seconds = int(seconds or 0)
    except (TypeError, ValueError):
        seconds = 0
    if seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}:{secs:02d}"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:02d}"


def format_play_count(count: int) -> str:
    """Format play count in Chinese compact form."""
    try:
        count = int(count or 0)
    except (TypeError, ValueError):
        count = 0
    if count >= 10000:
        return f"{count / 10000:.1f}万"
    return str(count)


def get_bilibili_video_url(bvid: str) -> str:
    bvid = extract_bvid(bvid) or bvid
    return f"https://www.bilibili.com/video/{bvid}"
