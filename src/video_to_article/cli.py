import argparse
from pathlib import Path
from typing import Optional

from .batch import default_prompt_names, find_local_videos, print_output_preview, read_batch_file, write_batch_file
from .config import load_config
from .cover import COVER_MODE_OFF, resolve_cover_pipeline_mode
from .data_paths import batch_list_path
from .logging_config import configure_logging, ensure_utf8_stdio
from .media.ffmpeg_tools import ensure_ffmpeg_on_path
from .paths import LOCAL_MEDIA_EXTENSIONS, ensure_runtime_dirs
from .platforms import is_youtube_collection_url
from .processor import (
    check_batch_report,
    make_regen_cover_command,
    plan_batch_urls,
    process_batch,
    process_download_only,
    process_raw_file,
    process_regen_cover,
    process_video,
    powershell_quote,
)
from .prompts import list_available_prompts
from .providers.bilibili import format_duration, format_play_count, search_bilibili_videos
from .providers.youtube import get_youtube_collection_urls, make_youtube_batch_root
from .providers.youtube_auth import (
    check_youtube_auth,
    inspect_cookie_file,
    refresh_cookie_file_from_browser,
    resolve_youtube_auth,
)


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser."""
    parser = argparse.ArgumentParser(
        description="视频转写工具 - 支持多平台、多提示词、音频/视频下载和批量处理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python transcribe.py
  python transcribe.py --url "https://www.bilibili.com/video/BV1xxx"
  python transcribe.py --url "https://..." --prompts evaluation,summary
  python transcribe.py --url "https://..." --save-video
  python transcribe.py --download-only --url "https://www.bilibili.com/video/BV1xxx"
  python transcribe.py --download-only --media-type both --url "https://v.douyin.com/xxx"
  python transcribe.py --batch urls.txt
  python transcribe.py --local-dir "G:\\美食\\小吃教程" --prompts snack_recipe --limit 3
  python transcribe.py --search "家常菜教程"
  python transcribe.py --search "家常菜教程" --search-count 10
  python transcribe.py --list-prompts

支持平台: Bilibili / YouTube / 抖音 / 小红书 / 微博（快手可识别，下载视 yt-dlp 能力）
默认仍只下载音频用于转写；加 --save-video 可额外保留视频；--download-only 仅下载不转写。
        """,
    )

    parser.add_argument("--url", type=str, help="视频链接（B站/YouTube/抖音/小红书/微博等）")
    parser.add_argument("--local", type=str, help="本地音频/视频文件路径")
    parser.add_argument("--from-raw", type=str, help="从已生成的 raw.md 重新生成优化文章，不重新转写音视频")
    parser.add_argument("--regen-cover", type=str, help="为已有文章重新生成 AI 封面，上传图床并回写 cover")
    parser.add_argument("--thumbnail", type=str, help="配合 --regen-cover 使用的本地参考图路径")
    parser.add_argument("--check-report", type=str, help="复查批量报告中的输出状态，并生成新的补救脚本")
    parser.add_argument("--batch", type=str, help="批量处理文件（每行一个 URL）")
    parser.add_argument("--youtube-collection", type=str, help="YouTube 频道、播放列表或频道 videos 页面，自动展开为视频链接")
    parser.add_argument("--youtube-limit", type=int, help="限制 YouTube 频道/播放列表展开的视频数量")
    parser.add_argument("--cookies-from-browser", type=str, help="让 yt-dlp 从浏览器读取 cookies，如 chrome、edge、firefox")
    parser.add_argument("--cookies", type=str, help="cookies 文件路径，支持 Netscape cookies.txt 或浏览器 Cookie 头文本")
    parser.add_argument("--youtube-po-token", type=str, help="YouTube 字幕 PO Token，例如 web.subs+XXX")
    parser.add_argument("--check-youtube-auth", action="store_true", help="检查 YouTube cookies/登录态，不处理视频")
    parser.add_argument("--refresh-youtube-cookies", type=str, help="从浏览器导出 cookies 到 data\\cookies\\youtube.txt，如 chrome、edge、firefox")
    parser.add_argument("--local-dir", type=str, help="本地音频/视频目录路径，默认递归扫描常见媒体格式")
    parser.add_argument("--no-recursive", action="store_true", help="配合 --local-dir 使用，只扫描当前目录")
    parser.add_argument("--limit", type=int, help="限制批量处理数量，适合先小批量试跑")
    parser.add_argument("--dry-run", action="store_true", help="只预览批量输入，不执行转写")
    parser.add_argument(
        "--write-list",
        nargs="?",
        const="auto",
        help="把批量链接写入清单文件；不写路径或填 auto 时自动保存到 data/local 或 data/youtube 对应批次目录",
    )
    parser.add_argument("--batch-root", type=str, help="配合 --batch 使用，指定用于保留输出层级的批次根目录")
    parser.add_argument("--skip-existing", action="store_true", help="批量处理时跳过已经生成完整输出的本地视频")
    parser.add_argument("--auto-repair", action="store_true", help="批量结束后自动有限补救局部问题，如补文章、补封面")
    parser.add_argument("--repair-rounds", type=int, default=2, help="配合 --auto-repair 使用，最多自动补救轮数，默认 2")
    parser.add_argument("--repair-delay", type=int, default=0, help="配合 --auto-repair 使用，每个补救动作之间等待秒数，默认 0")
    parser.add_argument("--search", type=str, help="B站搜索关键词")
    parser.add_argument("--search-count", type=int, default=5, help="搜索结果数量（默认5）")
    parser.add_argument(
        "--search-order",
        type=str,
        default="totalrank",
        choices=["totalrank", "pubdate", "click", "dm"],
        help="搜索排序方式：totalrank=综合排序, pubdate=最新发布, click=最多播放, dm=最多弹幕",
    )
    parser.add_argument(
        "--save-video",
        action="store_true",
        help="转写时额外下载并保留视频文件（默认只下载音频用于 ASR）",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="仅下载媒体，不转写、不调用大模型；配合 --url 或 --batch",
    )
    parser.add_argument(
        "--media-type",
        type=str,
        default=None,
        choices=["audio", "video", "both", "none"],
        help="下载媒体类型：audio=仅音频, video=仅视频, both=两者, none=不下载音视频（需配合 --download-subs）；"
        "默认：--download-only 时为 video，转写流程为 audio（可用 --save-video 变为 both）",
    )
    parser.add_argument(
        "--download-subs",
        action="store_true",
        help="下载字幕文件（srt/vtt 等）；可与 --download-only 的 media-type 组合，"
        "或 --download-only --download-subs --media-type none 仅下字幕",
    )
    parser.add_argument(
        "--subs-lang",
        type=str,
        default=None,
        help="字幕语言代码，逗号分隔（如 zh,zh-Hans,en）；默认优先中英常见语言",
    )
    parser.add_argument("--prompts", type=str, help="提示词名称，多个用逗号分隔（如: evaluation,summary）")
    parser.add_argument("--no-llm", action="store_true", help="禁用大模型优化")
    parser.add_argument(
        "--no-cover",
        action="store_true",
        help="不调用生图 API / 图床；仍导出 cover-prompt.txt 与 cover-ai.json，便于手动网页生图",
    )
    parser.add_argument(
        "--no-cover-assets",
        action="store_true",
        help="完全跳过封面相关产物（不写提示词、不写元数据、不生图）",
    )
    parser.add_argument("--model-size", type=str, default="tiny", choices=["tiny", "base", "small"], help="Whisper 模型大小")
    parser.add_argument("--cpu-threads", type=int, default=4, help="CPU 线程数")
    parser.add_argument("--asr-engine", type=str, default="funasr", choices=["funasr", "whisper"], help="语音转文字引擎，默认 FunASR")
    parser.add_argument(
        "--funasr-model",
        type=str,
        default="sensevoice",
        help="FunASR 模型: sensevoice、paraformer，或完整 ModelScope 模型名",
    )
    parser.add_argument("--list-prompts", action="store_true", help="列出所有可用的提示词")
    return parser


def parse_prompt_names(prompts_arg: Optional[str]) -> Optional[list[str]]:
    """Parse and validate prompt names from CLI."""
    if not prompts_arg:
        return None

    prompt_names = [p.strip() for p in prompts_arg.split(",")]
    available = list_available_prompts()
    for prompt in prompt_names:
        if prompt not in available:
            print(f"错误: 提示词 '{prompt}' 不存在")
            print(f"可用的提示词: {', '.join(available)}")
            return []
    return prompt_names


def resolve_args_cover_mode(args) -> str:
    """CLI cover flags win over config.youtube/ai_cover defaults."""
    if getattr(args, "no_cover_assets", False) and getattr(args, "no_cover", False):
        print("提示: 同时指定了 --no-cover 与 --no-cover-assets，以 --no-cover-assets 为准（完全跳过封面）")
    try:
        config = load_config()
    except Exception:
        config = {}
    return resolve_cover_pipeline_mode(
        no_cover=bool(getattr(args, "no_cover", False)),
        no_cover_assets=bool(getattr(args, "no_cover_assets", False)),
        config=config,
    )


def main() -> None:
    """CLI entrypoint."""
    ensure_utf8_stdio()
    configure_logging()
    ensure_runtime_dirs()
    ensure_ffmpeg_on_path()
    parser = build_parser()
    args = parser.parse_args()

    if args.list_prompts:
        from .prompts import list_article_prompts, list_system_prompts

        print("\n成稿提示词 (prompts/articles):")
        for prompt in list_article_prompts():
            print(f"  - {prompt}")
        print("\n系统/基础提示词 (prompts/system，GUI 默认不展示):")
        for prompt in list_system_prompts():
            print(f"  - {prompt}")
        extras = sorted(set(list_available_prompts()) - set(list_article_prompts()) - set(list_system_prompts()))
        if extras:
            print("\n其它 (兼容):")
            for prompt in extras:
                print(f"  - {prompt}")
        return

    prompt_names = parse_prompt_names(args.prompts)
    if prompt_names == []:
        return

    if args.check_youtube_auth:
        handle_youtube_auth_check(args)
        return

    if args.refresh_youtube_cookies:
        handle_youtube_cookie_refresh(args)
        return

    if args.check_report:
        check_batch_report(args.check_report)
        return

    if args.search:
        handle_bilibili_search(args, prompt_names)
        return

    if args.from_raw:
        handle_from_raw(args, prompt_names)
        return

    if args.regen_cover:
        handle_regen_cover(args)
        return

    if args.download_only:
        handle_download_only(args)
        return

    youtube_collection_url = args.youtube_collection
    if not youtube_collection_url and args.url and is_youtube_collection_url(args.url):
        youtube_collection_url = args.url
    if youtube_collection_url:
        handle_youtube_collection(args, prompt_names, youtube_collection_url)
        return

    if args.local_dir:
        handle_local_dir(args, prompt_names)
        return

    if args.batch:
        handle_batch(args, prompt_names)
        return

    handle_single(args, prompt_names)


def resolve_save_video(args) -> bool:
    """Whether the transcription pipeline should also keep video files."""
    if getattr(args, "save_video", False):
        return True
    return getattr(args, "media_type", None) in {"video", "both"}


def resolve_download_media_type(args) -> str:
    """Media type for --download-only mode."""
    if args.media_type:
        return args.media_type
    # Subtitle-only: default to none when user only asked for subs
    if getattr(args, "download_subs", False) and not getattr(args, "save_video", False):
        # Keep historical default video unless only-subs intent is clear:
        # --download-only --download-subs without --media-type still defaults to video+subs
        # Use --media-type none for subs-only.
        pass
    if args.save_video:
        return "both"
    return "video"


def parse_subs_langs(subs_lang: Optional[str]) -> Optional[list[str]]:
    if not subs_lang or not str(subs_lang).strip():
        return None
    langs = [p.strip() for p in str(subs_lang).split(",") if p.strip()]
    return langs or None


def handle_download_only(args) -> None:
    """Download media and/or subtitles without ASR/LLM."""
    media_type = resolve_download_media_type(args)
    download_subs = bool(getattr(args, "download_subs", False))
    subtitle_langs = parse_subs_langs(getattr(args, "subs_lang", None))

    if media_type == "none" and not download_subs:
        print("错误: --media-type none 需要同时指定 --download-subs")
        return

    if args.batch:
        batch_file = Path(args.batch)
        if not batch_file.exists():
            print(f"错误: 批量处理文件不存在: {batch_file}")
            return
        urls, batch_root = read_batch_file(batch_file)
        if args.batch_root:
            batch_root = args.batch_root
        if not urls:
            print("错误: 批量处理文件为空")
            return
        if args.limit:
            urls = urls[: max(1, int(args.limit))]
        print(
            f"\n仅下载模式 - 共 {len(urls)} 个链接，类型={media_type}"
            f"，字幕={'是' if download_subs else '否'}"
        )
        ok = 0
        for i, url in enumerate(urls, 1):
            print(f"\n[{i}/{len(urls)}] {url}")
            result = process_download_only(
                video_url=url,
                media_type=media_type,
                cookies_from_browser=args.cookies_from_browser,
                cookies_file=args.cookies,
                youtube_po_token=args.youtube_po_token,
                batch_root=batch_root,
                download_subs=download_subs,
                subtitle_langs=subtitle_langs,
            )
            if result.get("success"):
                ok += 1
            else:
                print(f"失败: {result.get('error')}")
        print(f"\n下载完成: 成功 {ok}/{len(urls)}")
        return

    video_url = args.url or args.local
    if not video_url:
        print("错误: --download-only 需要配合 --url 或 --batch")
        return

    result = process_download_only(
        video_url=video_url,
        media_type=media_type,
        cookies_from_browser=args.cookies_from_browser,
        cookies_file=args.cookies,
        youtube_po_token=args.youtube_po_token,
        batch_root=args.batch_root,
        download_subs=download_subs,
        subtitle_langs=subtitle_langs,
    )
    if not result.get("success"):
        print(f"错误: {result.get('error')}")


def handle_bilibili_search(args, prompt_names: Optional[list[str]]) -> None:
    """Handle Bilibili search mode."""
    print(f"\n搜索B站视频: {args.search}")
    print(f"   数量: {args.search_count}")
    print(f"   排序: {args.search_order}")

    videos = search_bilibili_videos(keyword=args.search, count=args.search_count, order=args.search_order)
    if not videos:
        print("错误: 搜索无结果或搜索失败")
        return

    print(f"\n找到 {len(videos)} 个视频:")
    for i, video in enumerate(videos, 1):
        print(f"  {i}. {video['title']}")
        print(
            f"     时长: {format_duration(video['duration'])}, "
            f"播放: {format_play_count(video['play'])}, "
            f"UP主: {video['author']}"
        )

    urls = [video["url"] for video in videos]
    if prompt_names is None:
        prompt_names = list_available_prompts()
        if prompt_names:
            print(f"\n未指定提示词，将使用所有可用的提示词: {', '.join(prompt_names)}")
        else:
            print("\n警告: 未找到可用的提示词，将只进行原始转写")

    print("\n开始批量转录...")
    process_batch(
        video_urls=urls,
        model_size=args.model_size,
        cpu_threads=args.cpu_threads,
        asr_engine=args.asr_engine,
        funasr_model=args.funasr_model,
        enable_llm_optimization=not args.no_llm,
        prompt_names=prompt_names,
        skip_existing=args.skip_existing,
        batch_root=None,
        cookies_from_browser=args.cookies_from_browser,
        cookies_file=args.cookies,
        youtube_po_token=args.youtube_po_token,
        cover_mode=resolve_args_cover_mode(args),
        auto_repair=args.auto_repair,
        repair_rounds=args.repair_rounds,
        repair_delay=args.repair_delay,
        save_video=resolve_save_video(args),
    )


def handle_from_raw(args, prompt_names: Optional[list[str]]) -> None:
    """Handle regenerating optimized article files from a raw.md file."""
    if args.no_llm:
        print("错误: --from-raw 需要启用大模型整理，不能同时使用 --no-llm")
        return
    process_raw_file(
        raw_file=args.from_raw,
        prompt_names=prompt_names or ["snack_recipe"],
        cover_mode=resolve_args_cover_mode(args),
    )


def handle_regen_cover(args) -> None:
    """Handle cover-only regeneration for an existing article."""
    if getattr(args, "no_cover_assets", False):
        print("错误: --regen-cover 不能同时使用 --no-cover-assets")
        return
    cover_mode = resolve_args_cover_mode(args)
    if cover_mode == COVER_MODE_OFF:
        print("错误: 当前封面模式为关闭，无法补封面")
        return
    result = process_regen_cover(args.regen_cover, args.thumbnail, cover_mode=cover_mode)
    if not result.get("success"):
        print(f"错误: {result.get('error')}")
        print("\n可复制下面命令重新补封面:")
        print('Set-Location "F:\\GitHub\\我的项目\\video-quick-eval"')
        print(".\\.venv\\Scripts\\Activate.ps1")
        command = make_regen_cover_command(Path(args.regen_cover))
        if args.thumbnail:
            command += f" --thumbnail {powershell_quote(args.thumbnail)}"
        print(command)


def handle_youtube_auth_check(args) -> None:
    """Check YouTube cookie/login state without processing a video."""
    auth = resolve_youtube_auth(
        cookies_from_browser=args.cookies_from_browser,
        cookies_file=args.cookies,
        youtube_po_token=args.youtube_po_token,
    )

    print("\nYouTube 登录态检查")
    print("=" * 60)
    print(f"认证来源: {auth.source}")
    if auth.cookies_file:
        print(f"cookies 文件: {auth.cookies_file}")
        cookie_status = inspect_cookie_file(auth.cookies_file)
        print(f"cookies 格式: {cookie_status.get('format')}")
        print(f"cookies 数量: {cookie_status.get('cookie_count')}")
        print(f"本地检查: {'通过' if cookie_status.get('ok') else '异常'}")
        print(f"说明: {cookie_status.get('message')}")
        important_present = cookie_status.get("important_present") or []
        if important_present:
            print(f"关键登录态: {', '.join(important_present)}")
        expired = cookie_status.get("expired_important") or []
        if expired:
            print(f"已过期关键项: {', '.join(expired)}")
        for warning in cookie_status.get("warnings") or []:
            print(f"提醒: {warning}")
    elif auth.cookies_from_browser:
        print(f"浏览器 cookies: {auth.cookies_from_browser}")
        print("本地检查: 跳过，浏览器 cookies 需要由 yt-dlp 读取后才能判断")
    else:
        print("cookies: 未配置")
        print("建议: 将导出的 Netscape cookies.txt 保存为 data\\cookies\\youtube.txt")

    print(f"PO Token: {'已配置' if auth.youtube_po_token else '未配置'}")

    if not args.url:
        print("\n未提供 --url，只完成本地 cookies 文件检查。")
        print("如需测试 YouTube 是否接受登录态，请加：--url \"https://www.youtube.com/watch?v=VIDEO_ID\"")
        return

    print("\n正在请求 YouTube 元数据...")
    result = check_youtube_auth(
        args.url,
        cookies_from_browser=args.cookies_from_browser,
        cookies_file=args.cookies,
        youtube_po_token=args.youtube_po_token,
    )
    if result.get("success"):
        print(f"YouTube 请求: {'通过' if result.get('usable') else '异常'}")
        print(f"视频标题: {result.get('title')}")
        print(f"可用格式数量: {result.get('format_count')}")
        subtitles = result.get("subtitles") or []
        auto_subtitles = result.get("automatic_captions") or []
        print(f"人工字幕语言: {', '.join(subtitles) if subtitles else '无'}")
        print(f"自动字幕语言: {', '.join(auto_subtitles) if auto_subtitles else '无'}")
        if result.get("hint"):
            print(f"诊断: {result.get('hint')}")
        elif not subtitles and not auto_subtitles:
            print("提醒: 登录态可用不代表一定能提取字幕；没有字幕时程序会回退到 ASR，当前默认使用 FunASR。")
    else:
        print("YouTube 请求: 失败")
        print(f"错误: {result.get('error')}")
        if result.get("hint"):
            print(f"诊断: {result.get('hint')}")


def handle_youtube_cookie_refresh(args) -> None:
    """Export browser cookies into the default project cookie file."""
    print("\n刷新 YouTube cookies 文件")
    print("=" * 60)
    result = refresh_cookie_file_from_browser(args.refresh_youtube_cookies, args.cookies)
    print(f"浏览器: {result.get('browser')}")
    print(f"输出文件: {result.get('output_file')}")
    if result.get("success"):
        print("刷新结果: 成功")
        status = result.get("cookie_status") or {}
        print(f"cookies 数量: {status.get('cookie_count')}")
        important_present = status.get("important_present") or []
        if important_present:
            print(f"关键登录态: {', '.join(important_present)}")
    else:
        print("刷新结果: 失败")
        print(f"错误: {result.get('error') or 'cookies 文件检查未通过'}")
        if result.get("hint"):
            print(f"诊断: {result.get('hint')}")
    for warning in result.get("warnings") or []:
        print(f"提醒: {warning}")


def resolve_batch_prompt_names(prompt_names: Optional[list[str]], use_all_available: bool = False) -> list[str]:
    """Resolve the prompt list used for batch planning and processing."""
    if prompt_names is not None:
        return prompt_names
    return list_available_prompts() if use_all_available else default_prompt_names()


def print_batch_plan_summary(input_count: int, plan: dict, skip_existing: bool) -> None:
    """Print the concrete batch plan after skip-existing and limit planning."""
    planned_count = len(plan["planned_urls"])
    status_counts = plan.get("status_counts", {})
    print("\n本次批量计划:")
    print(f"  清单条目: {input_count}")
    if skip_existing:
        print(f"  output 完整: {status_counts.get('complete', 0)}")
        print(f"  报告记录完成: {status_counts.get('report_complete', 0)}")
        print(f"  已完成合计: {len(plan['skipped_before_run'])}")
        print(f"  待补文章: {status_counts.get('raw_only', 0)}")
        print(f"  文章待重整: {status_counts.get('article_invalid', 0)}")
        print(f"  未处理: {status_counts.get('unprocessed', 0)}")
        if status_counts.get("unknown_title", 0):
            print(f"  待确认标题: {status_counts.get('unknown_title', 0)}")
        print(f"  本次运行前待处理: {plan['pending_before_limit']}")
    print(f"  本次计划处理: {planned_count}")
    if plan["remaining_after_plan"]:
        print(f"  本轮后预计剩余: {plan['remaining_after_plan']}")


def build_batch_plan(args, items: list[str], batch_root: Optional[str], prompt_names: list[str]) -> dict:
    """Build the same plan used by real batch processing."""
    return plan_batch_urls(
        video_urls=items,
        prompt_names=prompt_names,
        enable_llm_optimization=not args.no_llm,
        skip_existing=args.skip_existing,
        batch_root=batch_root,
        limit=args.limit,
        cookies_from_browser=args.cookies_from_browser,
        cookies_file=args.cookies,
        youtube_po_token=args.youtube_po_token,
    )


def handle_youtube_collection(args, prompt_names: Optional[list[str]], collection_url: str) -> None:
    """Handle YouTube channel/playlist expansion."""
    collection_limit = args.youtube_limit
    if collection_limit is None and args.limit and not args.skip_existing:
        collection_limit = args.limit

    try:
        urls = get_youtube_collection_urls(
            collection_url,
            limit=collection_limit,
            cookies_from_browser=args.cookies_from_browser,
            cookies_file=args.cookies,
            youtube_po_token=args.youtube_po_token,
        )
    except Exception as e:
        print(f"错误: YouTube 频道/播放列表展开失败: {e}")
        return

    if not urls:
        print(f"错误: 未找到 YouTube 视频: {collection_url}")
        return

    batch_root = make_youtube_batch_root(
        collection_url,
        cookies_from_browser=args.cookies_from_browser,
        cookies_file=args.cookies,
        youtube_po_token=args.youtube_po_token,
    )
    print(f"\nYouTube 批量链接展开完成: {collection_url}")
    print(f"批次根目录: {batch_root}")
    print(f"待处理视频: {len(urls)} 个")

    active_prompt_names = resolve_batch_prompt_names(prompt_names)
    if prompt_names is None:
        if active_prompt_names:
            print(f"\n未指定提示词，将使用: {', '.join(active_prompt_names)}")
        else:
            print("\n警告: 未找到可用的提示词，将只进行原始转写")

    plan = build_batch_plan(args, urls, batch_root, active_prompt_names)
    print_batch_plan_summary(len(urls), plan, args.skip_existing)
    print_items(plan["planned_urls"])
    print_output_preview(plan["planned_urls"], batch_root, active_prompt_names, not args.no_llm)

    if args.write_list is not None:
        list_path = batch_list_path("youtube", batch_root=batch_root, explicit_path=args.write_list)
        write_batch_file(list_path, urls, batch_root)
        print(f"\nYouTube 视频清单已写入: {list_path}")

    if args.dry_run:
        print("\n--dry-run 已启用，仅预览，不执行转写。")
        return

    process_batch(
        video_urls=urls,
        model_size=args.model_size,
        cpu_threads=args.cpu_threads,
        asr_engine=args.asr_engine,
        funasr_model=args.funasr_model,
        enable_llm_optimization=not args.no_llm,
        prompt_names=active_prompt_names,
        skip_existing=args.skip_existing,
        batch_root=batch_root,
        cookies_from_browser=args.cookies_from_browser,
        cookies_file=args.cookies,
        youtube_po_token=args.youtube_po_token,
        cover_mode=resolve_args_cover_mode(args),
        limit=args.limit,
        precomputed_plan=plan,
        auto_repair=args.auto_repair,
        repair_rounds=args.repair_rounds,
        repair_delay=args.repair_delay,
        save_video=resolve_save_video(args),
    )


def handle_local_dir(args, prompt_names: Optional[list[str]]) -> None:
    """Handle local directory batch mode."""
    batch_root = str(Path(args.local_dir))
    try:
        videos = find_local_videos(directory=batch_root, recursive=not args.no_recursive)
    except Exception as e:
        print(f"错误: 扫描本地视频目录失败: {e}")
        return

    if not videos:
        print(f"错误: 未在目录中找到支持的音频/视频文件: {args.local_dir}")
        print(f"支持格式: {', '.join(sorted(LOCAL_MEDIA_EXTENSIONS))}")
        return

    print(f"\n本地目录扫描完成: {args.local_dir}")
    print(f"   扫描方式: {'递归' if not args.no_recursive else '仅当前目录'}")
    print(f"   待处理视频: {len(videos)} 个")
    if args.limit:
        print(f"   本次处理阶段将按 --limit 计划处理 {args.limit} 个未完成视频")

    active_prompt_names = resolve_batch_prompt_names(prompt_names)
    if prompt_names is None:
        if active_prompt_names:
            print(f"\n未指定提示词，将使用: {', '.join(active_prompt_names)}")
        else:
            print("\n警告: 未找到可用的提示词，将只进行原始转写")

    plan = build_batch_plan(args, videos, batch_root, active_prompt_names)
    print_batch_plan_summary(len(videos), plan, args.skip_existing)
    print_items(plan["planned_urls"])
    print_output_preview(plan["planned_urls"], batch_root, active_prompt_names, not args.no_llm)

    if args.write_list is not None:
        list_path = batch_list_path("local", batch_root=batch_root, explicit_path=args.write_list)
        write_batch_file(list_path, videos, batch_root)
        print(f"\n视频清单已写入: {list_path}")

    if args.dry_run:
        print("\n--dry-run 已启用，仅预览，不执行转写。")
        return

    process_batch(
        video_urls=videos,
        model_size=args.model_size,
        cpu_threads=args.cpu_threads,
        asr_engine=args.asr_engine,
        funasr_model=args.funasr_model,
        enable_llm_optimization=not args.no_llm,
        prompt_names=active_prompt_names,
        skip_existing=args.skip_existing,
        batch_root=batch_root,
        cookies_from_browser=args.cookies_from_browser,
        cookies_file=args.cookies,
        youtube_po_token=args.youtube_po_token,
        cover_mode=resolve_args_cover_mode(args),
        limit=args.limit,
        precomputed_plan=plan,
        auto_repair=args.auto_repair,
        repair_rounds=args.repair_rounds,
        repair_delay=args.repair_delay,
        save_video=resolve_save_video(args),
    )


def handle_batch(args, prompt_names: Optional[list[str]]) -> None:
    """Handle batch file mode."""
    batch_file = Path(args.batch)
    if not batch_file.exists():
        print(f"错误: 批量处理文件不存在: {batch_file}")
        return

    urls, batch_root = read_batch_file(batch_file)
    if args.batch_root:
        batch_root = args.batch_root
    if not urls:
        print("错误: 批量处理文件为空")
        return

    print(f"\n批量文件读取完成: {batch_file}")
    print(f"待处理条目: {len(urls)} 个")
    if batch_root:
        print(f"批次根目录: {batch_root}")
    active_prompt_names = resolve_batch_prompt_names(prompt_names, use_all_available=True)
    if prompt_names is None:
        if active_prompt_names:
            print(f"未指定提示词，将使用所有可用的提示词: {', '.join(active_prompt_names)}")
        else:
            print("警告: 未找到可用的提示词，将只进行原始转写")

    plan = build_batch_plan(args, urls, batch_root, active_prompt_names)
    print_batch_plan_summary(len(urls), plan, args.skip_existing)
    print_items(plan["planned_urls"])
    print_output_preview(plan["planned_urls"], batch_root, active_prompt_names, not args.no_llm)

    if args.dry_run:
        print("\n--dry-run 已启用，仅预览，不执行转写。")
        return

    process_batch(
        video_urls=urls,
        model_size=args.model_size,
        cpu_threads=args.cpu_threads,
        asr_engine=args.asr_engine,
        funasr_model=args.funasr_model,
        enable_llm_optimization=not args.no_llm,
        prompt_names=active_prompt_names,
        skip_existing=args.skip_existing,
        batch_root=batch_root,
        cookies_from_browser=args.cookies_from_browser,
        cookies_file=args.cookies,
        youtube_po_token=args.youtube_po_token,
        cover_mode=resolve_args_cover_mode(args),
        limit=args.limit,
        precomputed_plan=plan,
        auto_repair=args.auto_repair,
        repair_rounds=args.repair_rounds,
        repair_delay=args.repair_delay,
        save_video=resolve_save_video(args),
    )


def handle_single(args, prompt_names: Optional[list[str]]) -> None:
    """Handle single URL/local or interactive mode."""
    video_url = args.url or args.local
    if not video_url:
        print("\n请输入视频链接或本地视频文件路径:")
        video_url = input("> ").strip()
        if not video_url:
            print("错误: 请输入有效的视频链接")
            return

        if not args.no_llm:
            print("\n是否启用大模型文本优化？(y/n，默认 y):")
            enable_opt = input("> ").strip().lower()
            enable_llm = enable_opt != "n"
            if enable_llm and not prompt_names:
                available = list_available_prompts()
                print(f"\n可用的提示词: {', '.join(available)}")
                print("请选择提示词（多个用逗号分隔，直接回车则选择全部）:")
                prompts_input = input("> ").strip()
                prompt_names = [p.strip() for p in prompts_input.split(",")] if prompts_input else available
        else:
            enable_llm = False
    else:
        enable_llm = not args.no_llm
        if enable_llm and prompt_names is None:
            prompt_names = list_available_prompts()
            if prompt_names:
                print(f"未指定提示词，将使用所有可用的提示词: {', '.join(prompt_names)}")
            else:
                print("警告: 未找到可用的提示词，将只进行原始转写")

    process_video(
        video_url=video_url,
        model_size=args.model_size,
        cpu_threads=args.cpu_threads,
        asr_engine=args.asr_engine,
        funasr_model=args.funasr_model,
        enable_llm_optimization=enable_llm,
        prompt_names=prompt_names,
        skip_existing=args.skip_existing,
        batch_root=None,
        cookies_from_browser=args.cookies_from_browser,
        cookies_file=args.cookies,
        youtube_po_token=args.youtube_po_token,
        cover_mode=resolve_args_cover_mode(args),
        save_video=resolve_save_video(args),
    )


def print_items(items: list[str], max_count: int = 10) -> None:
    """Print a numbered preview list."""
    preview_count = min(max_count, len(items))
    print(f"\n前 {preview_count} 个视频:")
    for i, item in enumerate(items[:preview_count], 1):
        print(f"  {i}. {item}")
    if len(items) > preview_count:
        print(f"  ... 还有 {len(items) - preview_count} 个")
