"""Console log view + stage/progress/clear controls (toolbar-friendly)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QFrame, QSizePolicy, QVBoxLayout, QWidget

from qfluentwidgets import CaptionLabel, PlainTextEdit, ProgressBar, PushButton

from ..theme_style import FONT_MONO


class LogPanel(QWidget):
    """Log body + controls meant to sit on the global action row (all modes share it).

    Public controls (place them in main toolbar — do not stack a second header):
      - stage_label
      - progress
      - clear_btn
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(80)

        # —— 供主窗口工具条挂载的控件（不在本面板再占一行）——
        self.stage_label = CaptionLabel("就绪")
        self.stage_label.setObjectName("logStage")
        self.stage_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.stage_label.setMinimumWidth(48)

        self.progress = ProgressBar()
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setMaximumWidth(140)
        self.progress.setMaximumHeight(0)
        self.progress.hide()

        self.clear_btn = PushButton("清空")
        self.clear_btn.setFixedWidth(64)
        self.clear_btn.setFixedHeight(30)
        self.clear_btn.setToolTip("清空运行日志")
        self.clear_btn.clicked.connect(self.clear)

        # —— 仅日志正文 ——
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.view = PlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(PlainTextEdit.NoWrap)
        self.view.setFrameShape(QFrame.NoFrame)
        font = QFont("Cascadia Mono")
        if not font.exactMatch():
            font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(FONT_MONO)
        self.view.setFont(font)
        self.view.setMinimumHeight(64)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.view.setStyleSheet(
            """
            PlainTextEdit, QPlainTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 6px;
                padding: 8px;
                selection-background-color: #264f78;
            }
            """
        )
        layout.addWidget(self.view, 1)

    def append(self, text: str) -> None:
        self.view.moveCursor(QTextCursor.End)
        self.view.insertPlainText(text)
        self.view.moveCursor(QTextCursor.End)

    def clear(self) -> None:
        self.view.clear()

    def set_stage(self, stage: str) -> None:
        text = (stage or "—").strip() or "—"
        self.stage_label.setText(text)

    def _show_progress(self) -> None:
        self.progress.setMaximumHeight(6)
        self.progress.show()

    def _hide_progress(self) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setMaximumHeight(0)
        self.progress.hide()

    def set_progress(self, current: int, total: int) -> None:
        if total <= 0:
            self._show_progress()
            self.progress.setRange(0, 0)
            return
        self._show_progress()
        self.progress.setRange(0, total)
        self.progress.setValue(min(max(current, 0), total))

    def reset_progress(self) -> None:
        self._hide_progress()
        self.stage_label.setText("就绪")
