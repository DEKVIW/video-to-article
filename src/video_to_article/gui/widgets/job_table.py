"""Simple status table for batch / search items — soft borders, no heavy grid."""

from __future__ import annotations

from typing import Iterable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem


class JobTable(QTableWidget):
    """Columns: check? | status | title/url | note"""

    def __init__(self, with_check: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.with_check = with_check
        headers = (["选", "状态", "标题 / 链接", "备注"] if with_check else ["状态", "标题 / 链接", "备注"])
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)  # 去掉密网格线，更干净
        self.setFocusPolicy(Qt.NoFocus)
        self.setFrameShape(QTableWidget.NoFrame)

        header = self.horizontalHeader()
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        if with_check:
            header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.Stretch)
            header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        else:
            header.setSectionResizeMode(1, QHeaderView.Stretch)
            header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.setMinimumHeight(160)
        self.setWordWrap(False)

    def clear_rows(self) -> None:
        self.setRowCount(0)

    def set_items(
        self,
        items: Sequence[dict],
        *,
        default_status: str = "待处理",
        check_all: bool = True,
    ) -> None:
        """items: {url, title?, note?, status?}"""
        self.setRowCount(len(items))
        for row, item in enumerate(items):
            status = str(item.get("status") or default_status)
            title = str(item.get("title") or item.get("url") or "")
            note = str(item.get("note") or "")
            url = str(item.get("url") or "")
            col = 0
            if self.with_check:
                check = QTableWidgetItem()
                check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                check.setCheckState(Qt.Checked if check_all else Qt.Unchecked)
                check.setData(Qt.UserRole, url)
                self.setItem(row, col, check)
                col = 1
            status_item = QTableWidgetItem(status)
            status_item.setData(Qt.UserRole, url)
            self.setItem(row, col, status_item)
            self.setItem(row, col + 1, QTableWidgetItem(title))
            self.setItem(row, col + 2, QTableWidgetItem(note))
            self.setRowHeight(row, 28)

    def urls(self) -> list[str]:
        urls = []
        status_col = 1 if self.with_check else 0
        for row in range(self.rowCount()):
            item = self.item(row, status_col)
            if item is None:
                continue
            url = item.data(Qt.UserRole)
            if url:
                urls.append(str(url))
        return urls

    def checked_urls(self) -> list[str]:
        if not self.with_check:
            return self.urls()
        selected = []
        for row in range(self.rowCount()):
            check = self.item(row, 0)
            if check is None or check.checkState() != Qt.Checked:
                continue
            url = check.data(Qt.UserRole)
            if url:
                selected.append(str(url))
        return selected

    def set_row_status_by_url(self, url: str, status: str, note: str = "") -> None:
        status_col = 1 if self.with_check else 0
        note_col = status_col + 2
        for row in range(self.rowCount()):
            item = self.item(row, status_col)
            if item is None:
                continue
            if str(item.data(Qt.UserRole) or "") != url:
                continue
            item.setText(status)
            note_item = self.item(row, note_col)
            if note_item is None:
                self.setItem(row, note_col, QTableWidgetItem(note))
            else:
                note_item.setText(note)
            return

    def apply_results(self, results: Iterable[dict]) -> None:
        for result in results:
            if not isinstance(result, dict):
                continue
            url = str(result.get("video_url") or result.get("url") or "")
            if not url:
                continue
            if result.get("success"):
                self.set_row_status_by_url(url, "成功", result.get("title") or "")
            elif result.get("skipped"):
                self.set_row_status_by_url(url, "跳过", str(result.get("reason") or ""))
            else:
                self.set_row_status_by_url(url, "失败", str(result.get("error") or "")[:80])
