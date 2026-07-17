import time
from typing import Optional

from ..logging_config import configure_logging
from ..prompts import load_prompt
from ..text_utils import format_time

logger = configure_logging()


def _render_prompt(prompt_template: str, text: str) -> str:
    """Render prompt text without treating Hexo/AnZhiYu tags as format fields."""
    return prompt_template.replace("{transcript_text}", text)


def optimize_text_with_llm(text: str, config: dict, prompt_name: str = "evaluation") -> Optional[str]:
    """Optimize/extract text using configured LLM provider."""
    if not config or "llm" not in config:
        logger.warning("未配置大模型，跳过文本优化")
        return None

    llm_config = config["llm"]
    provider = llm_config.get("provider", "openai")

    logger.info(f"使用 {provider} 和提示词 '{prompt_name}' 进行文本优化...")

    try:
        if provider == "openai":
            return _optimize_with_openai(text, llm_config, prompt_name)
        if provider == "anthropic":
            return _optimize_with_anthropic(text, llm_config, prompt_name)

        logger.error(f"不支持的提供商: {provider}")
        return None
    except Exception as e:
        logger.error(f"文本优化失败: {e}")
        return None


def _optimize_with_openai(text: str, config: dict, prompt_name: str) -> Optional[str]:
    """Optimize text with OpenAI-compatible chat completions."""
    try:
        from openai import OpenAI
    except ImportError:
        logger.error("未安装 openai 库，请运行: pip install openai")
        return None

    start_time = time.time()
    timeout_seconds = float(config.get("timeout_seconds", config.get("timeout", 180)))
    max_retries = int(config.get("max_retries", 3))
    client = OpenAI(
        api_key=config.get("api_key"),
        base_url=config.get("base_url", "https://api.openai.com/v1"),
        timeout=timeout_seconds,
        max_retries=max_retries,
    )

    prompt_template = load_prompt(prompt_name)
    if not prompt_template:
        return None
    prompt = _render_prompt(prompt_template, text)

    try:
        response = client.chat.completions.create(
            model=config.get("model", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            temperature=config.get("temperature", 0.3),
            max_tokens=config.get("max_tokens", 4000),
        )

        if hasattr(response, "choices"):
            optimized_text = response.choices[0].message.content
        elif isinstance(response, dict):
            optimized_text = response.get("choices", [{}])[0].get("message", {}).get("content", "")
        elif isinstance(response, str):
            if response.strip().startswith("<!doctype") or response.strip().startswith("<html"):
                logger.error("API 返回了 HTML 页面而不是 JSON 响应")
                return None
            optimized_text = response
        else:
            logger.error(f"未知的响应格式: {type(response)}")
            return None

        if not optimized_text:
            logger.error("API 返回空内容")
            return None

        if optimized_text.strip().startswith("<!doctype") or optimized_text.strip().startswith("<html"):
            logger.error("API 返回了 HTML 页面而不是文本内容")
            return None

        logger.info(f"文本优化完成 (耗时: {format_time(time.time() - start_time)})")
        return optimized_text

    except Exception as e:
        logger.error(f"API 调用失败: {e}")
        if hasattr(e, "response"):
            logger.error(f"HTTP 状态码: {getattr(e.response, 'status_code', 'unknown')}")
        return None


def _optimize_with_anthropic(text: str, config: dict, prompt_name: str) -> Optional[str]:
    """Optimize text with Anthropic."""
    try:
        from anthropic import Anthropic
    except ImportError:
        logger.error("未安装 anthropic 库，请运行: pip install anthropic")
        return None

    start_time = time.time()
    client = Anthropic(api_key=config.get("api_key"))

    prompt_template = load_prompt(prompt_name)
    if not prompt_template:
        return None
    prompt = _render_prompt(prompt_template, text)

    response = client.messages.create(
        model=config.get("model", "claude-3-5-sonnet-20241022"),
        max_tokens=config.get("max_tokens", 4000),
        temperature=config.get("temperature", 0.3),
        messages=[{"role": "user", "content": prompt}],
    )

    optimized_text = response.content[0].text
    logger.info(f"文本优化完成 (耗时: {format_time(time.time() - start_time)})")
    return optimized_text
