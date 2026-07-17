"""Video search: platform + keyword → results table → process options."""

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

    PLATFORM_BILIBILI = "bilibili"
    PLATFORM_YOUTUBE = "youtube"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _, _, root = page_scroll_root(self)

        search_card = CardWidget()
        sc = QVBoxLayout(search_card)
        sc.setContentsMargins(*card_margins())
        sc.setSpacing(SPACE_ROW)
        sc.addWidget(card_header("视频搜索"))

        row = QHBoxLayout()
        row.setSpacing(SPACE_ROW)

        self.platform = ComboBox()
        for label, value in (
            ("B 站", self.PLATFORM_BILIBILI),
            ("YouTube", self.PLATFORM_YOUTUBE),
        ):
            self.platform.addItem(label)
            self.platform.setItemData(self.platform.count() - 1, value)
        self.platform.setMinimumWidth(108)
        self.platform.setFixedWidth(118)
        self.platform.setMinimumHeight(32)
        self.platform.setToolTip(
            "支持关键词搜索：B 站、YouTube。\n"
            "抖音 / 小红书等暂无稳定公开搜索接口，请用「单条处理」粘贴视频链接。"
        )
        self.platform.currentIndexChanged.connect(self._on_platform_changed)

        self.keyword = LineEdit()
        self.keyword.setPlaceholderText("输入关键词，例如：家常菜教程")
        self.keyword.setMinimumHeight(32)
        self.keyword.returnPressed.connect(self.search_requested.emit)

        self.count = SpinBox()
        self.count.setRange(1, 50)
        self.count.setValue(5)
        self.count.setMinimumWidth(150)
        self.count.setMaximumWidth(160)
        self.count.setMinimumHeight(32)
        self.count.setToolTip("搜索结果条数（1～50）")

        self.order = ComboBox()
        self.order.setMinimumWidth(120)
        self.order.setFixedWidth(128)
        self.order.setMinimumHeight(32)

        self.search_btn = PrimaryPushButton("搜索")
        self.search_btn.setFixedWidth(88)
        self.search_btn.setMinimumHeight(32)
        self.search_btn.clicked.connect(self.search_requested.emit)

        row.addWidget(CaptionLabel("平台"), 0, Qt.AlignVCenter)
        row.addWidget(self.platform, 0, Qt.AlignVCenter)
        row.addWidget(self.keyword, 1)
        row.addWidget(CaptionLabel("数量"), 0, Qt.AlignVCenter)
        row.addWidget(self.count, 0, Qt.AlignVCenter)
        row.addWidget(CaptionLabel("排序"), 0, Qt.AlignVCenter)
        row.addWidget(self.order, 0, Qt.AlignVCenter)
        row.addWidget(self.search_btn, 0, Qt.AlignVCenter)
        sc.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(SPACE_ROW)
        self.select_all_btn = PushButton("全选")
        self.select_none_btn = PushButton("全不选")
        # 勿写死过窄宽度，否则「全不选」会被裁字
        self.select_all_btn.setMinimumWidth(72)
        self.select_all_btn.setMinimumHeight(32)
        self.select_none_btn.setMinimumWidth(80)
        self.select_none_btn.setMinimumHeight(32)
        self.select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        self.select_none_btn.clicked.connect(lambda: self._set_all_checked(False))
        self.hint = CaptionLabel(
            "先搜索 → 勾选要处理的条目 → 底部「开始」。双击某一行可在浏览器打开原视频。"
        )
        self.hint.setWordWrap(True)
        row2.addWidget(self.select_all_btn)
        row2.addWidget(self.select_none_btn)
        row2.addSpacing(8)
        row2.addWidget(self.hint, 1)
        sc.addLayout(row2)
        root.addWidget(search_card)

        results = CardWidget()
        rc = QVBoxLayout(results)
        rc.setContentsMargins(*card_margins())
        rc.setSpacing(SPACE_ROW)
        rc.addWidget(card_header("搜索结果"))
        self.table = JobTable(with_check=True, search_mode=True)
        self.table.setMinimumHeight(240)
        rc.addWidget(self.table)
        root.addWidget(results)

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
        self._on_platform_changed()

    def platform_key(self) -> str:
        return str(self.platform.currentData() or self.PLATFORM_BILIBILI)

    def _on_platform_changed(self) -> None:
        platform = self.platform_key()
        self.order.blockSignals(True)
        self.order.clear()
        if platform == self.PLATFORM_YOUTUBE:
            options = (
                ("相关程度", "relevance"),
                ("最新上传", "date"),
            )
            self.keyword.setPlaceholderText("YouTube 关键词，例如：home cooking")
        else:
            options = (
                ("综合排序", "totalrank"),
                ("最新发布", "pubdate"),
                ("最多播放", "click"),
                ("最多弹幕", "dm"),
            )
            self.keyword.setPlaceholderText("B 站关键词，例如：家常菜教程")
        for label, value in options:
            self.order.addItem(label)
            self.order.setItemData(self.order.count() - 1, value)
        self.order.blockSignals(False)

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        if not self.table.with_check:
            return
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None:
                item.setCheckState(state)

    def search_params(self) -> tuple[str, str, int, str]:
        return (
            self.platform_key(),
            self.keyword.text().strip(),
            int(self.count.value()),
            str(self.order.currentData() or ""),
        )

    def validate_search(self) -> str | None:
        _, keyword, _, _ = self.search_params()
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
            meta_parts = []
            if duration is not None:
                if isinstance(duration, (int, float)) and duration >= 0:
                    total = int(duration)
                    m, s = divmod(total, 60)
                    h, m = divmod(m, 60)
                    meta_parts.append(f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}")
                else:
                    meta_parts.append(str(duration))
            if play is not None:
                try:
                    n = int(play)
                    if n >= 10000:
                        meta_parts.append(f"{n / 10000:.1f}万播放")
                    else:
                        meta_parts.append(f"{n}播放")
                except (TypeError, ValueError):
                    meta_parts.append(f"播放 {play}")
            items.append(
                {
                    "url": url,
                    "title": title or url,
                    "author": author,
                    "meta": " · ".join(meta_parts) if meta_parts else "",
                    "status": "待处理",
                }
            )
        self.table.set_items(items, check_all=True)
        plat = "YouTube" if self.platform_key() == self.PLATFORM_YOUTUBE else "B 站"
        self.hint.setText(
            f"{plat}：共 {len(items)} 条。双击行可打开原视频；勾选后点底部「开始」处理。"
        )

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
