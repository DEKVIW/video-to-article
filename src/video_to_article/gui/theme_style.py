"""统一字号与间距 — 一览成文 GUI 视觉规范。

字号阶梯（pt，Windows 默认约 96dpi）:
  page_title  15  页面大标题
  section     13  卡片/区块标题
  body        12  正文、表单、按钮
  caption     11  说明、次要提示
  mono        11  日志等宽

间距:
  page_pad    12
  card_pad    10, 12
  card_gap    10
  row_gap      8
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel, QWidget

# --- scale ---
FONT_PAGE_TITLE = 15
FONT_SECTION = 13
FONT_BODY = 12
FONT_CAPTION = 11
FONT_MONO = 11

SPACE_PAGE = 12
SPACE_CARD_V = 12
SPACE_CARD_H = 14
SPACE_CARD_GAP = 12
SPACE_ROW = 8
TITLE_ROW_H = 32  # 卡片标题行统一高度
CARD_BODY_MIN = 96  # 主参数卡 body 最小高度，同行更整齐
CARD_FOOTER_MIN = 20  # 脚注区最小高度


def apply_app_typography(app: QApplication) -> None:
    """Set base font + global stylesheet for mixed Qt/Fluent widgets."""
    base = QFont()
    base.setPointSize(FONT_BODY)
    app.setFont(base)

    # Soft borders, unified type — avoid heavy double lines
    app.setStyleSheet(
        f"""
        QWidget {{
            font-size: {FONT_BODY}pt;
        }}
        QLabel {{
            font-size: {FONT_BODY}pt;
        }}
        QLabel[role="pageTitle"] {{
            font-size: {FONT_PAGE_TITLE}pt;
            font-weight: 600;
        }}
        QLabel[role="section"] {{
            font-size: {FONT_SECTION}pt;
            font-weight: 600;
        }}
        QLabel[role="caption"], QLabel[role="hint"] {{
            font-size: {FONT_CAPTION}pt;
            color: #666666;
        }}
        QGroupBox {{
            font-size: {FONT_SECTION}pt;
            font-weight: 600;
            margin-top: 6px;
            padding: 12px 10px 10px 10px;
            border: 1px solid rgba(0, 0, 0, 0.08);
            border-radius: 8px;
            background: transparent;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 6px;
            color: #333333;
        }}
        QStatusBar {{
            font-size: {FONT_CAPTION}pt;
        }}
        QMenuBar, QMenu {{
            font-size: {FONT_BODY}pt;
        }}
        QTableWidget {{
            font-size: {FONT_BODY}pt;
            border: 1px solid rgba(0, 0, 0, 0.08);
            border-radius: 6px;
            gridline-color: rgba(0, 0, 0, 0.06);
            background: #ffffff;
            outline: none;
        }}
        QTableWidget::item {{
            padding: 4px 6px;
            border: none;
        }}
        QTableWidget::item:selected {{
            background: rgba(0, 120, 212, 0.12);
            color: #111111;
        }}
        QHeaderView::section {{
            font-size: {FONT_CAPTION}pt;
            font-weight: 600;
            background: #f5f5f5;
            border: none;
            border-bottom: 1px solid rgba(0, 0, 0, 0.08);
            border-right: 1px solid rgba(0, 0, 0, 0.04);
            padding: 6px 8px;
        }}
        QHeaderView::section:last {{
            border-right: none;
        }}
        QScrollArea {{
            border: none;
            background: transparent;
        }}
        """
    )


def style_page_title(label: QLabel) -> QLabel:
    label.setProperty("role", "pageTitle")
    f = label.font()
    f.setPointSize(FONT_PAGE_TITLE)
    f.setWeight(QFont.DemiBold)
    label.setFont(f)
    return label


def style_section(label: QLabel) -> QLabel:
    label.setProperty("role", "section")
    f = label.font()
    f.setPointSize(FONT_SECTION)
    f.setWeight(QFont.DemiBold)
    label.setFont(f)
    return label


def style_caption(label: QLabel) -> QLabel:
    label.setProperty("role", "caption")
    f = label.font()
    f.setPointSize(FONT_CAPTION)
    label.setFont(f)
    label.setStyleSheet(f"font-size: {FONT_CAPTION}pt; color: #666666;")
    return label


def apply_fluent_label_sizes(widget: QWidget) -> None:
    """Best-effort: normalize qfluentwidgets label fonts under a subtree."""
    try:
        from qfluentwidgets import BodyLabel, CaptionLabel, StrongBodyLabel, SubtitleLabel, TitleLabel
    except ImportError:
        return

    for lab in widget.findChildren(TitleLabel):
        f = lab.font()
        f.setPointSize(FONT_PAGE_TITLE)
        lab.setFont(f)
    for lab in widget.findChildren(SubtitleLabel):
        f = lab.font()
        f.setPointSize(FONT_SECTION)
        f.setWeight(QFont.DemiBold)
        lab.setFont(f)
    for lab in widget.findChildren(StrongBodyLabel):
        f = lab.font()
        f.setPointSize(FONT_BODY)
        lab.setFont(f)
    for lab in widget.findChildren(BodyLabel):
        f = lab.font()
        f.setPointSize(FONT_BODY)
        lab.setFont(f)
    for lab in widget.findChildren(CaptionLabel):
        f = lab.font()
        f.setPointSize(FONT_CAPTION)
        lab.setFont(f)


def card_margins() -> tuple[int, int, int, int]:
    return (SPACE_CARD_H, SPACE_CARD_V, SPACE_CARD_H, SPACE_CARD_V)
