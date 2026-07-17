"""Main workbench window — 一览成文."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    FluentIcon,
    NavigationInterface,
    NavigationItemPosition,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
)

from ..config import load_config
from ..media.ffmpeg_tools import ffmpeg_status_message
from ..paths import DATA_DIR, OUTPUT_DIR, ensure_runtime_dirs
from .branding import (
    APP_ABOUT,
    APP_NAME_ZH,
    APP_VERSION,
    APP_WINDOW_TITLE,
    BLOG_LABEL,
    BLOG_URL,
    icon_path,
)
from .cli_builder import build_cli
from .modes.batch_page import BatchPage
from .modes.download_page import DownloadPage
from .modes.search_page import SearchPage
from .modes.single_page import SinglePage
from .modes.tools_page import ToolsPage
from .settings import SettingsDialog
from .state.prefs import load_prefs, save_prefs
from .widgets.log_panel import LogPanel
from .workers import JobRequest, JobWorker, start_job

MODE_SINGLE = "single"
MODE_BATCH = "batch"
MODE_SEARCH = "search"
MODE_DOWNLOAD = "download"
MODE_TOOLS = "tools"

MODE_LABELS = [
    (MODE_SINGLE, "单条处理"),
    (MODE_BATCH, "批量处理"),
    (MODE_SEARCH, "B站搜索"),
    (MODE_DOWNLOAD, "仅下载"),
    (MODE_TOOLS, "补跑工具"),
]

MODE_ICONS = {
    MODE_SINGLE: FluentIcon.VIDEO,
    MODE_BATCH: FluentIcon.LIBRARY,
    MODE_SEARCH: FluentIcon.SEARCH,
    MODE_DOWNLOAD: FluentIcon.DOWNLOAD,
    MODE_TOOLS: FluentIcon.CERTIFICATE,
}

RUNNABLE_MODES = {MODE_SINGLE, MODE_BATCH, MODE_SEARCH, MODE_DOWNLOAD, MODE_TOOLS}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_WINDOW_TITLE)
        self.resize(1180, 780)
        ensure_runtime_dirs()
        icon = icon_path()
        if icon is not None:
            self.setWindowIcon(QIcon(str(icon)))

        self._prefs = load_prefs()
        self._thread = None
        self._worker: Optional[JobWorker] = None
        self._last_result_dir: Optional[Path] = None
        self._job_kind: str = ""
        self._last_request: Optional[JobRequest] = None
        self._mode_order = [k for k, _ in MODE_LABELS]

        self._build_menu()
        self._build_ui()
        self._apply_prefs()
        self._apply_config_cookie_defaults()

    # ----- UI -----

    def _build_menu(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu("文件")
        act_settings = QAction("设置…", self)
        act_settings.setShortcut(QKeySequence("Ctrl+,"))
        act_settings.triggered.connect(self.open_settings)
        file_menu.addAction(act_settings)
        act_cli = QAction("复制等价命令行", self)
        act_cli.setShortcut(QKeySequence("Ctrl+Shift+C"))
        act_cli.triggered.connect(self.copy_equivalent_cli)
        file_menu.addAction(act_cli)
        file_menu.addSeparator()
        act_quit = QAction("退出", self)
        act_quit.setShortcut(QKeySequence.Quit)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        open_menu = menu.addMenu("打开")
        act_data = QAction("data 目录", self)
        act_data.triggered.connect(lambda: self._open_path(DATA_DIR))
        act_out = QAction("output 目录", self)
        act_out.triggered.connect(lambda: self._open_path(OUTPUT_DIR))
        open_menu.addAction(act_data)
        open_menu.addAction(act_out)

        help_menu = menu.addMenu("帮助")
        act_blog = QAction(f"打开{BLOG_LABEL}…", self)
        act_blog.triggered.connect(self._open_blog)
        help_menu.addAction(act_blog)
        act_about = QAction("关于", self)
        act_about.triggered.connect(self._about)
        help_menu.addAction(act_about)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.navigation = NavigationInterface(self, showMenuButton=True, showReturnButton=False)
        self.navigation.setExpandWidth(168)
        for key, label in MODE_LABELS:
            self.navigation.addItem(
                routeKey=key,
                icon=MODE_ICONS.get(key, FluentIcon.APPLICATION),
                text=label,
                onClick=lambda checked=False, k=key: self._switch_mode(k),
                position=NavigationItemPosition.TOP,
            )
        self.navigation.addItem(
            routeKey="settings",
            icon=FluentIcon.SETTING,
            text="设置",
            onClick=lambda: self.open_settings(),
            position=NavigationItemPosition.BOTTOM,
        )
        self.navigation.addItem(
            routeKey="open_output",
            icon=FluentIcon.FOLDER,
            text="打开 output",
            onClick=lambda: self._open_path(OUTPUT_DIR),
            position=NavigationItemPosition.BOTTOM,
        )
        self.navigation.addItem(
            routeKey="blog",
            icon=FluentIcon.GLOBE,
            text=BLOG_LABEL,
            onClick=lambda: self._open_blog(),
            position=NavigationItemPosition.BOTTOM,
        )
        outer.addWidget(self.navigation)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 10, 12, 10)
        right_layout.setSpacing(8)

        from PySide6.QtGui import QFont

        from .theme_style import FONT_PAGE_TITLE

        self.page_title = SubtitleLabel(MODE_LABELS[0][1])
        tf = self.page_title.font()
        tf.setPointSize(FONT_PAGE_TITLE)
        tf.setWeight(QFont.DemiBold)
        self.page_title.setFont(tf)
        right_layout.addWidget(self.page_title)

        splitter = QSplitter(Qt.Vertical)

        self.stack = QStackedWidget()
        self.single_page = SinglePage()
        self.batch_page = BatchPage()
        self.search_page = SearchPage()
        self.search_page.search_requested.connect(self.start_bilibili_search)
        self.download_page = DownloadPage()
        self.tools_page = ToolsPage()
        for page in (
            self.single_page,
            self.batch_page,
            self.search_page,
            self.download_page,
            self.tools_page,
        ):
            self.stack.addWidget(page)
        splitter.addWidget(self.stack)

        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        btn_row = QHBoxLayout()
        self.start_btn = PrimaryPushButton("开始")
        self.start_btn.clicked.connect(self.start_job)
        self.stop_btn = PushButton("停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_job)
        self.copy_cli_btn = PushButton("复制命令行")
        self.copy_cli_btn.clicked.connect(self.copy_equivalent_cli)
        # 根目录浏览走菜单「打开 → output/data」；底栏只跳转到本次/上次成功结果目录
        self.open_result_btn = PushButton("打开结果")
        self.open_result_btn.setEnabled(False)
        self.open_result_btn.setToolTip("打开最近一次成功任务的结果目录（与日志中的路径一致）")
        self.open_result_btn.clicked.connect(self._open_last_result)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addWidget(self.copy_cli_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.open_result_btn)
        bottom_layout.addLayout(btn_row)

        self.log_panel = LogPanel()
        bottom_layout.addWidget(self.log_panel, 1)
        splitter.addWidget(bottom)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        right_layout.addWidget(splitter, 1)
        outer.addWidget(right, 1)
        self.statusBar().showMessage(f"就绪 · {APP_NAME_ZH} · {APP_ABOUT}")
        blog_link = QLabel(
            f'<a href="{BLOG_URL}" style="color:#0078D4; text-decoration:none;">'
            f"{BLOG_LABEL}</a>"
        )
        blog_link.setOpenExternalLinks(True)
        blog_link.setTextInteractionFlags(Qt.TextBrowserInteraction)
        blog_link.setToolTip(BLOG_URL)
        self.statusBar().addPermanentWidget(blog_link)
        self.navigation.setCurrentItem(MODE_SINGLE)

    def _pipeline_pages(self):
        return (self.single_page, self.batch_page, self.search_page)

    def _cookie_pages(self):
        return (
            self.single_page.cookies,
            self.batch_page.cookies,
            self.tools_page.cookies_auth,
            self.search_page.cookies,
            self.download_page.cookies,
        )

    def _apply_prefs(self) -> None:
        mode = self._prefs.get("last_mode") or MODE_SINGLE
        if mode not in self._mode_order:
            mode = MODE_SINGLE
        self._switch_mode(mode)
        try:
            self.navigation.setCurrentItem(mode)
        except Exception:
            pass

        prompts = self._prefs.get("last_prompts") or []
        if isinstance(prompts, list):
            preferred = [str(p) for p in prompts]
            for page in self._pipeline_pages():
                page.prompts.refresh(preferred)
            self.tools_page.prompts.refresh(preferred)

        enable_llm = bool(self._prefs.get("enable_llm", True))
        save_video = bool(self._prefs.get("save_video", False))
        skip_existing = bool(self._prefs.get("skip_existing", True))
        cover_key = str(self._prefs.get("cover_mode") or "config")
        for page in self._pipeline_pages():
            page.pipeline.enable_llm.setChecked(enable_llm)
            page.pipeline.save_video.setChecked(save_video)
            page.cover.set_mode_key(cover_key)
        self.batch_page.pipeline.skip_existing.setChecked(skip_existing)
        self.search_page.pipeline.skip_existing.setChecked(skip_existing)

        batch_src = str(self._prefs.get("batch_source") or BatchPage.SOURCE_LIST)
        self.batch_page.set_source_type(batch_src)

        browser = str(self._prefs.get("cookies_from_browser") or "")
        cookies_file = str(self._prefs.get("cookies_file") or "")
        for cookies in self._cookie_pages():
            cookies.apply_defaults(browser, cookies_file)

        media = str(self._prefs.get("media_type") or "video")
        idx = self.download_page.media_type.findData(media)
        if idx >= 0:
            self.download_page.media_type.setCurrentIndex(idx)

        last_result = str(self._prefs.get("last_result_dir") or "").strip()
        if last_result:
            path = Path(last_result)
            if path.exists():
                self._last_result_dir = path
                self.open_result_btn.setEnabled(True)
                self.open_result_btn.setToolTip(str(path))

    def _apply_config_cookie_defaults(self) -> None:
        try:
            yt = (load_config() or {}).get("youtube") or {}
        except Exception:
            return
        browser = str(yt.get("cookies_from_browser") or "")
        cookies_file = str(yt.get("cookies_file") or "")
        if not browser and not cookies_file:
            return
        for cookies in self._cookie_pages():
            if not cookies.cookies_from_browser() and not cookies.cookies_file_path():
                cookies.apply_defaults(browser, cookies_file)

    def _switch_mode(self, key: str) -> None:
        if key not in self._mode_order:
            return
        row = self._mode_order.index(key)
        self.stack.setCurrentIndex(row)
        label = dict(MODE_LABELS).get(key, key)
        self.page_title.setText(label)
        runnable = key in RUNNABLE_MODES
        self.start_btn.setEnabled(runnable and self._worker is None)
        if key == MODE_SEARCH:
            self.start_btn.setText("开始处理勾选")
            self.statusBar().showMessage("B站搜索：先点页面「搜索」，再勾选后点「开始处理勾选」")
        elif key == MODE_TOOLS:
            self.start_btn.setText("运行工具")
            self.statusBar().showMessage("补跑工具：选择子工具后点「运行工具」")
        else:
            self.start_btn.setText("开始")
            self.statusBar().showMessage(f"当前模式：{label}")

    def current_mode(self) -> str:
        idx = self.stack.currentIndex()
        if idx < 0 or idx >= len(self._mode_order):
            return MODE_SINGLE
        return self._mode_order[idx]

    # ----- Job control -----

    def start_bilibili_search(self) -> None:
        if self._worker is not None:
            return
        err = self.search_page.validate_search()
        if err:
            QMessageBox.warning(self, "无法搜索", err)
            return
        keyword, count, order = self.search_page.search_params()
        request = JobRequest(
            kind="bilibili_search",
            search_keyword=keyword,
            search_count=count,
            search_order=order,
        )
        self._launch(request, busy_message="正在搜索 B 站…")

    def start_job(self) -> None:
        if self._worker is not None:
            return
        mode = self.current_mode()
        err = None
        request: Optional[JobRequest] = None

        if mode == MODE_SINGLE:
            err = self.single_page.validate()
            if not err:
                request = self._request_single()
        elif mode == MODE_BATCH:
            err = self.batch_page.validate()
            if not err:
                request = self._request_batch()
        elif mode == MODE_SEARCH:
            err = self.search_page.validate_process()
            if not err:
                request = self._request_search_process()
        elif mode == MODE_DOWNLOAD:
            err = self.download_page.validate()
            if not err:
                request = self._request_download()
        elif mode == MODE_TOOLS:
            err = self.tools_page.validate()
            if not err:
                request = self._request_tools()
        else:
            err = "当前模式尚未开放"

        if err:
            QMessageBox.warning(self, "无法开始", err)
            return
        assert request is not None
        self._save_ui_prefs()
        self._launch(request, busy_message="任务运行中…")

    def _launch(self, request: JobRequest, busy_message: str) -> None:
        self._job_kind = request.kind
        self._last_request = request
        self.log_panel.append("\n—— 开始任务 ——\n")
        try:
            cli = build_cli(request)
            self.log_panel.append(f"[等价 CLI] {cli}\n")
        except Exception:
            pass
        self.log_panel.set_stage("启动中…")
        self.log_panel.set_progress(0, 0)
        self.start_btn.setEnabled(False)
        self.search_page.search_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.navigation.setEnabled(False)
        self.statusBar().showMessage(busy_message)

        self._thread, self._worker = start_job(
            self,
            request,
            on_log=self.log_panel.append,
            on_stage=self.log_panel.set_stage,
            on_progress=self.log_panel.set_progress,
            on_ok=self._on_job_ok,
            on_fail=self._on_job_fail,
            on_search_results=self._on_search_results,
        )
        if self._thread is not None:
            self._thread.finished.connect(self._on_thread_finished)

    def stop_job(self) -> None:
        if self._worker is not None:
            self._worker.request_cancel()
            self.log_panel.append(
                "\n[GUI] 已请求停止（仅下载批量可在条目间中断；转写/计划任务需等当前步骤结束）\n"
            )
            self.statusBar().showMessage("正在停止…")

    def _cookies_from_page(self, cookies) -> tuple[Optional[str], Optional[str], Optional[str]]:
        browser = cookies.cookies_from_browser()
        file_path = cookies.cookies_file_path()
        if not browser and not file_path:
            try:
                yt = (load_config() or {}).get("youtube") or {}
            except Exception:
                yt = {}
            browser = yt.get("cookies_from_browser") or None
            file_path = yt.get("cookies_file") or None
            po = yt.get("po_token") or None
            return (
                str(browser) if browser else None,
                str(file_path) if file_path else None,
                str(po) if po else None,
            )
        try:
            po = ((load_config() or {}).get("youtube") or {}).get("po_token") or None
        except Exception:
            po = None
        return browser, file_path, str(po) if po else None

    def _asr_fields(self, page) -> dict:
        data = page.asr.as_dict()
        return {
            "asr_override": bool(data.get("use_override")),
            "asr_engine": data.get("asr_engine") or "funasr",
            "funasr_model": data.get("funasr_model") or "sensevoice",
            "model_size": data.get("model_size") or "tiny",
            "cpu_threads": int(data.get("cpu_threads") or 4),
        }

    def _pipeline_common(self, page) -> dict:
        browser, cookies_file, po = self._cookies_from_page(page.cookies)
        prompts = page.prompts.selected() if page.pipeline.enable_llm.isChecked() else []
        asr = self._asr_fields(page)
        return {
            "prompt_names": prompts or None,
            "enable_llm": page.pipeline.enable_llm.isChecked(),
            "save_video": page.pipeline.save_video.isChecked(),
            "cover_mode": page.cover.cover_mode_override(),
            "cookies_from_browser": browser,
            "cookies_file": cookies_file,
            "youtube_po_token": po,
            **asr,
        }

    def _request_single(self) -> JobRequest:
        page = self.single_page
        common = self._pipeline_common(page)
        return JobRequest(kind="single", source=page.source(), skip_existing=False, **common)

    def _request_batch(self) -> JobRequest:
        page = self.batch_page
        common = self._pipeline_common(page)
        st = page.source_type()
        return JobRequest(
            kind="batch",
            source_type=st,
            batch_file=page.list_path(),
            local_dir=page.local_dir(),
            recursive=page.recursive.isChecked(),
            youtube_collection=page.youtube_url(),
            youtube_limit=page.youtube_expand_limit(),
            skip_existing=page.pipeline.skip_existing.isChecked(),
            limit=page.pipeline.limit_value(),
            dry_run=page.pipeline.dry_run.isChecked(),
            batch_root=page.batch_root_override(),
            write_list=page.write_list_enabled(),
            write_list_path=page.write_list_path_value(),
            auto_repair=page.auto_repair_enabled(),
            repair_rounds=page.repair_rounds_value(),
            repair_delay=page.repair_delay_value(),
            **common,
        )

    def _request_tools(self) -> JobRequest:
        page = self.tools_page
        tool = page.tool_kind()
        if tool == ToolsPage.TOOL_FROM_RAW:
            return JobRequest(
                kind="from_raw",
                source=page.raw_edit.text().strip(),
                prompt_names=page.prompts.selected() or ["snack_recipe"],
                cover_mode=page.cover_from_raw.cover_mode_override(),
                enable_llm=True,
            )
        if tool == ToolsPage.TOOL_REGEN_COVER:
            return JobRequest(
                kind="regen_cover",
                source=page.article_edit.text().strip(),
                thumbnail=page.thumb_edit.text().strip(),
                cover_mode=page.cover_regen.cover_mode_override(),
            )
        if tool == ToolsPage.TOOL_CHECK_REPORT:
            return JobRequest(kind="check_report", source=page.report_edit.text().strip())
        if tool == ToolsPage.TOOL_YT_AUTH:
            browser, cookies_file, po = self._cookies_from_page(page.cookies_auth)
            return JobRequest(
                kind="youtube_auth",
                source=page.yt_url_edit.text().strip(),
                cookies_from_browser=browser,
                cookies_file=cookies_file,
                youtube_po_token=po,
            )
        browser = str(page.refresh_browser.currentData() or "firefox")
        out = page.refresh_out.text().strip() or None
        return JobRequest(
            kind="refresh_cookies",
            cookies_from_browser=browser,
            cookies_file=out,
        )

    def _current_request_for_cli(self) -> Optional[JobRequest]:
        """Build request from current form without running (for copy CLI)."""
        mode = self.current_mode()
        try:
            if mode == MODE_SINGLE:
                if self.single_page.validate():
                    return self._last_request
                return self._request_single()
            if mode == MODE_BATCH:
                if self.batch_page.validate():
                    return self._last_request
                return self._request_batch()
            if mode == MODE_SEARCH:
                # prefer process request if results exist
                if self.search_page.validate_process() is None:
                    return self._request_search_process()
                keyword, count, order = self.search_page.search_params()
                if keyword:
                    return JobRequest(
                        kind="bilibili_search",
                        search_keyword=keyword,
                        search_count=count,
                        search_order=order,
                    )
                return self._last_request
            if mode == MODE_DOWNLOAD:
                if self.download_page.validate():
                    return self._last_request
                return self._request_download()
            if mode == MODE_TOOLS:
                if self.tools_page.validate():
                    return self._last_request
                return self._request_tools()
        except Exception:
            return self._last_request
        return self._last_request

    def copy_equivalent_cli(self) -> None:
        req = self._current_request_for_cli()
        if req is None:
            QMessageBox.information(self, "复制命令行", "当前表单不完整，且没有上次任务可复制。")
            return
        cmd = build_cli(req)
        QApplication.clipboard().setText(cmd)
        self.log_panel.append(f"\n[已复制 CLI]\n{cmd}\n")
        self.statusBar().showMessage("等价命令行已复制到剪贴板", 4000)

    def _request_search_process(self) -> JobRequest:
        page = self.search_page
        common = self._pipeline_common(page)
        urls = page.selected_urls()
        return JobRequest(
            kind="batch",
            source_type="urls",
            urls=urls,
            skip_existing=page.pipeline.skip_existing.isChecked(),
            limit=page.pipeline.limit_value(),
            dry_run=page.pipeline.dry_run.isChecked(),
            **common,
        )

    def _request_download(self) -> JobRequest:
        page = self.download_page
        browser, cookies_file, po = self._cookies_from_page(page.cookies)
        common = {
            "media_type": page.media_type_value(),
            "download_subs": page.download_subs_enabled(),
            "subtitle_langs": page.subtitle_langs(),
            "cookies_from_browser": browser,
            "cookies_file": cookies_file,
            "youtube_po_token": po,
        }
        if page.is_batch():
            return JobRequest(
                kind="download_batch",
                batch_file=page.batch_edit.text().strip(),
                limit=page.limit_value(),
                **common,
            )
        return JobRequest(
            kind="download_single",
            source=page.url_edit.text().strip(),
            **common,
        )

    def _on_search_results(self, videos: object) -> None:
        if isinstance(videos, list):
            self.search_page.set_search_results(videos)

    def _on_job_ok(self, result: object) -> None:
        # update tables
        if self._job_kind == "batch":
            if isinstance(result, list):
                self.batch_page.apply_result_statuses(result)
                self.search_page.apply_result_statuses(result)
            elif isinstance(result, dict) and result.get("dry_run"):
                planned = result.get("planned_urls") or []
                items = [{"url": u, "title": u, "status": "计划处理", "note": "dry-run"} for u in planned]
                skipped = result.get("skipped_before_run") or []
                for item in skipped:
                    if isinstance(item, dict):
                        url = str(item.get("video_url") or item.get("url") or "")
                        title = str(item.get("title") or url)
                        items.append(
                            {
                                "url": url,
                                "title": title,
                                "status": "将跳过",
                                "note": str(item.get("status") or item.get("message") or ""),
                            }
                        )
                    else:
                        items.append({"url": str(item), "title": str(item), "status": "将跳过", "note": ""})
                if self.current_mode() == MODE_BATCH:
                    self.batch_page.table.set_items(items, default_status="计划")
                    self.batch_page.preview_label.setText(
                        f"dry-run：计划 {len(planned)} 条，跳过 {len(skipped)} 条"
                    )
                elif self.current_mode() == MODE_SEARCH:
                    # mark planned on search table
                    for u in planned:
                        self.search_page.table.set_row_status_by_url(str(u), "计划处理", "dry-run")

        if self._job_kind == "bilibili_search":
            self.log_panel.append("\n—— 搜索完成，请勾选后点「开始处理勾选」——\n")
            self.statusBar().showMessage("搜索完成")
            return

        if isinstance(result, dict) and result.get("dry_run"):
            planned = result.get("planned_urls") or []
            self.log_panel.append(f"\n—— dry-run 完成：计划处理 {len(planned)} 条 ——\n")
            self.statusBar().showMessage("dry-run 完成")
            QMessageBox.information(
                self,
                "预览完成",
                f"仅预览，未执行转写。\n计划处理 {len(planned)} 条，详见日志与列表。",
            )
            return
        if isinstance(result, dict) and result.get("success") is False:
            err = result.get("error") or "未知错误"
            self.log_panel.append(f"\n—— 任务结束：失败 ——\n{err}\n")
            self.statusBar().showMessage("任务失败")
            QMessageBox.warning(self, "失败", str(err))
            return
        if isinstance(result, list) and self._job_kind != "bilibili_search":
            ok = sum(1 for item in result if isinstance(item, dict) and item.get("success"))
            total = len(result)
            remembered = self._remember_result_dir(result) if ok > 0 else False
            self.log_panel.append(f"\n—— 任务结束：批量 {ok}/{total} 成功 ——\n")
            self.statusBar().showMessage(f"批量完成 {ok}/{total}")
            tip = "详见日志；可点「打开结果」跳转到最近成功目录。" if remembered else "详见日志。"
            QMessageBox.information(self, "完成", f"批量结束：成功 {ok}/{total}。{tip}")
            return
        # tool-specific short messages
        if self._job_kind == "check_report" and isinstance(result, dict):
            self._remember_result_dir(result)
            self.log_panel.append(
                f"\n—— 复查完成：剩余问题 {result.get('current_issue_count', '?')} ——\n"
            )
            self.statusBar().showMessage("复查完成")
            QMessageBox.information(
                self,
                "复查完成",
                f"当前剩余局部问题: {result.get('current_issue_count')}\n"
                f"已解决: {result.get('resolved_count')}\n详见日志。",
            )
            return
        if self._job_kind == "refresh_cookies" and isinstance(result, dict):
            ok = bool(result.get("success"))
            self.log_panel.append("\n—— cookies 刷新结束 ——\n")
            self.statusBar().showMessage("刷新完成" if ok else "刷新失败")
            if ok:
                self._remember_result_dir(result)
                QMessageBox.information(self, "完成", f"已写入: {result.get('output_file')}")
            else:
                QMessageBox.warning(self, "失败", str(result.get("error") or "刷新失败"))
            return
        if self._job_kind == "youtube_auth" and isinstance(result, dict):
            self.log_panel.append("\n—— YouTube 登录检查结束 ——\n")
            self.statusBar().showMessage("检查完成")
            QMessageBox.information(self, "完成", "登录检查已结束，详见日志。")
            return
        remembered = self._remember_result_dir(result)
        self.log_panel.append("\n—— 任务结束：成功 ——\n")
        self.statusBar().showMessage("任务完成")
        tip = (
            "任务已结束。可在日志中查看详情，或点「打开结果」跳转到结果目录。"
            if remembered
            else "任务已结束。可在日志中查看详情。"
        )
        QMessageBox.information(self, "完成", tip)

    def _on_job_fail(self, message: str) -> None:
        self.log_panel.append(f"\n—— 任务结束：{message} ——\n")
        self.statusBar().showMessage(message)
        QMessageBox.warning(self, "未完成", message)

    def _on_thread_finished(self) -> None:
        self._worker = None
        self._thread = None
        self._job_kind = ""
        mode = self.current_mode()
        self.start_btn.setEnabled(mode in RUNNABLE_MODES)
        self.search_page.search_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.navigation.setEnabled(True)
        self.log_panel.reset_progress()
        if self.log_panel.stage_label.text() in {"启动中…", "就绪"}:
            self.log_panel.set_stage("就绪")

    def _remember_result_dir(self, result: object) -> bool:
        """记住最近成功结果目录（与日志打印路径一致），并持久化到 prefs。"""
        path = self._extract_result_dir(result)
        if not path or not path.exists():
            return False
        self._last_result_dir = path
        self.open_result_btn.setEnabled(True)
        self.open_result_btn.setToolTip(str(path))
        self._prefs["last_result_dir"] = str(path)
        try:
            save_prefs(self._prefs)
        except Exception:
            pass
        return True

    def _extract_result_dir(self, result: object) -> Optional[Path]:
        """从任务返回值解析应打开的结果目录（优先 output_dir / 文章 / 媒资路径）。"""
        if isinstance(result, list) and result:
            # 批量：只取 success=True 的最近一条（与成功计数口径一致）
            for item in reversed(result):
                if isinstance(item, dict) and item.get("success"):
                    path = self._extract_result_dir(item)
                    if path is not None:
                        return path
            return None
        if not isinstance(result, dict):
            return None

        # 优先显式目录；再文件路径的父目录（与日志中的 raw/文章/下载路径对齐）
        for key in (
            "output_dir",
            "raw_file",
            "article_file",
            "video_path",
            "audio_path",
            "report_file",
            "output_file",
            "cookies_file",
        ):
            val = result.get(key)
            if not val:
                continue
            p = Path(str(val))
            candidate = p if p.is_dir() else p.parent
            if candidate.exists():
                return candidate

        # 仅下载字幕：成功结果常只有 subtitle_paths，无音视频路径
        subs = result.get("subtitle_paths")
        if isinstance(subs, (list, tuple)):
            for item in subs:
                if not item:
                    continue
                p = Path(str(item))
                candidate = p if p.is_dir() else p.parent
                if candidate.exists():
                    return candidate

        optimized = result.get("optimized_files") if isinstance(result.get("optimized_files"), dict) else {}
        if optimized:
            first = next(iter(optimized.values()), None)
            if first:
                candidate = Path(str(first)).parent
                if candidate.exists():
                    return candidate

        nested = result.get("result")
        if isinstance(nested, dict):
            return self._extract_result_dir(nested)
        return None

    def _open_last_result(self) -> None:
        if not self._last_result_dir:
            QMessageBox.information(
                self,
                "打开结果",
                "还没有可打开的结果目录。\n完成一次任务后，这里会跳转到日志中对应的结果路径。\n"
                "浏览整个 output / data 根目录请用菜单「打开」。",
            )
            return
        path = Path(self._last_result_dir)
        if not path.exists():
            self.open_result_btn.setEnabled(False)
            self._last_result_dir = None
            self._prefs["last_result_dir"] = ""
            try:
                save_prefs(self._prefs)
            except Exception:
                pass
            QMessageBox.warning(
                self,
                "打开结果",
                f"结果目录已不存在：\n{path}\n\n可用菜单「打开 → output 目录」浏览根目录。",
            )
            return
        self._open_path(path)

    # ----- prefs / settings -----

    def _save_ui_prefs(self) -> None:
        mode = self.current_mode()
        page = None
        if mode == MODE_SINGLE:
            page = self.single_page
        elif mode == MODE_BATCH:
            page = self.batch_page
        elif mode == MODE_SEARCH:
            page = self.search_page

        prompts = []
        enable_llm = True
        save_video = False
        skip_existing = True
        cover_mode = "config"
        browser = ""
        cookies_file = ""
        if page is not None:
            prompts = page.prompts.selected()
            enable_llm = page.pipeline.enable_llm.isChecked()
            save_video = page.pipeline.save_video.isChecked()
            cover_mode = page.cover.mode_key()
            if hasattr(page.pipeline, "skip_existing"):
                skip_existing = page.pipeline.skip_existing.isChecked()
            browser = page.cookies.cookies_from_browser() or ""
            cookies_file = page.cookies.cookies_file_path() or ""
        elif mode == MODE_DOWNLOAD:
            browser = self.download_page.cookies.cookies_from_browser() or ""
            cookies_file = self.download_page.cookies.cookies_file_path() or ""
        elif mode == MODE_TOOLS:
            # 工具页 cookies 也要持久化；为空时保留已有 prefs，避免误清空
            tb = self.tools_page.cookies_auth.cookies_from_browser() or ""
            tf = self.tools_page.cookies_auth.cookies_file_path() or ""
            if tb or tf:
                browser, cookies_file = tb, tf
            else:
                browser = str(self._prefs.get("cookies_from_browser") or "")
                cookies_file = str(self._prefs.get("cookies_file") or "")
            if self.tools_page.tool_kind() == ToolsPage.TOOL_FROM_RAW:
                selected = self.tools_page.prompts.selected()
                if selected:
                    prompts = selected
                cover_mode = self.tools_page.cover_from_raw.mode_key()
            elif self.tools_page.tool_kind() == ToolsPage.TOOL_REGEN_COVER:
                cover_mode = self.tools_page.cover_regen.mode_key()

        self._prefs.update(
            {
                "last_mode": mode,
                "last_prompts": prompts,
                "enable_llm": enable_llm,
                "save_video": save_video,
                "skip_existing": skip_existing,
                "cover_mode": cover_mode,
                "batch_source": self.batch_page.source_type(),
                "cookies_from_browser": browser,
                "cookies_file": cookies_file,
                "media_type": self.download_page.media_type_value(),
                "last_result_dir": str(self._last_result_dir or self._prefs.get("last_result_dir") or ""),
            }
        )
        save_prefs(self._prefs)

    def open_settings(self) -> None:
        dlg = SettingsDialog(self)
        if dlg.exec():
            self._apply_config_cookie_defaults()
            for page in self._pipeline_pages():
                if not page.asr.isChecked():
                    page.asr.load_from_config()
            self.statusBar().showMessage("设置已更新", 3000)

    def _open_blog(self) -> None:
        if not QDesktopServices.openUrl(QUrl(BLOG_URL)):
            QMessageBox.information(
                self,
                BLOG_LABEL,
                f"无法打开浏览器，请手动访问：\n{BLOG_URL}",
            )

    def _about(self) -> None:
        ff_msg = ffmpeg_status_message()
        box = QMessageBox(self)
        box.setWindowTitle(f"关于 {APP_NAME_ZH}")
        box.setIcon(QMessageBox.Information)
        box.setTextFormat(Qt.RichText)
        box.setText(
            f"<p><b>{APP_WINDOW_TITLE}</b><br/>"
            f"{APP_ABOUT}<br/>"
            f"版本 {APP_VERSION}</p>"
            f"<p>功能：单条 / 批量 / B站搜索 / 仅下载 / 补跑工具<br/>"
            f"成稿模板：prompts/articles（GUI 下拉）<br/>"
            f"系统基础提示词：prompts/system（默认不展示）</p>"
            f"<p>{ff_msg}</p>"
            f'<p>作者博客：<a href="{BLOG_URL}">{BLOG_URL}</a></p>'
        )
        box.setStandardButtons(QMessageBox.Ok)
        # Allow clicking the link
        for label in box.findChildren(QLabel):
            label.setOpenExternalLinks(True)
            label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        blog_btn = box.addButton(f"打开{BLOG_LABEL}", QMessageBox.ActionRole)
        box.exec()
        if box.clickedButton() is blog_btn:
            self._open_blog()

    def _open_path(self, path: Path) -> None:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            QMessageBox.warning(self, "无法打开", str(exc))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._worker is not None:
            reply = QMessageBox.question(
                self,
                "任务进行中",
                "有任务仍在运行。确定退出？（后台任务可能被中断）",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
            self.stop_job()
        try:
            self._save_ui_prefs()
        except Exception:
            pass
        event.accept()
