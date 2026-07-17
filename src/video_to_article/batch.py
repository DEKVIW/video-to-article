import os
from pathlib import Path
from typing import List, Optional

from .output_manager import build_output_paths
from .paths import LOCAL_MEDIA_EXTENSIONS
from .platforms import detect_platform
from .prompts import list_available_prompts
from .text_utils import sanitize_filename


def find_local_videos(
    directory: str,
    recursive: bool = True,
    extensions: Optional[List[str]] = None,
    limit: Optional[int] = None,
) -> List[str]:
    """Scan a local directory for supported local media files."""
    root = Path(directory)
    if not root.exists():
        raise FileNotFoundError(f"本地视频目录不存在: {directory}")
    if not root.is_dir():
        raise NotADirectoryError(f"不是有效目录: {directory}")

    allowed_extensions = {
        ext.lower() if ext.startswith(".") else f".{ext.lower()}"
        for ext in (extensions or LOCAL_MEDIA_EXTENSIONS)
    }
    videos = []

    if recursive:
        for current_root, dirs, files in os.walk(root):
            dirs.sort(key=str.lower)
            files.sort(key=str.lower)
            for file_name in files:
                path = Path(current_root) / file_name
                if path.suffix.lower() not in allowed_extensions:
                    continue
                videos.append(str(path))
                if limit and limit > 0 and len(videos) >= limit:
                    return videos
    else:
        for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            if not path.is_file() or path.suffix.lower() not in allowed_extensions:
                continue
            videos.append(str(path))
            if limit and limit > 0 and len(videos) >= limit:
                return videos

    return videos


def read_batch_file(batch_file: Path) -> tuple[List[str], Optional[str]]:
    """Read a batch list and optional batch_root metadata."""
    urls = []
    batch_root = None

    with open(batch_file, "r", encoding="utf-8") as f:
        for line in f:
            item = line.strip()
            if not item:
                continue
            if item.startswith("#"):
                if item.startswith("# batch_root="):
                    batch_root = item.split("=", 1)[1].strip()
                continue
            urls.append(item)

    return urls, batch_root


def write_batch_file(list_file: Path, items: List[str], batch_root: Optional[str] = None) -> None:
    """Write a batch list with optional batch_root metadata."""
    list_file.parent.mkdir(parents=True, exist_ok=True)
    with open(list_file, "w", encoding="utf-8") as f:
        if batch_root:
            f.write(f"# batch_root={batch_root}\n")
        for item in items:
            f.write(item + "\n")


def print_output_preview(
    videos: List[str],
    batch_root: Optional[str],
    prompt_names: Optional[List[str]] = None,
    enable_llm_optimization: bool = True,
    max_count: int = 3,
) -> None:
    """Print expected output paths for a few items."""
    if not videos:
        return

    preview_count = min(max_count, len(videos))
    print(f"\n前 {preview_count} 个视频的预计输出:")
    for i, video in enumerate(videos[:preview_count], 1):
        title = Path(video).stem if detect_platform(video) == "Local" else sanitize_filename(video, 40)
        raw_file, optimized_files = build_output_paths(
            title=title,
            source=video,
            prompt_names=prompt_names,
            enable_llm_optimization=enable_llm_optimization,
            batch_root=batch_root,
        )
        print(f"  {i}. {raw_file}")
        for file_path in optimized_files.values():
            print(f"     {file_path}")


def default_prompt_names() -> List[str]:
    """Prefer snack_recipe / article templates; not system base prompts."""
    from .prompts import default_article_prompt_names, list_article_prompts, list_available_prompts

    preferred = default_article_prompt_names()
    if preferred:
        return preferred
    articles = list_article_prompts()
    if articles:
        return articles
    available = list_available_prompts()
    return ["snack_recipe"] if "snack_recipe" in available else available
