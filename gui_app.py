"""Compatibility entrypoint: python gui_app.py

Mirrors transcribe.py so the GUI can start from the project root without
``pip install -e .``.
"""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from video_to_article.gui.app import main


if __name__ == "__main__":
    main()
