"""Placeholder for Phase B/C modes."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlaceholderPage(QWidget):
    def __init__(self, title: str, detail: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        head = QLabel(title)
        head.setAlignment(Qt.AlignCenter)
        font = head.font()
        font.setPointSize(14)
        font.setBold(True)
        head.setFont(font)
        body = QLabel(detail)
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignCenter)
        body.setStyleSheet("color: #555;")
        layout.addStretch(1)
        layout.addWidget(head)
        layout.addWidget(body)
        layout.addStretch(2)
