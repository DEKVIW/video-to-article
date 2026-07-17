"""Capture print()/logging output from worker threads into the GUI log panel."""

from __future__ import annotations

import logging
import sys
from typing import Callable, Optional, TextIO


class GuiLogStream:
    """File-like object that forwards writes to a callback (UTF-8 safe)."""

    encoding = "utf-8"
    errors = "replace"

    def __init__(self, write_callback: Callable[[str], None], also: Optional[TextIO] = None) -> None:
        self._write_callback = write_callback
        self._also = also
        self._buffer = ""

    def write(self, text) -> int:
        if text is None:
            return 0
        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="replace")
        if not isinstance(text, str):
            text = str(text)
        if not text:
            return 0
        if self._also is not None:
            try:
                self._also.write(text)
            except UnicodeEncodeError:
                try:
                    enc = getattr(self._also, "encoding", None) or "utf-8"
                    self._also.write(text.encode(enc, errors="replace").decode(enc, errors="replace"))
                except Exception:
                    pass
            except Exception:
                pass
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            try:
                self._write_callback(line + "\n")
            except Exception:
                pass
        return len(text)

    def flush(self) -> None:
        if self._buffer:
            try:
                self._write_callback(self._buffer)
            except Exception:
                pass
            self._buffer = ""
        if self._also is not None:
            try:
                self._also.flush()
            except Exception:
                pass

    def isatty(self) -> bool:
        return False

    def reconfigure(self, **kwargs) -> None:
        # Libraries (and Python 3.7+) may call this; keep UTF-8 identity.
        if "encoding" in kwargs and kwargs["encoding"]:
            type(self).encoding = str(kwargs["encoding"])


class GuiLogHandler(logging.Handler):
    """Logging handler that forwards records to the GUI log callback."""

    def __init__(self, write_callback: Callable[[str], None]) -> None:
        super().__init__()
        self._write_callback = write_callback
        self.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            if not isinstance(msg, str):
                msg = str(msg)
            self._write_callback(msg + "\n")
        except Exception:
            self.handleError(record)


class StdioRedirect:
    """Context manager: redirect stdout/stderr (and optional root logger) to GUI."""

    def __init__(self, write_callback: Callable[[str], None], capture_logging: bool = True) -> None:
        self._write_callback = write_callback
        self._capture_logging = capture_logging
        self._old_stdout = None
        self._old_stderr = None
        self._handler: Optional[GuiLogHandler] = None
        self._console_handlers: list[logging.Handler] = []

    def __enter__(self) -> "StdioRedirect":
        self._old_stdout = sys.stdout
        self._old_stderr = sys.stderr
        sys.stdout = GuiLogStream(self._write_callback, also=self._old_stdout)  # type: ignore[assignment]
        sys.stderr = GuiLogStream(self._write_callback, also=self._old_stderr)  # type: ignore[assignment]
        if self._capture_logging:
            # Avoid double lines: temporarily detach console StreamHandlers that still
            # point at the original stderr (they don't follow sys.stderr reassignment).
            root = logging.getLogger()
            self._console_handlers = []
            for h in list(root.handlers):
                if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
                    stream = getattr(h, "stream", None)
                    # Keep FileHandler; mute bare StreamHandler during GUI capture
                    if stream is self._old_stderr or stream is self._old_stdout or stream is sys.__stderr__:
                        self._console_handlers.append(h)
                        root.removeHandler(h)
            self._handler = GuiLogHandler(self._write_callback)
            self._handler.setLevel(logging.INFO)
            root.addHandler(self._handler)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if isinstance(sys.stdout, GuiLogStream):
                sys.stdout.flush()
            if isinstance(sys.stderr, GuiLogStream):
                sys.stderr.flush()
        except Exception:
            pass
        if self._old_stdout is not None:
            sys.stdout = self._old_stdout
        if self._old_stderr is not None:
            sys.stderr = self._old_stderr
        root = logging.getLogger()
        if self._handler is not None:
            root.removeHandler(self._handler)
            self._handler = None
        for h in self._console_handlers:
            root.addHandler(h)
        self._console_handlers = []
