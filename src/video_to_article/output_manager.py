import hashlib
import re
from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

from .blog import validate_snack_recipe_article
from .paths import OUTPUT_DIR
from .platforms import PLATFORM_BILIBILI, PLATFORM_LOCAL, PLATFORM_YOUTUBE, detect_platform, is_youtube_url, platform_slug
from .text_utils import sanitize_filename, sanitize_path_component


ARTICLE_IGNORE_NAMES = {"raw.md", "format.md", "summary.md", "evaluation.md", "snack_recipe.md", "snack_recipe.failed.md"}


def make_output_stem(title: str, source: str, include_hash: bool = True) -> str:
    """Create a stable output filename stem."""
    safe_title = sanitize_filename(title)
    if not include_hash:
        return safe_title

    source_hash = hashlib.sha1(source.encode("utf-8", errors="ignore")).hexdigest()[:8]
    return f"{safe_title}_{source_hash}"


def split_batch_root(batch_root: Optional[str]) -> list[str]:
    return [part for part in re.split(r"[\\/]+", batch_root or "") if part]


def strip_platform_prefix(parts: list[str], platform: str) -> list[str]:
    if parts and parts[0].lower() == platform.lower():
        return parts[1:]
    return parts


def get_youtube_video_id(source: str) -> str:
    parsed = urlparse(source)
    if "youtu.be" in parsed.netloc.lower():
        return parsed.path.strip("/").split("/")[0]
    query_id = parse_qs(parsed.query).get("v", [""])[0]
    if query_id:
        return query_id
    path_parts = [part for part in parsed.path.split("/") if part]
    return path_parts[-1] if path_parts else ""


def make_video_output_stem(title: str, source: str, batch_root: Optional[str] = None) -> str:
    """Create a readable stable per-video output directory name."""
    platform = detect_platform(source)
    safe_title = sanitize_filename(title, 80)
    if platform == PLATFORM_YOUTUBE:
        video_id = get_youtube_video_id(source)
        return sanitize_path_component(f"{safe_title}_{video_id}" if video_id else safe_title)
    if platform == PLATFORM_BILIBILI:
        return make_output_stem(title, source, include_hash=True)
    if platform == PLATFORM_LOCAL:
        return sanitize_path_component(Path(source).stem or safe_title)
    return make_output_stem(title, source, include_hash=not bool(batch_root))


def get_output_dir_for_source(source: str, batch_root: Optional[str] = None) -> Path:
    """Resolve base output directory for a source, preserving source semantics."""
    platform = detect_platform(source)

    if platform == PLATFORM_YOUTUBE:
        parts = strip_platform_prefix(split_batch_root(batch_root), "YouTube") or ["single"]
        output_dir = OUTPUT_DIR / "youtube"
        for part in parts:
            output_dir = output_dir / sanitize_path_component(part)
        return output_dir

    if platform == PLATFORM_BILIBILI:
        parts = strip_platform_prefix(split_batch_root(batch_root), "Bilibili") or ["single"]
        output_dir = OUTPUT_DIR / "bilibili"
        for part in parts:
            output_dir = output_dir / sanitize_path_component(part)
        return output_dir

    if platform != PLATFORM_LOCAL:
        # First-class online platforms (Douyin/XHS/Weibo/...) get their own folder.
        slug = platform_slug(platform)
        parts = strip_platform_prefix(split_batch_root(batch_root), platform) or ["single"]
        # Keep legacy "online/" nesting for Unknown to avoid surprising migrations.
        if slug in {"unknown"}:
            output_dir = OUTPUT_DIR / "online" / slug
        else:
            output_dir = OUTPUT_DIR / slug
        for part in parts:
            output_dir = output_dir / sanitize_path_component(part)
        return output_dir

    if not batch_root:
        source_parent = Path(source).parent
        batch_name = source_parent.name if source_parent.name else "single"
        return OUTPUT_DIR / "local" / sanitize_path_component(batch_name)

    source_path = Path(source)
    root_path = Path(batch_root)

    try:
        source_parent = source_path.resolve().parent
        resolved_root = root_path.resolve()
        relative_parent = source_parent.relative_to(resolved_root)
    except (OSError, ValueError):
        relative_parent = Path()

    output_dir = OUTPUT_DIR / "local" / sanitize_path_component(root_path.name)
    for part in relative_parent.parts:
        output_dir = output_dir / sanitize_path_component(part)

    return output_dir


def get_legacy_output_dir_for_source(source: str, batch_root: Optional[str] = None) -> Path:
    """Resolve the pre platform-folder output base for read-only compatibility."""
    if not batch_root:
        return OUTPUT_DIR

    if is_youtube_url(source):
        output_dir = OUTPUT_DIR
        for part in re.split(r"[\\/]+", batch_root):
            if part:
                output_dir = output_dir / sanitize_path_component(part)
        return output_dir

    source_path = Path(source)
    root_path = Path(batch_root)

    try:
        source_parent = source_path.resolve().parent
        resolved_root = root_path.resolve()
        relative_parent = source_parent.relative_to(resolved_root)
    except (OSError, ValueError):
        relative_parent = Path()

    output_dir = OUTPUT_DIR / sanitize_path_component(root_path.name)
    for part in relative_parent.parts:
        output_dir = output_dir / sanitize_path_component(part)

    return output_dir


def get_batch_output_dir(video_urls: List[str], batch_root: Optional[str] = None) -> Path:
    """Resolve the output directory that represents a whole batch run."""
    if batch_root:
        return get_output_dir_for_source(video_urls[0] if video_urls else "", batch_root)
    return OUTPUT_DIR


def get_candidate_batch_output_dirs(video_urls: List[str], batch_root: Optional[str] = None) -> list[Path]:
    """Return new batch output dir first, then legacy dirs for report lookup."""
    source = video_urls[0] if video_urls else ""
    dirs = [get_batch_output_dir(video_urls, batch_root)]
    if batch_root:
        dirs.append(get_legacy_output_dir_for_source(source, batch_root))
    else:
        dirs.append(OUTPUT_DIR)

    unique_dirs: list[Path] = []
    seen = set()
    for path in dirs:
        key = str(path)
        if key not in seen:
            unique_dirs.append(path)
            seen.add(key)
    return unique_dirs


def get_video_output_dir(title: str, source: str, batch_root: Optional[str] = None) -> Path:
    """Resolve the per-video output directory."""
    output_stem = make_video_output_stem(title, source, batch_root)
    return get_output_dir_for_source(source, batch_root) / sanitize_path_component(output_stem)


def get_legacy_video_output_dir(title: str, source: str, batch_root: Optional[str] = None) -> Path:
    """Resolve the pre platform-folder per-video output dir for read-only compatibility."""
    output_stem = make_output_stem(
        title,
        source,
        include_hash=(not bool(batch_root) or is_youtube_url(source)),
    )
    return get_legacy_output_dir_for_source(source, batch_root) / sanitize_path_component(output_stem)


def get_candidate_video_output_dirs(title: str, source: str, batch_root: Optional[str] = None) -> list[Path]:
    """Return new output dir first, then legacy dirs for read-only lookup."""
    dirs = [get_video_output_dir(title, source, batch_root), get_legacy_video_output_dir(title, source, batch_root)]
    unique_dirs: list[Path] = []
    seen = set()
    for path in dirs:
        key = str(path)
        if key not in seen:
            unique_dirs.append(path)
            seen.add(key)
    return unique_dirs


def find_existing_raw_file(title: str, source: str, batch_root: Optional[str] = None) -> Optional[Path]:
    """Find an existing raw.md in new or legacy output directories."""
    for output_dir in get_candidate_video_output_dirs(title, source, batch_root):
        raw_file = output_dir / "raw.md"
        if raw_file.exists():
            return raw_file
    return None


def find_article_markdown(output_dir: Path) -> Optional[Path]:
    """Find the generated article Markdown in an output directory."""
    if not output_dir.exists():
        return None
    for path in sorted(output_dir.glob("*.md")):
        if path.name not in ARTICLE_IGNORE_NAMES:
            return path
    return None


def build_output_paths(
    title: str,
    source: str,
    prompt_names: Optional[List[str]] = None,
    enable_llm_optimization: bool = True,
    batch_root: Optional[str] = None,
) -> tuple[Path, dict]:
    """Build raw and optimized output paths."""
    output_dir = get_video_output_dir(title, source, batch_root)
    raw_file = output_dir / "raw.md"
    optimized_files = {}

    if enable_llm_optimization and prompt_names:
        for prompt_name in prompt_names:
            if prompt_name == "snack_recipe":
                optimized_files[prompt_name] = output_dir / f"{sanitize_path_component(title)[:80].rstrip('. ')}.md"
            else:
                optimized_files[prompt_name] = output_dir / f"{sanitize_filename(prompt_name, 30)}.md"

    return raw_file, optimized_files


def outputs_exist(
    title: str,
    source: str,
    prompt_names: Optional[List[str]] = None,
    enable_llm_optimization: bool = True,
    batch_root: Optional[str] = None,
) -> bool:
    """Return whether all expected output files already exist."""
    return get_video_output_status(
        title,
        source,
        prompt_names,
        enable_llm_optimization,
        batch_root,
    )["complete"]


def get_video_output_status(
    title: str,
    source: str,
    prompt_names: Optional[List[str]] = None,
    enable_llm_optimization: bool = True,
    batch_root: Optional[str] = None,
) -> dict:
    """Classify output artifacts for one source.

    Status values:
    - complete: raw.md and the expected generated outputs exist.
    - raw_only: raw.md exists, but the publishable article is missing.
    - article_invalid: an article exists, but fails the basic recipe checks.
    - unprocessed: no raw.md was found in new or legacy output dirs.
    """
    prompt_names = prompt_names or []
    best_status = {
        "status": "unprocessed",
        "complete": False,
        "has_raw": False,
        "has_article": False,
        "article_valid": False,
        "output_dir": "",
        "raw_file": "",
        "article_file": "",
        "source": source,
        "title": title,
    }

    for output_dir in get_candidate_video_output_dirs(title, source, batch_root):
        raw_file = output_dir / "raw.md"
        if not raw_file.exists():
            continue

        article_file = find_article_markdown(output_dir)
        status = {
            **best_status,
            "status": "complete",
            "complete": True,
            "has_raw": True,
            "has_article": bool(article_file),
            "article_valid": True,
            "output_dir": str(output_dir),
            "raw_file": str(raw_file),
            "article_file": str(article_file) if article_file else "",
        }

        if enable_llm_optimization:
            for prompt_name in prompt_names:
                if prompt_name == "snack_recipe":
                    if not article_file:
                        status["status"] = "raw_only"
                        status["complete"] = False
                        status["article_valid"] = False
                        break
                    problems = validate_snack_recipe_article(
                        article_file.read_text(encoding="utf-8", errors="replace")
                    )
                    if problems:
                        status["status"] = "article_invalid"
                        status["complete"] = False
                        status["article_valid"] = False
                        status["problems"] = problems
                        break
                elif not (output_dir / f"{sanitize_filename(prompt_name, 30)}.md").exists():
                    status["status"] = "raw_only"
                    status["complete"] = False
                    status["article_valid"] = False
                    break

        if status["complete"]:
            return status
        if best_status["status"] == "unprocessed":
            best_status = status

    return best_status


def output_dir_has_article_markdown(output_dir: Path) -> bool:
    """Return whether the output directory contains any generated article Markdown."""
    if not output_dir.exists():
        return False
    return any(path.is_file() and path.suffix.lower() == ".md" and path.name not in ARTICLE_IGNORE_NAMES for path in output_dir.iterdir())


def output_dir_has_valid_article_markdown(output_dir: Path) -> bool:
    """Return whether the output directory contains a generated article that passes basic quality checks."""
    if not output_dir.exists():
        return False
    for path in output_dir.iterdir():
        if not path.is_file() or path.suffix.lower() != ".md" or path.name in ARTICLE_IGNORE_NAMES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not validate_snack_recipe_article(text):
            return True
    return False
