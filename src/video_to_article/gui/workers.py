"""Background workers that call core APIs (never shell out to CLI)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional

from PySide6.QtCore import QObject, QThread, Signal

from ..batch import find_local_videos, read_batch_file, write_batch_file
from ..config import load_config
from ..cover import COVER_MODE_OFF, resolve_cover_pipeline_mode
from ..data_paths import batch_list_path
from ..processor import (
    check_batch_report,
    plan_batch_urls,
    process_batch,
    process_download_only,
    process_raw_file,
    process_regen_cover,
    process_video,
)
from ..providers.bilibili import format_duration, format_play_count, search_bilibili_videos
from ..providers.youtube import (
    get_youtube_collection_urls,
    make_youtube_batch_root,
    search_youtube_videos,
)
from ..providers.youtube_auth import (
    check_youtube_auth,
    inspect_cookie_file,
    refresh_cookie_file_from_browser,
    resolve_youtube_auth,
)
from .log_bridge import StdioRedirect


@dataclass
class JobRequest:
    """Normalized job for the worker."""

    kind: str
    # single / download / tools path
    source: str = ""
    thumbnail: str = ""
    # batch file
    batch_file: str = ""
    # generic url list (search process, pre-expanded)
    urls: List[str] = field(default_factory=list)
    batch_root: Optional[str] = None
    # batch source expansion
    source_type: str = "list"  # list | local_dir | youtube | urls
    local_dir: str = ""
    recursive: bool = True
    youtube_collection: str = ""
    youtube_limit: Optional[int] = None
    dry_run: bool = False
    write_list: bool = False
    write_list_path: str = ""  # empty or auto path handled as auto
    auto_repair: bool = False
    repair_rounds: int = 2
    repair_delay: int = 0
    # pipeline
    prompt_names: Optional[List[str]] = None
    enable_llm: bool = True
    save_video: bool = False
    skip_existing: bool = True
    limit: Optional[int] = None
    media_type: str = "video"
    download_subs: bool = False
    subtitle_langs: Optional[List[str]] = None
    cover_mode: Optional[str] = None  # None = resolve from config
    # cookies
    cookies_from_browser: Optional[str] = None
    cookies_file: Optional[str] = None
    youtube_po_token: Optional[str] = None
    # ASR
    asr_override: bool = False
    model_size: str = "tiny"
    cpu_threads: int = 4
    asr_engine: str = "funasr"
    funasr_model: str = "sensevoice"
    # video search
    search_platform: str = "bilibili"  # bilibili | youtube
    search_keyword: str = ""
    search_count: int = 5
    search_order: str = "totalrank"
    extra: dict[str, Any] = field(default_factory=dict)


class JobWorker(QObject):
    """Runs one job on a QThread."""

    log_line = Signal(str)
    stage = Signal(str)
    finished_ok = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)
    search_results = Signal(object)

    def __init__(self, request: JobRequest) -> None:
        super().__init__()
        self.request = request
        self._cancel = False

    def request_cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            with StdioRedirect(self._emit_log):
                result = self._dispatch()
            short_ops = {
                "bilibili_search",
                "from_raw",
                "regen_cover",
                "check_report",
                "youtube_auth",
                "refresh_cookies",
            }
            if self._cancel and self.request.kind not in short_ops:
                self.failed.emit("已取消（当前条目可能仍已完成）")
                return
            self.finished_ok.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))

    def _emit_log(self, text: str) -> None:
        if text:
            self.log_line.emit(text)

    def _resolve_cover_mode(self) -> str:
        # GUI: None/"config" = 跟随设置；full/prompt_only/off = 本次覆盖
        mode = self.request.cover_mode
        if mode and str(mode).strip().lower() not in {"", "config", "none"}:
            from ..cover import normalize_cover_pipeline_mode

            return normalize_cover_pipeline_mode(mode)
        try:
            config = load_config()
        except Exception:
            config = {}
        return resolve_cover_pipeline_mode(no_cover=False, no_cover_assets=False, config=config)

    def _apply_asr_defaults(self) -> None:
        if self.request.asr_override:
            return
        try:
            cfg = load_config().get("transcribe") or {}
        except Exception:
            cfg = {}
        if cfg.get("model_size"):
            self.request.model_size = str(cfg["model_size"])
        if cfg.get("cpu_threads") is not None:
            try:
                self.request.cpu_threads = int(cfg["cpu_threads"])
            except (TypeError, ValueError):
                pass
        if cfg.get("asr_engine"):
            self.request.asr_engine = str(cfg["asr_engine"])
        if cfg.get("funasr_model"):
            self.request.funasr_model = str(cfg["funasr_model"])

    def _dispatch(self) -> Any:
        self._apply_asr_defaults()
        kind = self.request.kind
        handlers = {
            "single": self._run_single,
            "batch": self._run_batch,
            "download_single": self._run_download_single,
            "download_batch": self._run_download_batch,
            "bilibili_search": self._run_bilibili_search,
            "from_raw": self._run_from_raw,
            "regen_cover": self._run_regen_cover,
            "check_report": self._run_check_report,
            "youtube_auth": self._run_youtube_auth,
            "refresh_cookies": self._run_refresh_cookies,
        }
        fn = handlers.get(kind)
        if not fn:
            raise ValueError(f"未知任务类型: {kind}")
        return fn()

    def _run_single(self) -> dict:
        self.stage.emit("处理中")
        self.progress.emit(0, 1)
        result = process_video(
            video_url=self.request.source,
            model_size=self.request.model_size,
            cpu_threads=self.request.cpu_threads,
            asr_engine=self.request.asr_engine,
            funasr_model=self.request.funasr_model,
            enable_llm_optimization=self.request.enable_llm,
            prompt_names=self.request.prompt_names,
            skip_existing=self.request.skip_existing,
            cookies_from_browser=self.request.cookies_from_browser or None,
            cookies_file=self.request.cookies_file or None,
            youtube_po_token=self.request.youtube_po_token or None,
            cover_mode=self._resolve_cover_mode(),
            save_video=self.request.save_video,
        )
        self.progress.emit(1, 1)
        self.stage.emit("完成" if result.get("success") else "失败")
        return result

    def _resolve_batch_urls(self) -> tuple[List[str], Optional[str]]:
        st = self.request.source_type
        if st == "urls" or (self.request.urls and st == "urls"):
            return list(self.request.urls), self.request.batch_root
        if st == "local_dir":
            directory = self.request.local_dir
            videos = find_local_videos(directory=directory, recursive=self.request.recursive)
            if not videos:
                raise ValueError(f"未在目录中找到支持的音频/视频: {directory}")
            print(f"\n本地目录扫描完成: {directory}")
            print(f"   扫描方式: {'递归' if self.request.recursive else '仅当前目录'}")
            print(f"   待处理: {len(videos)} 个")
            return videos, str(Path(directory))
        if st == "youtube":
            collection_url = self.request.youtube_collection
            self.stage.emit("展开 YouTube 合集")
            urls = get_youtube_collection_urls(
                collection_url,
                limit=self.request.youtube_limit,
                cookies_from_browser=self.request.cookies_from_browser or None,
                cookies_file=self.request.cookies_file or None,
                youtube_po_token=self.request.youtube_po_token or None,
            )
            if not urls:
                raise ValueError(f"未找到 YouTube 视频: {collection_url}")
            batch_root = make_youtube_batch_root(
                collection_url,
                cookies_from_browser=self.request.cookies_from_browser or None,
                cookies_file=self.request.cookies_file or None,
                youtube_po_token=self.request.youtube_po_token or None,
            )
            print(f"\nYouTube 批量链接展开完成: {collection_url}")
            print(f"批次根目录: {batch_root}")
            print(f"待处理视频: {len(urls)} 个")
            return urls, batch_root
        batch_path = Path(self.request.batch_file)
        urls, batch_root = read_batch_file(batch_path)
        if not urls:
            raise ValueError(f"批量清单为空: {batch_path}")
        if self.request.batch_root:
            batch_root = self.request.batch_root
        return urls, batch_root

    def _maybe_write_list(self, urls: List[str], batch_root: Optional[str]) -> Optional[str]:
        if not self.request.write_list:
            return None
        st = self.request.source_type
        if st == "local_dir":
            kind = "local"
        elif st == "youtube":
            kind = "youtube"
        else:
            kind = "local"
        explicit = self.request.write_list_path.strip() or "auto"
        list_path = batch_list_path(kind, batch_root=batch_root, explicit_path=explicit)
        write_batch_file(list_path, urls, batch_root)
        print(f"\n清单已写入: {list_path}")
        return str(list_path)

    def _run_batch(self) -> Any:
        self.stage.emit("准备批量")
        urls, batch_root = self._resolve_batch_urls()
        if self.request.batch_root:
            batch_root = self.request.batch_root
        self.progress.emit(0, max(len(urls), 1))

        written = self._maybe_write_list(urls, batch_root)

        plan = plan_batch_urls(
            video_urls=urls,
            prompt_names=self.request.prompt_names,
            enable_llm_optimization=self.request.enable_llm,
            skip_existing=self.request.skip_existing,
            batch_root=batch_root,
            limit=self.request.limit,
            cookies_from_browser=self.request.cookies_from_browser or None,
            cookies_file=self.request.cookies_file or None,
            youtube_po_token=self.request.youtube_po_token or None,
        )
        planned = plan.get("planned_urls") or []
        skipped = plan.get("skipped_before_run") or []
        status_counts = plan.get("status_counts") or {}
        print("\n" + "=" * 60)
        print(f"批量计划：清单 {len(urls)}，计划处理 {len(planned)}，跳过 {len(skipped)}")
        if self.request.skip_existing:
            print(f"  完整输出: {status_counts.get('complete', 0)}")
            print(f"  报告完成: {status_counts.get('report_complete', 0)}")
            print(f"  待补文章: {status_counts.get('raw_only', 0)}")
            print(f"  未处理: {status_counts.get('unprocessed', 0)}")
        print("=" * 60)
        for i, u in enumerate(planned[:20], 1):
            print(f"  计划 {i}. {u}")
        if len(planned) > 20:
            print(f"  … 另有 {len(planned) - 20} 条")

        if self.request.dry_run:
            self.stage.emit("dry-run 完成")
            self.progress.emit(len(planned), max(len(urls), 1))
            return {
                "success": True,
                "dry_run": True,
                "urls": urls,
                "planned_urls": planned,
                "skipped_before_run": skipped,
                "status_counts": status_counts,
                "batch_root": batch_root,
                "list_file": written,
                "plan": plan,
            }

        if not planned:
            self.stage.emit("无待处理条目")
            return []

        self.stage.emit("批量处理")
        results = process_batch(
            video_urls=urls,
            model_size=self.request.model_size,
            cpu_threads=self.request.cpu_threads,
            asr_engine=self.request.asr_engine,
            funasr_model=self.request.funasr_model,
            enable_llm_optimization=self.request.enable_llm,
            prompt_names=self.request.prompt_names,
            skip_existing=self.request.skip_existing,
            batch_root=batch_root,
            cookies_from_browser=self.request.cookies_from_browser or None,
            cookies_file=self.request.cookies_file or None,
            youtube_po_token=self.request.youtube_po_token or None,
            cover_mode=self._resolve_cover_mode(),
            limit=self.request.limit,
            precomputed_plan=plan,
            save_video=self.request.save_video,
            auto_repair=self.request.auto_repair,
            repair_rounds=self.request.repair_rounds,
            repair_delay=self.request.repair_delay,
        )
        self.progress.emit(len(results), max(len(results), 1))
        self.stage.emit("批量完成")
        return results

    def _run_download_single(self) -> dict:
        self.stage.emit("仅下载")
        self.progress.emit(0, 1)
        result = process_download_only(
            video_url=self.request.source,
            media_type=self.request.media_type,
            cookies_from_browser=self.request.cookies_from_browser or None,
            cookies_file=self.request.cookies_file or None,
            youtube_po_token=self.request.youtube_po_token or None,
            download_subs=self.request.download_subs,
            subtitle_langs=self.request.subtitle_langs,
        )
        self.progress.emit(1, 1)
        self.stage.emit("下载完成" if result.get("success") else "下载失败")
        return result

    def _run_download_batch(self) -> list:
        self.stage.emit("批量仅下载")
        batch_path = Path(self.request.batch_file)
        urls, batch_root = read_batch_file(batch_path)
        if not urls:
            raise ValueError(f"批量清单为空: {batch_path}")
        if self.request.limit:
            urls = urls[: max(1, int(self.request.limit))]
        results = []
        total = len(urls)
        for i, url in enumerate(urls, 1):
            if self._cancel:
                break
            self.progress.emit(i - 1, total)
            self.stage.emit(f"下载 {i}/{total}")
            print(f"\n[{i}/{total}] {url}")
            result = process_download_only(
                video_url=url,
                media_type=self.request.media_type,
                cookies_from_browser=self.request.cookies_from_browser or None,
                cookies_file=self.request.cookies_file or None,
                youtube_po_token=self.request.youtube_po_token or None,
                batch_root=batch_root,
                download_subs=self.request.download_subs,
                subtitle_langs=self.request.subtitle_langs,
            )
            results.append(result)
            if not result.get("success"):
                print(f"失败: {result.get('error')}")
        self.progress.emit(len(results), total)
        ok = sum(1 for r in results if r.get("success"))
        self.stage.emit(f"下载完成 {ok}/{len(results)}")
        return results

    def _run_bilibili_search(self) -> list:
        """Platform search (kind kept for compatibility; supports bilibili / youtube)."""
        keyword = self.request.search_keyword.strip()
        count = max(1, int(self.request.search_count or 5))
        order = self.request.search_order or "totalrank"
        platform = (self.request.search_platform or "bilibili").strip().lower()
        label = "YouTube" if platform == "youtube" else "B 站"
        self.stage.emit(f"{label}搜索中")
        self.progress.emit(0, 0)
        print(f"\n搜索{label}视频: {keyword}")
        print(f"   数量: {count}")
        print(f"   排序: {order}")
        if platform == "youtube":
            videos = search_youtube_videos(
                keyword=keyword,
                count=count,
                order=order,
                cookies_from_browser=self.request.cookies_from_browser or None,
                cookies_file=self.request.cookies_file or None,
                youtube_po_token=self.request.youtube_po_token or None,
            )
        else:
            videos = search_bilibili_videos(keyword=keyword, count=count, order=order)
        if not videos:
            raise ValueError("搜索无结果或搜索失败")
        print(f"\n找到 {len(videos)} 个视频:")
        for i, video in enumerate(videos, 1):
            print(f"  {i}. {video.get('title')}")
            print(
                f"     时长: {format_duration(video.get('duration', 0))}, "
                f"播放: {format_play_count(video.get('play', 0))}, "
                f"作者: {video.get('author')}"
            )
        self.search_results.emit(videos)
        self.progress.emit(len(videos), len(videos))
        self.stage.emit(f"搜索完成 {len(videos)} 条")
        return videos

    def _run_from_raw(self) -> dict:
        self.stage.emit("从 raw 补文章")
        self.progress.emit(0, 1)
        result = process_raw_file(
            raw_file=self.request.source,
            prompt_names=self.request.prompt_names or ["snack_recipe"],
            cover_mode=self._resolve_cover_mode(),
        )
        self.progress.emit(1, 1)
        self.stage.emit("完成" if result.get("success") else "失败")
        return result

    def _run_regen_cover(self) -> dict:
        cover_mode = self._resolve_cover_mode()
        if cover_mode == COVER_MODE_OFF:
            raise ValueError("封面模式为关闭，无法补封面")
        self.stage.emit("重生成封面")
        self.progress.emit(0, 1)
        result = process_regen_cover(
            self.request.source,
            self.request.thumbnail or None,
            cover_mode=cover_mode,
        )
        self.progress.emit(1, 1)
        self.stage.emit("完成" if result.get("success") else "失败")
        return result

    def _run_check_report(self) -> dict:
        self.stage.emit("复查批量报告")
        self.progress.emit(0, 1)
        result = check_batch_report(self.request.source)
        self.progress.emit(1, 1)
        self.stage.emit("复查完成" if result.get("success") else "复查失败")
        return result

    def _run_youtube_auth(self) -> dict:
        self.stage.emit("检查 YouTube 登录")
        self.progress.emit(0, 1)
        auth = resolve_youtube_auth(
            cookies_from_browser=self.request.cookies_from_browser,
            cookies_file=self.request.cookies_file,
            youtube_po_token=self.request.youtube_po_token,
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

        result: dict[str, Any] = {
            "success": True,
            "auth_source": auth.source,
            "cookies_file": auth.cookies_file,
            "cookies_from_browser": auth.cookies_from_browser,
        }
        if not self.request.source:
            print("\n未提供测试 URL，只完成本地 cookies 检查。")
            self.progress.emit(1, 1)
            self.stage.emit("本地检查完成")
            return result

        print("\n正在请求 YouTube 元数据...")
        live = check_youtube_auth(
            self.request.source,
            cookies_from_browser=self.request.cookies_from_browser,
            cookies_file=self.request.cookies_file,
            youtube_po_token=self.request.youtube_po_token,
        )
        result.update(live)
        if live.get("success"):
            print(f"YouTube 请求: {'通过' if live.get('usable') else '异常'}")
            print(f"视频标题: {live.get('title')}")
            print(f"可用格式数量: {live.get('format_count')}")
            subtitles = live.get("subtitles") or []
            auto_subtitles = live.get("automatic_captions") or []
            print(f"人工字幕语言: {', '.join(subtitles) if subtitles else '无'}")
            print(f"自动字幕语言: {', '.join(auto_subtitles) if auto_subtitles else '无'}")
            if live.get("hint"):
                print(f"诊断: {live.get('hint')}")
        else:
            print("YouTube 请求: 失败")
            print(f"错误: {live.get('error')}")
            if live.get("hint"):
                print(f"诊断: {live.get('hint')}")
        self.progress.emit(1, 1)
        self.stage.emit("检查完成")
        return result

    def _run_refresh_cookies(self) -> dict:
        browser = self.request.cookies_from_browser or "firefox"
        self.stage.emit(f"从 {browser} 刷新 cookies")
        self.progress.emit(0, 1)
        print("\n刷新 YouTube cookies 文件")
        print("=" * 60)
        result = refresh_cookie_file_from_browser(browser, self.request.cookies_file or None)
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
        self.progress.emit(1, 1)
        self.stage.emit("刷新完成" if result.get("success") else "刷新失败")
        return result


def start_job(
    parent: QObject,
    request: JobRequest,
    on_log: Callable[[str], None],
    on_stage: Callable[[str], None],
    on_progress: Callable[[int, int], None],
    on_ok: Callable[[object], None],
    on_fail: Callable[[str], None],
    on_search_results: Optional[Callable[[object], None]] = None,
) -> tuple[QThread, JobWorker]:
    """Create thread+worker, wire signals, start. Caller must keep refs."""
    thread = QThread(parent)
    worker = JobWorker(request)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.log_line.connect(on_log)
    worker.stage.connect(on_stage)
    worker.progress.connect(on_progress)
    worker.finished_ok.connect(on_ok)
    worker.failed.connect(on_fail)
    if on_search_results is not None:
        worker.search_results.connect(on_search_results)
    worker.finished_ok.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.start()
    return thread, worker
