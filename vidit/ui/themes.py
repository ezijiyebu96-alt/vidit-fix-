"""Themes (Constitution section 3D & 10B).

Each theme is a small palette; ``stylesheet()`` turns it into Qt CSS. The
``dynamic`` theme follows Vidit's mood colour. ``custom`` reads the palette
from settings so the user can invent their own.
"""
from __future__ import annotations

from typing import Any, Dict

PALETTES: Dict[str, Dict[str, str]] = {
    "cyberpunk": {
        "bg": "#0b1020", "panel": "#111a33", "panel2": "#172244", "text": "#e6ecff", "muted": "#8b9bd1",
        "accent": "#4f7cff", "accent2": "#b14dff", "user": "#1e2a52", "bot": "#2a1f5c", "border": "#2c3b6f",
        "font": "Segoe UI",
    },
    "cozy": {
        "bg": "#f4ede4", "panel": "#fbf6ef", "panel2": "#efe4d6", "text": "#3b2f2f", "muted": "#8a7a6a",
        "accent": "#c96f3b", "accent2": "#e0a458", "user": "#f0dfc9", "bot": "#e6d3bd", "border": "#dcc7ae",
        "font": "Georgia",
    },
    "minimal": {
        "bg": "#ffffff", "panel": "#fafafa", "panel2": "#f0f0f0", "text": "#111111", "muted": "#777777",
        "accent": "#111111", "accent2": "#555555", "user": "#efefef", "bot": "#e2e2e2", "border": "#dddddd",
        "font": "Segoe UI",
    },
    "dark": {
        "bg": "#121212", "panel": "#1c1c1c", "panel2": "#242424", "text": "#eeeeee", "muted": "#9a9a9a",
        "accent": "#3b82f6", "accent2": "#60a5fa", "user": "#2a2a2a", "bot": "#1f2a44", "border": "#333333",
        "font": "Segoe UI",
    },
    "light": {
        "bg": "#f6f8fb", "panel": "#ffffff", "panel2": "#eef2f7", "text": "#1b2330", "muted": "#66738a",
        "accent": "#2563eb", "accent2": "#7c3aed", "user": "#e8eefb", "bot": "#ede9fe", "border": "#d7dee9",
        "font": "Segoe UI",
    },
    "game": {
        "bg": "rgba(5, 8, 16, 160)", "panel": "rgba(10, 14, 28, 170)", "panel2": "rgba(18, 24, 44, 170)", "text": "#d6ffe9",
        "muted": "#7bd7a8", "accent": "#22c55e", "accent2": "#a3e635", "user": "rgba(20, 40, 30, 170)", "bot": "rgba(10, 60, 40, 170)",
        "border": "#1f6b45", "font": "Consolas",
    },
    "high_contrast": {
        "bg": "#000000", "panel": "#000000", "panel2": "#101010", "text": "#ffffff", "muted": "#ffff00",
        "accent": "#ffff00", "accent2": "#00ffff", "user": "#1a1a1a", "bot": "#00203a", "border": "#ffffff",
        "font": "Arial",
    },
}


def palette(name: str, mood_color: str = "#4f7cff", custom: Dict[str, Any] | None = None) -> Dict[str, str]:
    if name == "dynamic":
        base = dict(PALETTES["cyberpunk"])
        base["accent"] = mood_color
        base["accent2"] = mood_color
        base["bot"] = _mix(mood_color, base["bg"], 0.35)
        return base
    if name == "custom" and custom:
        base = dict(PALETTES["dark"])
        base.update({k: str(v) for k, v in custom.items() if k in base})
        return base
    return dict(PALETTES.get(name, PALETTES["cyberpunk"]))


def stylesheet(p: Dict[str, str], font_size: int = 13, font_family: str | None = None, reduced_motion: bool = False,
               dyslexia_font: bool = False) -> str:
    family = "OpenDyslexic, Comic Sans MS, Verdana" if dyslexia_font else (font_family or p.get("font", "Segoe UI"))
    return f"""
    QWidget {{ background: {p['bg']}; color: {p['text']}; font-family: '{family}'; font-size: {font_size}px; }}
    QMainWindow, QDialog {{ background: {p['bg']}; }}
    QFrame#panel, QWidget#panel {{ background: {p['panel']}; border: 1px solid {p['border']}; border-radius: 14px; }}
    QTextEdit, QPlainTextEdit, QLineEdit, QListWidget, QTreeWidget, QTableWidget {{
        background: {p['panel']}; border: 1px solid {p['border']}; border-radius: 10px; padding: 6px; selection-background-color: {p['accent']};
    }}
    QTextBrowser {{ background: {p['panel']}; border: 1px solid {p['border']}; border-radius: 12px; padding: 8px; }}
    QPushButton {{ background: {p['panel2']}; border: 1px solid {p['border']}; border-radius: 10px; padding: 7px 14px; }}
    QPushButton:hover {{ border-color: {p['accent']}; color: {p['accent']}; }}
    QPushButton:pressed {{ background: {p['accent']}; color: {p['bg']}; }}
    QPushButton#primary {{ background: {p['accent']}; color: white; border: none; font-weight: 600; }}
    QPushButton#primary:hover {{ background: {p['accent2']}; }}
    QPushButton#ghost {{ background: transparent; border: none; color: {p['muted']}; }}
    QPushButton#ghost:hover {{ color: {p['accent']}; }}
    QLabel {{ background: transparent; }}
    QLabel#title {{ font-size: {font_size + 7}px; font-weight: 700; color: {p['accent']}; background: transparent; }}
    QLabel#muted {{ color: {p['muted']}; background: transparent; }}
    QCheckBox {{ background: transparent; }}
    QTabWidget::pane {{ border: 1px solid {p['border']}; border-radius: 12px; background: {p['panel']}; }}
    QTabBar::tab {{ background: {p['panel2']}; padding: 8px 16px; border-top-left-radius: 10px; border-top-right-radius: 10px; margin-right: 2px; }}
    QTabBar::tab:selected {{ background: {p['accent']}; color: white; }}
    QComboBox, QSpinBox, QDoubleSpinBox {{ background: {p['panel2']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 4px 8px; }}
    QComboBox QAbstractItemView {{ background: {p['panel']}; selection-background-color: {p['accent']}; }}
    QSlider::groove:horizontal {{ height: 6px; background: {p['panel2']}; border-radius: 3px; }}
    QSlider::handle:horizontal {{ width: 16px; margin: -6px 0; background: {p['accent']}; border-radius: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {p['border']}; background: {p['panel2']}; }}
    QCheckBox::indicator:checked {{ background: {p['accent']}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; }}
    QScrollBar::handle:vertical {{ background: {p['border']}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QProgressBar {{ border: 1px solid {p['border']}; border-radius: 6px; background: {p['panel2']}; text-align: center; }}
    QProgressBar::chunk {{ background: {p['accent']}; border-radius: 6px; }}
    QMenu {{ background: {p['panel']}; border: 1px solid {p['border']}; }}
    QMenu::item:selected {{ background: {p['accent']}; color: white; }}
    QToolTip {{ background: {p['panel']}; color: {p['text']}; border: 1px solid {p['border']}; }}
    QGroupBox {{ border: 1px solid {p['border']}; border-radius: 10px; margin-top: 12px; padding-top: 10px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; color: {p['accent']}; }}
    """


def _mix(hex_a: str, hex_b: str, t: float) -> str:
    def parse(h: str) -> tuple[int, int, int]:
        h = h.lstrip("#")
        if len(h) != 6:
            return (30, 30, 60)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    a, b = parse(hex_a), parse(hex_b)
    mixed = tuple(int(a[i] * t + b[i] * (1 - t)) for i in range(3))
    return "#%02x%02x%02x" % mixed
