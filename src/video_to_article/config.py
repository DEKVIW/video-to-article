import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .logging_config import configure_logging
from .paths import CONFIG_FILE

logger = configure_logging()


def load_config() -> dict:
    """Load app configuration from config.json."""
    if not CONFIG_FILE.exists():
        logger.warning(f"配置文件不存在: {CONFIG_FILE}")
        logger.warning("请复制 config.example.json 为 config.json 并填入 API key")
        return {}

    with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def save_config(config: dict[str, Any], path: Path | None = None) -> Path:
    """Write configuration back to config.json (UTF-8, indented)."""
    target = path or CONFIG_FILE
    payload = deepcopy(config)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    logger.info(f"配置已保存: {target}")
    return target


def deep_update(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge updates into base and return base."""
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_update(base[key], value)
        else:
            base[key] = value
    return base
