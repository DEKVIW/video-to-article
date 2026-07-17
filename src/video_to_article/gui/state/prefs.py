"""Lightweight UI preferences (not secrets; separate from config.json)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...paths import DATA_DIR

PREFS_FILE = DATA_DIR / "gui_prefs.json"

DEFAULT_PREFS: dict[str, Any] = {
    "last_mode": "single",
    "last_prompts": [],
    "enable_llm": True,
    "save_video": False,
    "skip_existing": True,
    "cover_mode": "config",
    "batch_source": "list",
    "cookies_from_browser": "",
    "cookies_file": "",
    "media_type": "video",
    "window_geometry": "",
    # 最近一次成功任务对应的结果目录（与日志中的路径一致）
    "last_result_dir": "",
}


def load_prefs() -> dict[str, Any]:
    prefs = dict(DEFAULT_PREFS)
    if not PREFS_FILE.exists():
        return prefs
    try:
        raw = json.loads(PREFS_FILE.read_text(encoding="utf-8-sig"))
        if isinstance(raw, dict):
            prefs.update(raw)
    except (OSError, json.JSONDecodeError):
        pass
    return prefs


def save_prefs(prefs: dict[str, Any]) -> None:
    PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
    merged = dict(DEFAULT_PREFS)
    merged.update(prefs)
    PREFS_FILE.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
