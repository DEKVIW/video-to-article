"""Shared option panels — unified skeleton, equal-height friendly, clicks intact."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
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
    SpinBox,
)

from ...config import load_config
from ...cover import COVER_MODE_OFF, COVER_MODE_PROMPT_ONLY
from ...paths import DATA_DIR, PROMPTS_DIR
from ...prompts import default_article_prompt_names, list_article_prompts
from ..theme_style import SPACE_ROW
from .layout_utils import attach_card_skeleton, card_header


def _body_box() -> tuple[QWidget, QVBoxLayout]:
    """主内容区：内容顶对齐，底部 stretch 吃齐行高。"""
    body = QWidget()
    lay = QVBoxLayout(body)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(SPACE_ROW)
    return body, lay


def _footer_label(text: str = " ") -> CaptionLabel:
    """固定脚注槽，无文案时用空格占位，保证并排卡脚注带对齐。"""
    lab = CaptionLabel(text if text.strip() else " ")
    lab.setWordWrap(True)
    lab.setAlignment(Qt.AlignLeft | Qt.AlignTop)
    return lab


class PromptPicker(CardWidget):
    """Article template picker — dropdown of prompts/articles only."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.refresh_btn = PushButton("刷新")
        self.refresh_btn.setFixedWidth(64)
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.clicked.connect(lambda: self.refresh())
        self.open_btn = PushButton("目录")
        self.open_btn.setFixedWidth(64)
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.clicked.connect(self._open_articles_dir)

        header = card_header("文章模板", [self.refresh_btn, self.open_btn])
        body, bl = _body_box()
        self.combo = ComboBox()
        self.combo.setMinimumWidth(160)
        self.combo.setMinimumHeight(32)
        self.combo.currentTextChanged.connect(lambda _t: self.changed.emit())
        bl.addWidget(self.combo)
        bl.addStretch(1)

        self._hint = _footer_label("成稿模板：prompts/articles")
        attach_card_skeleton(self, header, body, self._hint)
        self.refresh()

    def refresh(self, preferred: Optional[List[str]] = None) -> None:
        preferred = preferred or []
        current = self.combo.currentText()
        self.combo.blockSignals(True)
        self.combo.clear()
        names = list_article_prompts()
        if not names:
            self._hint.setText("未找到模板。请在 prompts/articles/ 添加 .md")
            self.combo.blockSignals(False)
            return

        for name in names:
            self.combo.addItem(name)

        pick = None
        for p in preferred:
            if p in names:
                pick = p
                break
        if pick is None and current in names:
            pick = current
        if pick is None:
            defaults = default_article_prompt_names()
            pick = defaults[0] if defaults else names[0]
        self.combo.setCurrentText(pick)
        self.combo.blockSignals(False)
        self._hint.setText(f"{pick} · 共 {len(names)} 个")
        self.changed.emit()

    def selected(self) -> List[str]:
        text = self.combo.currentText().strip()
        return [text] if text else []

    def set_enabled_prompts(self, enabled: bool) -> None:
        self.combo.setEnabled(enabled)
        self.refresh_btn.setEnabled(enabled)
        # 目录始终可点，方便加模板

    def _open_articles_dir(self) -> None:
        path = PROMPTS_DIR / "articles"
        path.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception:
            pass


class CoverModeBox(CardWidget):
    """三态封面策略。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        header = card_header("封面策略")
        body, bl = _body_box()
        radios = QHBoxLayout()
        radios.setSpacing(16)
        self.radio_config = RadioButton("跟随设置")
        self.radio_prompt = RadioButton("仅导出提示词")
        self.radio_off = RadioButton("完全跳过")
        self.radio_config.setChecked(True)
        self._group = QButtonGroup(self)
        for btn in (self.radio_config, self.radio_prompt, self.radio_off):
            self._group.addButton(btn)
            btn.setCursor(Qt.PointingHandCursor)
            radios.addWidget(btn)
        radios.addStretch(1)
        bl.addLayout(radios)
        bl.addStretch(1)
        footer = _footer_label("试跑可选用「仅导出」或「跳过」省时间")
        attach_card_skeleton(self, header, body, footer)

    def cover_mode_override(self) -> Optional[str]:
        if self.radio_prompt.isChecked():
            return COVER_MODE_PROMPT_ONLY
        if self.radio_off.isChecked():
            return COVER_MODE_OFF
        return None

    def set_mode_key(self, key: str) -> None:
        key = (key or "config").strip()
        if key in {COVER_MODE_PROMPT_ONLY, "prompt_only", "no_cover"}:
            self.radio_prompt.setChecked(True)
        elif key in {COVER_MODE_OFF, "off", "no_cover_assets"}:
            self.radio_off.setChecked(True)
        else:
            self.radio_config.setChecked(True)

    def mode_key(self) -> str:
        if self.radio_prompt.isChecked():
            return "prompt_only"
        if self.radio_off.isChecked():
            return "off"
        return "config"


class AsrOptions(CardWidget):
    """ASR 高级 — 全宽高级区，不与主参数 2×2 抢行高。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # 全宽高级卡：Preferred 高度即可
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.enable = CheckBox("覆盖本次 ASR（高级）")
        self.enable.setChecked(False)
        self.enable.setCursor(Qt.PointingHandCursor)

        header = QWidget()
        header.setFixedHeight(32)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(self.enable, 0, Qt.AlignVCenter)
        hl.addStretch(1)

        body, bl = _body_box()
        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.engine = ComboBox()
        self.engine.addItem("FunASR")
        self.engine.setItemData(0, "funasr")
        self.engine.addItem("Whisper")
        self.engine.setItemData(1, "whisper")
        self.funasr_model = LineEdit()
        self.funasr_model.setText("sensevoice")
        self.model_size = ComboBox()
        for size in ("tiny", "base", "small"):
            self.model_size.addItem(size)
            self.model_size.setItemData(self.model_size.count() - 1, size)
        self.cpu_threads = SpinBox()
        self.cpu_threads.setRange(1, 64)
        self.cpu_threads.setValue(4)
        self.cpu_threads.setMinimumWidth(120)

        form.addWidget(CaptionLabel("引擎"), 0, 0)
        form.addWidget(self.engine, 0, 1)
        form.addWidget(CaptionLabel("FunASR"), 0, 2)
        form.addWidget(self.funasr_model, 0, 3)
        form.addWidget(CaptionLabel("Whisper"), 1, 0)
        form.addWidget(self.model_size, 1, 1)
        form.addWidget(CaptionLabel("线程"), 1, 2)
        form.addWidget(self.cpu_threads, 1, 3)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)
        bl.addLayout(form)
        # 高级区不强制 min body / 不 stretch 抢空间
        body.setMinimumHeight(0)

        footer = _footer_label("未勾选时使用设置里的默认转写参数")
        outer = attach_card_skeleton(self, header, body, footer)
        # 覆盖 Expanding，避免高级卡被无意义拉高
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.engine.currentIndexChanged.connect(self._sync_engine_fields)
        self.enable.toggled.connect(self._on_toggled)
        self.load_from_config()
        self._sync_engine_fields()
        self._on_toggled(False)
        _ = outer

    def isChecked(self) -> bool:
        return self.enable.isChecked()

    def setChecked(self, checked: bool) -> None:
        self.enable.setChecked(checked)

    def _on_toggled(self, on: bool) -> None:
        for w in (self.engine, self.funasr_model, self.model_size, self.cpu_threads):
            w.setEnabled(on)
        if on:
            self._sync_engine_fields()

    def _sync_engine_fields(self) -> None:
        is_whisper = self.engine.currentData() == "whisper"
        self.model_size.setEnabled(self.isChecked() and is_whisper)
        self.funasr_model.setEnabled(self.isChecked() and not is_whisper)

    def load_from_config(self) -> None:
        try:
            cfg = (load_config() or {}).get("transcribe") or {}
        except Exception:
            cfg = {}
        engine = str(cfg.get("asr_engine") or "funasr")
        idx = self.engine.findData(engine)
        if idx >= 0:
            self.engine.setCurrentIndex(idx)
        self.funasr_model.setText(str(cfg.get("funasr_model") or "sensevoice"))
        size = str(cfg.get("model_size") or "tiny")
        sidx = self.model_size.findData(size)
        if sidx >= 0:
            self.model_size.setCurrentIndex(sidx)
        try:
            self.cpu_threads.setValue(int(cfg.get("cpu_threads") or 4))
        except (TypeError, ValueError):
            self.cpu_threads.setValue(4)

    def as_dict(self) -> dict:
        return {
            "use_override": self.isChecked(),
            "asr_engine": str(self.engine.currentData() or "funasr"),
            "funasr_model": self.funasr_model.text().strip() or "sensevoice",
            "model_size": str(self.model_size.currentData() or "tiny"),
            "cpu_threads": int(self.cpu_threads.value()),
        }


class PipelineOptions(CardWidget):
    """本次选项 — 固定 2×2 勾选槽 + 可选限制行，与模板卡同骨架。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        show_skip: bool = False,
        show_dry_run: bool = False,
    ) -> None:
        super().__init__(parent)
        header = card_header("本次选项")
        body, bl = _body_box()

        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(12)
        grid.setContentsMargins(0, 4, 0, 0)

        self.enable_llm = CheckBox("启用大模型")
        self.enable_llm.setChecked(True)
        self.enable_llm.setCursor(Qt.PointingHandCursor)
        self.save_video = CheckBox("同时保存视频")
        self.save_video.setCursor(Qt.PointingHandCursor)
        self.skip_existing = CheckBox("跳过已完成")
        self.skip_existing.setChecked(True)
        self.skip_existing.setCursor(Qt.PointingHandCursor)
        self.dry_run = CheckBox("仅预览 dry-run")
        self.dry_run.setCursor(Qt.PointingHandCursor)

        # 固定四槽，无内容时隐藏但保留网格节奏（隐藏不占位用 setVisible）
        grid.addWidget(self.enable_llm, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(self.save_video, 0, 1, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(self.skip_existing, 1, 0, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(self.dry_run, 1, 1, Qt.AlignLeft | Qt.AlignVCenter)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        bl.addLayout(grid)

        limit_row = QHBoxLayout()
        limit_row.setSpacing(SPACE_ROW)
        limit_row.setContentsMargins(0, 6, 0, 0)
        self._limit_label = CaptionLabel("限制条数")
        self.limit_edit = LineEdit()
        self.limit_edit.setPlaceholderText("空=不限 · 建议 1～3")
        self.limit_edit.setMinimumWidth(160)
        self.limit_edit.setMaximumWidth(220)
        self.limit_edit.setMinimumHeight(30)
        limit_row.addWidget(self._limit_label, 0, Qt.AlignVCenter)
        limit_row.addWidget(self.limit_edit, 0, Qt.AlignVCenter)
        limit_row.addStretch(1)
        self._limit_row_host = QWidget()
        self._limit_row_host.setLayout(limit_row)
        bl.addWidget(self._limit_row_host)
        bl.addStretch(1)

        self.skip_existing.setVisible(show_skip)
        self.dry_run.setVisible(show_dry_run)
        self._limit_row_host.setVisible(show_skip)

        footer = _footer_label("转写时的常用开关；批量可限制条数与 dry-run")
        attach_card_skeleton(self, header, body, footer)

    def set_batch_mode(self, batch: bool) -> None:
        self.skip_existing.setVisible(batch)
        self._limit_row_host.setVisible(batch)
        self.dry_run.setVisible(batch)

    def limit_value(self) -> Optional[int]:
        text = self.limit_edit.text().strip()
        if not text:
            return None
        try:
            value = int(text)
            return value if value > 0 else None
        except ValueError:
            return None


class CookiesOptions(CardWidget):
    """Cookies — 与主参数卡同骨架。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        header = card_header("Cookies")
        body, bl = _body_box()

        row1 = QHBoxLayout()
        row1.setSpacing(SPACE_ROW)
        lab1 = CaptionLabel("浏览器")
        lab1.setFixedWidth(48)
        row1.addWidget(lab1, 0, Qt.AlignVCenter)
        self.browser = ComboBox()
        self.browser.addItem("（默认）")
        self.browser.setItemData(0, "")
        for name in ("chrome", "edge", "firefox"):
            self.browser.addItem(name)
            self.browser.setItemData(self.browser.count() - 1, name)
        self.browser.setMinimumWidth(120)
        self.browser.setMinimumHeight(30)
        row1.addWidget(self.browser, 1)
        bl.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(SPACE_ROW)
        lab2 = CaptionLabel("文件")
        lab2.setFixedWidth(48)
        row2.addWidget(lab2, 0, Qt.AlignVCenter)
        self.cookies_file = LineEdit()
        self.cookies_file.setPlaceholderText("可选 cookies 路径")
        self.cookies_file.setMinimumHeight(30)
        browse = PushButton("浏览")
        browse.setFixedWidth(64)
        browse.setCursor(Qt.PointingHandCursor)
        browse.clicked.connect(self._browse)
        row2.addWidget(self.cookies_file, 1)
        row2.addWidget(browse)
        bl.addLayout(row2)
        bl.addStretch(1)

        footer = _footer_label("本次可覆盖设置中的默认 cookies")
        attach_card_skeleton(self, header, body, footer)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 cookies 文件",
            str(DATA_DIR / "cookies"),
            "Text (*.txt);;All (*.*)",
        )
        if path:
            self.cookies_file.setText(path)

    def cookies_from_browser(self) -> Optional[str]:
        data = self.browser.currentData()
        return str(data) if data else None

    def cookies_file_path(self) -> Optional[str]:
        text = self.cookies_file.text().strip()
        return text or None

    def apply_defaults(self, browser: str = "", cookies_file: str = "") -> None:
        if browser:
            idx = self.browser.findData(browser)
            if idx >= 0:
                self.browser.setCurrentIndex(idx)
        if cookies_file:
            self.cookies_file.setText(cookies_file)
