"""Scrollable log view + progress."""

from __future__ import annotations

from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import CaptionLabel, PlainTextEdit, ProgressBar, PushButton

from ..theme_style import FONT_MONO, SPACE_ROW


class LogPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_ROW)

        top = QHBoxLayout()
        top.setSpacing(SPACE_ROW)
        top.addWidget(CaptionLabel("阶段"))
        self.stage_label = CaptionLabel("就绪")
        self.progress = ProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.clear_btn = PushButton("清空")
        self.clear_btn.setFixedWidth(64)
        self.clear_btn.clicked.connect(self.clear)
        top.addWidget(self.stage_label, 0)
        top.addWidget(self.progress, 1)
        top.addWidget(self.clear_btn)
        layout.addLayout(top)

        self.view = PlainTextEdit()
        self.view.setReadOnly(True)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(FONT_MONO)
        self.view.setFont(font)
        self.view.setMinimumHeight(120)
        layout.addWidget(self.view)

    def append(self, text: str) -> None:
        self.view.moveCursor(QTextCursor.End)
        self.view.insertPlainText(text)
        self.view.moveCursor(QTextCursor.End)

    def clear(self) -> None:
        self.view.clear()

    def set_stage(self, stage: str) -> None:
        self.stage_label.setText(stage or "—")

    def set_progress(self, current: int, total: int) -> None:
        if total <= 0:
            self.progress.setRange(0, 0)
            return
        self.progress.setRange(0, total)
        self.progress.setValue(min(current, total))

    def reset_progress(self) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.stage_label.setText("就绪")
