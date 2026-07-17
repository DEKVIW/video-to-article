"""Runtime hook: chdir to onedir folder so relative paths resolve next to the exe."""

import os
import sys
from pathlib import Path


def _main() -> None:
    if not getattr(sys, "frozen", False):
        return
    root = Path(sys.executable).resolve().parent
    try:
        os.chdir(root)
    except OSError:
        pass


_main()
