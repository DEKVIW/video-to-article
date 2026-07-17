import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..config import load_config
from ..logging_config import configure_logging
from ..paths import DATA_DIR
from ..text_utils import import_required

logger = configure_logging()

DEFAULT_COOKIE_FILE = DATA_DIR / "cookies" / "youtube.txt"
YOUTUBE_COOKIE_FILE_ENV = "VQE_YOUTUBE_COOKIES"
YOUTUBE_COOKIES_FROM_BROWSER_ENV = "VQE_YOUTUBE_COOKIES_FROM_BROWSER"
YOUTUBE_PO_TOKEN_ENV = "VQE_YOUTUBE_PO_TOKEN"

IMPORTANT_COOKIE_NAMES = {
    "SID",
    "HSID",
    "SSID",
    "APISID",
    "SAPISID",
    "__Secure-1PSID",
    "__Secure-3PSID",
    "__Secure-1PAPISID",
    "__Secure-3PAPISID",
    "LOGIN_INFO",
}


class YtDlpMessageLogger:
    """Collect yt-dlp messages so auth checks can classify soft failures."""

    def __init__(self) -> None:
        self.debug_messages: list[str] = []
        self.warning_messages: list[str] = []
        self.error_messages: list[str] = []

    def debug(self, message: str) -> None:
        self.debug_messages.append(str(message))

    def warning(self, message: str) -> None:
        self.warning_messages.append(str(message))

    def error(self, message: str) -> None:
        self.error_messages.append(str(message))


@dataclass
class YouTubeAuth:
    """Resolved YouTube auth settings for yt-dlp."""

    cookies_from_browser: Optional[str] = None
    cookies_file: Optional[str] = None
    youtube_po_token: Optional[str] = None
    source: str = "none"


def parse_browser_spec(browser_spec: str) -> tuple:
    """Parse yt-dlp BROWSER[+KEYRING][:PROFILE][::CONTAINER] shorthand."""
    browser_spec = browser_spec.strip()
    if not browser_spec:
        return ()

    container = None
    before_container = browser_spec
    if "::" in browser_spec:
        before_container, container = browser_spec.split("::", 1)
        container = container or None

    profile = None
    before_profile = before_container
    if ":" in before_container:
        before_profile, profile = before_container.split(":", 1)
        profile = profile or None

    keyring = None
    browser = before_profile
    if "+" in before_profile:
        browser, keyring = before_profile.split("+", 1)
        keyring = keyring or None

    values = [browser, profile, keyring, container]
    while values and values[-1] is None:
        values.pop()
    return tuple(values)


def resolve_youtube_auth(
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    youtube_po_token: Optional[str] = None,
) -> YouTubeAuth:
    """Resolve YouTube auth from CLI args, env vars, config, then default files.

    Browser cookies are preferred for automatic auth. Cookie files remain useful
    for exported private/incognito sessions or machines without a browser.
    """
    config = load_config()
    youtube_config = config.get("youtube", {}) if isinstance(config, dict) else {}

    resolved_po_token = (
        youtube_po_token
        or os.getenv(YOUTUBE_PO_TOKEN_ENV)
        or youtube_config.get("po_token")
        or youtube_config.get("youtube_po_token")
    )

    if cookies_from_browser:
        return YouTubeAuth(
            cookies_from_browser=cookies_from_browser,
            youtube_po_token=resolved_po_token,
            source="--cookies-from-browser",
        )

    if cookies_file:
        return YouTubeAuth(
            cookies_file=prepare_cookie_file(cookies_file),
            youtube_po_token=resolved_po_token,
            source="--cookies",
        )

    env_browser = os.getenv(YOUTUBE_COOKIES_FROM_BROWSER_ENV)
    if env_browser:
        return YouTubeAuth(
            cookies_from_browser=env_browser,
            youtube_po_token=resolved_po_token,
            source=YOUTUBE_COOKIES_FROM_BROWSER_ENV,
        )

    env_cookie_file = os.getenv(YOUTUBE_COOKIE_FILE_ENV)
    if env_cookie_file:
        return YouTubeAuth(
            cookies_file=prepare_cookie_file(env_cookie_file),
            youtube_po_token=resolved_po_token,
            source=YOUTUBE_COOKIE_FILE_ENV,
        )

    config_browser = youtube_config.get("cookies_from_browser")
    if config_browser:
        return YouTubeAuth(
            cookies_from_browser=str(config_browser),
            youtube_po_token=resolved_po_token,
            source="config.youtube.cookies_from_browser",
        )

    config_cookie_file = youtube_config.get("cookies_file")
    if config_cookie_file:
        return YouTubeAuth(
            cookies_file=prepare_cookie_file(str(config_cookie_file)),
            youtube_po_token=resolved_po_token,
            source="config.youtube.cookies_file",
        )

    if DEFAULT_COOKIE_FILE.exists():
        return YouTubeAuth(
            cookies_file=prepare_cookie_file(str(DEFAULT_COOKIE_FILE)),
            youtube_po_token=resolved_po_token,
            source=str(DEFAULT_COOKIE_FILE),
        )

    return YouTubeAuth(youtube_po_token=resolved_po_token)


def apply_ytdlp_auth_options(
    ydl_opts: dict,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
) -> dict:
    """Attach cookie auth options to yt-dlp options."""
    auth = resolve_youtube_auth(cookies_from_browser, cookies_file)
    if auth.cookies_file:
        ydl_opts["cookiefile"] = auth.cookies_file
    elif auth.cookies_from_browser:
        ydl_opts["cookiesfrombrowser"] = parse_browser_spec(auth.cookies_from_browser)
    return ydl_opts


def apply_youtube_po_token(ydl_opts: dict, po_token: Optional[str] = None) -> dict:
    """Attach a YouTube PO token for subtitle requests when provided."""
    resolved_token = po_token or resolve_youtube_auth().youtube_po_token
    if not resolved_token:
        return ydl_opts
    extractor_args = ydl_opts.setdefault("extractor_args", {})
    youtube_args = extractor_args.setdefault("youtube", {})
    youtube_args["po_token"] = [resolved_token]
    return ydl_opts


def prepare_cookie_file(cookies_file: str) -> str:
    """Return a yt-dlp compatible cookie file path.

    yt-dlp expects Netscape cookies.txt. If the user saved a raw browser
    Cookie header, convert it into a local Netscape file automatically.
    """
    path = Path(cookies_file)
    if not path.exists():
        return cookies_file

    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return cookies_file
    if text.startswith("# Netscape HTTP Cookie File"):
        return str(path)
    if not looks_like_raw_cookie_header(text):
        return str(path)

    output_path = DATA_DIR / "cookies" / f"{path.stem}.netscape.txt"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(raw_cookie_header_to_netscape(text), encoding="utf-8")
    logger.info(f"已将浏览器 Cookie 头转换为 Netscape cookies.txt: {output_path}")
    return str(output_path)


def looks_like_raw_cookie_header(text: str) -> bool:
    """Detect a single-line browser Cookie header."""
    first_line = text.splitlines()[0].strip()
    return "=" in first_line and (";" in first_line or first_line.count("=") == 1) and "\t" not in first_line


def raw_cookie_header_to_netscape(cookie_header: str, domain: str = ".youtube.com") -> str:
    """Convert a browser Cookie header into Netscape cookies.txt content."""
    lines = [
        "# Netscape HTTP Cookie File",
        "# Generated from a browser Cookie header. Keep this file private.",
    ]
    for item in cookie_header.replace("\n", " ").split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        secure = "TRUE" if name.startswith("__Secure-") else "FALSE"
        lines.append(f"{domain}\tTRUE\t/\t{secure}\t0\t{name}\t{value}")
    return "\n".join(lines) + "\n"


def inspect_cookie_file(cookies_file: Optional[str]) -> dict:
    """Inspect a cookie file without exposing cookie values."""
    if not cookies_file:
        return {"exists": False, "ok": False, "message": "未指定 cookies 文件"}

    original_path = Path(cookies_file)
    prepared_path = Path(prepare_cookie_file(cookies_file))
    status = {
        "path": str(prepared_path),
        "original_path": str(original_path),
        "exists": prepared_path.exists(),
        "ok": False,
        "format": "unknown",
        "cookie_count": 0,
        "important_present": [],
        "expired_important": [],
        "expires_soon": [],
        "warnings": [],
    }

    if not prepared_path.exists():
        status["message"] = "cookies 文件不存在"
        return status

    text = prepared_path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        status["message"] = "cookies 文件为空"
        return status

    if looks_like_raw_cookie_header(text):
        status["format"] = "raw_cookie_header"
        status["warnings"].append("这是浏览器 Cookie 头格式，已支持自动转换，但没有可靠过期时间。")
        prepared_path = Path(prepare_cookie_file(cookies_file))
        text = prepared_path.read_text(encoding="utf-8", errors="replace").strip()
        status["path"] = str(prepared_path)

    if text.startswith("# Netscape HTTP Cookie File"):
        status["format"] = "netscape"
    elif "\t" in text:
        status["format"] = "netscape_without_header"
        status["warnings"].append("文件像 Netscape cookies.txt，但缺少标准头。建议用浏览器插件重新导出。")
    else:
        status["message"] = "cookies 文件不是 yt-dlp 需要的 Netscape cookies.txt 格式"
        return status

    now = int(time.time())
    soon_threshold = now + 7 * 24 * 60 * 60
    cookie_count = 0
    important_present = set()
    expired_important = set()
    expires_soon = set()

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        cookie_count += 1
        expires_raw = parts[4]
        name = parts[5]
        if name not in IMPORTANT_COOKIE_NAMES:
            continue
        important_present.add(name)
        try:
            expires = int(expires_raw)
        except ValueError:
            continue
        if expires == 0:
            continue
        if expires < now:
            expired_important.add(name)
        elif expires < soon_threshold:
            expires_soon.add(name)

    status["cookie_count"] = cookie_count
    status["important_present"] = sorted(important_present)
    status["expired_important"] = sorted(expired_important)
    status["expires_soon"] = sorted(expires_soon)

    if not cookie_count:
        status["message"] = "没有解析到有效 cookie 行"
        return status
    if not important_present:
        status["message"] = "没有找到 YouTube/Google 登录态关键 cookie"
        return status
    if expired_important:
        status["message"] = "关键登录态 cookie 已过期"
        return status

    if expires_soon:
        status["warnings"].append("部分关键 cookie 将在 7 天内过期，建议近期重新导出。")

    status["ok"] = True
    status["message"] = "cookies 文件格式正常，包含 YouTube 登录态关键 cookie"
    return status


def diagnose_ytdlp_error(error: Exception | str) -> str:
    """Return a short user-facing hint for common yt-dlp YouTube auth failures."""
    message = str(error)
    lower = message.lower()

    if "does not look like a netscape format cookies file" in lower:
        return "cookies 文件格式不对：请用浏览器插件导出 Netscape cookies.txt，或把浏览器 Cookie 头单独保存。"
    if "failed to decrypt with dpapi" in lower:
        return "Windows DPAPI 无法解密浏览器 cookies：请用和 Chrome/Edge 相同的 Windows 用户运行终端，不要管理员/普通用户混用；也可指定正确 Profile，或改用 Firefox/导出的 cookies.txt。"
    if "could not copy chrome cookie database" in lower:
        return "无法复制 Chrome cookie 数据库：建议先完全关闭 Chrome/Edge 后重试；仍失败时指定 Profile、改用 Firefox，或使用导出的 data\\cookies\\youtube.txt。"
    if "account cookies are no longer valid" in lower or "cookies are no longer valid" in lower:
        return "cookies 文件格式正常，但 YouTube 登录态已被浏览器或 YouTube 轮换失效，需要重新导出 cookies.txt。"
    if "sign in to confirm" in lower or "not a bot" in lower:
        return "YouTube 没有接受当前登录态：cookies 可能过期、账号未登录、导出域名不完整，建议重新导出 cookies.txt。"
    if "po token" in lower:
        return "字幕接口需要 YouTube PO Token；批量场景建议让程序回退到 ASR 转写，当前默认使用 FunASR。"
    if "requested format is not available" in lower or "only images are available" in lower:
        return "yt-dlp 没拿到可下载音视频格式，常见原因是 YouTube JS challenge、cookie 登录态不足或当前网络被风控。"
    if "read timed out" in lower or "timed out" in lower or "connection reset" in lower:
        return "网络下载超时：通常是 googlevideo 连接不稳定，建议重试，或稍后再跑。"
    if "remote components" in lower or "challenge solving failed" in lower:
        return "YouTube JS challenge 解析失败：确认 yt-dlp 已更新，并允许 --remote-components ejs:github。"
    return ""


def is_youtube_auth_error(error: Exception | str) -> bool:
    """Return True only when retrying without cookies is meaningful."""
    lower = str(error).lower()
    markers = [
        "sign in to confirm",
        "not a bot",
        "account cookies are no longer valid",
        "cookies are no longer valid",
        "does not look like a netscape format cookies file",
        "failed to decrypt with dpapi",
        "could not copy chrome cookie database",
    ]
    return any(marker in lower for marker in markers)


def diagnose_ytdlp_messages(messages: list[str]) -> str:
    """Diagnose yt-dlp warning/error messages."""
    joined = "\n".join(messages)
    return diagnose_ytdlp_error(joined)


def check_youtube_auth(
    video_url: str,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    youtube_po_token: Optional[str] = None,
) -> dict:
    """Run a quick yt-dlp metadata/subtitle check for YouTube auth."""
    from .youtube import apply_youtube_extractor_options

    yt_dlp = import_required("yt_dlp", "yt-dlp")
    auth = resolve_youtube_auth(cookies_from_browser, cookies_file, youtube_po_token)
    cookie_status = inspect_cookie_file(auth.cookies_file) if auth.cookies_file else None

    ydl_opts = {
        "quiet": True,
        "no_warnings": False,
        "noplaylist": True,
        "skip_download": True,
        "format": None,
        "ignore_no_formats_error": True,
    }
    apply_youtube_extractor_options(ydl_opts)
    if auth.youtube_po_token:
        apply_youtube_po_token(ydl_opts, auth.youtube_po_token)
    if auth.cookies_file:
        ydl_opts["cookiefile"] = auth.cookies_file
    elif auth.cookies_from_browser:
        ydl_opts["cookiesfrombrowser"] = parse_browser_spec(auth.cookies_from_browser)

    message_logger = YtDlpMessageLogger()
    ydl_opts["logger"] = message_logger

    result = {
        "success": False,
        "usable": False,
        "auth": auth,
        "cookie_status": cookie_status,
        "title": None,
        "format_count": 0,
        "subtitles": [],
        "automatic_captions": [],
        "warnings": [],
        "errors": [],
        "error": None,
        "hint": None,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
    except Exception as e:
        result["warnings"] = message_logger.warning_messages
        result["errors"] = message_logger.error_messages
        result["error"] = str(e)
        result["hint"] = diagnose_ytdlp_error(e) or diagnose_ytdlp_messages(
            message_logger.warning_messages + message_logger.error_messages
        )
        return result

    result["success"] = True
    result["title"] = info.get("title")
    result["format_count"] = len(info.get("formats") or [])
    result["subtitles"] = sorted((info.get("subtitles") or {}).keys())
    result["automatic_captions"] = sorted((info.get("automatic_captions") or {}).keys())
    result["warnings"] = message_logger.warning_messages
    result["errors"] = message_logger.error_messages

    warning_hint = diagnose_ytdlp_messages(message_logger.warning_messages + message_logger.error_messages)
    if warning_hint:
        result["hint"] = warning_hint

    has_content = bool(result["format_count"] or result["subtitles"] or result["automatic_captions"])
    has_cookie_invalid_warning = any("cookies are no longer valid" in warning.lower() for warning in result["warnings"])
    result["usable"] = bool(has_content and not has_cookie_invalid_warning)

    if not result["hint"] and not has_content:
        result["hint"] = "YouTube 请求返回了元数据，但没有可用音视频格式或字幕；通常是 cookie 登录态失效、PO Token 缺失或网络被风控。"
    return result


def refresh_cookie_file_from_browser(browser: str, output_file: Optional[str] = None) -> dict:
    """Ask yt-dlp to export browser cookies into a Netscape cookies.txt file."""
    yt_dlp_cookies = import_required("yt_dlp.cookies", "yt-dlp")
    output_path = Path(output_file) if output_file else DEFAULT_COOKIE_FILE
    output_path.parent.mkdir(parents=True, exist_ok=True)

    message_logger = YtDlpMessageLogger()
    result = {
        "success": False,
        "browser": browser,
        "output_file": str(output_path),
        "cookie_status": None,
        "warnings": [],
        "errors": [],
        "error": None,
        "hint": None,
    }

    try:
        browser_name, profile, keyring, container = (*parse_browser_spec(browser), None, None, None)[:4]
        cookie_jar = yt_dlp_cookies.extract_cookies_from_browser(
            browser_name,
            profile,
            logger=message_logger,
            keyring=keyring,
            container=container,
        )
        cookie_jar.save(str(output_path), ignore_discard=True, ignore_expires=True)
    except Exception as e:
        result["warnings"] = message_logger.warning_messages
        result["errors"] = message_logger.error_messages
        result["error"] = str(e)
        result["hint"] = diagnose_ytdlp_error(e) or diagnose_ytdlp_messages(
            message_logger.warning_messages + message_logger.error_messages
        )
        return result

    result["warnings"] = message_logger.warning_messages
    result["errors"] = message_logger.error_messages
    result["cookie_status"] = inspect_cookie_file(str(output_path))
    result["success"] = bool(result["cookie_status"].get("ok"))
    if not result["success"]:
        result["hint"] = result["cookie_status"].get("message")
    return result
