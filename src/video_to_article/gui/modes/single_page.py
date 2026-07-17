"""Single URL / local file processing page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QVBoxLayout, QWidget
from qfluentwidgets import CaptionLabel, CardWidget, LineEdit, PushButton

from ..theme_style import SPACE_ROW, card_margins
from ..widgets.common_options import AsrOptions, CookiesOptions, CoverModeBox, PipelineOptions, PromptPicker
from ..widgets.layout_utils import card_header, grid_two_col, page_scroll_root


class SinglePage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _, _, root = page_scroll_root(self)

        # --- input card (full width) ---
        input_card = CardWidget()
        ic = QVBoxLayout(input_card)
        ic.setContentsMargins(*card_margins())
        ic.setSpacing(SPACE_ROW)
        browse = PushButton("浏览文件")
        browse.setFixedWidth(88)
        browse.clicked.connect(self._browse)
        ic.addWidget(card_header("输入", [browse]))
        ic.addWidget(CaptionLabel("视频链接或本地音视频文件"))
        self.input_edit = LineEdit()
        self.input_edit.setPlaceholderText("https://…  或  D:\\视频\\xxx.mp4")
        self.input_edit.setMinimumHeight(32)
        ic.addWidget(self.input_edit)
        root.addWidget(input_card)

        # --- options: 2×2 grid ---
        self.prompts = PromptPicker()
        self.pipeline = PipelineOptions(show_skip=False, show_dry_run=False)
        self.cover = CoverModeBox()
        self.cookies = CookiesOptions()
        # 主参数 2×2：同行等高（equal_height=True）
        root.addWidget(
            grid_two_col(
                [self.prompts, self.pipeline, self.cover, self.cookies],
                equal_height=True,
            )
        )

        # 高级：全宽，不进 2×2
        self.asr = AsrOptions()
        root.addWidget(self.asr)
        root.addStretch(1)

        # 功能：禁用 LLM 时灰掉模板选择
        self.pipeline.enable_llm.toggled.connect(self.prompts.set_enabled_prompts)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择本地媒体",
            "",
            "Media (*.mp4 *.mkv *.mov *.webm *.mp3 *.m4a *.wav);;All (*.*)",
        )
        if path:
            self.input_edit.setText(path)

    def source(self) -> str:
        return self.input_edit.text().strip()

    def validate(self) -> str | None:
        src = self.source()
        if not src:
            return "请填写视频链接或本地文件路径"
        if not src.startswith(("http://", "https://")):
            if not Path(src).exists():
                return f"本地文件不存在: {src}"
        if self.pipeline.enable_llm.isChecked() and not self.prompts.selected():
            return "已启用大模型，请至少选择一个文章模板"
        return None
