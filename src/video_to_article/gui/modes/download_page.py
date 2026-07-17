"""Download-only mode page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    LineEdit,
    PushButton,
    RadioButton,
)

from ...batch import read_batch_file
from ...paths import DATA_DIR
from ..theme_style import SPACE_ROW, card_margins
from ..widgets.common_options import CookiesOptions
from ..widgets.layout_utils import card_header, grid_two_col, page_scroll_root


class DownloadPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _, _, root = page_scroll_root(self)

        src_box = CardWidget()
        src_layout = QVBoxLayout(src_box)
        src_layout.setContentsMargins(*card_margins())
        src_layout.setSpacing(SPACE_ROW)
        src_layout.addWidget(card_header("输入来源"))

        mode_row = QHBoxLayout()
        mode_row.setSpacing(16)
        self.radio_url = RadioButton("单个链接")
        self.radio_batch = RadioButton("批量清单")
        self.radio_url.setChecked(True)
        self._group = QButtonGroup(self)
        self._group.addButton(self.radio_url)
        self._group.addButton(self.radio_batch)
        mode_row.addWidget(self.radio_url)
        mode_row.addWidget(self.radio_batch)
        mode_row.addStretch(1)
        src_layout.addLayout(mode_row)

        url_row = QHBoxLayout()
        self.url_edit = LineEdit()
        self.url_edit.setPlaceholderText("https://…")
        self.url_edit.setMinimumHeight(32)
        url_row.addWidget(CaptionLabel("链接"))
        url_row.addWidget(self.url_edit, 1)
        src_layout.addLayout(url_row)

        batch_row = QHBoxLayout()
        self.batch_edit = LineEdit()
        self.batch_edit.setPlaceholderText("清单文件路径")
        browse = PushButton("浏览")
        browse.setFixedWidth(64)
        browse.clicked.connect(self._browse)
        batch_row.addWidget(CaptionLabel("清单"))
        batch_row.addWidget(self.batch_edit, 1)
        batch_row.addWidget(browse)
        src_layout.addLayout(batch_row)

        opts = CardWidget()
        opts_layout = QVBoxLayout(opts)
        opts_layout.setContentsMargins(*card_margins())
        opts_layout.setSpacing(SPACE_ROW)
        opts_layout.addWidget(card_header("下载选项"))
        opt_row = QHBoxLayout()
        opt_row.setSpacing(SPACE_ROW)
        self.media_type = ComboBox()
        self._media_keys = ["video", "audio", "both", "none"]
        for label, key in (
            ("仅视频", "video"),
            ("仅音频", "audio"),
            ("音频+视频", "both"),
            ("仅字幕", "none"),
        ):
            self.media_type.addItem(label)
            self.media_type.setItemData(self.media_type.count() - 1, key)
        self.limit_edit = LineEdit()
        self.limit_edit.setPlaceholderText("批量条数，空=不限")
        self.limit_edit.setMaximumWidth(140)
        opt_row.addWidget(CaptionLabel("类型"))
        opt_row.addWidget(self.media_type, 1)
        opt_row.addWidget(CaptionLabel("限制"))
        opt_row.addWidget(self.limit_edit)
        opts_layout.addLayout(opt_row)
        self.download_subs = CheckBox("下载字幕（srt/vtt）")
        self.download_subs.setChecked(False)
        opts_layout.addWidget(self.download_subs)
        lang_row = QHBoxLayout()
        lang_row.setSpacing(SPACE_ROW)
        self.subs_lang = LineEdit()
        self.subs_lang.setPlaceholderText("可选：zh,zh-Hans,en（空=默认中英）")
        lang_row.addWidget(CaptionLabel("语言"))
        lang_row.addWidget(self.subs_lang, 1)
        opts_layout.addLayout(lang_row)
        opts_layout.addWidget(CaptionLabel("不转写、不调用大模型、不生成封面"))
        self.media_type.currentIndexChanged.connect(self._on_media_type_changed)
        self._on_media_type_changed()

        # 顶对齐，避免矮卡片被拉高
        root.addWidget(grid_two_col([src_box, opts]))

        self.cookies = CookiesOptions()
        root.addWidget(self.cookies)
        root.addStretch(1)

        self.radio_url.toggled.connect(self._sync_enabled)
        self._sync_enabled()

    def _sync_enabled(self) -> None:
        is_url = self.radio_url.isChecked()
        self.url_edit.setEnabled(is_url)
        self.batch_edit.setEnabled(not is_url)
        self.limit_edit.setEnabled(not is_url)

    def _on_media_type_changed(self) -> None:
        # 仅字幕时强制勾选下载字幕
        if self.media_type_value() == "none":
            self.download_subs.setChecked(True)
            self.download_subs.setEnabled(False)
        else:
            self.download_subs.setEnabled(True)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择批量清单",
            str(DATA_DIR),
            "Text (*.txt);;All (*.*)",
        )
        if path:
            self.batch_edit.setText(path)
            self.radio_batch.setChecked(True)

    def is_batch(self) -> bool:
        return self.radio_batch.isChecked()

    def media_type_value(self) -> str:
        data = self.media_type.currentData()
        if data:
            return str(data)
        idx = self.media_type.currentIndex()
        if 0 <= idx < len(self._media_keys):
            return self._media_keys[idx]
        return "video"

    def download_subs_enabled(self) -> bool:
        return bool(self.download_subs.isChecked())

    def subtitle_langs(self) -> list[str] | None:
        text = self.subs_lang.text().strip()
        if not text:
            return None
        langs = [p.strip() for p in text.split(",") if p.strip()]
        return langs or None

    def limit_value(self) -> int | None:
        text = self.limit_edit.text().strip()
        if not text:
            return None
        try:
            value = int(text)
            return value if value > 0 else None
        except ValueError:
            return None

    def validate(self) -> str | None:
        if self.media_type_value() == "none" and not self.download_subs_enabled():
            return "选择「仅字幕」时请勾选「下载字幕」"
        if self.is_batch():
            path = self.batch_edit.text().strip()
            if not path:
                return "请选择批量清单"
            if not Path(path).exists():
                return f"清单不存在: {path}"
            urls, _ = read_batch_file(Path(path))
            if not urls:
                return "清单为空"
            raw = self.limit_edit.text().strip()
            if raw and self.limit_value() is None:
                return "限制条数请填写正整数，或留空"
        else:
            url = self.url_edit.text().strip()
            if not url:
                return "请填写下载链接"
            if not url.startswith(("http://", "https://")):
                return "仅下载模式需要在线链接（本地文件请用「单条处理」）"
        return None
