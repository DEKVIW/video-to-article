"""Runtime paths. Work relative to app root (dev project root or frozen exe dir)."""

from __future__ import annotations

import sys
from pathlib import Path


def get_app_root() -> Path:
    """Directory that holds config.json, prompts/, data/, output/, models/."""
    if getattr(sys, "frozen", False):
        # PyInstaller onedir: YilanChengWen.exe sits next to runtime folders
        return Path(sys.executable).resolve().parent

    # Dev: src/video_to_article/paths.py -> project root
    here = Path(__file__).resolve()
    # .../src/video_to_article/paths.py
    if here.parent.name == "video_to_article" and here.parents[1].name == "src":
        return here.parents[2]

    # Fallback: cwd (e.g. editable install without src layout)
    return Path.cwd()


APP_ROOT = get_app_root()

OUTPUT_DIR = APP_ROOT / "output"
DATA_DIR = APP_ROOT / "data"
MODEL_DIR = APP_ROOT / "models" / "whisper"
FUNASR_MODEL_DIR = APP_ROOT / "models" / "funasr"
PROMPTS_DIR = APP_ROOT / "prompts"
CONFIG_FILE = APP_ROOT / "config.json"
CONFIG_EXAMPLE_FILE = APP_ROOT / "config.example.json"
LOGS_DIR = APP_ROOT / "logs"

VIDEO_EXTENSIONS = {".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".webm", ".m4v", ".rm", ".rmvb"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
LOCAL_MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS


def ensure_runtime_dirs() -> None:
    """Create runtime directories used by the CLI / GUI app."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / "cookies").mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    FUNASR_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    PROMPTS_DIR.mkdir(exist_ok=True)
    (PROMPTS_DIR / "system").mkdir(exist_ok=True)
    (PROMPTS_DIR / "articles").mkdir(exist_ok=True)
    LOGS_DIR.mkdir(exist_ok=True)
    (APP_ROOT / "ffmpeg").mkdir(parents=True, exist_ok=True)
