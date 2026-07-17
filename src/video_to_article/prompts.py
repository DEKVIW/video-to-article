"""Prompt template discovery and loading.

Layout (preferred)::

    prompts/
      system/      # base / intermediate (hidden in GUI by default)
      articles/    # publishable article templates (GUI default list)

Legacy flat ``prompts/*.md`` is still supported for compatibility.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .logging_config import configure_logging
from .paths import PROMPTS_DIR

logger = configure_logging()

SYSTEM_SUBDIR = "system"
ARTICLES_SUBDIR = "articles"


def ensure_prompt_dirs() -> None:
    """Create preferred prompt subdirectories."""
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    (PROMPTS_DIR / SYSTEM_SUBDIR).mkdir(exist_ok=True)
    (PROMPTS_DIR / ARTICLES_SUBDIR).mkdir(exist_ok=True)


def _is_prompt_file(path: Path) -> bool:
    if path.suffix.lower() != ".md":
        return False
    if path.name.lower() == "readme.md":
        return False
    try:
        return path.stat().st_size > 0 and bool(path.read_text(encoding="utf-8").strip())
    except OSError:
        return False


def _collect_stems(directory: Path) -> List[str]:
    if not directory.is_dir():
        return []
    names = [p.stem for p in sorted(directory.glob("*.md")) if _is_prompt_file(p)]
    return names


def list_article_prompts() -> List[str]:
    """Publishable article templates (GUI primary list)."""
    ensure_prompt_dirs()
    names = _collect_stems(PROMPTS_DIR / ARTICLES_SUBDIR)
    # Legacy flat files that are not also under system/
    system = set(_collect_stems(PROMPTS_DIR / SYSTEM_SUBDIR))
    for stem in _collect_stems(PROMPTS_DIR):
        if stem not in system and stem not in names:
            # Prefer known system stems even if still flat
            if stem in {"format", "summary", "evaluation"}:
                continue
            names.append(stem)
    # If articles empty but snack_recipe only exists flat (migration mid-way)
    if not names:
        flat = _collect_stems(PROMPTS_DIR)
        names = [n for n in flat if n not in {"format", "summary", "evaluation"}]
    return sorted(set(names))


def list_system_prompts() -> List[str]:
    """Base / intermediate prompts (hidden in GUI by default)."""
    ensure_prompt_dirs()
    names = set(_collect_stems(PROMPTS_DIR / SYSTEM_SUBDIR))
    for stem in ("format", "summary", "evaluation"):
        if (PROMPTS_DIR / f"{stem}.md").is_file() and _is_prompt_file(PROMPTS_DIR / f"{stem}.md"):
            names.add(stem)
    return sorted(names)


def list_available_prompts() -> List[str]:
    """All loadable prompt names (CLI --list-prompts, validation)."""
    ensure_prompt_dirs()
    names = set(list_article_prompts()) | set(list_system_prompts())
    names |= set(_collect_stems(PROMPTS_DIR))
    return sorted(names)


def resolve_prompt_path(prompt_name: str) -> Optional[Path]:
    """Resolve a prompt name to a file path."""
    name = (prompt_name or "").strip().replace("\\", "/")
    if not name:
        return None

    # Explicit relative path under prompts/
    if "/" in name or name.endswith(".md"):
        rel = name if name.endswith(".md") else f"{name}.md"
        candidate = PROMPTS_DIR / rel
        if candidate.is_file():
            return candidate

    stem = name[:-3] if name.endswith(".md") else name
    candidates = [
        PROMPTS_DIR / ARTICLES_SUBDIR / f"{stem}.md",
        PROMPTS_DIR / SYSTEM_SUBDIR / f"{stem}.md",
        PROMPTS_DIR / f"{stem}.md",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def load_prompt(prompt_name: str = "evaluation") -> Optional[str]:
    """Load a prompt template by name (articles / system / legacy flat)."""
    ensure_prompt_dirs()
    prompt_file = resolve_prompt_path(prompt_name)

    if prompt_file is None:
        logger.warning(f"提示词文件不存在: {prompt_name}")
        logger.warning(f"可用的提示词: {', '.join(list_available_prompts())}")
        logger.warning("使用默认提示词")
        return "请优化以下文本，去除冗余，重构逻辑结构：\n\n{transcript_text}"

    with open(prompt_file, "r", encoding="utf-8") as f:
        content = f.read().strip()

    if not content:
        logger.error(f"提示词文件为空: {prompt_file}")
        return None

    if "{transcript_text}" not in content:
        logger.warning(f"提示词文件缺少 {{transcript_text}} 占位符: {prompt_file}")
        logger.warning("将在末尾自动添加占位符")
        content += "\n\n{transcript_text}"

    return content


def default_article_prompt_names() -> List[str]:
    """Default publishable prompt(s) for GUI / batch when unspecified."""
    articles = list_article_prompts()
    if "snack_recipe" in articles:
        return ["snack_recipe"]
    return articles[:1] if articles else []
