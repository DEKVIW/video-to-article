# -*- mode: python ; coding: utf-8 -*-
# PyInstaller onedir spec for Video Quick Eval GUI.
# Build: see scripts/build_gui_onedir.ps1
#
# Notes:
# - Prefer onedir over onefile for torch/funasr stability.
# - models/ are NOT bundled here (too large); assemble step may copy optionally.
# - First full build can take a long time and produce multi-GB folders.

import sys
from pathlib import Path

block_cipher = None

# Spec may be analyzed with cwd = project root or packaging/
SPECDIR = Path(SPEC).resolve().parent if "SPEC" in dir() else Path(".").resolve()
ROOT = SPECDIR.parent if SPECDIR.name == "packaging" else SPECDIR
SRC = ROOT / "src"

# Ensure package import during analysis
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

datas = [
    (str(ROOT / "prompts"), "prompts"),
    (str(ROOT / "config.example.json"), "."),
    (str(ROOT / "packaging" / "user_README.txt"), "."),
    (str(ROOT / "packaging" / "app.ico"), "."),
    (str(ROOT / "src" / "video_to_article" / "gui" / "resources"), "video_to_article/gui/resources"),
]

hiddenimports = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "qfluentwidgets",
    "video_to_article",
    "video_to_article.gui",
    "video_to_article.gui.app",
    "video_to_article.gui.main_window",
    "video_to_article.gui.branding",
    "video_to_article.gui.workers",
    "video_to_article.processor",
    "video_to_article.batch",
    "video_to_article.prompts",
    "video_to_article.media.audio",
    "video_to_article.media.download",
    "video_to_article.providers.bilibili",
    "video_to_article.providers.youtube",
    "video_to_article.providers.youtube_auth",
    "video_to_article.providers.llm",
    "video_to_article.providers.subtitles",
    "video_to_article.providers.ytdlp_common",
    "yt_dlp",
    "openai",
    "anthropic",
    "requests",
    "PIL",
    "opencc",
    # ASR stack (may pull torch — large)
    "funasr",
    "modelscope",
    "faster_whisper",
]

_icon = str(ROOT / "packaging" / "app.ico")

a = Analysis(
    [str(ROOT / "packaging" / "gui_entry.py")],
    pathex=[str(SRC), str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "packaging" / "pyi_rth_app_root.py")],
    excludes=[
        "tkinter",
        "matplotlib",
        "notebook",
        "IPython",
        "pytest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="YilanChengWen",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI app, no black console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon if Path(_icon).is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="YilanChengWen",
)
