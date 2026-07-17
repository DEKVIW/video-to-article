import json
import mimetypes
import os
import re
import time
import base64
from pathlib import Path
from typing import Any, Optional

import requests

from .blog import extract_frontmatter_title, replace_frontmatter_field, split_frontmatter
from .logging_config import configure_logging
logger = configure_logging()


DEFAULT_NEGATIVE_PROMPT = (
    "不要文字，不要中文大字，不要水印，不要logo，不要品牌包装，不要YouTube封面风格，"
    "不要拼贴图，不要箭头，不要人物正脸，不要截图质感，不要信息图，不要菜单页，"
    "不要菜谱卡片，不要表格，不要步骤说明，不要营养分析页，不要网页界面，不要侧边栏，"
    "不要纯白背景，不要摄影棚白盘孤立图，不要电商产品图，不要菜单样张，不要塑料质感，"
    "不要低清晰度，不要畸形餐具，不要变形食物，不要过度饱和。"
)

STRICT_SINGLE_FOOD_PHOTO_PROMPT = (
    "必须是一张单张成品菜照片，只允许一个主画面、一个成品食物主体；"
    "不要任何文字、汉字、英文字母、数字、标题、品牌名、站点名、logo、水印、二维码、印章、标签；"
    "不要拼贴图、分屏、多宫格、多张照片、缩略图、边框、相框、海报版式、宣传图设计、菜单页、菜谱卡、信息图、网页界面；"
    "不要把参考图里的文字、贴纸、角标、字幕、二维码、边框或排版复制到结果中。"
)

DEFAULT_FOOD_PHOTO_STYLE = (
    "真实自然的家常餐桌美食摄影，45度俯拍或轻微俯视角，温暖木质餐桌或厨房台面，柔和自然暖光，"
    "陶瓷餐具、筷子、小碟、少量真实食材或调料作为环境点缀，画面有生活气息和食欲感，"
    "主体是一盘或一碗完成后的菜，环境元素约占画面 20%-35%"
)

DEFAULT_IMAGE_SUBMIT_TIMEOUT_SECONDS = 300
DEFAULT_IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 180
DEFAULT_IMAGE_POLL_TIMEOUT_SECONDS = 120
DEFAULT_IMAGE_HOST_TIMEOUT_SECONDS = 180

# Cover pipeline modes (CLI + config).
COVER_MODE_FULL = "full"
COVER_MODE_PROMPT_ONLY = "prompt_only"
COVER_MODE_OFF = "off"

# ai_cover.pipeline 取值（勿与 ai_cover.mode 文生/图生策略混淆）
COVER_PIPELINE_VALUES = {COVER_MODE_FULL, COVER_MODE_PROMPT_ONLY, COVER_MODE_OFF}


def resolve_cover_pipeline_from_config(cover_config: Optional[dict]) -> str:
    """Map ai_cover config → pipeline mode.

    Preferred field: ``pipeline`` = full | prompt_only | off

    Legacy (仍可读):
      enable + generate_image + export_prompt
    """
    if not isinstance(cover_config, dict):
        cover_config = {}

    raw = str(
        cover_config.get("pipeline")
        or cover_config.get("cover_pipeline")
        or ""
    ).strip().lower()
    if raw in COVER_PIPELINE_VALUES:
        return raw

    # legacy bools
    if any(k in cover_config for k in ("enable", "generate_image", "export_prompt")):
        if not bool(cover_config.get("enable", False)):
            return COVER_MODE_OFF
        if bool(cover_config.get("generate_image", True)):
            return COVER_MODE_FULL
        if bool(cover_config.get("export_prompt", True)):
            return COVER_MODE_PROMPT_ONLY
        return COVER_MODE_OFF

    return COVER_MODE_OFF


def pipeline_to_legacy_flags(pipeline: str) -> dict:
    """Mirror pipeline into legacy enable/generate_image/export_prompt for old readers."""
    pipeline = normalize_cover_pipeline_mode(pipeline)
    if pipeline == COVER_MODE_FULL:
        return {"enable": True, "generate_image": True, "export_prompt": True}
    if pipeline == COVER_MODE_PROMPT_ONLY:
        return {"enable": True, "generate_image": False, "export_prompt": True}
    return {"enable": False, "generate_image": False, "export_prompt": False}


def resolve_cover_pipeline_mode(
    *,
    no_cover: bool = False,
    no_cover_assets: bool = False,
    config: Optional[dict] = None,
    cover_pipeline: Optional[str] = None,
) -> str:
    """Resolve cover pipeline mode. CLI / explicit pipeline wins over config.

    - full: 提示词 + 调用生图 API（文生图/图生图）
    - prompt_only: 仅导出 cover-prompt.txt 等（不调 API）
    - off: 不做封面相关
    """
    if no_cover_assets:
        return COVER_MODE_OFF
    if cover_pipeline is not None and str(cover_pipeline).strip():
        return normalize_cover_pipeline_mode(cover_pipeline)
    if no_cover:
        return COVER_MODE_PROMPT_ONLY

    cover_config = (config or {}).get("ai_cover", {}) if isinstance(config, dict) else {}
    return resolve_cover_pipeline_from_config(cover_config)


def cover_pipeline_mode_label(mode: str) -> str:
    """Human-readable cover pipeline mode for CLI banners."""
    if mode == COVER_MODE_FULL:
        return "启用 AI 封面（提示词 + 生图 API）"
    if mode == COVER_MODE_PROMPT_ONLY:
        return "仅导出封面提示词"
    return "关闭（不做封面）"


def cover_mode_exports_assets(mode: str) -> bool:
    return mode in {COVER_MODE_FULL, COVER_MODE_PROMPT_ONLY}


def cover_mode_generates_image(mode: str) -> bool:
    return mode == COVER_MODE_FULL


def normalize_cover_pipeline_mode(value: object, *, enable_ai_cover_fallback: Optional[bool] = None) -> str:
    """Normalize stored/legacy cover pipeline mode values."""
    text = str(value or "").strip().lower()
    if text in {COVER_MODE_FULL, COVER_MODE_PROMPT_ONLY, COVER_MODE_OFF}:
        return text
    if enable_ai_cover_fallback is None:
        return COVER_MODE_FULL
    return COVER_MODE_FULL if enable_ai_cover_fallback else COVER_MODE_OFF


def apply_ai_cover_to_article(
    article_text: str,
    config: dict,
    output_dir: Path,
    source_title: str,
    source_url: str,
    platform: str,
    transcript_source: str,
    youtube_metadata: Optional[dict] = None,
    local_thumbnail: Optional[str] = None,
    cover_mode: str = COVER_MODE_FULL,
) -> tuple[str, Optional[dict]]:
    """Prepare cover assets and optionally generate/upload an image.

    cover_mode:
      - full: prompt + metadata + image API + optional host upload / front-matter
      - prompt_only: prompt + metadata only (for manual web generation)
      - off: no-op
    """
    cover_mode = normalize_cover_pipeline_mode(cover_mode)
    if cover_mode == COVER_MODE_OFF:
        return article_text, None

    cover_config = config.get("ai_cover", {}) if isinstance(config, dict) else {}
    if not isinstance(cover_config, dict):
        cover_config = {}

    generate_image = cover_mode_generates_image(cover_mode)
    if generate_image:
        logger.info(
            "开始生成 AI 封面 (provider=%s, timeout=%ss)...",
            cover_config.get("provider", "unknown"),
            cover_config.get("submit_timeout_seconds", DEFAULT_IMAGE_SUBMIT_TIMEOUT_SECONDS),
        )
    else:
        logger.info("导出封面提示词与元数据（不调用生图 API）...")

    output_dir.mkdir(parents=True, exist_ok=True)
    article_title = extract_frontmatter_title(article_text, source_title)
    explicit_reference_image_url = cover_config.get("reference_image_url") or ""
    reference_image_url = explicit_reference_image_url or (
        youtube_metadata.get("thumbnail") if youtube_metadata else ""
    )
    prepared_reference = prepare_cover_reference(
        local_thumbnail=local_thumbnail,
        output_dir=output_dir,
        cover_config=cover_config,
    )
    if prepared_reference.get("action") == "ignore":
        effective_local_thumbnail = None
        if not explicit_reference_image_url:
            reference_image_url = ""
    else:
        effective_local_thumbnail = prepared_reference.get("path") or local_thumbnail
    prompt = build_cover_prompt(
        article_text=article_text,
        article_title=article_title,
        source_title=source_title,
        platform=platform,
        transcript_source=transcript_source,
        youtube_metadata=youtube_metadata,
        cover_config=cover_config,
        local_thumbnail=effective_local_thumbnail,
        reference_image_url=reference_image_url,
    )

    prompt_file = output_dir / "cover-prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")
    logger.info(f"已写入封面提示词: {prompt_file}")

    requested_mode = resolve_cover_mode(cover_config, effective_local_thumbnail, reference_image_url)
    effective_mode = resolve_effective_cover_mode(cover_config, effective_local_thumbnail, reference_image_url)
    result: dict[str, Any] = {
        "enabled": True,
        "cover_mode": cover_mode,
        "generate_image": generate_image,
        "export_prompt": True,
        "title": article_title,
        "prompt_file": str(prompt_file),
        "size": cover_config.get("size") or cover_config.get("aspect_ratio") or "",
        "style": cover_config.get("style") or "",
        "negative_prompt": cover_config.get("negative_prompt") or "",
        "mode": effective_mode,
        "requested_mode": requested_mode,
        "reference_strategy": prepared_reference,
        "status": "prompt_only" if not generate_image else "pending_generate",
        "success": True,
        "local_path": None,
        "image_url": None,
        "hint": (
            "可将 cover-prompt.txt 复制到任意文生图网页生成封面，"
            "再自行上传图床并填写文章 front-matter 的 cover 字段。"
            if not generate_image
            else ""
        ),
    }

    if not generate_image:
        write_cover_metadata(output_dir, result)
        return article_text, result

    image_host_config = config.get("image_host", {}) if isinstance(config, dict) else {}
    try:
        local_cover = generate_cover_image(
            prompt,
            output_dir,
            cover_config,
            effective_local_thumbnail,
            image_host_config,
            reference_image_url,
        )
        result.update(local_cover)
        result["status"] = "generated" if result.get("local_path") or result.get("image_url") else "failed"
        result["success"] = bool(result.get("local_path") or result.get("image_url") or result.get("success"))
        logger.info(f"AI 封面生成完成: {result.get('local_path') or result.get('image_url') or '无本地文件'}")
    except Exception as e:
        logger.warning(f"AI 封面生成失败，保留原 cover: {e}")
        result.update(
            {
                "success": False,
                "error": str(e),
                "status": "failed",
                "hint": (
                    "自动生图失败，但 cover-prompt.txt 已保留；"
                    "可复制提示词到网页手动生图。"
                ),
            }
        )
        write_cover_metadata(output_dir, result)
        return article_text, result

    cover_url = None
    if image_host_config.get("enable", False) and result.get("local_path"):
        try:
            logger.info("正在上传封面到图床...")
            upload_result = upload_image_to_host(Path(result["local_path"]), image_host_config)
            result["upload"] = upload_result
            cover_url = upload_result.get("url")
            if cover_url:
                logger.info(f"封面已上传: {cover_url}")
        except Exception as e:
            logger.warning(f"AI 封面上传图床失败，保留原 cover: {e}")
            result["upload"] = {"success": False, "error": str(e)}

    if not cover_url and cover_config.get("use_model_output_url_in_frontmatter", False):
        cover_url = result.get("image_url")

    if cover_url:
        article_text = replace_frontmatter_field(article_text, "cover", cover_url)
        result["frontmatter_cover"] = cover_url
    elif cover_config.get("use_local_cover_in_frontmatter", False) and result.get("local_path"):
        article_text = replace_frontmatter_field(article_text, "cover", Path(result["local_path"]).name)
        result["frontmatter_cover"] = Path(result["local_path"]).name

    write_cover_metadata(output_dir, result)
    return article_text, result

def generate_cover_image(
    prompt: str,
    output_dir: Path,
    cover_config: dict,
    local_thumbnail: Optional[str] = None,
    image_host_config: Optional[dict] = None,
    reference_image_url: str = "",
) -> dict:
    provider = cover_config.get("provider", "modelscope")
    if provider == "modelscope":
        return generate_with_modelscope(
            prompt,
            output_dir,
            cover_config,
            local_thumbnail,
            image_host_config or {},
            reference_image_url,
        )
    if provider == "openai":
        return generate_with_openai_compatible(
            prompt,
            output_dir,
            cover_config,
            local_thumbnail,
            reference_image_url,
        )
    if provider == "dry_run":
        return {"success": True, "provider": "dry_run", "local_path": None, "image_url": None}
    raise ValueError(f"不支持的 AI 封面提供商: {provider}")


def generate_with_openai_compatible(
    prompt: str,
    output_dir: Path,
    cover_config: dict,
    local_thumbnail: Optional[str] = None,
    reference_image_url: str = "",
) -> dict:
    """Call an OpenAI-compatible image API and save the first returned image locally."""
    api_key = resolve_secret(cover_config, "api_key", "api_key_env", "OPENAI_API_KEY")
    if not api_key:
        raise ValueError("未配置 OpenAI 兼容生图 API Key，请在 config.json 的 ai_cover.api_key 填写，或设置 OPENAI_API_KEY")

    output_format = cover_config.get("output_format", "jpg").lstrip(".").lower()
    output_file = output_dir / f"cover-ai.{output_format}"
    mode = resolve_effective_cover_mode(cover_config, local_thumbnail, reference_image_url)
    edit_enabled = bool(cover_config.get("enable_image_edit", True))
    use_edit_endpoint = mode == "enhance" and edit_enabled and (local_thumbnail or reference_image_url)
    if use_edit_endpoint and should_force_text_to_image(local_thumbnail, cover_config):
        logger.info("参考图可能包含人物/文字/海报元素，改用文生图生成干净单张成品菜照片")
        use_edit_endpoint = False

    operation = "text_to_image"
    edit_error = None
    if use_edit_endpoint:
        try:
            payload = submit_openai_compatible_edit(
                cover_config.get("base_url", "https://api.openai.com/v1"),
                api_key,
                prompt,
                cover_config,
                local_thumbnail,
                reference_image_url,
            )
            operation = "image_edit"
        except Exception as e:
            edit_error = str(e)
            if not cover_config.get("fallback_to_text_to_image", True):
                raise
            logger.warning(f"OpenAI 兼容图像编辑失败，回退文生图: {e}")
            payload = submit_openai_compatible_generation(
                cover_config.get("base_url", "https://api.openai.com/v1"),
                api_key,
                prompt,
                cover_config,
            )
    else:
        payload = submit_openai_compatible_generation(
            cover_config.get("base_url", "https://api.openai.com/v1"),
            api_key,
            prompt,
            cover_config,
        )

    image_url = None
    task_id = find_task_id(payload)
    if task_id and not extract_openai_image(payload):
        image_url = poll_modelscope_task(
            cover_config.get("base_url", "https://api.openai.com/v1"),
            api_key,
            task_id,
            cover_config,
        )
        download_image(
            image_url,
            output_file,
            timeout=int(cover_config.get("download_timeout_seconds", DEFAULT_IMAGE_DOWNLOAD_TIMEOUT_SECONDS)),
        )
    else:
        image = extract_openai_image(payload)
        if not image:
            raise RuntimeError(f"OpenAI 兼容图片生成成功但未找到图片数据: {payload}")
        image_url = image.get("url")
        if image.get("b64_json"):
            write_base64_image(image["b64_json"], output_file)
        elif image_url:
            download_image(
                image_url,
                output_file,
                timeout=int(cover_config.get("download_timeout_seconds", DEFAULT_IMAGE_DOWNLOAD_TIMEOUT_SECONDS)),
            )
        else:
            raise RuntimeError(f"OpenAI 兼容图片生成成功但未找到可保存的图片: {payload}")

    result = {
        "success": True,
        "provider": "openai",
        "model": cover_config.get("edit_model" if operation == "image_edit" else "model"),
        "operation": operation,
        "image_url": image_url,
        "local_path": str(output_file),
        "response": sanitize_openai_response(payload),
    }
    if task_id:
        result["task_id"] = task_id
    if edit_error:
        result["edit_error"] = edit_error
    return result


def submit_openai_compatible_generation(base_url: str, api_key: str, prompt: str, cover_config: dict) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = build_openai_image_payload(
        cover_config,
        model_key="model",
        prompt=prompt,
        base_url=base_url,
    )
    response = requests.post(
        openai_endpoint(base_url, "images/generations"),
        headers=headers,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=int(cover_config.get("submit_timeout_seconds", DEFAULT_IMAGE_SUBMIT_TIMEOUT_SECONDS)),
    )
    raise_for_status_with_body(response)
    return parse_response_json(response)


def submit_openai_compatible_edit(
    base_url: str,
    api_key: str,
    prompt: str,
    cover_config: dict,
    local_thumbnail: Optional[str] = None,
    reference_image_url: str = "",
) -> dict:
    strategies = normalize_openai_edit_strategies(cover_config, base_url)
    errors = []
    for strategy in strategies:
        try:
            if strategy == "json_image_url":
                return submit_openai_json_image_edit(
                    base_url,
                    api_key,
                    prompt,
                    cover_config,
                    local_thumbnail,
                    reference_image_url,
                )
            if strategy == "multipart":
                return submit_openai_multipart_image_edit(
                    base_url,
                    api_key,
                    prompt,
                    cover_config,
                    local_thumbnail,
                )
        except Exception as e:
            errors.append(f"{strategy}: {e}")
            continue
    raise RuntimeError("; ".join(errors) or "未找到可用的 OpenAI 兼容图像编辑策略")


def submit_openai_json_image_edit(
    base_url: str,
    api_key: str,
    prompt: str,
    cover_config: dict,
    local_thumbnail: Optional[str],
    reference_image_url: str,
) -> dict:
    image_url = reference_image_url
    if local_thumbnail and cover_config.get("send_local_reference_as_base64", True):
        image_url = image_file_to_data_url(Path(local_thumbnail))
    if not image_url:
        raise ValueError("json_image_url 图像编辑需要本地参考图或 reference_image_url")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = build_openai_image_payload(
        cover_config,
        model_key="edit_model",
        prompt=prompt,
        base_url=base_url,
    )
    # xAI Imagine edit often expects `image` object; OpenAI-compat proxies may use image_url.
    if is_xai_image_api(base_url):
        payload["image"] = {"url": image_url, "type": "image_url"}
    else:
        payload["image_url"] = [image_url]
    endpoint_path = "images/edits" if is_xai_image_api(base_url) else "images/generations"
    response = requests.post(
        openai_endpoint(base_url, endpoint_path),
        headers=headers,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=int(cover_config.get("submit_timeout_seconds", DEFAULT_IMAGE_SUBMIT_TIMEOUT_SECONDS)),
    )
    raise_for_status_with_body(response)
    return parse_response_json(response)


def submit_openai_multipart_image_edit(
    base_url: str,
    api_key: str,
    prompt: str,
    cover_config: dict,
    local_thumbnail: Optional[str],
) -> dict:
    if not local_thumbnail:
        raise ValueError("multipart 图像编辑需要本地参考图")
    image_path = Path(local_thumbnail)
    if not image_path.exists():
        raise FileNotFoundError(f"参考图不存在: {image_path}")

    headers = {"Authorization": f"Bearer {api_key}"}
    data = build_openai_image_payload(
        cover_config,
        model_key="edit_model",
        prompt=prompt,
        include_optional=False,
        base_url=base_url,
    )
    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    with image_path.open("rb") as image_file:
        files = {"image": (image_path.name, image_file, mime_type)}
        response = requests.post(
            openai_endpoint(base_url, "images/edits"),
            headers=headers,
            data=data,
            files=files,
            timeout=int(cover_config.get("submit_timeout_seconds", DEFAULT_IMAGE_SUBMIT_TIMEOUT_SECONDS)),
        )
    raise_for_status_with_body(response)
    return parse_response_json(response)


def is_xai_image_api(base_url: str) -> bool:
    return "api.x.ai" in str(base_url or "").lower()


def size_to_aspect_ratio(size: str) -> str:
    """Map WxH size strings to the closest common aspect ratio for xAI Imagine."""
    text = str(size or "").lower().strip()
    match = re.match(r"(\d+)\s*x\s*(\d+)", text)
    if not match:
        return "16:9"
    width = max(int(match.group(1)), 1)
    height = max(int(match.group(2)), 1)
    ratio = width / height
    candidates = {
        "1:1": 1.0,
        "4:3": 4 / 3,
        "3:2": 1.5,
        "16:9": 16 / 9,
        "2:1": 2.0,
        "3:4": 0.75,
        "2:3": 2 / 3,
        "9:16": 9 / 16,
    }
    return min(candidates.items(), key=lambda item: abs(item[1] - ratio))[0]


def build_openai_image_payload(
    cover_config: dict,
    model_key: str,
    prompt: str,
    include_optional: bool = True,
    base_url: str = "",
) -> dict:
    payload = {
        "model": cover_config.get(model_key) or cover_config.get("model", "gpt-image-1"),
        "prompt": prompt,
        "n": int(cover_config.get("n", 1)),
    }

    # xAI Imagine rejects OpenAI-style `size`; it uses aspect_ratio (+ optional resolution).
    if is_xai_image_api(base_url) or str(cover_config.get("image_size_mode", "")).lower() == "aspect_ratio":
        aspect = cover_config.get("aspect_ratio") or size_to_aspect_ratio(cover_config.get("size", "1344x768"))
        payload["aspect_ratio"] = aspect
        if cover_config.get("resolution"):
            payload["resolution"] = cover_config.get("resolution")
    else:
        payload["size"] = cover_config.get("size", "1344x768")

    optional_keys = [
        "quality",
        "background",
        "moderation",
        "response_format",
        "output_compression",
        "style_preset",
    ]
    if include_optional:
        for key in optional_keys:
            if key in cover_config and cover_config[key] not in (None, ""):
                payload[key] = cover_config[key]
        # xAI may not accept OpenAI output_format; only send for non-xAI unless forced.
        if cover_config.get("output_format") and not is_xai_image_api(base_url):
            payload["output_format"] = normalize_api_output_format(cover_config["output_format"])
    return payload


def normalize_openai_edit_strategies(cover_config: dict, base_url: str) -> list[str]:
    configured = cover_config.get("openai_edit_strategy", "auto")
    if isinstance(configured, list):
        return [str(item) for item in configured if item]
    if configured and configured != "auto":
        return [str(configured)]
    if "api.openai.com" in str(base_url):
        return ["multipart", "json_image_url"]
    # xAI Imagine edit is JSON-oriented; try that before multipart.
    if is_xai_image_api(base_url):
        return ["json_image_url", "multipart"]
    return ["json_image_url", "multipart"]


def generate_with_modelscope(
    prompt: str,
    output_dir: Path,
    cover_config: dict,
    local_thumbnail: Optional[str] = None,
    image_host_config: Optional[dict] = None,
    reference_image_url: str = "",
) -> dict:
    """Call ModelScope async image API and save the first image locally."""
    api_key = resolve_secret(cover_config, "api_key", "api_key_env", "MODELSCOPE_SDK_TOKEN")
    if not api_key:
        raise ValueError("未配置 ModelScope API Key，请在 config.json 的 ai_cover.api_key 填写，或设置 MODELSCOPE_SDK_TOKEN")

    output_format = cover_config.get("output_format", "jpg").lstrip(".").lower()
    output_file = output_dir / f"cover-ai.{output_format}"
    mode = resolve_effective_cover_mode(cover_config, local_thumbnail, reference_image_url)
    edit_enabled = bool(cover_config.get("enable_image_edit", True))
    use_edit_endpoint = mode == "enhance" and edit_enabled and (local_thumbnail or reference_image_url)
    if use_edit_endpoint and should_force_text_to_image(local_thumbnail, cover_config):
        logger.info("参考图可能包含人物/文字/海报元素，改用文生图生成干净单张成品菜照片")
        use_edit_endpoint = False

    base_url = cover_config.get("base_url", "https://api-inference.modelscope.cn/")
    reference_upload = None
    if use_edit_endpoint:
        if local_thumbnail and cover_config.get("send_local_reference_as_base64", True):
            reference_image_url = image_file_to_data_url(Path(local_thumbnail))
        elif not reference_image_url and image_host_config and image_host_config.get("enable", False):
            reference_upload = upload_image_to_host(Path(local_thumbnail), image_host_config)
            reference_image_url = reference_upload.get("url")

        if reference_image_url:
            task = submit_modelscope_edit_task(base_url, api_key, prompt, cover_config, reference_image_url)
        elif cover_config.get("fallback_to_text_to_image", True):
            logger.warning("ModelScope 图像编辑需要公网参考图 URL，当前未配置图床或 reference_image_url，回退文生图")
            use_edit_endpoint = False
            task = submit_modelscope_generation_task(base_url, api_key, prompt, cover_config)
        else:
            raise ValueError("ModelScope 图像编辑需要公网参考图 URL，请配置 image_host 或 ai_cover.reference_image_url")
    else:
        task = submit_modelscope_generation_task(base_url, api_key, prompt, cover_config)

    task_id = task.get("task_id")
    if not task_id:
        raise RuntimeError(f"ModelScope 任务提交失败: {task}")

    image_url = poll_modelscope_task(base_url, api_key, task_id, cover_config)
    download_image(
        image_url,
        output_file,
        timeout=int(cover_config.get("download_timeout_seconds", DEFAULT_IMAGE_DOWNLOAD_TIMEOUT_SECONDS)),
    )
    return {
        "success": True,
        "provider": "modelscope",
        "model": cover_config.get("edit_model" if use_edit_endpoint else "model"),
        "operation": "image_edit" if use_edit_endpoint else "text_to_image",
        "task_id": task_id,
        "image_url": image_url,
        "local_path": str(output_file),
        "reference_upload": reference_upload,
    }


def submit_modelscope_generation_task(base_url: str, api_key: str, prompt: str, cover_config: dict) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-ModelScope-Async-Mode": "true",
    }
    payload = {
        "model": cover_config.get("model", "Qwen/Qwen-Image"),
        "prompt": prompt,
        "size": cover_config.get("size", "1344x768"),
    }
    response = requests.post(
        modelscope_endpoint(base_url, "v1/images/generations"),
        headers=headers,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=int(cover_config.get("submit_timeout_seconds", DEFAULT_IMAGE_SUBMIT_TIMEOUT_SECONDS)),
    )
    raise_for_status_with_body(response)
    return response.json()


def submit_modelscope_edit_task(
    base_url: str,
    api_key: str,
    prompt: str,
    cover_config: dict,
    reference_image_url: str,
) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-ModelScope-Async-Mode": "true",
    }
    payload = {
        "model": cover_config.get("edit_model", "Qwen/Qwen-Image-Edit-2511"),
        "prompt": prompt,
        "image_url": [reference_image_url],
        "size": cover_config.get("size", "1344x768"),
    }
    response = requests.post(
        modelscope_endpoint(base_url, "v1/images/generations"),
        headers=headers,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=int(cover_config.get("submit_timeout_seconds", DEFAULT_IMAGE_SUBMIT_TIMEOUT_SECONDS)),
    )
    raise_for_status_with_body(response)
    return response.json()


def poll_modelscope_task(base_url: str, api_key: str, task_id: str, cover_config: dict) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-ModelScope-Task-Type": "image_generation",
    }
    interval = float(cover_config.get("poll_interval_seconds", 5))
    max_wait = float(cover_config.get("max_wait_seconds", 600))
    deadline = time.time() + max_wait

    while time.time() < deadline:
        time.sleep(interval)
        response = requests.get(
            modelscope_endpoint(base_url, f"v1/tasks/{task_id}"),
            headers=headers,
            timeout=int(cover_config.get("poll_timeout_seconds", DEFAULT_IMAGE_POLL_TIMEOUT_SECONDS)),
        )
        raise_for_status_with_body(response)
        payload = response.json()
        status = payload.get("task_status")
        if status == "SUCCEED":
            images = payload.get("output_images") or []
            if not images:
                raise RuntimeError(f"ModelScope 任务成功但没有返回图片: {payload}")
            return images[0]
        if status == "FAILED":
            raise RuntimeError(f"ModelScope 图片生成失败: {payload}")

    raise TimeoutError(f"ModelScope 图片生成超时: {task_id}")


def upload_image_to_host(image_path: Path, image_host_config: dict) -> dict:
    provider = image_host_config.get("provider", "easyimage")
    if provider != "easyimage":
        raise ValueError(f"不支持的图床提供商: {provider}")
    return upload_to_easyimage(image_path, image_host_config)


def prepare_cover_reference(
    local_thumbnail: Optional[str],
    output_dir: Path,
    cover_config: dict,
) -> dict[str, Any]:
    """Choose whether to use, crop, or ignore a local thumbnail as image-edit reference."""
    result: dict[str, Any] = {
        "source_path": local_thumbnail,
        "path": None,
        "action": "none",
        "reason": "no_local_thumbnail",
    }
    if not local_thumbnail or not cover_config.get("enable_reference_preprocess", True):
        return result

    source_path = Path(local_thumbnail)
    if not source_path.exists():
        result["reason"] = "thumbnail_missing"
        return result

    analysis = analyze_thumbnail_for_cover(source_path)
    result["analysis"] = analysis
    decision = decide_reference_action(analysis, cover_config)
    result.update({"action": decision["action"], "reason": decision["reason"]})

    if decision["action"] == "use_original":
        result["path"] = str(source_path)
        return result

    if decision["action"] == "crop_center":
        crop_path = output_dir / f"cover-reference{source_path.suffix or '.jpg'}"
        try:
            crop_thumbnail_reference(
                source_path,
                crop_path,
                top_ratio=float(cover_config.get("reference_crop_top_ratio", 0.18)),
                bottom_ratio=float(cover_config.get("reference_crop_bottom_ratio", 0.18)),
            )
            result["path"] = str(crop_path)
            return result
        except Exception as e:
            logger.warning(f"参考缩略图裁剪失败，回退文生图: {e}")
            result.update({"action": "ignore", "reason": f"crop_failed: {e}", "path": None})
            return result

    return result


def analyze_thumbnail_for_cover(image_path: Path) -> dict[str, Any]:
    """Heuristic thumbnail analysis for food-cover routing."""
    try:
        from PIL import Image, ImageStat
    except ImportError:
        return {"available": False, "reason": "pillow_missing"}

    with Image.open(image_path) as image:
        image = image.convert("RGB")
        width, height = image.size
        sample = image.resize((160, max(1, round(160 * height / width))))
        sw, sh = sample.size

        def region_stats(box: tuple[int, int, int, int]) -> dict[str, float]:
            region = sample.crop(box)
            gray = region.convert("L")
            stat = ImageStat.Stat(region)
            gray_stat = ImageStat.Stat(gray)
            pixels = list(region.getdata())
            red_green = sum(1 for r, g, b in pixels if r > g * 1.12 and r > b * 1.12 and r > 95)
            green = sum(1 for r, g, b in pixels if g > r * 1.05 and g > b * 1.05 and g > 80)
            warm = sum(1 for r, g, b in pixels if r > 120 and g > 70 and b < 125)
            bright = sum(1 for r, g, b in pixels if r > 220 and g > 220 and b > 220)
            dark = sum(1 for r, g, b in pixels if r < 45 and g < 45 and b < 45)
            total = max(1, len(pixels))
            return {
                "brightness": float(gray_stat.mean[0]),
                "stddev": float(gray_stat.stddev[0]),
                "red_green_ratio": (red_green + green) / total,
                "warm_ratio": warm / total,
                "bright_ratio": bright / total,
                "dark_ratio": dark / total,
                "r_mean": float(stat.mean[0]),
                "g_mean": float(stat.mean[1]),
                "b_mean": float(stat.mean[2]),
            }

        top = region_stats((0, 0, sw, max(1, round(sh * 0.28))))
        center = region_stats((0, round(sh * 0.22), sw, round(sh * 0.78)))
        bottom = region_stats((0, round(sh * 0.72), sw, sh))
        full = region_stats((0, 0, sw, sh))

        face_like = detect_face_like_center(sample)
        black_bar_like = (
            top["dark_ratio"] > 0.65
            and bottom["dark_ratio"] > 0.65
            and top["bright_ratio"] < 0.12
            and bottom["bright_ratio"] < 0.12
        )
        top_text_score = text_like_score(top)
        bottom_text_score = text_like_score(bottom)
        if black_bar_like:
            top_text_score *= 0.25
            bottom_text_score *= 0.25
        center_food_score = food_like_score(center)
        full_food_score = food_like_score(full)

    return {
        "available": True,
        "width": width,
        "height": height,
        "top_text_score": top_text_score,
        "bottom_text_score": bottom_text_score,
        "text_score": max(top_text_score, bottom_text_score),
        "center_food_score": center_food_score,
        "full_food_score": full_food_score,
        "face_like_center": face_like,
        "black_bar_like": black_bar_like,
        "top": top,
        "center": center,
        "bottom": bottom,
        "full": full,
    }


def text_like_score(stats: dict[str, float]) -> float:
    # Large thumbnail text usually creates high contrast plus large white/black blocks.
    return (
        stats["stddev"] / 90
        + stats["bright_ratio"] * 1.2
        + stats["dark_ratio"] * 1.1
    )


def food_like_score(stats: dict[str, float]) -> float:
    return (
        stats["red_green_ratio"] * 2.0
        + stats["warm_ratio"] * 1.5
        + max(0.0, (stats["stddev"] - 25) / 120)
    )


def detect_face_like_center(image: Any) -> bool:
    # Cheap heuristic: central upper skin-colored blob often means a presenter thumbnail.
    width, height = image.size
    region = image.crop((round(width * 0.30), round(height * 0.08), round(width * 0.70), round(height * 0.55)))
    pixels = list(region.getdata())
    if not pixels:
        return False
    skin = 0
    for r, g, b in pixels:
        if r > 95 and g > 55 and b > 35 and r > g * 1.12 and r > b * 1.25 and abs(r - g) > 12:
            skin += 1
    return skin / len(pixels) > 0.18


def decide_reference_action(analysis: dict[str, Any], cover_config: dict) -> dict[str, str]:
    if not analysis.get("available"):
        if analysis.get("reason") == "pillow_missing":
            return {"action": "use_original", "reason": "pillow_missing_use_original_reference"}
        return {"action": "ignore", "reason": analysis.get("reason", "analysis_unavailable")}

    text_score = float(analysis.get("text_score", 0))
    center_food_score = float(analysis.get("center_food_score", 0))
    full_food_score = float(analysis.get("full_food_score", 0))
    face_like = bool(analysis.get("face_like_center", False))
    black_bar_like = bool(analysis.get("black_bar_like", False))

    min_food_score = float(cover_config.get("reference_min_food_score", 0.38))
    text_threshold = float(cover_config.get("reference_text_score_threshold", 0.95))
    crop_food_score = float(cover_config.get("reference_crop_min_food_score", 0.42))

    if face_like and not black_bar_like and center_food_score < 1.2:
        return {"action": "ignore", "reason": "presenter_or_non_finished_food_thumbnail"}
    if face_like and not black_bar_like and center_food_score < 1.4 and text_score < text_threshold:
        return {"action": "ignore", "reason": "presenter_thumbnail_without_finished_food"}
    if text_score >= text_threshold and center_food_score >= crop_food_score:
        return {"action": "crop_center", "reason": "text_overlay_with_food_center"}
    if full_food_score >= min_food_score or center_food_score >= crop_food_score:
        return {"action": "use_original", "reason": "clean_or_food_dominant_thumbnail"}
    return {"action": "ignore", "reason": "thumbnail_not_food_dominant"}


def crop_thumbnail_reference(source_path: Path, output_path: Path, top_ratio: float, bottom_ratio: float) -> None:
    try:
        from PIL import Image
    except ImportError as e:
        raise RuntimeError("Pillow is required for reference cropping") from e

    with Image.open(source_path) as image:
        image = image.convert("RGB")
        width, height = image.size
        top = max(0, min(height - 1, round(height * top_ratio)))
        bottom = max(top + 1, min(height, round(height * (1 - bottom_ratio))))
        crop = image.crop((0, top, width, bottom))
        crop.save(output_path, quality=92)


def should_force_text_to_image(local_thumbnail: Optional[str], cover_config: dict) -> bool:
    """Avoid image-edit only when the prepared reference should still be ignored."""
    if not local_thumbnail or not cover_config.get("force_text_to_image_for_noisy_thumbnail", False):
        return False
    path = Path(local_thumbnail)
    if not path.exists():
        return False
    analysis = analyze_thumbnail_for_cover(path)
    return decide_reference_action(analysis, cover_config)["action"] == "ignore"


def image_file_to_data_url(image_path: Path) -> str:
    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    payload = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{payload}"


def raise_for_status_with_body(response: requests.Response) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as e:
        body = response.text[:500]
        raise requests.HTTPError(f"{e}; response body: {body}", response=response) from e


def modelscope_endpoint(base_url: str, path: str) -> str:
    """Join ModelScope root or /v1 base URLs with an API path."""
    base = str(base_url or "https://api-inference.modelscope.cn/").rstrip("/")
    clean_path = path.lstrip("/")
    if base.endswith("/v1") and clean_path.startswith("v1/"):
        clean_path = clean_path[3:]
    return f"{base}/{clean_path}"


def openai_endpoint(base_url: str, path: str) -> str:
    """Join an OpenAI-compatible /v1 base URL with an API path."""
    base = str(base_url or "https://api.openai.com/v1").rstrip("/")
    clean_path = path.lstrip("/")
    return f"{base}/{clean_path}"


def extract_openai_image(payload: Any) -> Optional[dict[str, str]]:
    """Return the first image object from common OpenAI-compatible response shapes."""
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            for item in data:
                image = extract_openai_image(item)
                if image:
                    return image
        if isinstance(data, dict):
            image = extract_openai_image(data)
            if image:
                return image
        if payload.get("url") or payload.get("b64_json"):
            return {
                "url": str(payload.get("url") or "") or None,
                "b64_json": str(payload.get("b64_json") or "") or None,
            }
        for key in ("image", "image_url", "output_image", "output_url"):
            value = payload.get(key)
            if isinstance(value, str):
                if value.startswith(("http://", "https://")):
                    return {"url": value, "b64_json": None}
                if is_probable_base64_image(value):
                    return {"url": None, "b64_json": value}
            image = extract_openai_image(value)
            if image:
                return image
    if isinstance(payload, list):
        for item in payload:
            image = extract_openai_image(item)
            if image:
                return image
    if isinstance(payload, str):
        if payload.startswith(("http://", "https://")):
            return {"url": payload, "b64_json": None}
        if is_probable_base64_image(payload):
            return {"url": None, "b64_json": payload}
    return None


def sanitize_openai_response(payload: Any) -> Any:
    """Keep metadata readable by trimming huge base64 image payloads."""
    if isinstance(payload, dict):
        sanitized = {}
        for key, value in payload.items():
            if key == "b64_json" and isinstance(value, str):
                sanitized[key] = f"<base64 image omitted, {len(value)} chars>"
            else:
                sanitized[key] = sanitize_openai_response(value)
        return sanitized
    if isinstance(payload, list):
        return [sanitize_openai_response(item) for item in payload]
    return payload


def find_task_id(payload: Any) -> Optional[str]:
    if isinstance(payload, dict):
        for key in ("task_id", "id"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        output = payload.get("output")
        if isinstance(output, dict):
            value = output.get("task_id")
            if isinstance(value, str) and value:
                return value
    return None


def write_base64_image(value: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = value.split(",", 1)[1] if value.startswith("data:") and "," in value else value
    output_path.write_bytes(base64.b64decode(payload))


def is_probable_base64_image(value: str) -> bool:
    if value.startswith("data:image/"):
        return True
    if len(value) < 256:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9+/=\s]+", value[:512]))


def normalize_api_output_format(value: Any) -> str:
    output_format = str(value or "").lstrip(".").lower()
    return "jpeg" if output_format in {"jpg", "jpeg"} else output_format


def upload_to_easyimage(image_path: Path, image_host_config: dict) -> dict:
    api_url = image_host_config.get("api_url")
    if not api_url:
        raise ValueError("未配置 EasyImage API 地址 image_host.api_url")

    token = resolve_secret(image_host_config, "token", "token_env", "EASYIMAGE_TOKEN")
    if not token:
        raise ValueError("未配置 EasyImage Token，请在 config.json 的 image_host.token 填写，或设置 EASYIMAGE_TOKEN")

    token_field = image_host_config.get("token_field", "token")
    file_field = image_host_config.get("file_field", "image")
    data = {token_field: token}
    data.update(image_host_config.get("extra_fields", {}) or {})

    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    with image_path.open("rb") as image_file:
        files = {file_field: (image_path.name, image_file, mime_type)}
        response = requests.post(
            api_url,
            data=data,
            files=files,
            timeout=int(image_host_config.get("timeout_seconds", DEFAULT_IMAGE_HOST_TIMEOUT_SECONDS)),
        )

    response.raise_for_status()
    payload = parse_response_json(response)
    image_url = get_json_path(payload, image_host_config.get("url_json_path", "url")) or first_url_value(payload)
    if not image_url:
        raise RuntimeError(f"EasyImage 上传成功但未找到图片 URL: {payload}")

    return {
        "success": True,
        "provider": "easyimage",
        "url": image_url,
        "response": payload,
    }


def resolve_cover_mode(
    cover_config: dict,
    local_thumbnail: Optional[str],
    reference_image_url: str = "",
) -> str:
    mode = cover_config.get("mode", "auto")
    if mode in {"enhance", "regenerate"}:
        return mode
    if (local_thumbnail or reference_image_url) and cover_config.get("use_reference_image", True):
        return "enhance"
    return "regenerate"


def resolve_effective_cover_mode(
    cover_config: dict,
    local_thumbnail: Optional[str],
    reference_image_url: str = "",
) -> str:
    mode = resolve_cover_mode(cover_config, local_thumbnail, reference_image_url)
    if mode == "enhance" and should_force_text_to_image(local_thumbnail, cover_config):
        return "regenerate"
    return mode


def make_article_digest(body: str, max_chars: int = 900) -> str:
    lines = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("{%") or line.startswith("|"):
            continue
        if line.startswith("#"):
            lines.append(line.lstrip("# ").strip())
        elif len(line) > 8:
            lines.append(line)
        if sum(len(item) for item in lines) >= max_chars:
            break
    digest = "\n".join(lines)
    return digest[:max_chars].strip() or "一篇家常美食菜谱文章，重点展示成品菜品和可复做的教程感。"


def normalize_prompt_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if value in (None, ""):
        return []
    return [str(value)]


def build_visual_subject(article_title: str, source_title: str, tags: list[str], dish_type: str = "") -> str:
    subject_candidates = [article_title, *tags[:4], dish_type, source_title]
    stop_phrases = [
        "美食频道",
        "food",
        "百吃不厌",
        "孩子老人",
        "做法",
        "吃一口",
        "满嘴香",
        "太香了",
        "不会遗憾",
    ]
    for candidate in subject_candidates:
        cleaned = str(candidate or "").strip()
        for phrase in stop_phrases:
            cleaned = cleaned.replace(phrase, "")
        cleaned = re.sub(r"[#｜|].*$", "", cleaned).strip(" ，,。-_/")
        if cleaned and len(cleaned) <= 24:
            return cleaned
    return article_title[:24] or "成品美食"


def build_visual_clues(
    tags: list[str],
    categories: list[str],
    cooking_method: list[str],
    scene: list[str],
    cuisine: str,
    dish_type: str,
) -> list[str]:
    raw = [*tags[:8], *categories[:3], *cooking_method[:4], *scene[:3], cuisine, dish_type]
    blocked = {"封面测试", "美食", "教程", "家常", "餐馆", "外卖"}
    clues: list[str] = []
    for item in raw:
        value = str(item or "").strip()
        if not value or value in blocked:
            continue
        if len(value) > 18:
            continue
        if value not in clues:
            clues.append(value)
    return clues[:10] or ["成品食物", "干净构图", "自然光"]


def build_dish_scene_instruction(visual_subject: str, visual_clues: list[str], dish_type: str) -> str:
    text = " ".join([visual_subject, dish_type, *visual_clues])
    if any(keyword in text for keyword in ["鱼", "汤", "羹", "粥", "煲", "水煮", "酸菜"]):
        return (
            "如果主体是鱼类或汤菜，请生成中式大碗或深盘里的热菜，不要西式白盘摆盘；"
            "画面应能看到汤汁、酸菜或配菜、辣椒点缀和热乎的家常餐桌氛围。"
        )
    if any(keyword in text for keyword in ["饼", "面点", "早餐", "馒头", "包子", "面包", "烘焙"]):
        return (
            "如果主体是饼类或面点，请生成木桌上的成品摆盘，可见切面、层次或酥脆表面，"
            "周围可有小碟、筷子、擀面杖或少量原料点缀。"
        )
    return (
        "如果主体是炒菜或家常菜，请生成中式陶瓷盘或浅碗里的成品菜，"
        "搭配木桌、筷子、小碟或少量真实食材，呈现家常饭桌感。"
    )


def build_cover_prompt(
    article_text: str,
    article_title: str,
    source_title: str,
    platform: str,
    transcript_source: str,
    youtube_metadata: Optional[dict],
    cover_config: dict,
    local_thumbnail: Optional[str] = None,
    reference_image_url: str = "",
) -> str:
    """Build a strict single-food-photo prompt for blog cover generation."""
    parsed_frontmatter, _ = split_frontmatter(article_text)
    tags = normalize_prompt_list(parsed_frontmatter.get("tags"))
    categories = normalize_prompt_list(parsed_frontmatter.get("categories"))
    cooking_method = normalize_prompt_list(parsed_frontmatter.get("cooking_method"))
    scene = normalize_prompt_list(parsed_frontmatter.get("scene"))
    cuisine = str(parsed_frontmatter.get("cuisine") or "").strip()
    dish_type = str(parsed_frontmatter.get("dish_type") or "").strip()
    mode = resolve_effective_cover_mode(cover_config, local_thumbnail, reference_image_url)

    visual_subject = build_visual_subject(article_title, source_title, tags, dish_type)
    visual_clues = build_visual_clues(tags, categories, cooking_method, scene, cuisine, dish_type)
    dish_scene_instruction = build_dish_scene_instruction(visual_subject, visual_clues, dish_type)
    size = cover_config.get("size", "1344x768")
    style = cover_config.get("style", DEFAULT_FOOD_PHOTO_STYLE)
    configured_negative_prompt = cover_config.get("negative_prompt") or DEFAULT_NEGATIVE_PROMPT
    negative_prompt = "；".join(
        item for item in [STRICT_SINGLE_FOOD_PHOTO_PROMPT, configured_negative_prompt] if item
    )

    context_lines = [
        f"主体食物：{visual_subject}",
        f"视觉关键词：{'、'.join(visual_clues)}",
    ]
    if cuisine:
        context_lines.append(f"料理风格：{cuisine}")
    if dish_type:
        context_lines.append(f"食物类型：{dish_type}")
    if cooking_method:
        context_lines.append(f"成品状态参考：{'、'.join(cooking_method)}")
    if scene:
        context_lines.append(f"氛围参考：{'、'.join(scene)}")

    if mode == "enhance":
        reference_instruction = (
            "参考图只用于识别食物主体、颜色、形状和成品状态。"
            "不要保留参考图中的人物、衣服、厨房背景、文字气泡、字幕、logo、二维码、边框、拼贴、小图或海报排版。"
            "请把它重新拍成一张干净的成品菜照片。"
        )
    elif mode == "regenerate":
        reference_instruction = "不需要复刻任何视频缩略图，只根据主体食物生成一张新的干净成品菜照片。"
    else:
        reference_instruction = (
            "如果参考图干净，只参考食物主体和成品状态；如果参考图有大字、贴纸、人物、logo、拼贴或平台元素，"
            "必须忽略这些干扰，只生成干净的单张成品食物照片。"
        )

    return "\n".join(
        [
            "生成一张横版真实美食摄影照片。画面只能是一张照片，不是海报版式或宣传图设计。",
            "",
            "【视觉主体】",
            *context_lines,
            "",
            "【画面要求】",
            f"- 比例和尺寸：16:9 横图，目标尺寸 {size}。",
            f"- 风格：{style}。",
            "- 画面必须只有一个主画面：一盘或一碗完成后的成品食物，主体清晰，居中或略偏一侧。",
            "- 只展示一个成品菜主体，不要出现多个版本、多个小图、多个镜头、分屏、多宫格或拼贴布局。",
            "- 不要出现任何文字、数字、二维码、logo、品牌名、站点名、水印、贴纸、标签、菜单排版或标题区域。",
            "- 不要生成海报版式、视频缩略图风格、菜谱卡片、营养分析页、步骤说明页或网页截图。",
            "- 可以有干净餐具、筷子、小碟、少量真实食材或调料点缀，环境元素约占画面 20%-35%，不要变成孤立白底产品图。",
            f"- {dish_scene_instruction}",
            "- 构图适合 16:9 横图裁切，食物占画面主要区域，边缘保持自然桌面留白。",
            f"- {reference_instruction}",
            "- 不要把文章内容、营养提醒、制作步骤、标题文案或任何说明文字画进图片。",
            "",
            "【强制禁止】",
            negative_prompt,
            "NO TEXT, NO WORDS, NO LETTERS, NO NUMBERS, NO LOGO, NO WATERMARK, NO QR CODE, NO COLLAGE, NO SPLIT SCREEN, NO MULTI IMAGE.",
        ]
    )


def resolve_secret(config: dict, value_key: str, env_key: str, default_env: str) -> str:
    value = config.get(value_key)
    if value:
        return str(value)
    env_name = config.get(env_key) or default_env
    return os.getenv(str(env_name), "")


def parse_response_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}


def get_json_path(payload: Any, path: str) -> Optional[str]:
    current = payload
    for part in str(path).split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return str(current) if current not in (None, "") else None


def first_url_value(payload: Any) -> Optional[str]:
    if isinstance(payload, str):
        return payload if payload.startswith(("http://", "https://")) else None
    if isinstance(payload, list):
        for item in payload:
            found = first_url_value(item)
            if found:
                return found
    if isinstance(payload, dict):
        preferred = ["url", "src", "image", "image_url", "path"]
        for key in preferred:
            found = first_url_value(payload.get(key))
            if found:
                return found
        for value in payload.values():
            found = first_url_value(value)
            if found:
                return found
    return None


def download_image(url: str, output_path: Path, timeout: int = 120) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    output_path.write_bytes(response.content)


def write_cover_metadata(output_dir: Path, result: dict) -> None:
    metadata_file = output_dir / "cover-ai.json"
    metadata_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
