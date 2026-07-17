"""Bilibili search: search toolbar → results table → process options."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    CardWidget,
    ComboBox,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SpinBox,
)

from ..theme_style import SPACE_ROW, card_margins
from ..widgets.common_options import (
    AsrOptions,
    CookiesOptions,
    CoverModeBox,
    PipelineOptions,
    PromptPicker,
)
from ..widgets.job_table import JobTable
from ..widgets.layout_utils import card_header, grid_two_col, page_scroll_root


class SearchPage(QWidget):
    """Search is page-local; processing uses main window Start."""

    search_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _, _, root = page_scroll_root(self)

        # —— 顶部工具条式搜索（全宽、紧凑，避免左右等高空白）——
        search_card = CardWidget()
        sc = QVBoxLayout(search_card)
        sc.setContentsMargins(*card_margins())
        sc.setSpacing(SPACE_ROW)
        sc.addWidget(card_header("搜索 B 站"))

        # 第一行：关键词占满 + 数量 + 排序 + 主按钮
        row = QHBoxLayout()
        row.setSpacing(SPACE_ROW)
        self.keyword = LineEdit()
        self.keyword.setPlaceholderText("输入关键词，例如：家常菜教程")
        self.keyword.setMinimumHeight(32)
        self.keyword.returnPressed.connect(self.search_requested.emit)

        # Fluent SpinBox 默认最小宽约 140+，过窄会只剩上下箭头、数字被裁掉
        self.count = SpinBox()
        self.count.setRange(1, 50)
        self.count.setValue(5)
        self.count.setMinimumWidth(150)
        self.count.setMaximumWidth(160)
        self.count.setMinimumHeight(32)
        self.count.setToolTip("搜索结果条数（1～50）")

        self.order = ComboBox()
        for label, value in (
            ("综合排序", "totalrank"),
            ("最新发布", "pubdate"),
            ("最多播放", "click"),
            ("最多弹幕", "dm"),
        ):
            self.order.addItem(label)
            self.order.setItemData(self.order.count() - 1, value)
        # 给「综合排序」等完整文案留宽度，避免截成「综合排」
        self.order.setMinimumWidth(120)
        self.order.setFixedWidth(128)
        self.order.setMinimumHeight(32)

        self.search_btn = PrimaryPushButton("搜索")
        self.search_btn.setFixedWidth(88)
        self.search_btn.setMinimumHeight(32)
        self.search_btn.clicked.connect(self.search_requested.emit)

        row.addWidget(self.keyword, 1)
        row.addWidget(CaptionLabel("数量"), 0, Qt.AlignVCenter)
        row.addWidget(self.count, 0, Qt.AlignVCenter)
        row.addWidget(CaptionLabel("排序"), 0, Qt.AlignVCenter)
        row.addWidget(self.order, 0, Qt.AlignVCenter)
        row.addWidget(self.search_btn, 0, Qt.AlignVCenter)
        sc.addLayout(row)

        # 第二行：次要操作 + 说明
        row2 = QHBoxLayout()
        row2.setSpacing(SPACE_ROW)
        self.select_all_btn = PushButton("全选")
        self.select_none_btn = PushButton("全不选")
        self.select_all_btn.setFixedWidth(72)
        self.select_none_btn.setFixedWidth(72)
        self.select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        self.select_none_btn.clicked.connect(lambda: self._set_all_checked(False))
        self.hint = CaptionLabel("两步：先搜索 → 勾选结果 → 再点底部「开始处理勾选」（不会搜完自动全跑）")
        self.hint.setWordWrap(True)
        row2.addWidget(self.select_all_btn)
        row2.addWidget(self.select_none_btn)
        row2.addSpacing(8)
        row2.addWidget(self.hint, 1)
        sc.addLayout(row2)
        root.addWidget(search_card)

        # —— 结果表全宽 ——
        results = CardWidget()
        rc = QVBoxLayout(results)
        rc.setContentsMargins(*card_margins())
        rc.setSpacing(SPACE_ROW)
        rc.addWidget(card_header("搜索结果"))
        self.table = JobTable(with_check=True)
        self.table.setMinimumHeight(220)
        rc.addWidget(self.table)
        root.addWidget(results)

        # —— 处理选项 2×2 ——
        self.prompts = PromptPicker()
        self.pipeline = PipelineOptions(show_skip=True, show_dry_run=True)
        self.cover = CoverModeBox()
        self.cookies = CookiesOptions()
        root.addWidget(grid_two_col([self.prompts, self.pipeline, self.cover, self.cookies]))

        self.asr = AsrOptions()
        root.addWidget(self.asr)
        root.addStretch(1)

        self.pipeline.enable_llm.toggled.connect(self.prompts.set_enabled_prompts)
        self._videos: list[dict] = []

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        if not self.table.with_check:
            return
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None:
                item.setCheckState(state)

    def search_params(self) -> tuple[str, int, str]:
        return (
            self.keyword.text().strip(),
            int(self.count.value()),
            str(self.order.currentData() or "totalrank"),
        )

    def validate_search(self) -> str | None:
        keyword, _, _ = self.search_params()
        if not keyword:
            return "请填写搜索关键词"
        return None

    def set_search_results(self, videos: list[dict]) -> None:
        self._videos = list(videos or [])
        items = []
        for v in self._videos:
            title = str(v.get("title") or "")
            author = str(v.get("author") or "")
            url = str(v.get("url") or "")
            duration = v.get("duration")
            play = v.get("play")
            note = f"{author}"
            if duration is not None:
                note += f" · {duration}s" if isinstance(duration, (int, float)) else f" · {duration}"
            if play is not None:
                note += f" · 播放 {play}"
            items.append({"url": url, "title": title or url, "status": "待处理", "note": note})
        self.table.set_items(items, check_all=True)
        self.hint.setText(f"找到 {len(items)} 个结果，默认全选。确认后点底部「开始处理勾选」。")

    def selected_urls(self) -> list[str]:
        return self.table.checked_urls()

    def apply_result_statuses(self, results: list) -> None:
        if isinstance(results, list):
            self.table.apply_results(results)

    def validate_process(self) -> str | None:
        if self.table.rowCount() == 0:
            return "请先搜索并得到结果"
        if not self.selected_urls():
            return "请至少勾选一条搜索结果"
        if self.pipeline.enable_llm.isChecked() and not self.prompts.selected():
            return "已启用大模型，请至少选择一个文章模板"
        raw_limit = self.pipeline.limit_edit.text().strip()
        if raw_limit and self.pipeline.limit_value() is None:
            return "限制条数请填写正整数，或留空"
        return None
