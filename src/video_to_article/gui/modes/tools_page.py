"""补跑与工具：from-raw / regen-cover / check-report / YouTube 登录。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...paths import OUTPUT_DIR
from ..widgets.common_options import CookiesOptions, CoverModeBox, PromptPicker


class ToolsPage(QWidget):
    TOOL_FROM_RAW = "from_raw"
    TOOL_REGEN_COVER = "regen_cover"
    TOOL_CHECK_REPORT = "check_report"
    TOOL_YT_AUTH = "youtube_auth"
    TOOL_YT_REFRESH = "refresh_cookies"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        root = QVBoxLayout(body)

        pick = QGroupBox("选择工具")
        pick_layout = QHBoxLayout(pick)
        pick_layout.setSpacing(12)
        self.radio_from_raw = QRadioButton("补文章")
        self.radio_regen = QRadioButton("重生成封面")
        self.radio_report = QRadioButton("复查报告")
        self.radio_yt_auth = QRadioButton("YT 登录检查")
        self.radio_yt_refresh = QRadioButton("刷新 cookies")
        self.radio_from_raw.setChecked(True)
        self._group = QButtonGroup(self)
        for btn in (
            self.radio_from_raw,
            self.radio_regen,
            self.radio_report,
            self.radio_yt_auth,
            self.radio_yt_refresh,
        ):
            self._group.addButton(btn)
            pick_layout.addWidget(btn)
        pick_layout.addStretch(1)
        root.addWidget(pick)

        # from-raw
        self.box_from_raw = QGroupBox("从 raw 补文章")
        fr = QVBoxLayout(self.box_from_raw)
        row = QHBoxLayout()
        self.raw_edit = QLineEdit()
        self.raw_edit.setPlaceholderText("output\\某视频\\raw.md")
        b1 = QPushButton("浏览…")
        b1.clicked.connect(self._browse_raw)
        row.addWidget(self.raw_edit, 1)
        row.addWidget(b1)
        fr.addLayout(row)
        self.prompts = PromptPicker()
        self.cover_from_raw = CoverModeBox()
        pair = QHBoxLayout()
        pair.setSpacing(10)
        pair.addWidget(self.prompts, 1)
        pair.addWidget(self.cover_from_raw, 1)
        fr.addLayout(pair)
        tip = QLabel("不重新下载、不重新 ASR；适合 LLM 超时后补文章。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#555; font-size: 11pt;")
        fr.addWidget(tip)
        root.addWidget(self.box_from_raw)

        # regen cover
        self.box_regen = QGroupBox("重生成封面")
        rg = QFormLayout(self.box_regen)
        art_row = QHBoxLayout()
        self.article_edit = QLineEdit()
        self.article_edit.setPlaceholderText("output\\某视频\\文章.md")
        b2 = QPushButton("浏览…")
        b2.clicked.connect(self._browse_article)
        art_row.addWidget(self.article_edit, 1)
        art_row.addWidget(b2)
        th_row = QHBoxLayout()
        self.thumb_edit = QLineEdit()
        self.thumb_edit.setPlaceholderText("可选参考图 thumbnail.jpg")
        b3 = QPushButton("浏览…")
        b3.clicked.connect(self._browse_thumb)
        th_row.addWidget(self.thumb_edit, 1)
        th_row.addWidget(b3)
        rg.addRow("文章 Markdown", art_row)
        rg.addRow("参考图（可选）", th_row)
        self.cover_regen = CoverModeBox()
        # default for regen: follow config, but off is invalid at runtime
        rg.addRow(self.cover_regen)
        root.addWidget(self.box_regen)

        # check report
        self.box_report = QGroupBox("复查批量报告")
        rp = QHBoxLayout(self.box_report)
        self.report_edit = QLineEdit()
        self.report_edit.setPlaceholderText("output\\...\\_batch_reports\\batch_report_*.json")
        b4 = QPushButton("浏览…")
        b4.clicked.connect(self._browse_report)
        rp.addWidget(self.report_edit, 1)
        rp.addWidget(b4)
        root.addWidget(self.box_report)

        # youtube auth
        self.box_yt_auth = QGroupBox("YouTube 登录检查")
        ya = QFormLayout(self.box_yt_auth)
        self.yt_url_edit = QLineEdit()
        self.yt_url_edit.setPlaceholderText("可选：https://www.youtube.com/watch?v=… 用于实测请求")
        ya.addRow("测试 URL（可选）", self.yt_url_edit)
        self.cookies_auth = CookiesOptions()
        ya.addRow(self.cookies_auth)
        root.addWidget(self.box_yt_auth)

        # refresh cookies
        self.box_yt_refresh = QGroupBox("刷新 cookies 文件")
        yf = QFormLayout(self.box_yt_refresh)
        self.refresh_browser = QComboBox()
        for name in ("firefox", "chrome", "edge"):
            self.refresh_browser.addItem(name, name)
        self.refresh_out = QLineEdit()
        self.refresh_out.setPlaceholderText("空=默认 data\\cookies\\youtube.txt")
        yf.addRow("浏览器", self.refresh_browser)
        yf.addRow("输出文件（可选）", self.refresh_out)
        tip2 = QLabel("请先在浏览器登录 YouTube，再执行刷新。")
        tip2.setWordWrap(True)
        tip2.setStyleSheet("color:#555;")
        yf.addRow(tip2)
        root.addWidget(self.box_yt_refresh)

        root.addStretch(1)

        for btn in self._group.buttons():
            btn.toggled.connect(self._sync_visibility)
        self._sync_visibility()

    def _sync_visibility(self) -> None:
        tool = self.tool_kind()
        self.box_from_raw.setVisible(tool == self.TOOL_FROM_RAW)
        self.box_regen.setVisible(tool == self.TOOL_REGEN_COVER)
        self.box_report.setVisible(tool == self.TOOL_CHECK_REPORT)
        self.box_yt_auth.setVisible(tool == self.TOOL_YT_AUTH)
        self.box_yt_refresh.setVisible(tool == self.TOOL_YT_REFRESH)

    def tool_kind(self) -> str:
        if self.radio_regen.isChecked():
            return self.TOOL_REGEN_COVER
        if self.radio_report.isChecked():
            return self.TOOL_CHECK_REPORT
        if self.radio_yt_auth.isChecked():
            return self.TOOL_YT_AUTH
        if self.radio_yt_refresh.isChecked():
            return self.TOOL_YT_REFRESH
        return self.TOOL_FROM_RAW

    def set_tool_kind(self, kind: str) -> None:
        mapping = {
            self.TOOL_FROM_RAW: self.radio_from_raw,
            self.TOOL_REGEN_COVER: self.radio_regen,
            self.TOOL_CHECK_REPORT: self.radio_report,
            self.TOOL_YT_AUTH: self.radio_yt_auth,
            self.TOOL_YT_REFRESH: self.radio_yt_refresh,
        }
        btn = mapping.get(kind, self.radio_from_raw)
        btn.setChecked(True)

    def _browse_raw(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 raw.md", str(OUTPUT_DIR), "Markdown (*.md);;All (*.*)"
        )
        if path:
            self.raw_edit.setText(path)

    def _browse_article(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择文章 Markdown", str(OUTPUT_DIR), "Markdown (*.md);;All (*.*)"
        )
        if path:
            self.article_edit.setText(path)

    def _browse_thumb(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择参考图", str(OUTPUT_DIR), "Images (*.jpg *.jpeg *.png *.webp);;All (*.*)"
        )
        if path:
            self.thumb_edit.setText(path)

    def _browse_report(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择批量报告", str(OUTPUT_DIR), "JSON (*.json);;All (*.*)"
        )
        if path:
            self.report_edit.setText(path)

    def validate(self) -> str | None:
        tool = self.tool_kind()
        if tool == self.TOOL_FROM_RAW:
            path = self.raw_edit.text().strip()
            if not path:
                return "请选择 raw.md"
            if not Path(path).exists():
                return f"文件不存在: {path}"
            if not self.prompts.selected():
                return "请至少勾选一个提示词"
            return None
        if tool == self.TOOL_REGEN_COVER:
            path = self.article_edit.text().strip()
            if not path:
                return "请选择文章 Markdown"
            if not Path(path).exists():
                return f"文件不存在: {path}"
            if self.cover_regen.mode_key() == "off":
                return "重生成封面不能选择「完全跳过封面」"
            thumb = self.thumb_edit.text().strip()
            if thumb and not Path(thumb).exists():
                return f"参考图不存在: {thumb}"
            return None
        if tool == self.TOOL_CHECK_REPORT:
            path = self.report_edit.text().strip()
            if not path:
                return "请选择批量报告 JSON"
            if not Path(path).exists():
                return f"文件不存在: {path}"
            return None
        if tool == self.TOOL_YT_AUTH:
            return None
        if tool == self.TOOL_YT_REFRESH:
            return None
        return None
