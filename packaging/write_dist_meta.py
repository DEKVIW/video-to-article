# -*- coding: utf-8 -*-
"""写入绿色包元数据（UTF-8 BOM），避免 PowerShell 中文乱码。

用法:
  python packaging/write_dist_meta.py <dist_dir> <version>
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: write_dist_meta.py <dist_dir> <version>", file=sys.stderr)
        return 2

    dist = Path(sys.argv[1])
    ver = sys.argv[2].strip()
    root = Path(__file__).resolve().parent.parent
    dist.mkdir(parents=True, exist_ok=True)

    version_text = f"一览成文 YilanChengWen {ver}\n"
    (dist / "VERSION.txt").write_text(version_text, encoding="utf-8-sig")

    readme_src = root / "packaging" / "user_README.txt"
    if readme_src.is_file():
        body = readme_src.read_text(encoding="utf-8")
        # 标题行带上版本，便于用户核对
        if not body.lstrip().startswith("一览成文"):
            body = f"一览成文 YilanChengWen {ver}\n\n{body}"
        elif ver not in body.splitlines()[0]:
            lines = body.splitlines()
            lines[0] = f"一览成文（YilanChengWen）v{ver} — 桌面版使用说明"
            body = "\n".join(lines) + ("\n" if body.endswith("\n") else "")
    else:
        body = (
            f"一览成文 YilanChengWen {ver}\n"
            "================\n\n"
            "双击 YilanChengWen.exe 启动。\n"
        )

    readme_cn = dist / "使用说明.txt"
    readme_cn.write_text(body, encoding="utf-8-sig")
    (dist / "README.txt").write_text(body, encoding="utf-8-sig")

    # 兼容旧文件名
    (dist / "user_README.txt").write_text(body, encoding="utf-8-sig")
    (dist / "README_USER.txt").write_text(body, encoding="utf-8-sig")

    keep = {
        "VERSION.txt",
        "README.txt",
        "使用说明.txt",
        "user_README.txt",
        "README_USER.txt",
    }
    for p in dist.glob("*.txt"):
        if p.name not in keep and p.name not in {"models\\README.txt"}:
            # only top-level leftover junk
            if p.parent == dist and p.name.startswith("README"):
                continue
            if p.parent == dist and p.name not in keep:
                # keep models note etc. only under subdirs; top-level only known
                try:
                    if p.name not in keep:
                        # do not delete random user files; only known garbled leftovers
                        pass
                except OSError:
                    pass

    for d in (
        "data",
        "data/cookies",
        "output",
        "logs",
        "models",
        "models/funasr",
        "models/whisper",
        "ffmpeg",
    ):
        (dist / d).mkdir(parents=True, exist_ok=True)

    ico = root / "packaging" / "app.ico"
    if ico.is_file():
        (dist / "app.ico").write_bytes(ico.read_bytes())

    models_note = dist / "models" / "README.txt"
    if not models_note.is_file():
        models_note.write_text(
            "Models directory (external)\n"
            "===========================\n"
            "FunASR / Whisper weights are NOT bundled by default.\n"
            "1. Copy your models folder next to YilanChengWen.exe\n"
            "2. Or allow first-run model download into this folder\n"
            "Download-only mode works without local ASR models.\n",
            encoding="utf-8-sig",
        )

    assert readme_cn.name == "使用说明.txt", readme_cn.name
    assert (dist / "VERSION.txt").read_text(encoding="utf-8-sig").startswith("一览成文")
    print(f"meta written: {dist} (v{ver})")
    print("  VERSION.txt OK, 使用说明.txt OK, README.txt OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
