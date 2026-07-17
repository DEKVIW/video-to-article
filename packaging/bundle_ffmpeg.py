# -*- coding: utf-8 -*-
"""Copy ffmpeg.exe / ffprobe.exe into a target ffmpeg/ directory.

Search order for source binaries:
  1. --source DIR
  2. env VQE_FFMPEG_DIR
  3. project_root/ffmpeg/ (if already populated)
  4. directory of `ffmpeg` found on PATH

Usage:
  python packaging/bundle_ffmpeg.py
  python packaging/bundle_ffmpeg.py --target dist/YilanChengWen/ffmpeg
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ("ffmpeg", "ffprobe")


def _win_name(tool: str) -> str:
    return f"{tool}.exe" if sys.platform.startswith("win") else tool


def find_source_dir(explicit: str = "") -> Path | None:
    candidates: list[Path] = []
    if explicit.strip():
        candidates.append(Path(explicit.strip()))
    env = os.environ.get("VQE_FFMPEG_DIR", "").strip()
    if env:
        candidates.append(Path(env))
    candidates.append(ROOT / "ffmpeg")

    which = shutil.which("ffmpeg")
    if which:
        candidates.append(Path(which).resolve().parent)

    for d in candidates:
        if not d.is_dir():
            continue
        ff = d / _win_name("ffmpeg")
        if ff.is_file():
            return d.resolve()
    return None


def copy_tools(src_dir: Path, dst_dir: Path) -> list[str]:
    dst_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    src_dir = src_dir.resolve()
    dst_dir = dst_dir.resolve()
    for tool in TOOLS:
        name = _win_name(tool)
        src = src_dir / name
        if not src.is_file():
            print(f"  skip missing: {src}")
            continue
        dst = dst_dir / name
        if src_dir == dst_dir or (dst.is_file() and src.resolve() == dst.resolve()):
            print(f"  already in place: {dst}")
            copied.append(name)
            continue
        try:
            shutil.copy2(src, dst)
        except OSError as e:
            if dst.is_file() and dst.stat().st_size > 0:
                print(f"  keep existing {name} ({e})")
                copied.append(name)
                continue
            raise
        mb = dst.stat().st_size / (1024 * 1024)
        print(f"  copied {name} ({mb:.1f} MB) -> {dst}")
        copied.append(name)

    note = dst_dir / "README.txt"
    note.write_text(
        "Bundled FFmpeg for 一览成文 / YilanChengWen\n"
        "==========================================\n\n"
        "This folder should contain ffmpeg.exe and ffprobe.exe.\n"
        "The app prefers binaries here over the system PATH.\n\n"
        "FFmpeg is free software (typically LGPL/GPL depending on build).\n"
        "Upstream: https://ffmpeg.org/\n"
        "If redistributing, keep this notice and respect the build license.\n",
        encoding="utf-8",
    )
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description="Bundle ffmpeg into app ffmpeg/ dir")
    parser.add_argument("--source", default="", help="Directory containing ffmpeg binaries")
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="Target ffmpeg/ directory (repeatable). Default: project ffmpeg/ only",
    )
    parser.add_argument(
        "--also-project",
        action="store_true",
        help="Also ensure project_root/ffmpeg is populated",
    )
    args = parser.parse_args()

    src = find_source_dir(args.source)
    if not src:
        print(
            "ERROR: could not find ffmpeg. Install FFmpeg, or set VQE_FFMPEG_DIR, "
            "or pass --source DIR",
            file=sys.stderr,
        )
        return 1

    print(f"Source: {src}")
    targets = [Path(t) for t in args.target] if args.target else []
    if not targets or args.also_project:
        targets = list(targets) + [ROOT / "ffmpeg"]
    # unique preserve order
    seen: set[str] = set()
    uniq: list[Path] = []
    for t in targets:
        key = str(t.resolve()) if t.exists() or True else str(t)
        # normalize
        t = t if t.name.lower() == "ffmpeg" else t / "ffmpeg"
        key = str(t)
        if key not in seen:
            seen.add(key)
            uniq.append(t)

    ok = False
    for dst in uniq:
        print(f"Target: {dst}")
        copied = copy_tools(src, dst)
        if "ffmpeg.exe" in copied or "ffmpeg" in copied:
            ok = True
        else:
            print("  WARNING: ffmpeg binary not copied", file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
