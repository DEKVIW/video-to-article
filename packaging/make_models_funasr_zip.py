# -*- coding: utf-8 -*-
"""Pack FunASR (SenseVoice + VAD) into a versionless offline zip under dist/releases.

The model pack is independent of the app version — same zip works for any release.

Usage (from project root):
  .venv\\Scripts\\python.exe packaging\\make_models_funasr_zip.py
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FUNASR_SRC = ROOT / "models" / "funasr"
SENSEVOICE_MARKER = (
    FUNASR_SRC / "models" / "iic" / "SenseVoiceSmall" / "model.pt"
)
ZIP_NAME = "YilanChengWen-models-funasr-sensevoice.zip"
SKIP_DIR_NAMES = {"._____temp", "__pycache__", ".git"}
SKIP_NAME_PARTS = {".lock"}


def _should_skip(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(p in SKIP_DIR_NAMES for p in rel.parts):
        return True
    if any(part in SKIP_NAME_PARTS for part in rel.parts):
        return True
    if path.suffix.lower() in {".pyc", ".tmp", ".part"}:
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pack FunASR offline models (no version tag in zip name)."
    )
    parser.add_argument(
        "--out-dir",
        default="",
        help="Output directory (default: dist/releases)",
    )
    args = parser.parse_args()

    if not SENSEVOICE_MARKER.is_file():
        print(f"ERROR: missing SenseVoice weights: {SENSEVOICE_MARKER}", file=sys.stderr)
        print("Run FunASR once to download, or copy models into models/funasr/.", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "dist" / "releases"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / ZIP_NAME
    if zip_path.exists():
        zip_path.unlink()

    readme_src = ROOT / "packaging" / "models_funasr_README.txt"
    if not readme_src.is_file():
        print(f"ERROR: missing {readme_src}", file=sys.stderr)
        return 1
    readme_body = readme_src.read_text(encoding="utf-8")

    # Staging: only models/ + 使用说明.txt (no VERSION / app version tags)
    stage = out_dir / "_stage_models_funasr"
    if stage.exists():
        shutil.rmtree(stage)
    stage_models = stage / "models" / "funasr"
    stage_models.parent.mkdir(parents=True, exist_ok=True)

    print(f"Copying {FUNASR_SRC} -> {stage_models} ...")
    shutil.copytree(
        FUNASR_SRC,
        stage_models,
        ignore=shutil.ignore_patterns(
            "._____temp",
            "__pycache__",
            "*.pyc",
            ".lock",
            "*.lock",
        ),
    )

    (stage / "使用说明.txt").write_text(readme_body, encoding="utf-8-sig")

    # Short pointer next to zip (also versionless)
    pointer = out_dir / "离线模型-FunASR说明.txt"
    pointer.write_text(
        "一览成文 — FunASR 离线模型\n"
        "========================\n\n"
        f"文件：{ZIP_NAME}\n"
        "内容：SenseVoiceSmall + 中文 VAD（默认转写引擎）\n\n"
        "用法：\n"
        "  1. 解压主程序绿色包\n"
        f"  2. 解压 {ZIP_NAME}\n"
        "  3. 把压缩包内的 models 文件夹复制到 YilanChengWen.exe 同级目录（合并）\n"
        "  4. 确认存在：models\\funasr\\models\\iic\\SenseVoiceSmall\\model.pt\n\n"
        "详细步骤见压缩包内「使用说明.txt」。\n",
        encoding="utf-8-sig",
    )

    count = 0
    total = 0
    print(f"Zipping -> {zip_path}")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in stage.rglob("*"):
            if not path.is_file():
                continue
            if _should_skip(path, stage):
                continue
            arc = path.relative_to(stage).as_posix()
            zf.write(path, arcname=arc)
            count += 1
            total += path.stat().st_size

    shutil.rmtree(stage, ignore_errors=True)

    zip_mb = zip_path.stat().st_size / (1024 * 1024)
    raw_mb = total / (1024 * 1024)
    print(f"OK: {zip_path}")
    print(f"    files={count}, raw≈{raw_mb:.1f} MB, zip≈{zip_mb:.1f} MB")
    print(f"    pointer: {pointer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
