"""GUI application entrypoint — 一览成文."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _bootstrap_paths() -> Path:
    """Set cwd to app root; ensure import path in dev."""
    if getattr(sys, "frozen", False):
        root = Path(sys.executable).resolve().parent
    else:
        here = Path(__file__).resolve()
        root = here.parents[3] if here.parents[1].name == "video_to_article" else Path.cwd()
        src_dir = root / "src"
        if src_dir.is_dir() and str(src_dir) not in sys.path:
            sys.path.insert(0, str(src_dir))

    for candidate in (root, Path.cwd()):
        if (candidate / "config.example.json").exists() or (candidate / "config.json").exists():
            root = candidate
            break

    try:
        os.chdir(root)
    except OSError:
        pass
    return root


def _hydrate_bundled_assets(app_root: Path) -> None:
    """Copy prompts / example config out of PyInstaller _MEIPASS on first run."""
    if not getattr(sys, "frozen", False):
        return
    meipass = Path(getattr(sys, "_MEIPASS", "") or "")
    if not meipass.is_dir():
        return

    example_src = meipass / "config.example.json"
    example_dst = app_root / "config.example.json"
    if example_src.is_file() and not example_dst.exists():
        try:
            example_dst.write_bytes(example_src.read_bytes())
        except OSError:
            pass

    prompts_src = meipass / "prompts"
    prompts_dst = app_root / "prompts"
    if prompts_src.is_dir():
        try:
            # merge tree without wiping user files
            for src in prompts_src.rglob("*"):
                if src.is_dir():
                    continue
                rel = src.relative_to(prompts_src)
                dst = prompts_dst / rel
                if not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
        except OSError:
            pass

    for name in ("user_README.txt", "使用说明.txt"):
        readme_src = meipass / name
        if readme_src.is_file():
            readme_dst = app_root / "使用说明.txt"
            if not readme_dst.exists():
                try:
                    readme_dst.write_bytes(readme_src.read_bytes())
                except OSError:
                    pass
            break


def main() -> None:
    app_root = _bootstrap_paths()
    _hydrate_bundled_assets(app_root)

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox
    from qfluentwidgets import Theme, setTheme

    from video_to_article.gui.branding import APP_NAME_EN, APP_ORG, APP_WINDOW_TITLE, icon_path
    from video_to_article.gui.main_window import MainWindow
    from video_to_article.logging_config import configure_logging, ensure_utf8_stdio
    from video_to_article.media.ffmpeg_tools import ensure_ffmpeg_on_path, ffmpeg_status_message
    from video_to_article.paths import CONFIG_EXAMPLE_FILE, CONFIG_FILE, ensure_runtime_dirs, get_app_root

    ensure_utf8_stdio()
    configure_logging()
    ensure_runtime_dirs()
    ensure_ffmpeg_on_path()

    if not CONFIG_FILE.exists() and CONFIG_EXAMPLE_FILE.exists():
        try:
            CONFIG_FILE.write_text(CONFIG_EXAMPLE_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME_EN)
    app.setOrganizationName(APP_ORG)
    setTheme(Theme.AUTO)

    from video_to_article.gui.theme_style import apply_app_typography, apply_fluent_label_sizes

    apply_app_typography(app)

    icon = icon_path()
    if icon is not None:
        app.setWindowIcon(QIcon(str(icon)))

    window = MainWindow()
    window.setWindowTitle(APP_WINDOW_TITLE)
    if icon is not None:
        window.setWindowIcon(QIcon(str(icon)))
    apply_fluent_label_sizes(window)
    window.show()

    if not CONFIG_FILE.exists():
        QMessageBox.warning(
            window,
            "缺少配置",
            "未找到 config.json。\n"
            "请在程序目录放置 config.json（可复制 config.example.json 后填写 API Key）。\n"
            f"当前目录：{get_app_root()}",
        )

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
