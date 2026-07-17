"""Resolve bundled FFmpeg next to the app (preferred) then system PATH."""

from __future__ import annotations

import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional

from ..paths import APP_ROOT, get_app_root


def ffmpeg_dir() -> Path:
    """Directory that may contain ffmpeg.exe / ffprobe.exe."""
    return get_app_root() / "ffmpeg"


def _exe_name(tool: str) -> str:
    if sys.platform.startswith("win"):
        return f"{tool}.exe"
    return tool


@lru_cache(maxsize=4)
def resolve_ffmpeg_tool(tool: str = "ffmpeg") -> Optional[str]:
    """Return absolute path to ffmpeg or ffprobe, or None.

    Priority:
      1. APP_ROOT/ffmpeg/<tool>[.exe]
      2. shutil.which(tool) on PATH
    """
    name = _exe_name(tool)
    bundled = ffmpeg_dir() / name
    if bundled.is_file():
        return str(bundled.resolve())

    # Also accept bare name without .exe on Windows if present
    bare = ffmpeg_dir() / tool
    if bare.is_file():
        return str(bare.resolve())

    found = shutil.which(tool) or shutil.which(name)
    return str(Path(found).resolve()) if found else None


def resolve_ffmpeg() -> Optional[str]:
    return resolve_ffmpeg_tool("ffmpeg")


def resolve_ffprobe() -> Optional[str]:
    return resolve_ffmpeg_tool("ffprobe")


def ffmpeg_location_for_ytdlp() -> Optional[str]:
    """Directory or binary path for yt-dlp ``ffmpeg_location`` option."""
    path = resolve_ffmpeg()
    if not path:
        return None
    p = Path(path)
    # yt-dlp accepts a directory containing ffmpeg, or the binary path
    return str(p.parent if p.is_file() else p)


def ensure_ffmpeg_on_path() -> Optional[str]:
    """Prepend bundled ffmpeg dir to PATH so child processes (yt-dlp) find it.

    Returns the resolved ffmpeg binary path if available.
    """
    # Clear cache so newly-copied binaries are visible after first call
    resolve_ffmpeg_tool.cache_clear()

    bin_path = resolve_ffmpeg()
    if not bin_path:
        return None

    bin_dir = str(Path(bin_path).resolve().parent)
    path_env = os.environ.get("PATH", "")
    parts = path_env.split(os.pathsep) if path_env else []
    # Keep bundled dir first
    parts = [p for p in parts if p and Path(p).resolve() != Path(bin_dir).resolve()]
    os.environ["PATH"] = os.pathsep.join([bin_dir] + parts)
    return bin_path


def ffmpeg_status_message() -> str:
    path = resolve_ffmpeg()
    if not path:
        return (
            "未找到 FFmpeg。请将 ffmpeg.exe / ffprobe.exe 放到程序目录的 ffmpeg\\ 下，"
            "或安装系统 FFmpeg 并加入 PATH。"
        )
    bundled = Path(path).resolve().parent == ffmpeg_dir().resolve()
    where = "程序自带" if bundled else "系统 PATH"
    return f"FFmpeg ({where}): {path}"
