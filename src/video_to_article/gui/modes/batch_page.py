"""Batch processing: list file / local directory / YouTube collection."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    CardWidget,
    CheckBox,
    LineEdit,
    PushButton,
    RadioButton,
    SpinBox,
)

from ...batch import find_local_videos, read_batch_file
from ...paths import DATA_DIR, LOCAL_MEDIA_EXTENSIONS
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


class BatchPage(QWidget):
    SOURCE_LIST = "list"
    SOURCE_LOCAL = "local_dir"
    SOURCE_YOUTUBE = "youtube"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _, _, root = page_scroll_root(self)

        # 来源全宽（避免左右等高拉伸出大空白）
        src = CardWidget()
        src_layout = QVBoxLayout(src)
        src_layout.setContentsMargins(*card_margins())
        src_layout.setSpacing(SPACE_ROW)
        preview_btn = PushButton("预览列表")
        preview_btn.setFixedWidth(88)
        preview_btn.clicked.connect(self.preview)
        src_layout.addWidget(card_header("输入来源", [preview_btn]))

        mode_row = QHBoxLayout()
        mode_row.setSpacing(16)
        self.radio_list = RadioButton("清单文件")
        self.radio_local = RadioButton("本地目录")
        self.radio_youtube = RadioButton("YouTube 合集")
        self.radio_list.setChecked(True)
        self._src_group = QButtonGroup(self)
        for btn in (self.radio_list, self.radio_local, self.radio_youtube):
            self._src_group.addButton(btn)
            mode_row.addWidget(btn)
        mode_row.addStretch(1)
        src_layout.addLayout(mode_row)

        list_row = QHBoxLayout()
        self.list_edit = LineEdit()
        self.list_edit.setPlaceholderText("data\\urls.txt")
        list_browse = PushButton("浏览")
        list_browse.setFixedWidth(64)
        list_browse.clicked.connect(self._browse_list)
        list_row.addWidget(CaptionLabel("清单"))
        list_row.addWidget(self.list_edit, 1)
        list_row.addWidget(list_browse)
        src_layout.addLayout(list_row)

        dir_row = QHBoxLayout()
        self.dir_edit = LineEdit()
        self.dir_edit.setPlaceholderText("本地媒体目录")
        dir_browse = PushButton("目录")
        dir_browse.setFixedWidth(64)
        dir_browse.clicked.connect(self._browse_dir)
        dir_row.addWidget(CaptionLabel("目录"))
        dir_row.addWidget(self.dir_edit, 1)
        dir_row.addWidget(dir_browse)
        self.recursive = CheckBox("递归")
        self.recursive.setChecked(True)
        dir_row.addWidget(self.recursive)
        src_layout.addLayout(dir_row)

        yt_row = QHBoxLayout()
        self.yt_edit = LineEdit()
        self.yt_edit.setPlaceholderText("频道 / 播放列表 URL")
        self.yt_limit = SpinBox()
        self.yt_limit.setRange(0, 5000)
        self.yt_limit.setSpecialValueText("不限展开")
        self.yt_limit.setValue(0)
        # Fluent SpinBox 过窄会裁掉数字区，只剩箭头
        self.yt_limit.setMinimumWidth(150)
        self.yt_limit.setMaximumWidth(170)
        yt_row.addWidget(CaptionLabel("合集"))
        yt_row.addWidget(self.yt_edit, 1)
        yt_row.addWidget(CaptionLabel("上限"))
        yt_row.addWidget(self.yt_limit)
        src_layout.addLayout(yt_row)

        self.preview_label = CaptionLabel(
            "尚未预览。清单可直接开始；本地目录 / YouTube 建议先点「预览列表」。"
            " 限制条数建议 1～3。格式: "
            + ", ".join(sorted(LOCAL_MEDIA_EXTENSIONS)[:6])
            + "…"
        )
        self.preview_label.setWordWrap(True)
        src_layout.addWidget(self.preview_label)
        root.addWidget(src)

        table_card = CardWidget()
        tc = QVBoxLayout(table_card)
        tc.setContentsMargins(*card_margins())
        tc.setSpacing(SPACE_ROW)
        tc.addWidget(card_header("条目预览"))
        self.table = JobTable(with_check=False)
        self.table.setMinimumHeight(180)
        tc.addWidget(self.table)
        root.addWidget(table_card)

        self.prompts = PromptPicker()
        self.pipeline = PipelineOptions(show_skip=True, show_dry_run=True)
        self.cover = CoverModeBox()
        self.cookies = CookiesOptions()
        root.addWidget(grid_two_col([self.prompts, self.pipeline, self.cover, self.cookies]))

        self.asr = AsrOptions()
        root.addWidget(self.asr)

        adv = QGroupBox("高级：批量额外选项")
        adv.setCheckable(True)
        adv.setChecked(False)
        adv_form = QGridLayout(adv)
        adv_form.setHorizontalSpacing(12)
        adv_form.setVerticalSpacing(6)
        self.batch_root_edit = LineEdit()
        self.batch_root_edit.setPlaceholderText("可选 batch-root")
        self.write_list = CheckBox("写入清单 --write-list")
        self.write_list_path = LineEdit()
        self.write_list_path.setPlaceholderText("空/auto → data/…")
        self.auto_repair = CheckBox("自动补救 --auto-repair")
        self.repair_rounds = SpinBox()
        self.repair_rounds.setRange(1, 10)
        self.repair_rounds.setValue(2)
        self.repair_delay = SpinBox()
        self.repair_delay.setRange(0, 600)
        self.repair_delay.setValue(0)
        self.repair_delay.setSuffix(" 秒")
        adv_form.addWidget(CaptionLabel("batch-root"), 0, 0)
        adv_form.addWidget(self.batch_root_edit, 0, 1)
        adv_form.addWidget(self.write_list, 0, 2)
        adv_form.addWidget(self.write_list_path, 0, 3)
        adv_form.addWidget(self.auto_repair, 1, 0, 1, 2)
        adv_form.addWidget(CaptionLabel("轮数"), 1, 2)
        adv_form.addWidget(self.repair_rounds, 1, 3)
        adv_form.addWidget(CaptionLabel("间隔"), 1, 4)
        adv_form.addWidget(self.repair_delay, 1, 5)
        root.addWidget(adv)
        self.adv_box = adv
        root.addStretch(1)

        self.pipeline.enable_llm.toggled.connect(self.prompts.set_enabled_prompts)
        self.radio_list.toggled.connect(self._sync_source_enabled)
        self.radio_local.toggled.connect(self._sync_source_enabled)
        self.radio_youtube.toggled.connect(self._sync_source_enabled)
        self._sync_source_enabled()
        self._preview_cache: list[dict] = []

    def _sync_source_enabled(self) -> None:
        is_list = self.radio_list.isChecked()
        is_local = self.radio_local.isChecked()
        is_yt = self.radio_youtube.isChecked()
        self.list_edit.setEnabled(is_list)
        self.dir_edit.setEnabled(is_local)
        self.recursive.setEnabled(is_local)
        self.yt_edit.setEnabled(is_yt)
        self.yt_limit.setEnabled(is_yt)

    def source_type(self) -> str:
        if self.radio_local.isChecked():
            return self.SOURCE_LOCAL
        if self.radio_youtube.isChecked():
            return self.SOURCE_YOUTUBE
        return self.SOURCE_LIST

    def set_source_type(self, key: str) -> None:
        if key == self.SOURCE_LOCAL:
            self.radio_local.setChecked(True)
        elif key == self.SOURCE_YOUTUBE:
            self.radio_youtube.setChecked(True)
        else:
            self.radio_list.setChecked(True)

    def _browse_list(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择批量清单", str(DATA_DIR), "Text (*.txt);;All (*.*)"
        )
        if path:
            self.list_edit.setText(path)
            self.radio_list.setChecked(True)
            self.preview()

    def _browse_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择本地媒体目录", str(DATA_DIR))
        if path:
            self.dir_edit.setText(path)
            self.radio_local.setChecked(True)
            self.preview()

    def list_path(self) -> str:
        return self.list_edit.text().strip()

    def local_dir(self) -> str:
        return self.dir_edit.text().strip()

    def youtube_url(self) -> str:
        return self.yt_edit.text().strip()

    def youtube_expand_limit(self) -> int | None:
        value = int(self.yt_limit.value())
        return value if value > 0 else None

    def preview(self) -> None:
        st = self.source_type()
        try:
            if st == self.SOURCE_LIST:
                path = self.list_path()
                if not path:
                    self.preview_label.setText("请先选择清单文件")
                    return
                p = Path(path)
                if not p.exists():
                    self.preview_label.setText(f"文件不存在: {path}")
                    return
                urls, batch_root = read_batch_file(p)
                items = [{"url": u, "title": u, "status": "待处理", "note": ""} for u in urls]
                self._preview_cache = items
                self.table.set_items(items)
                root_txt = f"；batch_root={batch_root}" if batch_root else ""
                self.preview_label.setText(f"清单共 {len(urls)} 条{root_txt}")
            elif st == self.SOURCE_LOCAL:
                directory = self.local_dir()
                if not directory:
                    self.preview_label.setText("请选择本地目录")
                    return
                videos = find_local_videos(directory=directory, recursive=self.recursive.isChecked())
                items = [
                    {"url": v, "title": Path(v).name, "status": "待处理", "note": str(Path(v).parent)}
                    for v in videos
                ]
                self._preview_cache = items
                self.table.set_items(items)
                self.preview_label.setText(
                    f"找到 {len(videos)} 个媒体（{'递归' if self.recursive.isChecked() else '当前层'}）"
                )
            else:
                url = self.youtube_url()
                if not url:
                    self.preview_label.setText("请填写 YouTube 合集 URL")
                    return
                self.table.clear_rows()
                self._preview_cache = []
                lim = self.youtube_expand_limit()
                self.preview_label.setText(
                    f"开始时展开：{url}"
                    + (f"（上限 {lim}）" if lim else "（不限展开）")
                    + " · 可先 dry-run"
                )
        except Exception as exc:
            self.preview_label.setText(f"预览失败: {exc}")

    def apply_result_statuses(self, results: list) -> None:
        if isinstance(results, list):
            self.table.apply_results(results)

    def validate(self) -> str | None:
        st = self.source_type()
        if st == self.SOURCE_LIST:
            path = self.list_path()
            if not path:
                return "请选择批量清单文件"
            if not Path(path).exists():
                return f"清单不存在: {path}"
            urls, _ = read_batch_file(Path(path))
            if not urls:
                return "清单为空"
        elif st == self.SOURCE_LOCAL:
            directory = self.local_dir()
            if not directory:
                return "请选择本地目录"
            if not Path(directory).is_dir():
                return f"不是有效目录: {directory}"
        else:
            url = self.youtube_url()
            if not url:
                return "请填写 YouTube 合集 URL"
            if "youtube.com" not in url and "youtu.be" not in url:
                return "请填写有效的 YouTube 链接"
        if self.pipeline.enable_llm.isChecked() and not self.prompts.selected():
            return "已启用大模型，请至少选择一个文章模板"
        raw_limit = self.pipeline.limit_edit.text().strip()
        if raw_limit and self.pipeline.limit_value() is None:
            return "限制条数请填写正整数，或留空"
        return None

    def batch_root_override(self) -> str | None:
        text = self.batch_root_edit.text().strip()
        return text or None

    def write_list_enabled(self) -> bool:
        return self.write_list.isChecked()

    def write_list_path_value(self) -> str:
        return self.write_list_path.text().strip()

    def auto_repair_enabled(self) -> bool:
        return self.auto_repair.isChecked()

    def repair_rounds_value(self) -> int:
        return int(self.repair_rounds.value())

    def repair_delay_value(self) -> int:
        return int(self.repair_delay.value())
