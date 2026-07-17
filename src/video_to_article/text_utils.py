import re
from typing import Optional

from .logging_config import configure_logging

logger = configure_logging()


def format_time(seconds: float) -> str:
    """Format seconds in a compact Chinese display."""
    if seconds < 60:
        return f"{seconds:.1f}秒"
    if seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}分{secs:.0f}秒"

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours}小时{minutes}分"


def sanitize_filename(name: str, max_length: int = 60) -> str:
    """Create a filesystem-safe filename segment."""
    safe_name = "".join(c for c in name if c.isalnum() or c in (" ", "-", "_")).strip()
    safe_name = "_".join(safe_name.split())
    return safe_name[:max_length] or "untitled"


def sanitize_path_component(name: str) -> str:
    """Keep directory name semantics while replacing illegal path characters."""
    invalid_chars = '<>:"/\\|?*'
    safe_name = "".join("_" if c in invalid_chars else c for c in name).strip()
    safe_name = safe_name.rstrip(". ")
    return safe_name or "untitled"


def traditional_to_simplified(text: str) -> str:
    """Convert Traditional Chinese text to Simplified Chinese when OpenCC exists."""
    try:
        from opencc import OpenCC
    except ImportError:
        logger.warning("未安装 opencc-python-reimplemented，跳过繁简转换")
        return text

    cc = OpenCC("t2s")
    return cc.convert(text)


def import_required(module_name: str, install_name: Optional[str] = None):
    """Lazy import a dependency and provide a friendly install error."""
    try:
        return __import__(module_name)
    except ImportError as e:
        package_name = install_name or module_name
        raise RuntimeError(f"缺少依赖 {package_name}，请先运行: pip install -r requirements.txt") from e


def clean_caption_text(text: str) -> str:
    """Clean subtitle markup and duplicate consecutive lines."""
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'")
    lines = []
    seen_consecutive = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "-->" in line:
            continue
        if re.match(r"^(WEBVTT|Kind:|Language:)", line, re.IGNORECASE):
            continue
        if re.match(r"^\d+$", line):
            continue
        if line == seen_consecutive:
            continue
        lines.append(line)
        seen_consecutive = line

    return "\n".join(lines).strip()
