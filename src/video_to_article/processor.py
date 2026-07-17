import json
import re
import time
from pathlib import Path
from typing import List, Optional

from .blog import (
    build_blog_prompt_input,
    extract_frontmatter_title,
    format_snack_recipe_article,
    make_article_markdown_filename,
    replace_frontmatter_field,
    split_frontmatter,
    validate_snack_recipe_article,
)
from .config import load_config
from .cover import (
    COVER_MODE_FULL,
    COVER_MODE_OFF,
    COVER_MODE_PROMPT_ONLY,
    apply_ai_cover_to_article,
    cover_mode_exports_assets,
    cover_mode_generates_image,
    cover_pipeline_mode_label,
    normalize_cover_pipeline_mode,
)
from .logging_config import configure_logging
from .media.audio import prepare_local_audio, transcribe_audio
from .media.download import download_media
from .media.thumbnails import save_source_assets
from .output_manager import (
    build_output_paths,
    find_existing_raw_file,
    get_candidate_batch_output_dirs,
    get_batch_output_dir,
    get_video_output_dir,
    get_video_output_status,
)
from .paths import OUTPUT_DIR
from .platforms import PLATFORM_LOCAL, PLATFORM_YOUTUBE, detect_platform, platform_download_hint
from .prompts import load_prompt
from .providers.llm import optimize_text_with_llm
from .providers.subtitles import extract_platform_subtitle_text, supports_platform_subtitles
from .providers.youtube import build_youtube_metadata, extract_youtube_subtitle_text, get_youtube_info
from .providers.youtube_auth import diagnose_ytdlp_error
from .text_utils import format_time, sanitize_filename, sanitize_path_component, traditional_to_simplified

logger = configure_logging()

ARTICLE_IGNORE_NAMES = {
    "raw.md",
    "format.md",
    "summary.md",
    "evaluation.md",
    "snack_recipe.md",
    "snack_recipe.failed.md",
}


def make_youtube_batch_root_from_metadata(metadata: Optional[dict]) -> Optional[str]:
    """Build a virtual YouTube batch root from video metadata."""
    if not metadata:
        return None
    channel = metadata.get("channel") or metadata.get("uploader") or metadata.get("channel_id")
    if not channel:
        return None
    return f"YouTube\\{sanitize_path_component(str(channel))}"


def fetch_youtube_metadata_for_output(
    video_url: str,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    youtube_po_token: Optional[str] = None,
) -> Optional[dict]:
    """Fetch YouTube metadata for stable output/audio directories."""
    try:
        info = get_youtube_info(
            video_url,
            download=False,
            cookies_from_browser=cookies_from_browser,
            cookies_file=cookies_file,
            youtube_po_token=youtube_po_token,
        )
    except Exception as e:
        logger.warning(f"YouTube 元数据预取失败，将使用默认输出目录: {e}")
        return None
    return build_youtube_metadata(info, video_url)


def normalize_report_key(value: object) -> str:
    """Normalize a URL/path/title for lightweight report matching."""
    return str(value or "").strip().replace("/", "\\").lower()


def load_batch_report_completions(video_urls: List[str], batch_root: Optional[str]) -> dict[str, dict]:
    """Read batch reports and index items that previously generated an article."""
    completions: dict[str, dict] = {}
    for batch_dir in get_candidate_batch_output_dirs(video_urls, batch_root):
        report_dir = batch_dir / "_batch_reports"
        if not report_dir.exists():
            continue
        for report_file in sorted(report_dir.glob("batch_report_*.json")):
            try:
                payload = json.loads(report_file.read_text(encoding="utf-8", errors="replace"))
            except (OSError, json.JSONDecodeError):
                continue
            for result in payload.get("results") or []:
                if not isinstance(result, dict) or not result.get("success"):
                    continue
                optimized_files = result.get("optimized_files") or {}
                article_file = optimized_files.get("snack_recipe")
                raw_file = result.get("raw_file")
                if not article_file or not raw_file:
                    continue
                record = {
                    "status": "report_complete",
                    "complete": True,
                    "has_raw": True,
                    "has_article": False,
                    "article_valid": True,
                    "raw_file": str(raw_file),
                    "article_file": str(article_file),
                    "report_file": str(report_file),
                    "message": "同批次报告记录曾经成功生成文章，可能已移动到博客目录",
                }
                for key_value in (result.get("video_url"), result.get("title")):
                    key = normalize_report_key(key_value)
                    if key:
                        completions[key] = record
    return completions


def process_video(
    video_url: str,
    model_size: str = "tiny",
    cpu_threads: int = 4,
    asr_engine: str = "funasr",
    funasr_model: str = "sensevoice",
    enable_llm_optimization: bool = True,
    prompt_names: Optional[List[str]] = None,
    skip_existing: bool = False,
    batch_root: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    youtube_po_token: Optional[str] = None,
    cover_mode: Optional[str] = None,
    enable_ai_cover: Optional[bool] = None,
    print_remedies: bool = True,
    save_video: bool = False,
) -> dict:
    """Process one video/local file from text extraction through output saving.

    save_video: when True, also download and keep the original video file
    (online sources only). Transcription still prefers audio/subtitles.

    cover_mode: full | prompt_only | off.
    enable_ai_cover: legacy bool (True=full, False=off) when cover_mode is omitted.
    """
    if cover_mode is not None:
        cover_mode = normalize_cover_pipeline_mode(cover_mode)
    elif enable_ai_cover is not None:
        cover_mode = COVER_MODE_FULL if enable_ai_cover else COVER_MODE_OFF
    else:
        cover_mode = COVER_MODE_FULL
    total_start = time.time()
    platform = detect_platform(video_url)
    saved_video_path = None
    audio_path = None
    title = None

    print("\n" + "=" * 60)
    print("视频转写工具（增强版 - 支持大模型优化）")
    print(f"平台: {platform}")
    if platform not in {PLATFORM_LOCAL, PLATFORM_YOUTUBE}:
        print(f"下载说明: {platform_download_hint(platform)}")
    if save_video:
        print("额外保存: 视频文件")
    print("=" * 60 + "\n")

    if prompt_names is None:
        prompt_names = []

    if skip_existing and platform in ("Local", "YouTube"):
        existing_title = Path(video_url).stem if platform == "Local" else None
        existing_batch_root = batch_root
        if platform == "YouTube":
            try:
                existing_info = get_youtube_info(
                    video_url,
                    download=False,
                    cookies_from_browser=cookies_from_browser,
                    cookies_file=cookies_file,
                    youtube_po_token=youtube_po_token,
                )
                existing_title = existing_info.get("title")
                existing_batch_root = batch_root or make_youtube_batch_root_from_metadata(existing_info)
            except Exception:
                existing_title = None
        existing_status = (
            get_video_output_status(
                existing_title,
                video_url,
                prompt_names,
                enable_llm_optimization,
                existing_batch_root,
            )
            if existing_title
            else {"complete": False}
        )
        if existing_title and existing_status.get("complete"):
            raw_file, expected_optimized_files = build_output_paths(
                existing_title,
                video_url,
                prompt_names,
                enable_llm_optimization,
                existing_batch_root,
            )
            raw_file = Path(str(existing_status.get("raw_file") or raw_file))
            optimized_files = {k: Path(v) for k, v in expected_optimized_files.items()}
            if existing_status.get("article_file") and "snack_recipe" in (prompt_names or []):
                optimized_files["snack_recipe"] = Path(str(existing_status["article_file"]))
            print(f"[跳过] 已存在输出: {existing_title}")
            return {
                "success": True,
                "skipped": True,
                "title": existing_title,
                "video_url": video_url,
                "platform": platform,
                "raw_file": str(raw_file),
                "optimized_files": {k: str(v) for k, v in optimized_files.items()},
            }
        if existing_title and enable_llm_optimization and prompt_names:
            raw_file = find_existing_raw_file(existing_title, video_url, existing_batch_root)
            if raw_file and raw_file.exists():
                print(f"[补跑] 已存在 raw.md，跳过音频提取/ASR: {raw_file}")
                result = process_raw_file(
                    raw_file=str(raw_file),
                    prompt_names=prompt_names,
                    cover_mode=cover_mode,
                    print_remedies=print_remedies,
                )
                result.setdefault("title", existing_title)
                result["video_url"] = video_url
                result["platform"] = platform
                result["reused_raw"] = True
                return result

    config = load_config()

    youtube_metadata = None
    source_metadata: Optional[dict] = None
    transcript_source = asr_engine
    transcript_text = None

    if platform == "Local":
        print("步骤 1: 从本地视频提取音频...")
        try:
            audio_path, title, extracted_audio = prepare_local_audio(video_url, batch_root=batch_root)
            if extracted_audio:
                print("   已从本地视频提取音频")
            else:
                print("   已使用本地音频文件，跳过音频提取")
        except Exception as e:
            logger.error(f"音频提取失败: {e}")
            return {"success": False, "error": str(e), "video_url": video_url, "platform": platform}
    elif platform == "YouTube":
        print("步骤 1: 提取 YouTube 字幕...")
        try:
            subtitle_text, youtube_metadata = extract_youtube_subtitle_text(
                video_url,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
                youtube_po_token=youtube_po_token,
            )
            title = youtube_metadata.get("title") if youtube_metadata else "未知标题"
            batch_root = batch_root or make_youtube_batch_root_from_metadata(youtube_metadata)
            source_metadata = youtube_metadata
        except Exception as e:
            logger.warning(f"YouTube 字幕提取失败，将回退到音频转写: {e}")
            hint = diagnose_ytdlp_error(e)
            if hint:
                print(f"   诊断: {hint}")
            subtitle_text = None
            youtube_metadata = fetch_youtube_metadata_for_output(
                video_url,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
                youtube_po_token=youtube_po_token,
            )
            title = youtube_metadata.get("title") if youtube_metadata else None
            batch_root = batch_root or make_youtube_batch_root_from_metadata(youtube_metadata)
            source_metadata = youtube_metadata

        if subtitle_text:
            transcript_text = traditional_to_simplified(subtitle_text)
            transcript_source = (
                f"youtube_subtitle:{youtube_metadata.get('caption_source')}:"
                f"{youtube_metadata.get('caption_language')}"
            )
            audio_path = None
            print(
                f"   已使用 YouTube 字幕: "
                f"{youtube_metadata.get('caption_source')} / {youtube_metadata.get('caption_language')}"
            )
            if save_video:
                print("   额外下载视频文件...")
                try:
                    if youtube_metadata is None:
                        youtube_metadata = {}
                    video_result = download_media(
                        video_url,
                        media_type="video",
                        cookies_from_browser=cookies_from_browser,
                        cookies_file=cookies_file,
                        youtube_po_token=youtube_po_token,
                        batch_root=batch_root,
                        metadata=youtube_metadata,
                    )
                    saved_video_path = video_result.video_path
                    youtube_metadata.update(video_result.metadata or {})
                    source_metadata = youtube_metadata
                    batch_root = batch_root or make_youtube_batch_root_from_metadata(youtube_metadata)
                    print(f"   视频已保存: {saved_video_path}")
                except Exception as e:
                    logger.warning(f"视频下载失败（字幕转写仍继续）: {e}")
                    print(f"   警告: 视频下载失败，转写继续。{e}")
        else:
            reason = (youtube_metadata or {}).get("caption_failure_reason") if youtube_metadata else None
            if reason == "no_caption_tracks":
                print("   未发现字幕轨，回退到下载音频并转写...")
            elif reason == "auth_or_bot_check":
                print("   字幕不可用（疑似 YouTube 登录/风控），回退到下载音频并转写...")
                print("   提示: 更新 cookies 或配置 --youtube-po-token 后可优先使用字幕")
            elif reason == "download_or_parse_failed":
                print("   字幕轨存在但下载/解析失败，回退到下载音频并转写...")
                manual_langs = (youtube_metadata or {}).get("caption_available_manual") or []
                auto_langs = (youtube_metadata or {}).get("caption_available_automatic") or []
                if manual_langs or auto_langs:
                    print(
                        f"   可用语言: 人工={', '.join(manual_langs[:8]) or '无'}; "
                        f"自动={', '.join(auto_langs[:8]) or '无'}"
                    )
                print("   提示: 可配置 cookies / --youtube-po-token 后重试字幕")
            else:
                print("   未找到可用字幕，回退到下载音频并转写...")
            try:
                if youtube_metadata is None:
                    youtube_metadata = {}
                media_type = "both" if save_video else "audio"
                media_result = download_media(
                    video_url,
                    media_type=media_type,
                    cookies_from_browser=cookies_from_browser,
                    cookies_file=cookies_file,
                    youtube_po_token=youtube_po_token,
                    batch_root=batch_root,
                    metadata=youtube_metadata,
                )
                audio_path = media_result.audio_path
                title = media_result.title
                saved_video_path = media_result.video_path
                youtube_metadata.update(media_result.metadata or {})
                source_metadata = youtube_metadata
                batch_root = batch_root or make_youtube_batch_root_from_metadata(youtube_metadata)
                if save_video and saved_video_path:
                    print(f"   视频已保存: {saved_video_path}")
            except Exception as e:
                logger.error(f"下载失败: {e}")
                hint = diagnose_ytdlp_error(e)
                if hint:
                    print(f"   诊断: {hint}")
                return {
                    "success": False,
                    "error": str(e),
                    "hint": hint,
                    "video_url": video_url,
                    "platform": platform,
                }
    elif supports_platform_subtitles(platform):
        # Bilibili (and other subtitle-capable platforms): try captions before ASR.
        print(f"步骤 1: 提取平台字幕 ({platform})...")
        platform_metadata = None
        subtitle_text = None
        try:
            subtitle_text, platform_metadata = extract_platform_subtitle_text(
                video_url,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
                youtube_po_token=youtube_po_token,
                platform=platform,
            )
            title = (platform_metadata or {}).get("title") or title
            source_metadata = dict(platform_metadata or {})
        except Exception as e:
            logger.warning(f"{platform} 字幕提取失败，将回退到音频转写: {e}")
            hint = diagnose_ytdlp_error(e)
            if hint:
                print(f"   诊断: {hint}")
            subtitle_text = None

        if subtitle_text:
            transcript_text = traditional_to_simplified(subtitle_text)
            caption_source = (platform_metadata or {}).get("caption_source") or "unknown"
            caption_language = (platform_metadata or {}).get("caption_language") or "unknown"
            transcript_source = f"platform_subtitle:{caption_source}:{caption_language}"
            audio_path = None
            print(f"   已使用平台字幕: {caption_source} / {caption_language}")
            if save_video:
                print("   额外下载视频文件...")
                try:
                    video_result = download_media(
                        video_url,
                        media_type="video",
                        cookies_from_browser=cookies_from_browser,
                        cookies_file=cookies_file,
                        youtube_po_token=youtube_po_token,
                        batch_root=batch_root,
                        metadata=platform_metadata,
                    )
                    saved_video_path = video_result.video_path
                    title = video_result.title or title
                    if video_result.metadata:
                        source_metadata = {**(source_metadata or {}), **video_result.metadata}
                    if save_video and saved_video_path:
                        print(f"   视频已保存: {saved_video_path}")
                except Exception as e:
                    logger.warning(f"视频下载失败（字幕转写仍继续）: {e}")
                    print(f"   警告: 视频下载失败，转写继续。{e}")
        else:
            reason = (platform_metadata or {}).get("caption_failure_reason") if platform_metadata else None
            if reason == "no_caption_tracks":
                print("   未发现字幕轨，回退到下载音频并转写...")
            elif reason == "auth_or_bot_check":
                print("   字幕不可用（疑似登录/风控），回退到下载音频并转写...")
            elif reason == "download_or_parse_failed":
                print("   字幕轨存在但下载/解析失败，回退到下载音频并转写...")
            else:
                print("   未找到可用字幕，回退到下载音频并转写...")
            try:
                media_type = "both" if save_video else "audio"
                media_result = download_media(
                    video_url,
                    media_type=media_type,
                    cookies_from_browser=cookies_from_browser,
                    cookies_file=cookies_file,
                    youtube_po_token=youtube_po_token,
                    batch_root=batch_root,
                    metadata=platform_metadata,
                )
                audio_path = media_result.audio_path
                title = media_result.title
                saved_video_path = media_result.video_path
                if media_result.metadata:
                    source_metadata = {**(source_metadata or {}), **media_result.metadata}
                elif platform_metadata:
                    source_metadata = dict(platform_metadata)
                if save_video and saved_video_path:
                    print(f"   视频已保存: {saved_video_path}")
            except Exception as e:
                logger.error(f"下载失败: {e}")
                hint = diagnose_ytdlp_error(e)
                if hint:
                    print(f"   诊断: {hint}")
                return {
                    "success": False,
                    "error": str(e),
                    "hint": hint,
                    "video_url": video_url,
                    "platform": platform,
                }
    else:
        step_label = "下载音频/视频" if save_video else "下载音频"
        print(f"步骤 1: {step_label} ({platform})...")
        try:
            media_type = "both" if save_video else "audio"
            media_result = download_media(
                video_url,
                media_type=media_type,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
                youtube_po_token=youtube_po_token,
                batch_root=batch_root,
            )
            audio_path = media_result.audio_path
            title = media_result.title
            saved_video_path = media_result.video_path
            if media_result.metadata:
                source_metadata = dict(media_result.metadata)
            if save_video and saved_video_path:
                print(f"   视频已保存: {saved_video_path}")
        except Exception as e:
            logger.error(f"下载失败: {e}")
            hint = diagnose_ytdlp_error(e)
            if hint:
                print(f"   诊断: {hint}")
            return {
                "success": False,
                "error": str(e),
                "hint": hint,
                "video_url": video_url,
                "platform": platform,
            }

    if transcript_text is None:
        print("\n步骤 2: 转写音频...")
        if asr_engine == "funasr":
            print(f"   ASR 引擎: FunASR ({funasr_model})")
        else:
            print(f"   ASR 引擎: Whisper ({model_size})")
        try:
            transcript_text = transcribe_audio(audio_path, model_size, cpu_threads, asr_engine, funasr_model)
        except Exception as e:
            logger.error(f"转写失败: {e}")
            return {"success": False, "error": str(e), "video_url": video_url, "title": title}
    else:
        print("\n步骤 2: 使用字幕文本，跳过音频转写。")

    optimized_texts = {}
    formatted_text = transcript_text

    if enable_llm_optimization and prompt_names:
        print(f"\n步骤 3: 大模型优化 (使用 {len(prompt_names)} 个提示词)...")

        if "format" in prompt_names:
            print("   - 使用提示词: format (格式化转录稿)")
            prompt_template = load_prompt("format")
            if prompt_template:
                formatted_text = optimize_text_with_llm(transcript_text, config, "format")
                if formatted_text:
                    optimized_texts["format"] = formatted_text
                    print("     格式化完成，后续提示词将使用格式化后的文本")
                else:
                    logger.warning("格式化失败，后续提示词将使用原始转写")
                    formatted_text = transcript_text
            else:
                logger.warning("format 提示词无效，跳过")

            prompt_names = [p for p in prompt_names if p != "format"]

        for prompt_name in prompt_names:
            print(f"   - 使用提示词: {prompt_name}")
            prompt_template = load_prompt(prompt_name)
            if not prompt_template:
                logger.warning(f"跳过无效的提示词: {prompt_name}")
                continue

            prompt_input = formatted_text
            if prompt_name == "snack_recipe":
                prompt_input = build_blog_prompt_input(
                    formatted_text,
                    title,
                    platform,
                    video_url,
                    transcript_source,
                    youtube_metadata,
                )

            optimized_text = optimize_text_with_llm(prompt_input, config, prompt_name)
            if optimized_text:
                if prompt_name == "snack_recipe":
                    optimized_text = format_snack_recipe_article(
                        optimized_text,
                        title,
                        video_url,
                        platform,
                        transcript_source,
                        youtube_metadata,
                    )
                optimized_texts[prompt_name] = optimized_text

    print("\n步骤 4: 保存结果...")
    save_start = time.time()

    raw_file, expected_optimized_files = build_output_paths(
        title,
        video_url,
        prompt_names,
        enable_llm_optimization,
        batch_root,
    )
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    with open(raw_file, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        f.write(f"**视频链接**: {video_url}\n\n")
        f.write(f"**文本来源**: {transcript_source}\n\n")
        f.write("---\n\n")
        f.write("## 原始转写\n\n")
        f.write(transcript_text)

    source_assets: dict = {}
    meta_for_assets = dict(source_metadata or youtube_metadata or {})
    if platform != PLATFORM_LOCAL and (meta_for_assets or transcript_text):
        meta_for_assets["transcript_source"] = transcript_source
        meta_for_assets.setdefault("platform", platform)
        meta_for_assets.setdefault("title", title)
        meta_for_assets.setdefault("webpage_url", video_url)
        # Prefer richer YouTube metadata object when present
        if youtube_metadata:
            meta_for_assets = {**meta_for_assets, **youtube_metadata}
            meta_for_assets["transcript_source"] = transcript_source
        try:
            source_assets = save_source_assets(
                raw_file,
                meta_for_assets,
                transcript_text or "",
                platform=platform,
            )
        except Exception as e:
            logger.warning(f"保存来源素材（含封面）失败: {e}")
    # Backward-compatible alias used in result payload
    youtube_assets = source_assets

    optimized_files = {}
    cover_assets = {}
    local_thumbnail = source_assets.get("thumbnail")
    for prompt_name, optimized_text in optimized_texts.items():
        fallback_file = get_video_output_dir(title, video_url, batch_root) / f"{sanitize_filename(prompt_name, 30)}.md"
        if prompt_name == "snack_recipe":
            cover_result = None
            if cover_mode_exports_assets(cover_mode):
                if cover_mode_generates_image(cover_mode):
                    print("   生成 AI 封面中（可能需要 1–5 分钟，请稍候）...")
                else:
                    print("   导出封面提示词/元数据（不调用生图 API）...")
                optimized_text, cover_result = apply_ai_cover_to_article(
                    article_text=optimized_text,
                    config=config,
                    output_dir=raw_file.parent,
                    source_title=title,
                    source_url=video_url,
                    platform=platform,
                    transcript_source=transcript_source,
                    youtube_metadata=youtube_metadata or meta_for_assets or None,
                    local_thumbnail=local_thumbnail,
                    cover_mode=cover_mode,
                )
                if cover_result and cover_result.get("local_path"):
                    print(f"   封面已生成: {cover_result.get('local_path')}")
                elif cover_result and cover_result.get("status") == "prompt_only":
                    print(f"   封面提示词: {cover_result.get('prompt_file')}")
                    print(f"   封面元数据: {raw_file.parent / 'cover-ai.json'}")
                elif cover_result and cover_result.get("error"):
                    print(f"   封面生成失败（文章仍会保存）: {cover_result.get('error')}")
                    if cover_result.get("prompt_file"):
                        print(f"   仍可使用提示词手动生图: {cover_result.get('prompt_file')}")
            if cover_result:
                cover_assets[prompt_name] = cover_result
            article_title = extract_frontmatter_title(optimized_text, title)
            fallback_file = get_video_output_dir(title, video_url, batch_root) / make_article_markdown_filename(article_title, title)

        optimized_file = expected_optimized_files.get(
            prompt_name,
            fallback_file,
        )
        if prompt_name == "snack_recipe":
            optimized_file = fallback_file

        optimized_file.parent.mkdir(parents=True, exist_ok=True)
        with open(optimized_file, "w", encoding="utf-8") as f:
            f.write(optimized_text)
        optimized_files[prompt_name] = str(optimized_file)

    logger.info(f"结果保存完成 (耗时: {format_time(time.time() - save_start)})")
    total_elapsed = time.time() - total_start

    print("\n" + "=" * 60)
    print("处理完成！")
    print(f"总耗时: {format_time(total_elapsed)}")
    print(f"原始转写: {raw_file}")
    if saved_video_path:
        print(f"视频文件: {saved_video_path}")
    for prompt_name, file_path in optimized_files.items():
        print(f"优化版本 ({prompt_name}): {file_path}")
    print("=" * 60)

    print("\n原始转写预览:")
    print("-" * 60)
    print(transcript_text[:200] + ("..." if len(transcript_text) > 200 else ""))
    print("-" * 60)

    result = {
        "success": True,
        "title": title,
        "video_url": video_url,
        "platform": platform,
        "raw_file": str(raw_file),
        "optimized_files": optimized_files,
        "assets": {**youtube_assets, "cover": cover_assets} if cover_assets else youtube_assets,
        "transcript_text": transcript_text,
        "optimized_texts": optimized_texts,
        "total_time": total_elapsed,
        "video_path": saved_video_path,
        "audio_path": audio_path,
    }
    if print_remedies:
        partial_issues = collect_batch_health_issues(
            results=[result],
            config=config,
            cover_mode=cover_mode,
            enable_llm_optimization=enable_llm_optimization,
            prompt_names=prompt_names,
        )
        if partial_issues:
            print("\n本次处理有可补救问题:")
            print_partial_issues(partial_issues)
    return result


def process_raw_file(
    raw_file: str,
    prompt_names: Optional[List[str]] = None,
    cover_mode: Optional[str] = None,
    enable_ai_cover: Optional[bool] = None,
    print_remedies: bool = True,
) -> dict:
    """Regenerate optimized article files from an existing raw.md without ASR."""
    total_start = time.time()
    raw_path = Path(raw_file)
    if not raw_path.exists():
        return {
            "success": False,
            "error": f"raw 文件不存在: {raw_file}",
            "raw_file": str(raw_path),
        }

    config = load_config()
    if cover_mode is not None:
        cover_mode = normalize_cover_pipeline_mode(cover_mode)
    elif enable_ai_cover is not None:
        cover_mode = COVER_MODE_FULL if enable_ai_cover else COVER_MODE_OFF
    else:
        cover_mode = COVER_MODE_PROMPT_ONLY
    parsed_raw = parse_raw_transcript_file(raw_path)
    title = parsed_raw["title"]
    source = parsed_raw["source"]
    transcript_source = parsed_raw["transcript_source"]
    transcript_text = parsed_raw["transcript_text"]
    platform = detect_platform(source)
    prompt_names = prompt_names or ["snack_recipe"]
    output_dir = raw_path.parent
    existing_cover = find_existing_article_cover(output_dir)

    print("\n" + "=" * 60)
    print("从已有 raw.md 重新生成文章")
    print(f"标题: {title}")
    print(f"raw: {raw_path}")
    print(f"跳过视频/ASR: 是")
    print(f"AI 封面: {cover_pipeline_mode_label(cover_mode)}")
    print("=" * 60)

    optimized_files: dict[str, str] = {}
    for prompt_name in prompt_names:
        print(f"\n- 使用提示词: {prompt_name}")
        prompt_input = transcript_text
        if prompt_name == "snack_recipe":
            prompt_input = build_blog_prompt_input(
                transcript_text,
                title,
                platform,
                source,
                transcript_source,
                None,
            )

        optimized_text = optimize_text_with_llm(prompt_input, config, prompt_name)
        if not optimized_text:
            result = {
                "success": False,
                "error": f"{prompt_name} 大模型整理失败",
                "raw_file": str(raw_path),
                "remedy_command": make_from_raw_command(raw_path),
            }
            if print_remedies:
                print("\n本次补跑失败，可复制下面命令重试:")
                print(f"  {make_from_raw_command(raw_path)}")
            return result

        if prompt_name == "snack_recipe":
            optimized_text = format_snack_recipe_article(
                optimized_text,
                title,
                source,
                platform,
                transcript_source,
                None,
            )
            if existing_cover and "cover:" not in optimized_text.split("---", 2)[1]:
                optimized_text = replace_frontmatter_field(optimized_text, "cover", existing_cover)

            problems = validate_snack_recipe_article(optimized_text)
            if problems:
                failed_file = output_dir / "snack_recipe.failed.md"
                failed_file.write_text(optimized_text, encoding="utf-8")
                print("\n生成结果未通过质检，已保存失败稿:")
                print(failed_file)
                for problem in problems:
                    print(f"  - {problem}")
                result = {
                    "success": False,
                    "error": "生成结果未通过质检",
                    "problems": problems,
                    "raw_file": str(raw_path),
                    "failed_file": str(failed_file),
                    "remedy_command": make_from_raw_command(raw_path),
                }
                if print_remedies:
                    print("\n可复制下面命令重新补跑文章:")
                    print(f"  {make_from_raw_command(raw_path)}")
                return result

            if cover_mode_exports_assets(cover_mode):
                local_thumbnail = find_existing_thumbnail(output_dir)
                if existing_cover and cover_mode_generates_image(cover_mode):
                    print(f"复用已有封面: {existing_cover}")
                elif cover_mode_generates_image(cover_mode):
                    print("生成 AI 封面中（可能需要 1–5 分钟，请稍候）...")
                    print("  提示: 加 --no-cover 可只导出提示词、不调生图 API")
                    if local_thumbnail:
                        print(f"  参考图: {local_thumbnail}")
                    optimized_text, cover_result = apply_ai_cover_to_article(
                        article_text=optimized_text,
                        config=config,
                        output_dir=output_dir,
                        source_title=title,
                        source_url=source,
                        platform=platform,
                        transcript_source=transcript_source,
                        youtube_metadata=None,
                        local_thumbnail=local_thumbnail,
                        cover_mode=cover_mode,
                    )
                    if cover_result and cover_result.get("local_path"):
                        print(f"  封面已生成: {cover_result.get('local_path')}")
                    elif cover_result and cover_result.get("error"):
                        print(f"  封面生成失败（文章仍会保存）: {cover_result.get('error')}")
                        if cover_result.get("prompt_file"):
                            print(f"  仍可使用提示词手动生图: {cover_result.get('prompt_file')}")
                else:
                    print("导出封面提示词/元数据（不调用生图 API）...")
                    optimized_text, cover_result = apply_ai_cover_to_article(
                        article_text=optimized_text,
                        config=config,
                        output_dir=output_dir,
                        source_title=title,
                        source_url=source,
                        platform=platform,
                        transcript_source=transcript_source,
                        youtube_metadata=None,
                        local_thumbnail=local_thumbnail,
                        cover_mode=cover_mode,
                    )
                    if cover_result and cover_result.get("prompt_file"):
                        print(f"  封面提示词: {cover_result.get('prompt_file')}")
                        print(f"  封面元数据: {output_dir / 'cover-ai.json'}")
                        print("  可将提示词复制到网页手动生图，再自行填写文章 cover 字段")

            article_title = extract_frontmatter_title(optimized_text, title)
            output_file = output_dir / make_article_markdown_filename(article_title, title)
        else:
            output_file = output_dir / f"{sanitize_filename(prompt_name, 30)}.md"

        output_file.write_text(optimized_text, encoding="utf-8")
        optimized_files[prompt_name] = str(output_file)
        print(f"输出: {output_file}")

    result = {
        "success": True,
        "title": title,
        "video_url": source,
        "platform": platform,
        "raw_file": str(raw_path),
        "optimized_files": optimized_files,
        "total_time": time.time() - total_start,
    }
    if print_remedies:
        partial_issues = collect_batch_health_issues(
            results=[result],
            config=config,
            cover_mode=cover_mode,
            enable_llm_optimization=True,
            prompt_names=prompt_names,
        )
        if partial_issues:
            result["partial_issues"] = partial_issues
            print("\n本次补跑有可补救问题:")
            print_partial_issues(partial_issues)
    return result


def process_regen_cover(
    article_file: str,
    thumbnail: Optional[str] = None,
    cover_mode: str = COVER_MODE_FULL,
) -> dict:
    """Generate/upload a cover for an existing article and write the cover field back."""
    article_path = Path(article_file)
    if not article_path.exists():
        return {"success": False, "error": f"文章文件不存在: {article_file}"}

    config = load_config()
    cover_mode = normalize_cover_pipeline_mode(cover_mode)
    if cover_mode == COVER_MODE_OFF:
        return {"success": False, "error": "封面已关闭（--no-cover-assets），无法补封面"}
    cover_config = config.get("ai_cover", {}) if isinstance(config, dict) else {}
    if cover_mode_generates_image(cover_mode) and not cover_config.get("enable", False):
        return {"success": False, "error": "config.json 中 ai_cover.enable 未开启，无法自动生图"}

    article_text = article_path.read_text(encoding="utf-8", errors="replace")
    parsed_frontmatter, _ = split_frontmatter(article_text)
    article_title = extract_frontmatter_title(article_text, article_path.stem)
    source_title = str(parsed_frontmatter.get("source_title") or article_title)
    platform = str(parsed_frontmatter.get("source_type") or "local")
    source_url = str(parsed_frontmatter.get("source_url") or source_title or article_path)
    transcript_source = str(parsed_frontmatter.get("transcript_source") or "article")
    output_dir = article_path.parent

    local_thumbnail = thumbnail or find_existing_thumbnail(output_dir)
    if thumbnail and not Path(thumbnail).exists():
        return {"success": False, "error": f"参考图不存在: {thumbnail}"}

    print("\n" + "=" * 60)
    print("重新生成文章封面")
    print(f"文章: {article_path}")
    print(f"标题: {article_title}")
    print(f"AI 封面: {cover_pipeline_mode_label(cover_mode)}")
    print(f"参考图: {local_thumbnail or '无，使用文章信息文生图'}")
    print("=" * 60)

    updated_text, cover_result = apply_ai_cover_to_article(
        article_text=article_text,
        config=config,
        output_dir=output_dir,
        source_title=source_title,
        source_url=source_url,
        platform=platform,
        transcript_source=transcript_source,
        youtube_metadata=None,
        local_thumbnail=local_thumbnail,
        cover_mode=cover_mode,
    )

    if not cover_result:
        return {
            "success": False,
            "error": "AI 封面未生成，检查 ai_cover 配置",
            "article_file": str(article_path),
            "remedy_command": make_regen_cover_command(article_path),
        }

    if cover_result.get("status") == "prompt_only":
        print(f"封面提示词: {cover_result.get('prompt_file')}")
        print(f"封面元数据: {output_dir / 'cover-ai.json'}")
        print("可将提示词复制到网页手动生图，再自行填写文章 cover 字段")
        return {
            "success": True,
            "article_file": str(article_path),
            "cover": cover_result,
            "cover_mode": cover_mode,
        }

    if cover_result.get("frontmatter_cover"):
        article_path.write_text(updated_text, encoding="utf-8")
        print(f"封面已写入: {cover_result['frontmatter_cover']}")
        print(f"文章已更新: {article_path}")
        return {
            "success": True,
            "article_file": str(article_path),
            "cover": cover_result["frontmatter_cover"],
            "result": cover_result,
        }

    error = cover_result.get("error") or (cover_result.get("upload") or {}).get("error") or "封面生成或上传未得到可写入的 URL"
    print(f"封面未写入: {error}")
    return {
        "success": False,
        "error": error,
        "article_file": str(article_path),
        "result": cover_result,
        "remedy_command": make_regen_cover_command(article_path),
    }


def find_existing_thumbnail(output_dir: Path) -> Optional[str]:
    """Find a local thumbnail/reference image beside an article."""
    preferred_names = [
        "thumbnail.jpg",
        "thumbnail.jpeg",
        "thumbnail.png",
        "thumbnail.webp",
        "cover-reference.jpg",
        "cover-reference.jpeg",
        "cover-reference.png",
        "cover-reference.webp",
    ]
    for name in preferred_names:
        path = output_dir / name
        if path.exists():
            return str(path)
    return None


def parse_raw_transcript_file(raw_path: Path) -> dict[str, str]:
    """Parse the raw.md generated by process_video."""
    text = raw_path.read_text(encoding="utf-8", errors="replace")
    title_match = re.search(r"^#\s+(.+?)\s*$", text, flags=re.MULTILINE)
    source_match = re.search(r"^\*\*视频链接\*\*:\s*(.+?)\s*$", text, flags=re.MULTILINE)
    transcript_source_match = re.search(r"^\*\*文本来源\*\*:\s*(.+?)\s*$", text, flags=re.MULTILINE)
    transcript_match = re.search(r"^## 原始转写\s*(.+)\s*$", text, flags=re.MULTILINE | re.DOTALL)
    title = title_match.group(1).strip() if title_match else raw_path.parent.name
    source = source_match.group(1).strip() if source_match else str(raw_path)
    transcript_source = transcript_source_match.group(1).strip() if transcript_source_match else "raw"
    transcript_text = transcript_match.group(1).strip() if transcript_match else text.strip()
    return {
        "title": title,
        "source": source,
        "transcript_source": transcript_source,
        "transcript_text": transcript_text,
    }


def find_existing_article_cover(output_dir: Path) -> str:
    """Return an existing article cover URL from the output directory, if any."""
    for path in sorted(output_dir.glob("*.md")):
        if path.name in ARTICLE_IGNORE_NAMES:
            continue
        parsed, _ = split_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        cover = parsed.get("cover")
        if cover:
            return str(cover)
    cover_metadata_file = output_dir / "cover-ai.json"
    if cover_metadata_file.exists():
        try:
            cover_metadata = json.loads(cover_metadata_file.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            cover_metadata = {}
        cover = cover_metadata.get("frontmatter_cover")
        upload = cover_metadata.get("upload")
        if not cover and isinstance(upload, dict):
            cover = upload.get("url")
        if cover:
            return str(cover)
    return ""


def find_article_file(output_dir: Path, preferred_file: Optional[str] = None) -> Optional[Path]:
    """Find the publishable Markdown article in an output directory."""
    if preferred_file:
        path = Path(preferred_file)
        if path.exists():
            return path

    if not output_dir.exists():
        return None

    for path in sorted(output_dir.glob("*.md")):
        if path.name not in ARTICLE_IGNORE_NAMES:
            return path
    return None


def powershell_quote(value: str) -> str:
    """Quote a command argument for copyable PowerShell snippets."""
    return '"' + value.replace('"', '`"') + '"'


def make_regen_cover_command(article_file: Path) -> str:
    return f"python transcribe.py --regen-cover {powershell_quote(str(article_file))}"


def make_from_raw_command(raw_file: Path) -> str:
    return f"python transcribe.py --from-raw {powershell_quote(str(raw_file))} --prompts snack_recipe"


def powershell_single_quote(value: str) -> str:
    """Quote a string for a PowerShell single-quoted literal."""
    return "'" + value.replace("'", "''") + "'"


def load_cover_metadata(output_dir: Path) -> tuple[Optional[dict], Optional[str]]:
    """Load cover-ai.json from an output directory."""
    metadata_file = output_dir / "cover-ai.json"
    if not metadata_file.exists():
        return None, "未找到 cover-ai.json"
    try:
        return json.loads(metadata_file.read_text(encoding="utf-8", errors="replace")), None
    except json.JSONDecodeError as e:
        return None, f"cover-ai.json 解析失败: {e}"


def get_article_cover(article_file: Path) -> str:
    try:
        parsed, _ = split_frontmatter(article_file.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return ""
    cover = parsed.get("cover")
    return str(cover).strip() if cover else ""


def cover_frontmatter_expected(config: dict) -> bool:
    """Return whether current config intends to write a cover into article front-matter."""
    cover_config = config.get("ai_cover", {}) if isinstance(config, dict) else {}
    image_host_config = config.get("image_host", {}) if isinstance(config, dict) else {}
    return bool(
        cover_config.get("enable", False)
        and (
            image_host_config.get("enable", False)
            or cover_config.get("use_model_output_url_in_frontmatter", False)
            or cover_config.get("use_local_cover_in_frontmatter", False)
        )
    )


def get_cover_error(cover_metadata: dict) -> str:
    """Extract the most useful cover error from cover-ai.json content."""
    if cover_metadata.get("error"):
        return str(cover_metadata["error"])
    upload = cover_metadata.get("upload")
    if isinstance(upload, dict) and upload.get("error"):
        return str(upload["error"])
    return "封面生成、上传或回写未完成"


def collect_result_health_issues(
    result: dict,
    config: dict,
    cover_mode: str,
    enable_llm_optimization: bool,
    prompt_names: Optional[List[str]],
    enable_ai_cover: Optional[bool] = None,
) -> list[dict]:
    """Collect non-fatal issues for one processed result."""
    if not result.get("success") or result.get("skipped"):
        return []

    cover_mode = normalize_cover_pipeline_mode(cover_mode, enable_ai_cover_fallback=enable_ai_cover)
    prompt_names = prompt_names or []
    should_check_article = enable_llm_optimization and "snack_recipe" in prompt_names
    if not should_check_article:
        return []

    raw_file = Path(str(result.get("raw_file", ""))) if result.get("raw_file") else None
    output_dir = raw_file.parent if raw_file else None
    optimized_files = result.get("optimized_files") or {}
    article_file = find_article_file(output_dir, optimized_files.get("snack_recipe")) if output_dir else None
    title = str(result.get("title") or (article_file.stem if article_file else result.get("video_url", "unknown")))
    base_issue = {
        "title": title,
        "video_url": result.get("video_url", ""),
        "output_dir": str(output_dir) if output_dir else "",
        "article_file": str(article_file) if article_file else "",
        "raw_file": str(raw_file) if raw_file else "",
    }

    issues: list[dict] = []
    if not raw_file or not raw_file.exists():
        issues.append(
            {
                **base_issue,
                "stage": "transcript.raw",
                "type": "raw_missing",
                "message": "缺少 raw.md，无法确认原始转写是否完整",
                "remedy_command": "",
            }
        )
        return issues

    if not article_file or not article_file.exists():
        issues.append(
            {
                **base_issue,
                "stage": "article.generate",
                "type": "article_missing",
                "message": "缺少 snack_recipe 正式文章",
                "remedy_command": make_from_raw_command(raw_file),
            }
        )
        return issues

    article_text = article_file.read_text(encoding="utf-8", errors="replace")
    article_problems = validate_snack_recipe_article(article_text)
    if article_problems:
        issues.append(
            {
                **base_issue,
                "article_file": str(article_file),
                "stage": "article.validate",
                "type": "article_quality",
                "message": "文章结构质检未通过: " + "；".join(article_problems[:5]),
                "problems": article_problems,
                "remedy_command": make_from_raw_command(raw_file),
            }
        )

    # prompt_only / off: do not treat missing image or frontmatter cover as failures.
    if not cover_mode_generates_image(cover_mode) or not cover_frontmatter_expected(config):
        return issues

    cover_metadata, cover_error = load_cover_metadata(article_file.parent)
    if cover_error:
        issues.append(
            {
                **base_issue,
                "article_file": str(article_file),
                "stage": "ai_cover.metadata",
                "type": "cover_metadata",
                "message": cover_error,
                "remedy_command": make_regen_cover_command(article_file),
            }
        )
        return issues

    if not cover_metadata:
        return issues

    # Successful prompt-only exports store success=True with status=prompt_only.
    if cover_metadata.get("status") == "prompt_only" or cover_metadata.get("cover_mode") == COVER_MODE_PROMPT_ONLY:
        return issues

    if cover_metadata.get("success") is False:
        issues.append(
            {
                **base_issue,
                "article_file": str(article_file),
                "stage": "ai_cover.generate",
                "type": "cover_generate",
                "message": get_cover_error(cover_metadata),
                "remedy_command": make_regen_cover_command(article_file),
            }
        )
        return issues

    upload = cover_metadata.get("upload")
    if isinstance(upload, dict) and upload.get("success") is False:
        issues.append(
            {
                **base_issue,
                "article_file": str(article_file),
                "stage": "image_host.upload",
                "type": "cover_upload",
                "message": get_cover_error(cover_metadata),
                "remedy_command": make_regen_cover_command(article_file),
            }
        )
        return issues

    local_path = cover_metadata.get("local_path")
    if local_path and not Path(str(local_path)).exists():
        issues.append(
            {
                **base_issue,
                "article_file": str(article_file),
                "stage": "ai_cover.local_file",
                "type": "cover_local_missing",
                "message": f"cover-ai 本地文件不存在: {local_path}",
                "remedy_command": make_regen_cover_command(article_file),
            }
        )

    article_cover = get_article_cover(article_file)
    if not article_cover:
        issues.append(
            {
                **base_issue,
                "article_file": str(article_file),
                "stage": "article.frontmatter",
                "type": "cover_frontmatter",
                "message": "AI 封面已生成但文章 front-matter 未写入 cover",
                "remedy_command": make_regen_cover_command(article_file),
            }
        )

    return issues


def collect_batch_health_issues(
    results: List[dict],
    config: dict,
    cover_mode: str,
    enable_llm_optimization: bool,
    prompt_names: Optional[List[str]],
    enable_ai_cover: Optional[bool] = None,
) -> list[dict]:
    issues: list[dict] = []
    cover_mode = normalize_cover_pipeline_mode(cover_mode, enable_ai_cover_fallback=enable_ai_cover)
    for result in results:
        issues.extend(
            collect_result_health_issues(
                result,
                config,
                cover_mode,
                enable_llm_optimization,
                prompt_names,
            )
        )
    return issues


def issue_identity(issue: dict) -> str:
    """Return a stable key for comparing health issues across repair rounds."""
    return "|".join(
        [
            str(issue.get("stage") or ""),
            str(issue.get("type") or ""),
            str(issue.get("raw_file") or ""),
            str(issue.get("article_file") or ""),
            str(issue.get("output_dir") or ""),
            str(issue.get("title") or ""),
        ]
    )


def unique_remedy_commands(partial_issues: list[dict]) -> list[str]:
    """Return deduplicated remedy commands, preserving issue order."""
    remedy_commands = []
    seen = set()
    for issue in partial_issues:
        command = issue.get("remedy_command")
        if command and command not in seen:
            remedy_commands.append(command)
            seen.add(command)
    return remedy_commands


def write_repair_script(
    partial_issues: list[dict],
    report_dir: Path,
    label: str = "",
    check_report_file: Optional[Path] = None,
) -> Optional[Path]:
    """Write a copy-safe PowerShell repair script for the current issues."""
    remedy_commands = unique_remedy_commands(partial_issues)
    if not remedy_commands:
        return None

    report_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"_{label}" if label else ""
    script_file = report_dir / f"repair{suffix}_{time.strftime('%Y%m%d-%H%M%S')}.ps1"
    project_root = Path.cwd().resolve()
    lines = [
        "# Auto-generated by video-to-article. Safe to rerun.",
        "$failed = @()",
        f"Set-Location {powershell_single_quote(str(project_root))}",
        'if (Test-Path ".\\.venv\\Scripts\\Activate.ps1") { . ".\\.venv\\Scripts\\Activate.ps1" }',
        "",
    ]
    total = len(remedy_commands)
    for index, command in enumerate(remedy_commands, 1):
        lines.extend(
            [
                f'Write-Host "[{index}/{total}] {command}"',
                command,
                'if ($LASTEXITCODE -ne 0) { $failed += ' + powershell_single_quote(command) + " }",
                "",
            ]
        )
    if check_report_file:
        check_command = f"python transcribe.py --check-report {powershell_single_quote(str(check_report_file))}"
        lines.extend(
            [
                'Write-Host "Repair commands completed. Rechecking batch report..."',
                f"Write-Host {powershell_single_quote(check_command)}",
                check_command,
                'if ($LASTEXITCODE -ne 0) { $failed += ' + powershell_single_quote(check_command) + " }",
                "",
            ]
        )
    else:
        lines.append('Write-Host "Repair commands completed."')

    lines.extend(
        [
            'if ($failed.Count -gt 0) {',
            '  Write-Warning "Some repair or recheck commands failed:"',
            '  $failed | ForEach-Object { Write-Warning $_ }',
            "  exit 1",
            "}",
        ]
    )
    script_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return script_file


def print_partial_issues(partial_issues: list[dict], repair_script: Optional[Path] = None) -> None:
    """Print non-fatal batch issues and copyable remedies."""
    if not partial_issues:
        return

    print("\n局部问题明细:")
    for issue in partial_issues:
        print(f"  - [{issue.get('stage', 'unknown')}] {issue.get('title', 'unknown')}")
        print(f"    原因: {issue.get('message', '未提供原因')}")
        if issue.get("remedy_command"):
            print(f"    补救: {issue['remedy_command']}")

    remedy_commands = unique_remedy_commands(partial_issues)

    if remedy_commands:
        if repair_script:
            print("\n一键补救脚本:")
            print(f"  powershell -ExecutionPolicy Bypass -File {powershell_quote(str(repair_script))}")
        print("\n可复制的补救命令:")
        print(f"Set-Location {powershell_quote(str(Path.cwd().resolve()))}")
        print(".\\.venv\\Scripts\\Activate.ps1")
        for command in remedy_commands:
            print(command)


def repair_issue(
    issue: dict,
    prompt_names: Optional[List[str]],
    cover_mode: str,
) -> dict:
    """Run the smallest repair action for one issue."""
    stage = str(issue.get("stage") or "")
    raw_file = str(issue.get("raw_file") or "")
    article_file = str(issue.get("article_file") or "")
    cover_mode = normalize_cover_pipeline_mode(cover_mode)

    try:
        if stage.startswith("article.") and raw_file:
            result = process_raw_file(
                raw_file=raw_file,
                prompt_names=prompt_names or ["snack_recipe"],
                cover_mode=cover_mode,
                print_remedies=False,
            )
            return {"success": bool(result.get("success")), "action": "from_raw", "result": result}
        if (
            stage.startswith("ai_cover.")
            or stage.startswith("image_host.")
            or stage == "article.frontmatter"
        ) and article_file:
            result = process_regen_cover(article_file, cover_mode=COVER_MODE_FULL)
            return {"success": bool(result.get("success")), "action": "regen_cover", "result": result}
        return {
            "success": False,
            "action": "skip",
            "error": "没有可执行的补救动作",
            "issue": issue,
        }
    except Exception as e:
        logger.error(f"自动补救失败: {issue.get('title', 'unknown')}, 错误: {e}")
        return {"success": False, "action": "error", "error": str(e), "issue": issue}


def sort_repair_issues(partial_issues: list[dict]) -> list[dict]:
    """Repair articles before covers because cover repair depends on article files."""
    def rank(issue: dict) -> tuple[int, str]:
        stage = str(issue.get("stage") or "")
        if stage.startswith("article."):
            return (0, stage)
        if stage.startswith("ai_cover.") or stage.startswith("image_host."):
            return (1, stage)
        return (2, stage)

    return sorted(partial_issues, key=rank)


def run_auto_repair(
    partial_issues: list[dict],
    results: list[dict],
    config: dict,
    cover_mode: str,
    enable_llm_optimization: bool,
    prompt_names: Optional[List[str]],
    max_rounds: int = 2,
    repair_delay: int = 0,
    enable_ai_cover: Optional[bool] = None,
) -> tuple[list[dict], dict]:
    """Run bounded repairs and return final health issues plus a summary."""
    cover_mode = normalize_cover_pipeline_mode(cover_mode, enable_ai_cover_fallback=enable_ai_cover)
    current_issues = list(partial_issues)
    summary = {
        "enabled": True,
        "max_rounds": max_rounds,
        "initial_issue_count": len(current_issues),
        "rounds": [],
        "resolved_count": 0,
        "new_issue_count": 0,
        "final_issue_count": len(current_issues),
    }

    if not current_issues or max_rounds <= 0:
        return current_issues, summary

    print("\n" + "=" * 60)
    print(f"开始自动补救，最多 {max_rounds} 轮")
    print("=" * 60)

    initial_keys = {issue_identity(issue) for issue in current_issues}
    previous_keys = set(initial_keys)

    for round_index in range(1, max_rounds + 1):
        repairable = [issue for issue in sort_repair_issues(current_issues) if issue.get("remedy_command")]
        if not repairable:
            print("没有可自动补救的问题，停止。")
            break

        print(f"\n自动补救第 {round_index}/{max_rounds} 轮，尝试 {len(repairable)} 个问题...")
        attempts = []
        for issue_index, issue in enumerate(repairable, 1):
            print(f"  [{issue_index}/{len(repairable)}] [{issue.get('stage')}] {issue.get('title')}")
            attempt = {
                "stage": issue.get("stage"),
                "title": issue.get("title"),
                "message": issue.get("message"),
                "remedy_command": issue.get("remedy_command"),
            }
            repair_result = repair_issue(issue, prompt_names, cover_mode)
            attempt["success"] = bool(repair_result.get("success"))
            attempt["action"] = repair_result.get("action")
            if repair_result.get("error"):
                attempt["error"] = repair_result.get("error")
            attempts.append(attempt)
            if repair_delay > 0 and issue_index < len(repairable):
                time.sleep(repair_delay)

        next_issues = collect_batch_health_issues(
            results=results,
            config=config,
            cover_mode=cover_mode,
            enable_llm_optimization=enable_llm_optimization,
            prompt_names=prompt_names,
        )
        next_keys = {issue_identity(issue) for issue in next_issues}
        resolved = previous_keys - next_keys
        new = next_keys - previous_keys
        round_summary = {
            "round": round_index,
            "attempted": len(repairable),
            "command_success": sum(1 for attempt in attempts if attempt.get("success")),
            "command_failed": sum(1 for attempt in attempts if not attempt.get("success")),
            "resolved_since_previous_round": len(resolved),
            "new_since_previous_round": len(new),
            "remaining": len(next_issues),
            "attempts": attempts,
        }
        summary["rounds"].append(round_summary)

        print(
            f"本轮结果: 命令成功 {round_summary['command_success']}，"
            f"命令失败 {round_summary['command_failed']}，"
            f"解决 {len(resolved)}，新增 {len(new)}，剩余 {len(next_issues)}"
        )

        current_issues = next_issues
        if not current_issues:
            break

        previous_keys = next_keys

    final_keys = {issue_identity(issue) for issue in current_issues}
    summary["resolved_count"] = len(initial_keys - final_keys)
    summary["new_issue_count"] = len(final_keys - initial_keys)
    summary["final_issue_count"] = len(current_issues)

    print("\n自动补救完成:")
    print(f"  初始问题: {summary['initial_issue_count']}")
    print(f"  已解决: {summary['resolved_count']}")
    print(f"  新增问题: {summary['new_issue_count']}")
    print(f"  最终剩余: {summary['final_issue_count']}")
    return current_issues, summary


def check_batch_report(report_file: str) -> dict:
    """Recheck local output health from a saved batch report."""
    report_path = Path(report_file)
    if not report_path.exists():
        print(f"错误: 批量报告不存在: {report_path}")
        return {"success": False, "error": f"批量报告不存在: {report_path}"}

    try:
        payload = json.loads(report_path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        print(f"错误: 批量报告解析失败: {e}")
        return {"success": False, "error": f"批量报告解析失败: {e}"}

    results = payload.get("results") or []
    if not isinstance(results, list):
        print("错误: 批量报告中 results 格式不正确")
        return {"success": False, "error": "批量报告中 results 格式不正确"}

    settings = payload.get("settings") or {}
    prompt_names = settings.get("prompt_names")
    if not isinstance(prompt_names, list):
        prompt_names = ["snack_recipe"]

    enable_ai_cover = settings.get("enable_ai_cover")
    cover_mode = normalize_cover_pipeline_mode(
        settings.get("cover_mode"),
        enable_ai_cover_fallback=bool(enable_ai_cover) if enable_ai_cover is not None else True,
    )
    enable_llm_optimization = bool(settings.get("enable_llm_optimization", True))

    try:
        health_config = load_config()
    except Exception as e:
        logger.warning(f"批量报告复查读取配置失败，将跳过配置相关检查: {e}")
        health_config = {}

    current_issues = collect_batch_health_issues(
        results=results,
        config=health_config,
        cover_mode=cover_mode,
        enable_llm_optimization=enable_llm_optimization,
        prompt_names=prompt_names,
    )

    initial_issues = payload.get("initial_partial_issues")
    if not isinstance(initial_issues, list):
        initial_issues = payload.get("partial_issues") or []
    initial_keys = {issue_identity(issue) for issue in initial_issues if isinstance(issue, dict)}
    current_keys = {issue_identity(issue) for issue in current_issues}
    failed_results = [result for result in results if isinstance(result, dict) and not result.get("success")]

    print("\n" + "=" * 60)
    print("批量报告复查")
    print("=" * 60)
    print(f"报告: {report_path}")
    print(f"报告记录初始局部问题: {len(initial_issues)} 个")
    print(f"当前剩余局部问题: {len(current_issues)} 个")
    print(f"已解决局部问题: {len(initial_keys - current_keys)} 个")
    print(f"新增局部问题: {len(current_keys - initial_keys)} 个")
    if failed_results:
        print(f"主流程失败视频: {len(failed_results)} 个")
        for result in failed_results:
            print(f"  - {result.get('video_url', 'unknown')}: {result.get('error', 'unknown error')}")

    repair_script = write_repair_script(
        current_issues,
        report_path.parent,
        "recheck",
        check_report_file=report_path,
    )
    if current_issues:
        print_partial_issues(current_issues, repair_script)
    else:
        print("\n复查通过，没有剩余局部问题。")

    return {
        "success": True,
        "report_file": str(report_path),
        "initial_issue_count": len(initial_issues),
        "current_issue_count": len(current_issues),
        "resolved_count": len(initial_keys - current_keys),
        "new_issue_count": len(current_keys - initial_keys),
        "failed_count": len(failed_results),
        "repair_script": str(repair_script or ""),
        "issues": current_issues,
    }


def process_download_only(
    video_url: str,
    media_type: str = "video",
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    youtube_po_token: Optional[str] = None,
    batch_root: Optional[str] = None,
    download_subs: bool = False,
    subtitle_langs: Optional[List[str]] = None,
) -> dict:
    """Download online media and/or subtitles without transcription or LLM."""
    platform = detect_platform(video_url)
    print("\n" + "=" * 60)
    print("仅下载模式（不转写）")
    print(f"平台: {platform}")
    print(f"类型: {media_type}")
    print(f"字幕: {'是' if download_subs else '否'}")
    print(f"说明: {platform_download_hint(platform)}")
    print("=" * 60 + "\n")

    if platform == PLATFORM_LOCAL:
        return {
            "success": False,
            "error": "本地文件无需下载，请直接使用 --local",
            "video_url": video_url,
            "platform": platform,
        }

    try:
        result = download_media(
            video_url,
            media_type=media_type,
            cookies_from_browser=cookies_from_browser,
            cookies_file=cookies_file,
            youtube_po_token=youtube_po_token,
            batch_root=batch_root,
            download_subs=download_subs,
            subtitle_langs=subtitle_langs,
        )
    except Exception as e:
        logger.error(f"下载失败: {e}")
        hint = diagnose_ytdlp_error(e)
        if hint:
            print(f"诊断: {hint}")
        return {
            "success": False,
            "error": str(e),
            "hint": hint,
            "video_url": video_url,
            "platform": platform,
        }

    print(f"标题: {result.title}")
    if result.audio_path:
        print(f"音频: {result.audio_path}")
    if result.video_path:
        print(f"视频: {result.video_path}")
    if result.subtitle_paths:
        print(f"字幕: {len(result.subtitle_paths)} 个文件")
        for p in result.subtitle_paths[:8]:
            print(f"  - {p}")
        if len(result.subtitle_paths) > 8:
            print(f"  … 另有 {len(result.subtitle_paths) - 8} 个")
    elif download_subs:
        print("字幕: 未找到可用字幕文件")
    return {
        "success": True,
        "title": result.title,
        "video_url": video_url,
        "platform": platform,
        "audio_path": result.audio_path,
        "video_path": result.video_path,
        "subtitle_paths": result.subtitle_paths,
        "metadata": result.metadata,
    }


def process_batch(
    video_urls: List[str],
    model_size: str = "tiny",
    cpu_threads: int = 4,
    asr_engine: str = "funasr",
    funasr_model: str = "sensevoice",
    enable_llm_optimization: bool = True,
    prompt_names: Optional[List[str]] = None,
    skip_existing: bool = False,
    batch_root: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    youtube_po_token: Optional[str] = None,
    cover_mode: Optional[str] = None,
    enable_ai_cover: Optional[bool] = None,
    limit: Optional[int] = None,
    precomputed_plan: Optional[dict] = None,
    auto_repair: bool = False,
    repair_rounds: int = 2,
    repair_delay: int = 0,
    save_video: bool = False,
) -> List[dict]:
    """Process a list of videos."""
    if cover_mode is not None:
        cover_mode = normalize_cover_pipeline_mode(cover_mode)
    elif enable_ai_cover is not None:
        cover_mode = COVER_MODE_FULL if enable_ai_cover else COVER_MODE_OFF
    else:
        cover_mode = COVER_MODE_FULL
    original_video_urls = list(video_urls)
    original_count = len(video_urls)
    batch_output_dir = get_batch_output_dir(original_video_urls, batch_root)
    plan = precomputed_plan or plan_batch_urls(
        video_urls=video_urls,
        prompt_names=prompt_names,
        enable_llm_optimization=enable_llm_optimization,
        skip_existing=skip_existing,
        batch_root=batch_root,
        limit=limit,
        cookies_from_browser=cookies_from_browser,
        cookies_file=cookies_file,
        youtube_po_token=youtube_po_token,
    )
    video_urls = plan["planned_urls"]
    skipped_before_run = plan["skipped_before_run"]
    total_pending_count = plan["pending_before_limit"]
    status_counts = plan.get("status_counts", {})

    print("\n" + "=" * 60)
    print(f"批量处理模式 - 本次计划处理 {len(video_urls)} 个视频")
    print("=" * 60)
    print(f"清单条目: {original_count}")
    if skip_existing:
        print(f"output 完整: {status_counts.get('complete', 0)}")
        print(f"报告记录完成: {status_counts.get('report_complete', 0)}")
        print(f"已完成合计: {len(skipped_before_run)}")
        print(f"待补文章: {status_counts.get('raw_only', 0)}")
        print(f"文章待重整: {status_counts.get('article_invalid', 0)}")
        print(f"未处理: {status_counts.get('unprocessed', 0)}")
        if status_counts.get("unknown_title", 0):
            print(f"待确认标题: {status_counts.get('unknown_title', 0)}")
        print(f"本次运行前待处理: {total_pending_count}")
        print(f"本次计划处理: {len(video_urls)}")
        if limit and total_pending_count > len(video_urls):
            print(f"本轮后预计剩余: {total_pending_count - len(video_urls)}")

    results = []
    for i, url in enumerate(video_urls, 1):
        print(f"\n{'=' * 60}")
        print(f"处理第 {i}/{len(video_urls)} 个视频")
        print(f"{'=' * 60}")

        try:
            result = process_video(
                video_url=url,
                model_size=model_size,
                cpu_threads=cpu_threads,
                asr_engine=asr_engine,
                funasr_model=funasr_model,
                enable_llm_optimization=enable_llm_optimization,
                prompt_names=prompt_names,
                skip_existing=skip_existing,
                batch_root=batch_root,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
                youtube_po_token=youtube_po_token,
                cover_mode=cover_mode,
                print_remedies=False,
                save_video=save_video,
            )
            results.append(result)
        except Exception as e:
            logger.error(f"处理视频失败: {url}, 错误: {e}")
            results.append({"success": False, "video_url": url, "error": str(e)})

    print("\n" + "=" * 60)
    print("批量处理完成！")
    print("=" * 60)

    success_count = sum(1 for r in results if r.get("success", False))
    fail_count = len(results) - success_count
    skipped_count = sum(1 for r in results if r.get("skipped", False))
    processed_count = success_count - skipped_count
    remaining_count = max(total_pending_count - processed_count, 0) if skip_existing else 0
    try:
        health_config = load_config()
    except Exception as e:
        logger.warning(f"批量健康检查读取配置失败，将跳过配置相关检查: {e}")
        health_config = {}
    partial_issues = collect_batch_health_issues(
        results=results,
        config=health_config,
        cover_mode=cover_mode,
        enable_llm_optimization=enable_llm_optimization,
        prompt_names=prompt_names,
    )

    print(f"\n新处理成功: {processed_count} 个")
    if skip_existing:
        print(f"本次运行前已完成: {len(skipped_before_run)} 个")
        if status_counts.get("report_complete", 0):
            print(f"其中报告记录完成: {status_counts.get('report_complete', 0)} 个")
        print(f"剩余待处理: {remaining_count} 个")
    else:
        print(f"已跳过: {skipped_count} 个")
    print(f"失败: {fail_count} 个")
    initial_partial_issues = list(partial_issues)
    print(f"局部问题: {len(partial_issues)} 个")

    if fail_count > 0:
        print("\n失败的视频:")
        for r in results:
            if not r.get("success", False):
                print(f"  - {r.get('video_url', 'unknown')}: {r.get('error', 'unknown error')}")

    report_dir = batch_output_dir / "_batch_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_file = report_dir / f"batch_report_{time.strftime('%Y%m%d-%H%M%S')}.json"
    initial_repair_script = write_repair_script(
        partial_issues,
        report_dir,
        "initial",
        check_report_file=report_file,
    )
    print_partial_issues(partial_issues, initial_repair_script)

    repair_summary = None
    final_repair_script = None
    if auto_repair and partial_issues:
        partial_issues, repair_summary = run_auto_repair(
            partial_issues=partial_issues,
            results=results,
            config=health_config,
            cover_mode=cover_mode,
            enable_llm_optimization=enable_llm_optimization,
            prompt_names=prompt_names,
            max_rounds=repair_rounds,
            repair_delay=repair_delay,
        )
        final_repair_script = write_repair_script(
            partial_issues,
            report_dir,
            "final",
            check_report_file=report_file,
        )
        if partial_issues:
            print("\n自动补救后仍有局部问题:")
            print_partial_issues(partial_issues, final_repair_script)
        else:
            print("\n自动补救后没有剩余局部问题。")
    elif auto_repair:
        repair_summary = {
            "enabled": True,
            "max_rounds": repair_rounds,
            "initial_issue_count": 0,
            "rounds": [],
            "resolved_count": 0,
            "new_issue_count": 0,
            "final_issue_count": 0,
        }

    report_payload = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "batch_root": batch_root,
        "settings": {
            "cover_mode": cover_mode,
            "enable_ai_cover": cover_mode_generates_image(cover_mode),
            "enable_llm_optimization": enable_llm_optimization,
            "prompt_names": prompt_names or [],
            "asr_engine": asr_engine,
            "funasr_model": funasr_model,
            "model_size": model_size,
            "cpu_threads": cpu_threads,
            "skip_existing": skip_existing,
            "limit": limit,
        },
        "input_count": original_count,
        "already_completed_before_run": len(skipped_before_run),
        "pending_before_limit": total_pending_count,
        "planned_count": len(video_urls),
        "status_counts_before_run": status_counts,
        "planned_items": plan.get("planned_items", []),
        "pending_statuses_before_run": plan.get("pending_statuses", []),
        "processed_success": processed_count,
        "failed": fail_count,
        "initial_partial_issue_count": len(initial_partial_issues),
        "initial_partial_issues": initial_partial_issues,
        "partial_issue_count": len(partial_issues),
        "partial_issues": partial_issues,
        "repair_script": str(final_repair_script or initial_repair_script or ""),
        "initial_repair_script": str(initial_repair_script or ""),
        "final_repair_script": str(final_repair_script or ""),
        "auto_repair": repair_summary,
        "remaining_after_run": remaining_count,
        "results": results,
    }
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report_payload, f, ensure_ascii=False, indent=2)

    print(f"\n详细报告已保存: {report_file}")
    return results


def plan_batch_urls(
    video_urls: List[str],
    prompt_names: Optional[List[str]],
    enable_llm_optimization: bool,
    skip_existing: bool,
    batch_root: Optional[str],
    limit: Optional[int] = None,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    youtube_po_token: Optional[str] = None,
) -> dict:
    """Return the concrete URLs to process after skip-existing and limit planning."""
    skipped_before_run: list[dict] = []
    pending_items: list[dict] = []
    pending_statuses: list[dict] = []
    status_counts = {
        "complete": 0,
        "report_complete": 0,
        "raw_only": 0,
        "article_invalid": 0,
        "unprocessed": 0,
        "unknown_title": 0,
        "planned": 0,
    }
    report_completions = load_batch_report_completions(video_urls, batch_root) if skip_existing else {}

    if skip_existing:
        for url in video_urls:
            platform = detect_platform(url)
            title = Path(url).stem if platform == "Local" else None
            status_batch_root = batch_root
            if platform == "YouTube":
                try:
                    youtube_info = get_youtube_info(
                        url,
                        download=False,
                        cookies_from_browser=cookies_from_browser,
                        cookies_file=cookies_file,
                        youtube_po_token=youtube_po_token,
                    )
                    title = youtube_info.get("title")
                    status_batch_root = batch_root or make_youtube_batch_root_from_metadata(youtube_info)
                except Exception:
                    title = None

            if title:
                status = get_video_output_status(
                    title,
                    url,
                    prompt_names,
                    enable_llm_optimization,
                    status_batch_root,
                )
                if status.get("status") == "raw_only":
                    report_completion = report_completions.get(normalize_report_key(url)) or report_completions.get(
                        normalize_report_key(title)
                    )
                    if report_completion:
                        status = {
                            **status,
                            **report_completion,
                            "output_dir": status.get("output_dir", ""),
                            "raw_file": status.get("raw_file") or report_completion.get("raw_file", ""),
                            "source": url,
                            "title": title,
                        }
                item = {
                    **status,
                    "success": status.get("complete", False),
                    "skipped": status.get("complete", False),
                    "video_url": url,
                    "title": title,
                    "platform": platform,
                    "batch_root": status_batch_root,
                }
            else:
                item = {
                    "status": "unknown_title",
                    "complete": False,
                    "success": False,
                    "skipped": False,
                    "video_url": url,
                    "title": "",
                    "platform": platform,
                    "batch_root": status_batch_root,
                    "message": "无法预取标题，按未处理条目执行",
                }

            status_name = str(item.get("status") or "unprocessed")
            status_counts[status_name] = status_counts.get(status_name, 0) + 1
            if item.get("complete"):
                skipped_before_run.append(item)
            else:
                pending_statuses.append(item)
                pending_items.append(item)
    else:
        pending_items = [
            {"video_url": url, "status": "planned", "complete": False}
            for url in video_urls
        ]
        status_counts["planned"] = len(pending_items)

    pending_items.sort(
        key=lambda item: {
            "raw_only": 0,
            "article_invalid": 1,
            "unknown_title": 2,
            "unprocessed": 3,
            "planned": 4,
            "report_complete": 9,
        }.get(str(item.get("status")), 9)
    )

    pending_before_limit = len(pending_items)
    planned_items = pending_items[:limit] if limit and limit > 0 else pending_items
    planned_urls = [item["video_url"] for item in planned_items]
    return {
        "planned_urls": planned_urls,
        "planned_items": planned_items,
        "skipped_before_run": skipped_before_run,
        "pending_statuses": pending_statuses,
        "status_counts": status_counts,
        "pending_before_limit": pending_before_limit,
        "remaining_after_plan": max(pending_before_limit - len(planned_urls), 0),
    }
