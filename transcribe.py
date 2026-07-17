"""Compatibility entrypoint for running the CLI from the project root.

The real application code lives in ``src/video_to_article`` so it can be
shared by the CLI, a future GUI, and packaging tools. This wrapper keeps the
existing ``python transcribe.py ...`` command working during development.
"""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_to_article.cli import main


if __name__ == "__main__":
    main()
