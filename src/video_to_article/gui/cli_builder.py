"""Build equivalent CLI command strings from JobRequest / UI state."""

from __future__ import annotations

from typing import List, Optional

from .workers import JobRequest


def _q(value: str) -> str:
    """PowerShell-friendly quoting for paths/urls with spaces."""
    text = str(value)
    if not text:
        return '""'
    if any(ch in text for ch in (' ', '"', "'", "\t")):
        escaped = text.replace("'", "''")
        return f"'{escaped}'"
    return text


def _join(parts: List[str]) -> str:
    return " ".join(p for p in parts if p)


def _cover_flags(cover_mode: Optional[str]) -> List[str]:
    if cover_mode in {"prompt_only", "full", "off"}:
        return ["--cover-pipeline", str(cover_mode)]
    return []


def _common_pipeline(req: JobRequest) -> List[str]:
    parts: List[str] = []
    if req.prompt_names:
        parts.append(f"--prompts {_q(','.join(req.prompt_names))}")
    if not req.enable_llm and req.kind not in {"from_raw"}:
        parts.append("--no-llm")
    if req.save_video:
        parts.append("--save-video")
    parts.extend(_cover_flags(req.cover_mode))
    if req.cookies_from_browser:
        parts.append(f"--cookies-from-browser {_q(req.cookies_from_browser)}")
    if req.cookies_file:
        parts.append(f"--cookies {_q(req.cookies_file)}")
    if req.youtube_po_token:
        parts.append(f"--youtube-po-token {_q(req.youtube_po_token)}")
    if req.asr_override:
        parts.append(f"--asr-engine {_q(req.asr_engine)}")
        if req.asr_engine == "whisper":
            parts.append(f"--model-size {_q(req.model_size)}")
        else:
            parts.append(f"--funasr-model {_q(req.funasr_model)}")
        parts.append(f"--cpu-threads {int(req.cpu_threads)}")
    return parts


def build_cli(req: JobRequest) -> str:
    """Return a single-line ``python transcribe.py ...`` command."""
    base = "python transcribe.py"
    kind = req.kind

    if kind == "single":
        flag = "--url" if str(req.source).startswith(("http://", "https://")) else "--local"
        return _join([base, f"{flag} {_q(req.source)}", *_common_pipeline(req)])

    if kind == "batch":
        parts = [base]
        st = req.source_type
        if st == "local_dir":
            parts.append(f"--local-dir {_q(req.local_dir)}")
            if not req.recursive:
                parts.append("--no-recursive")
        elif st == "youtube":
            parts.append(f"--youtube-collection {_q(req.youtube_collection)}")
            if req.youtube_limit:
                parts.append(f"--youtube-limit {int(req.youtube_limit)}")
        elif st == "urls":
            # search process / pre-expanded — no perfect single CLI without writing a list
            if req.urls:
                parts.append("# 请先将勾选 URL 写入清单后使用 --batch")
                parts.append(f"# 共 {len(req.urls)} 条")
            parts.append("--batch YOUR_LIST.txt")
        else:
            parts.append(f"--batch {_q(req.batch_file)}")
        if req.batch_root:
            parts.append(f"--batch-root {_q(req.batch_root)}")
        if req.limit:
            parts.append(f"--limit {int(req.limit)}")
        if req.skip_existing:
            parts.append("--skip-existing")
        if req.dry_run:
            parts.append("--dry-run")
        if req.write_list:
            if req.write_list_path:
                parts.append(f"--write-list {_q(req.write_list_path)}")
            else:
                parts.append("--write-list")
        if req.auto_repair:
            parts.append("--auto-repair")
            parts.append(f"--repair-rounds {int(req.repair_rounds)}")
            if req.repair_delay:
                parts.append(f"--repair-delay {int(req.repair_delay)}")
        parts.extend(_common_pipeline(req))
        return _join(parts)

    if kind == "download_single":
        parts = [
            base,
            "--download-only",
            f"--url {_q(req.source)}",
            f"--media-type {req.media_type}",
        ]
        if req.download_subs:
            parts.append("--download-subs")
            if req.subtitle_langs:
                parts.append(f"--subs-lang {_q(','.join(req.subtitle_langs))}")
        parts.extend(_common_pipeline(req))
        return _join(parts)

    if kind == "download_batch":
        parts = [
            base,
            "--download-only",
            f"--batch {_q(req.batch_file)}",
            f"--media-type {req.media_type}",
        ]
        if req.download_subs:
            parts.append("--download-subs")
            if req.subtitle_langs:
                parts.append(f"--subs-lang {_q(','.join(req.subtitle_langs))}")
        if req.limit:
            parts.append(f"--limit {int(req.limit)}")
        parts.extend(_common_pipeline(req))
        return _join(parts)

    if kind == "bilibili_search":
        return _join(
            [
                base,
                f"--search {_q(req.search_keyword)}",
                f"--search-count {int(req.search_count)}",
                f"--search-order {req.search_order}",
                *_common_pipeline(req),
            ]
        )

    if kind == "from_raw":
        parts = [base, f"--from-raw {_q(req.source)}"]
        if req.prompt_names:
            parts.append(f"--prompts {_q(','.join(req.prompt_names))}")
        parts.extend(_cover_flags(req.cover_mode))
        return _join(parts)

    if kind == "regen_cover":
        parts = [base, f"--regen-cover {_q(req.source)}"]
        if req.thumbnail:
            parts.append(f"--thumbnail {_q(req.thumbnail)}")
        parts.extend(_cover_flags(req.cover_mode))
        return _join(parts)

    if kind == "check_report":
        return _join([base, f"--check-report {_q(req.source)}"])

    if kind == "youtube_auth":
        parts = [base, "--check-youtube-auth"]
        if req.source:
            parts.append(f"--url {_q(req.source)}")
        if req.cookies_from_browser:
            parts.append(f"--cookies-from-browser {_q(req.cookies_from_browser)}")
        if req.cookies_file:
            parts.append(f"--cookies {_q(req.cookies_file)}")
        if req.youtube_po_token:
            parts.append(f"--youtube-po-token {_q(req.youtube_po_token)}")
        return _join(parts)

    if kind == "refresh_cookies":
        browser = req.cookies_from_browser or "firefox"
        parts = [base, f"--refresh-youtube-cookies {_q(browser)}"]
        if req.cookies_file:
            # CLI uses --cookies as output override in refresh handler
            parts.append(f"--cookies {_q(req.cookies_file)}")
        return _join(parts)

    return f"{base}  # 未知任务类型: {kind}"
