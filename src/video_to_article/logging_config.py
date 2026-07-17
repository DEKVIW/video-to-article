"""Application logging — force UTF-8 on Windows console + log files."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional, TextIO

from .paths import LOGS_DIR, ensure_runtime_dirs

_CONFIGURED = False


def ensure_utf8_stdio() -> None:
    """Best-effort: make stdout/stderr accept Unicode without mojibake on Windows."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                try:
                    reconfigure(errors="replace")
                except Exception:
                    pass


class _Utf8StreamWrapper:
    """Wrap a binary/text stream so logging always writes UTF-8 text safely."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self.encoding = "utf-8"

    def write(self, msg: str) -> int:
        if not msg:
            return 0
        try:
            return self._stream.write(msg)
        except UnicodeEncodeError:
            enc = getattr(self._stream, "encoding", None) or "utf-8"
            raw = msg.encode(enc, errors="replace")
            # binary fallback
            buffer = getattr(self._stream, "buffer", None)
            if buffer is not None:
                buffer.write(raw)
                return len(msg)
            return self._stream.write(raw.decode(enc, errors="replace"))
        except Exception:
            try:
                safe = msg.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
                return self._stream.write(safe)
            except Exception:
                return 0

    def flush(self) -> None:
        try:
            self._stream.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        try:
            return bool(self._stream.isatty())
        except Exception:
            return False


def configure_logging(*, force: bool = False) -> logging.Logger:
    """Configure app logging once and return the package logger.

    - File: logs/app.log as UTF-8
    - Console: UTF-8 when possible, never crash on non-encodable glyphs
    """
    global _CONFIGURED
    ensure_runtime_dirs()
    ensure_utf8_stdio()

    root_logger = logging.getLogger()
    package_logger = logging.getLogger("video_to_article")

    if _CONFIGURED and not force and root_logger.handlers:
        return package_logger

    if force:
        for h in list(root_logger.handlers):
            root_logger.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass

    if not root_logger.handlers or force:
        root_logger.setLevel(logging.INFO)
        # Prevent accidental double handlers if configure is raced
        for h in list(root_logger.handlers):
            root_logger.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass

        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        )

        log_path = Path(LOGS_DIR) / "app.log"
        file_handler = logging.FileHandler(log_path, encoding="utf-8", errors="replace")
        file_handler.setFormatter(fmt)
        file_handler.setLevel(logging.INFO)
        root_logger.addHandler(file_handler)

        stream = getattr(sys, "stderr", None) or sys.__stderr__
        console_handler = logging.StreamHandler(_Utf8StreamWrapper(stream))  # type: ignore[arg-type]
        console_handler.setFormatter(fmt)
        console_handler.setLevel(logging.INFO)
        root_logger.addHandler(console_handler)

        # Quiet noisy third-party loggers that flood the GUI / console
        for name in (
            "urllib3",
            "httpx",
            "httpcore",
            "openai",
            "filelock",
            "modelscope",
            "torch",
            "jieba",
        ):
            logging.getLogger(name).setLevel(logging.WARNING)

        # FunASR / ModelScope: keep warnings, drop chatty INFO (ckpt paths etc.)
        for name in ("funasr", "funasr.auto", "funasr.auto.auto_model"):
            logging.getLogger(name).setLevel(logging.WARNING)

        _CONFIGURED = True

    return package_logger
