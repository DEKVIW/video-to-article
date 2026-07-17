import os
import re
from urllib.parse import urlparse


# Canonical platform names used across download, output, and blog modules.
PLATFORM_LOCAL = "Local"
PLATFORM_YOUTUBE = "YouTube"
PLATFORM_BILIBILI = "Bilibili"
PLATFORM_DOUYIN = "Douyin"
PLATFORM_KUAISHOU = "Kuaishou"
PLATFORM_XIAOHONGSHU = "Xiaohongshu"
PLATFORM_WEIBO = "Weibo"
PLATFORM_UNKNOWN = "Unknown"

# Platforms with first-class yt-dlp support in this project.
SUPPORTED_ONLINE_PLATFORMS = {
    PLATFORM_YOUTUBE,
    PLATFORM_BILIBILI,
    PLATFORM_DOUYIN,
    PLATFORM_XIAOHONGSHU,
    PLATFORM_WEIBO,
}

# Detected but download may fail until yt-dlp gains an extractor.
PARTIAL_ONLINE_PLATFORMS = {
    PLATFORM_KUAISHOU,
}


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def detect_platform(url: str) -> str:
    """Detect source platform for a URL or local path."""
    if not url:
        return PLATFORM_UNKNOWN

    if os.path.exists(url) or (not url.startswith("http://") and not url.startswith("https://")):
        return PLATFORM_LOCAL

    url_lower = url.lower()
    host = _host(url)

    if "bilibili.com" in host or host.endswith("b23.tv") or "b23.tv" in url_lower:
        return PLATFORM_BILIBILI

    if "youtube.com" in host or "youtu.be" in host or "youtube.com" in url_lower or "youtu.be" in url_lower:
        return PLATFORM_YOUTUBE

    # Douyin / 抖音（含短链 v.douyin.com）
    if any(token in host for token in ("douyin.com", "iesdouyin.com")) or "v.douyin.com" in url_lower:
        return PLATFORM_DOUYIN

    # 快手（yt-dlp 可能尚无 extractor，仍先识别）
    if any(token in host for token in ("kuaishou.com", "chenzhongtech.com", "gifshow.com", "kwai.com")):
        return PLATFORM_KUAISHOU

    # 小红书
    if any(token in host for token in ("xiaohongshu.com", "xhslink.com", "xhscdn.com")):
        return PLATFORM_XIAOHONGSHU

    # 微博视频
    if any(token in host for token in ("weibo.com", "weibo.cn", "weibo.com.cn")):
        return PLATFORM_WEIBO

    return PLATFORM_UNKNOWN


def platform_slug(platform: str) -> str:
    """Filesystem-friendly platform folder name."""
    mapping = {
        PLATFORM_LOCAL: "local",
        PLATFORM_YOUTUBE: "youtube",
        PLATFORM_BILIBILI: "bilibili",
        PLATFORM_DOUYIN: "douyin",
        PLATFORM_KUAISHOU: "kuaishou",
        PLATFORM_XIAOHONGSHU: "xiaohongshu",
        PLATFORM_WEIBO: "weibo",
        PLATFORM_UNKNOWN: "unknown",
    }
    return mapping.get(platform, re.sub(r"[^a-z0-9]+", "-", (platform or "unknown").lower()).strip("-") or "unknown")


def is_online_platform(platform: str) -> bool:
    return platform not in {PLATFORM_LOCAL, PLATFORM_UNKNOWN, ""}


def is_youtube_url(url: str) -> bool:
    """Return whether a URL points to YouTube."""
    return detect_platform(url) == PLATFORM_YOUTUBE


def is_bilibili_url(url: str) -> bool:
    return detect_platform(url) == PLATFORM_BILIBILI


def is_youtube_collection_url(url: str) -> bool:
    """Return whether a YouTube URL looks like a playlist/channel/videos page."""
    if not is_youtube_url(url):
        return False

    parsed = urlparse(url)
    path = parsed.path.lower()
    query = parsed.query.lower()
    if "list=" in query:
        return True
    return (
        path.startswith("/@")
        or path.startswith("/channel/")
        or path.startswith("/c/")
        or path.startswith("/user/")
        or path.endswith("/videos")
        or "/videos" in path
    )


def platform_download_hint(platform: str) -> str:
    """Human-readable capability note for a platform."""
    if platform == PLATFORM_LOCAL:
        return "本地文件，无需下载"
    if platform in SUPPORTED_ONLINE_PLATFORMS:
        return "支持音频/视频下载（依赖 yt-dlp）"
    if platform == PLATFORM_KUAISHOU:
        return "已识别快手链接，但当前 yt-dlp 未内置快手提取器，下载可能失败"
    if platform == PLATFORM_UNKNOWN:
        return "未知平台，将尝试用 yt-dlp 通用提取"
    return "将尝试用 yt-dlp 下载"
