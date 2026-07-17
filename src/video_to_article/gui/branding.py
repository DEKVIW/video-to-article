"""Product branding constants for 一览成文."""

from __future__ import annotations

from pathlib import Path

APP_NAME_ZH = "一览成文"
APP_NAME_EN = "YilanChengWen"
APP_WINDOW_TITLE = "一览成文 — 视频整理工作台"
APP_ABOUT = "视频转写 · 多类型文章模板 · 可选封面"
APP_ORG = "yilanapp"
APP_VERSION = "0.4.5"

# 作者博客（帮助菜单 / 关于 / 侧栏 / 状态栏可点击打开）
BLOG_URL = "https://blog.yilanapp.com/"
BLOG_LABEL = "作者博客"

# Prefer package resources, then project resources/, then packaging/
_PKG_DIR = Path(__file__).resolve().parent


def icon_path() -> Path | None:
    candidates = [
        _PKG_DIR / "resources" / "app.ico",
        _PKG_DIR / "resources" / "app.png",
        Path.cwd() / "resources" / "app.ico",
        Path.cwd() / "resources" / "app.png",
        Path.cwd() / "packaging" / "app.ico",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None
