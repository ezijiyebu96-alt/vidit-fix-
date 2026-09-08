"""Themes (Constitution section 3D & 10B).

Each theme is a small palette; ``stylesheet()`` turns it into Qt CSS. The
``dynamic`` theme follows Vidit's mood colour. ``custom`` reads the palette
from settings so the user can invent their own.
"""
from __future__ import annotations

from typing import Any, Dict

PALETTES: Dict[str, Dict[str, str]] = {
    "cyberpunk": {
        # cyber-glass: deep space base, neon cyan/violet accents, glass panels
        "bg": "#070b16", "panel": "rgba(16, 24, 48, 205)", "panel2": "rgba(30, 42, 80, 190)",
        "text": "#eaf2ff", "muted": "#8ea3d0",
        "accent": "#00e5ff", "accent2": "#a855f7",
        "user": "rgba(0, 229, 255, 0.10)", "bot": "rgba(123, 92, 255, 0.13)",
        "border": "rgba(0, 229, 255, 0.22)", "glow": "#7b5cff",
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
    glow = p.get("glow", p.get("accent2", p["accent"]))
    return f"""
    QWidget {{ background: {p['bg']}; color: {p['text']}; font-family: '{family}'; font-size: {font_size}px; }}
    QMainWindow, QDialog {{ background: {p['bg']}; }}
    QFrame#panel, QWidget#panel {{ background: {p['panel']}; border: 1px solid {p['border']}; border-radius: 16px; }}
    QFrame#glassCard {{ background: {p['panel']}; border: 1px solid {p['border']}; border-radius: 18px; }}
    QFrame#softCard {{ background: {p['panel2']}; border: 1px solid {p['border']}; border-radius: 14px; }}
    QLabel#onlinePill {{ color: #34d399; background: rgba(52, 211, 153, 0.10);
                        border: 1px solid rgba(52, 211, 153, 0.45); border-radius: 10px; padding: 3px 12px; font-weight: 700; }}
    QLabel#tagline {{ color: {p['muted']}; background: transparent; font-size: {font_size - 1}px; }}
    QLabel#quote {{ color: {p['muted']}; background: transparent; font-style: italic; }}
    QLabel#hint {{ color: {p['muted']}; background: transparent; font-size: {font_size - 2}px; }}
    QListWidget#navList {{ background: transparent; border: none; padding: 6px 0; outline: none; }}
    QListWidget#navList::item {{ color: {p['muted']}; padding: 10px 14px; margin: 2px 10px; border-radius: 10px;
                                 border-left: 2px solid transparent; }}
    QListWidget#navList::item:hover {{ color: {p['text']}; background: {p['panel2']}; }}
    QListWidget#navList::item:selected {{ color: {p['accent']}; background: {p['panel2']};
                                         border-left: 2px solid {p['accent']}; font-weight: 600; }}
    QPushButton#modeChip {{ background: {p['panel2']}; color: {p['muted']}; border: 1px solid {p['border']};
                            border-radius: 14px; padding: 7px 14px; font-weight: 600; }}
    QPushButton#modeChip:hover {{ color: {p['text']}; border-color: {p['accent']}; }}
    QPushButton#modeChip:checked {{ background: rgba(0, 229, 255, 0.12); color: {p['accent']};
                                   border: 1px solid {p['accent']}; font-weight: 700; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QTextEdit, QPlainTextEdit, QLineEdit, QListWidget, QTreeWidget, QTableWidget {{
        background: {p['panel']}; border: 1px solid {p['border']}; border-radius: 10px; padding: 6px; selection-background-color: {p['accent']};
    }}
    QTextEdit:focus, QPlainTextEdit:focus, QLineEdit:focus {{ border: 1px solid {p['accent']}; }}
    QTextBrowser {{ background: {p['panel']}; border: 1px solid {p['border']}; border-radius: 12px; padding: 8px; }}
    QPushButton {{ background: {p['panel2']}; border: 1px solid {p['border']}; border-radius: 10px; padding: 7px 14px; }}
    QPushButton:hover {{ border-color: {p['accent']}; color: {p['accent']}; }}
    QPushButton:pressed {{ background: {p['accent']}; color: {p['bg']}; }}
    QPushButton:focus {{ border-color: {p['accent']}; }}
    QPushButton:disabled {{ color: {p['muted']}; background: {p['panel']}; }}
    QPushButton#primary {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p['accent']}, stop:1 {glow});
                           color: #051022; border: none; font-weight: 700; min-height: 34px; padding: 8px 22px; }}
    QPushButton#primary:hover {{ border: 1px solid white; }}
    QPushButton#primary:disabled {{ background: {p['panel2']}; color: {p['muted']}; }}
    QPushButton#ghost {{ background: transparent; border: none; color: {p['muted']}; }}
    QPushButton#ghost:hover {{ color: {p['accent']}; }}
    QPushButton#danger {{ background: transparent; border: 1px solid #ef4444; color: #f87171; border-radius: 10px; padding: 7px 14px; }}
    QPushButton#danger:hover {{ background: rgba(239, 68, 68, 0.15); }}
    /* Mic button states (dynamic property micState, see ChatWindow) */
    QPushButton#mic {{ font-weight: 600; min-width: 96px; }}
    QPushButton#mic[micState="listening"] {{ background: #16a34a; color: white; border: 1px solid #15803d; }}
    QPushButton#mic[micState="listening"]:hover {{ background: #15803d; }}
    QPushButton#mic[micState="processing"] {{ background: {p['accent']}; color: #051022; border: 1px solid {p['accent2']}; }}
    QPushButton#mic[micState="error"] {{ background: #b91c1c; color: white; border: 1px solid #7f1d1d; }}
    QLabel {{ background: transparent; }}
    QLabel#title {{ font-size: {font_size + 7}px; font-weight: 700; color: {p['accent']}; background: transparent; }}
    QLabel#muted {{ color: {p['muted']}; background: transparent; }}
    QCheckBox {{ background: transparent; }}
    QTabWidget::pane {{ border: 1px solid {p['border']}; border-radius: 12px; background: {p['panel']}; }}
    QTabBar::tab {{ background: {p['panel2']}; padding: 8px 16px; border-top-left-radius: 10px; border-top-right-radius: 10px; margin-right: 2px; color: {p['muted']}; }}
    QTabBar::tab:selected {{ background: {p['accent']}; color: #051022; }}
    QTabBar::tab:hover {{ color: {p['text']}; }}
    QTabBar::tab:selected:hover {{ color: #051022; }}
    QComboBox, QSpinBox, QDoubleSpinBox {{ background: {p['panel2']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 4px 8px; }}
    QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {p['accent']}; }}
    QComboBox QAbstractItemView {{ background: {p['panel']}; selection-background-color: {p['accent']}; }}
    QSlider::groove:horizontal {{ height: 6px; background: {p['panel2']}; border-radius: 3px; }}
    QSlider::handle:horizontal {{ width: 16px; margin: -6px 0; background: {p['accent']}; border-radius: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {p['border']}; background: {p['panel2']}; }}
    QCheckBox::indicator:checked {{ background: {p['accent']}; }}
    QListWidget::item {{ padding: 6px 8px; border-radius: 8px; }}
    QListWidget::item:hover {{ background: {p['panel2']}; }}
    QListWidget::item:selected {{ background: {p['accent']}; color: #051022; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; }}
    QScrollBar::handle:vertical {{ background: {p['border']}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {p['muted']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QProgressBar {{ border: 1px solid {p['border']}; border-radius: 6px; background: {p['panel2']}; text-align: center; color: {p['text']}; }}
    QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p['accent']}, stop:1 {glow}); border-radius: 6px; }}
    QMenu {{ background: {p['panel']}; border: 1px solid {p['border']}; border-radius: 8px; }}
    QMenu::item {{ padding: 5px 18px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {p['accent']}; color: #051022; }}
    QToolTip {{ background: {p['panel']}; color: {p['text']}; border: 1px solid {p['accent']}; border-radius: 6px; padding: 4px 8px; }}
    QGroupBox {{ border: 1px solid {p['border']}; border-radius: 10px; margin-top: 12px; padding-top: 10px; font-weight: 600; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; color: {p['accent']}; }}
    QSplitter::handle {{ background: transparent; }}
    QSplitter::handle:horizontal {{ width: 6px; }}
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
