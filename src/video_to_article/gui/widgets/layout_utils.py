"""Layout helpers — card skeleton + equal-height param rows."""

from __future__ import annotations

from typing import Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import SubtitleLabel

from ..theme_style import (
    CARD_BODY_MIN,
    CARD_FOOTER_MIN,
    SPACE_CARD_GAP,
    SPACE_PAGE,
    SPACE_ROW,
    TITLE_ROW_H,
)


def page_scroll_root(outer_widget: QWidget) -> tuple[QVBoxLayout, QWidget, QVBoxLayout]:
    """Return (outer_layout, body_widget, body_layout) with scrollable body."""
    from PySide6.QtWidgets import QScrollArea

    outer = QVBoxLayout(outer_widget)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    scroll = QScrollArea(outer_widget)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.NoFrame)
    outer.addWidget(scroll)
    body = QWidget()
    scroll.setWidget(body)
    root = QVBoxLayout(body)
    root.setContentsMargins(SPACE_PAGE, SPACE_PAGE, SPACE_PAGE, SPACE_PAGE)
    root.setSpacing(SPACE_CARD_GAP)
    return outer, body, root


def card_header(title: str, actions: Optional[Sequence[QWidget]] = None) -> QWidget:
    """统一卡片标题行高度，左右卡片标题基线对齐。"""
    host = QWidget()
    host.setFixedHeight(TITLE_ROW_H)
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(SPACE_ROW)
    row.setAlignment(Qt.AlignVCenter)
    title_lab = SubtitleLabel(title)
    row.addWidget(title_lab, 0, Qt.AlignVCenter)
    row.addStretch(1)
    for w in actions or ():
        # 保证按钮可点：不放进会吞事件的容器逻辑里
        w.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        row.addWidget(w, 0, Qt.AlignVCenter)
    return host


def attach_card_skeleton(
    card: QWidget,
    header: QWidget,
    body: QWidget,
    footer: Optional[QWidget] = None,
) -> QVBoxLayout:
    """标准三层：Header / Body(可伸展顶对齐) / Footer。

    同行等高时 body 底部 stretch 吃掉多余高度，控件仍在顶部、可正常点击。
    """
    layout = QVBoxLayout(card)
    from ..theme_style import card_margins

    layout.setContentsMargins(*card_margins())
    layout.setSpacing(SPACE_ROW)
    card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    layout.addWidget(header, 0)

    body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    body.setMinimumHeight(CARD_BODY_MIN)
    layout.addWidget(body, 1)  # stretch

    if footer is not None:
        footer.setMinimumHeight(CARD_FOOTER_MIN)
        layout.addWidget(footer, 0)
    return layout


def two_column_row(
    left: QWidget,
    right: QWidget,
    left_stretch: int = 1,
    right_stretch: int = 1,
    *,
    equal_height: bool = True,
) -> QWidget:
    """Side-by-side pair. equal_height=True 时同行等高、内容顶对齐留白。"""
    host = QWidget()
    lay = QHBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(SPACE_CARD_GAP)
    if equal_height:
        left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    else:
        left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        right.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay.setAlignment(left, Qt.AlignTop)
        lay.setAlignment(right, Qt.AlignTop)
    lay.addWidget(left, left_stretch)
    lay.addWidget(right, right_stretch)
    return host


def grid_two_col(widgets: list[QWidget], *, equal_height: bool = True) -> QWidget:
    """2-column grid of param cards.

    equal_height=True（默认）: 同一行两卡同高，矮卡底部留白，整齐美观。
    依赖卡片内部 body stretch，控件保持顶对齐且可点击。
    """
    host = QWidget()
    grid = QGridLayout(host)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(SPACE_CARD_GAP)
    grid.setVerticalSpacing(SPACE_CARD_GAP)
    for i, w in enumerate(widgets):
        r, c = i // 2, i % 2
        if equal_height:
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            grid.addWidget(w, r, c)
        else:
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            grid.addWidget(w, r, c, Qt.AlignTop)
    # 每行按内容决定高度，行内两卡被撑到同一高度
    return host
