"""Capture print()/logging output from worker threads into the GUI log panel.

Why GUI logs look worse than PowerShell CLI
------------------------------------------
PowerShell is a TTY: tqdm rewrites the *same* line with ``\\r`` + ANSI colors.
The GUI log panel is a plain text widget (not a terminal): each ``\\r`` becomes
a new fragment, ANSI codes show as garbage, and partial writes glue onto the
next real ``[INFO]`` line.

Strategy
--------
1. Prefer disabling third-party progress bars at the source (e.g. FunASR
   ``disable_pbar`` on AutoModel).
2. Sanitize anything that still slips through: strip ANSI, drop tqdm/rtf noise,
   but *salvage* real log lines that got glued onto progress junk.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from typing import Callable, List, Optional, TextIO

# ANSI color / cursor junk from tqdm & terminal libraries
_ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[a-zA-Z]"
    r"|\x1b\].*?(?:\x07|\x1b\\)"
    r"|\x1b[()][0-9A-B]"
    r"|\x9b[0-9;?]*[a-zA-Z]"  # CSI without ESC
)

# Real application log lines we must keep even when stuck to tqdm residue.
# Use fixed HH:MM:SS (not \d{1,2}) so "12:35:02" is never split into "1"+"2:35:02".
_LOG_TS_LEVEL = r"\d{2}:\d{2}:\d{2}\s+\[(?:DEBUG|INFO|WARNING|ERROR|CRITICAL)\]"
_KEEP_LINE_RE = re.compile(
    r"(?:"
    rf"{_LOG_TS_LEVEL}"
    r"|^\s*\[GUI\]"
    r"|^\s*步骤\s*\d+"
    r"|^\s*(?:警告|错误|提醒|提示)[:：]"
    r")"
)

# FunASR / tqdm progress noise markers (substring match after ANSI strip)
_PROGRESS_NOISE_RE = re.compile(
    r"(?:"
    r"\d+%\|"  # 0%| or 100%|
    r"|[█░▓▒▀▄■□▪▫]+"  # block progress glyphs
    r"|rtf_avg\s*:"
    r"|time_speech\s*:"
    r"|time_escape\s*:"
    r"|'load_data'\s*:"
    r"|'extract_feat'\s*:"
    r"|'forward'\s*:"
    r"|'batch_size'\s*:"
    r"|\bit/s\b"
    r"|\bs/it\b"
    r"|\[\??\s*\d*:?\d*<[^\]]*\]"  # [00:01<00:00, ...] or [00:00<?, ?it/s]
    r")"
)

# Split glued tqdm dumps so we can recover trailing INFO lines
_SPLIT_KEEP_RE = re.compile(rf"(?=(?:{_LOG_TS_LEVEL}))")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _is_progress_noise(stripped: str) -> bool:
    if not stripped:
        return True
    if _PROGRESS_NOISE_RE.search(stripped):
        # Still keep if the *whole* useful payload is a real log line and noise is incidental
        # (handled by split); pure/mostly progress → drop
        keep_hits = _KEEP_LINE_RE.findall(stripped)
        if not keep_hits:
            return True
        # If keep markers exist but line is dominated by tqdm, treat as mixed — not pure noise
        return False
    if stripped.startswith("{") and stripped.endswith("}") and "rtf" in stripped.lower():
        return True
    # leftover spinner / bare percent lines
    if re.fullmatch(r"[\d\s%|/\-:<>,.?it]+", stripped):
        return True
    return False


def _extract_keepable_parts(text: str) -> List[str]:
    """From a (possibly glued) chunk, return clean non-progress lines."""
    text = _strip_ansi(text)
    text = text.replace("\r", "\n")
    # collapse leftover control chars
    text = "".join(ch if ch == "\n" or ord(ch) >= 32 or ch in "\t" else "" for ch in text)

    out: list[str] = []
    for raw_part in text.split("\n"):
        if not raw_part.strip():
            continue
        # tqdm may glue "....it]12:35:26 [INFO] ..."
        pieces = _SPLIT_KEEP_RE.split(raw_part)
        if len(pieces) == 1:
            pieces = [raw_part]
        for piece in pieces:
            stripped = piece.strip()
            if not stripped:
                continue
            if _is_progress_noise(stripped) and not _KEEP_LINE_RE.search(stripped):
                continue
            if _KEEP_LINE_RE.search(stripped) and _PROGRESS_NOISE_RE.search(stripped):
                # Mixed: keep only from the first real log marker onward
                m = re.search(rf"{_LOG_TS_LEVEL}.*", stripped)
                if m:
                    out.append(m.group(0).rstrip())
                continue
            if _is_progress_noise(stripped):
                continue
            out.append(piece.rstrip())
    return out


def sanitize_gui_log_line(line: str) -> Optional[str]:
    """Strip ANSI and drop tqdm/progress-only lines. Returns None to skip."""
    if line is None:
        return None
    if not isinstance(line, str):
        line = str(line)
    parts = _extract_keepable_parts(line)
    if not parts:
        return None
    return "\n".join(parts) + "\n"


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

        # Normalize CR-only tqdm updates into newlines so they can be filtered.
        # Also force a split before a glued "HH:MM:SS [LEVEL]" so INFO is not lost.
        # Lookbehind excludes digits so "12:35:02" is never split after the leading "1".
        chunk = text.replace("\r\n", "\n").replace("\r", "\n")
        chunk = re.sub(rf"(?<=[^\d\n])(?={_LOG_TS_LEVEL})", "\n", chunk)
        self._buffer += chunk
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            cleaned = sanitize_gui_log_line(line + "\n")
            if not cleaned:
                continue
            try:
                self._write_callback(cleaned)
            except Exception:
                pass
        return len(text)

    def flush(self) -> None:
        # Always sanitize residual buffer (tqdm often leaves a partial line without \\n)
        if self._buffer:
            residual = self._buffer
            self._buffer = ""
            cleaned = sanitize_gui_log_line(residual)
            if cleaned:
                try:
                    self._write_callback(cleaned)
                except Exception:
                    pass
        if self._also is not None:
            try:
                self._also.flush()
            except Exception:
                pass

    def isatty(self) -> bool:
        # Critical: tqdm / rich treat non-TTY as "no fancy bar" when disable is auto.
        return False

    def reconfigure(self, **kwargs) -> None:
        # Libraries (and Python 3.7+) may call this; keep UTF-8 identity.
        if "encoding" in kwargs and kwargs["encoding"]:
            type(self).encoding = str(kwargs["encoding"])

    def fileno(self) -> int:
        # Some libs probe fileno; prefer not to expose a real TTY fd.
        raise OSError("GuiLogStream has no fileno")

    def readable(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False


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
            cleaned = sanitize_gui_log_line(msg + "\n")
            if cleaned:
                self._write_callback(cleaned)
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
        self._old_tqdm_disable: Optional[str] = None

    def __enter__(self) -> "StdioRedirect":
        self._old_stdout = sys.stdout
        self._old_stderr = sys.stderr
        sys.stdout = GuiLogStream(self._write_callback, also=self._old_stdout)  # type: ignore[assignment]
        sys.stderr = GuiLogStream(self._write_callback, also=self._old_stderr)  # type: ignore[assignment]
        # Disable tqdm globally while GUI captures output (best-effort)
        self._old_tqdm_disable = os.environ.get("TQDM_DISABLE")
        os.environ["TQDM_DISABLE"] = "1"
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
        if self._old_tqdm_disable is None:
            os.environ.pop("TQDM_DISABLE", None)
        else:
            os.environ["TQDM_DISABLE"] = self._old_tqdm_disable
        root = logging.getLogger()
        if self._handler is not None:
            root.removeHandler(self._handler)
            self._handler = None
        for h in self._console_handlers:
            root.addHandler(h)
        self._console_handlers = []
