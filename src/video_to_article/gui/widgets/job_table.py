"""Status table for batch / search items — soft borders, double-click opens URL in search mode."""

from __future__ import annotations

from typing import Iterable, Sequence

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)


class JobTable(QTableWidget):
    """Batch: 选? | 状态 | 标题 | 备注
    Search: 选 | 状态 | 标题 | 作者 | 信息  （双击行打开原视频）
    """

    open_url_requested = Signal(str)

    def __init__(
        self,
        with_check: bool = False,
        *,
        search_mode: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.with_check = with_check
        self.search_mode = search_mode
        if search_mode:
            headers = ["选", "状态", "标题", "作者", "信息"]
        elif with_check:
            headers = ["选", "状态", "标题 / 链接", "备注"]
        else:
            headers = ["状态", "标题 / 链接", "备注"]
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFrameShape(QTableWidget.NoFrame)
        self.setMouseTracking(True)

        header = self.horizontalHeader()
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        if search_mode:
            header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.Stretch)
            header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        elif with_check:
            header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.Stretch)
            header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        else:
            header.setSectionResizeMode(1, QHeaderView.Stretch)
            header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.setMinimumHeight(160)
        self.setWordWrap(False)
        # 搜索结果：双击打开原视频（不再单独占一列图标）
        self.cellDoubleClicked.connect(self._on_double_click)

    def _status_col(self) -> int:
        return 1 if self.with_check else 0

    def clear_rows(self) -> None:
        self.setRowCount(0)

    def set_items(
        self,
        items: Sequence[dict],
        *,
        default_status: str = "待处理",
        check_all: bool = True,
    ) -> None:
        """items: {url, title?, note?, status?, author?, meta?}"""
        self.setRowCount(len(items))
        for row, item in enumerate(items):
            status = str(item.get("status") or default_status)
            title = str(item.get("title") or item.get("url") or "")
            note = str(item.get("note") or "")
            author = str(item.get("author") or "")
            meta = str(item.get("meta") or note)
            url = str(item.get("url") or "")
            col = 0
            if self.with_check:
                check = QTableWidgetItem()
                check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                check.setCheckState(Qt.Checked if check_all else Qt.Unchecked)
                check.setData(Qt.UserRole, url)
                self.setItem(row, col, check)
                col = 1
            status_item = QTableWidgetItem(status)
            status_item.setData(Qt.UserRole, url)
            self.setItem(row, col, status_item)
            title_item = QTableWidgetItem(title)
            if self.search_mode and url:
                title_item.setToolTip(f"双击打开原视频\n{url}")
            else:
                title_item.setToolTip(url or title)
            self.setItem(row, col + 1, title_item)
            if self.search_mode:
                self.setItem(row, col + 2, QTableWidgetItem(author))
                self.setItem(row, col + 3, QTableWidgetItem(meta))
            else:
                self.setItem(row, col + 2, QTableWidgetItem(note))
            self.setRowHeight(row, 30 if self.search_mode else 28)

    def _open_url(self, url: str) -> None:
        url = (url or "").strip()
        if not url:
            return
        self.open_url_requested.emit(url)
        QDesktopServices.openUrl(QUrl(url))

    def _on_double_click(self, row: int, _col: int) -> None:
        if not self.search_mode:
            return
        url = self.url_at_row(row)
        if url:
            self._open_url(url)

    def url_at_row(self, row: int) -> str:
        status_col = self._status_col()
        item = self.item(row, status_col)
        if item is None:
            return ""
        return str(item.data(Qt.UserRole) or "")

    def urls(self) -> list[str]:
        urls = []
        status_col = self._status_col()
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
        status_col = self._status_col()
        # search: 信息 col; batch: 备注 col
        note_col = status_col + 3 if self.search_mode else status_col + 2
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
