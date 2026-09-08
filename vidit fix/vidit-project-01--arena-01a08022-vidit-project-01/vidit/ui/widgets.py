"""Reusable visual pieces: the Orb, the Face, the Waveform, emotion badges.

Also the "cyber-glass" component kit used by the Settings redesign:
GlassCard, NeonToggle, GradientSlider, ModeChip, AvatarCircle/AvatarPicker
and StatusToast — all QPainter/stylesheet based, 100% offline.
"""
from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Callable, Dict, List, Optional

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PyQt5.QtWidgets import QAbstractButton, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

from ..constitution import EMOTION_COLORS

ASSETS_DIR = Path(__file__).parent / "assets"
AVATAR_DIR = ASSETS_DIR / "avatars"

# Avatar carousel styles: id -> (label, gradient a, gradient b, initial)
AVATAR_STYLES: Dict[str, Dict[str, str]] = {
    "nebula": {"label": "Nebula", "a": "#7b5cff", "b": "#2a1f5c", "letter": "V"},
    "aurora": {"label": "Aurora", "a": "#00e5ff", "b": "#0b3a55", "letter": "V"},
    "ember": {"label": "Ember", "a": "#ff7a59", "b": "#5c1d3a", "letter": "V"},
    "frost": {"label": "Frost", "a": "#9be8ff", "b": "#1b3f66", "letter": "V"},
    "sigil": {"label": "Sigil", "a": "#34d399", "b": "#0d3b2e", "letter": "\u25c8"},
}


def avatar_image(style_id: str) -> Optional[QPixmap]:
    """Local portrait for a style, or None (the painter falls back to a
    gradient glyph — the app never needs the assets to work)."""
    path = AVATAR_DIR / f"{style_id}.png"
    if path.exists():
        pix = QPixmap(str(path))
        if not pix.isNull():
            return pix
    return None


class OrbWidget(QWidget):
    """The glowing, breathing orb. Colour = mood; pulse speed = intensity."""

    clicked = pyqtSignal()
    doubleClicked = pyqtSignal()

    def __init__(self, size: int = 72, parent: Optional[QWidget] = None, animate: bool = True):
        super().__init__(parent)
        self._size = size
        self._color = QColor(EMOTION_COLORS["happy"])
        self._target = QColor(self._color)
        self._intensity = 0.5
        self._speaking = False
        self._thinking = False
        self._listening = False
        self._phase = 0.0
        self._glow = 0.8
        self._pulse_speed = 1.0
        self._face = "smiling"
        self._show_face = True
        self.setFixedSize(size + 24, size + 24)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        if animate:
            self._timer.start(33)

    # -- state ---------------------------------------------------------------
    def set_emotion(self, emotion: str, intensity: float, face: str = "smiling") -> None:
        self._target = QColor(EMOTION_COLORS.get(emotion, "#3B82F6"))
        self._intensity = max(0.15, min(1.0, intensity))
        self._face = face

    def set_speaking(self, speaking: bool) -> None:
        self._speaking = speaking

    def set_thinking(self, thinking: bool) -> None:
        self._thinking = thinking

    def set_listening(self, listening: bool) -> None:
        """Ears are open — the orb shows a soft green ripple while you talk."""
        self._listening = listening

    def set_style(self, size: Optional[int] = None, pulse_speed: Optional[float] = None, glow: Optional[float] = None,
                  show_face: Optional[bool] = None, animate: Optional[bool] = None) -> None:
        if size:
            self._size = size
            self.setFixedSize(size + 24, size + 24)
        if pulse_speed is not None:
            self._pulse_speed = pulse_speed
        if glow is not None:
            self._glow = glow
        if show_face is not None:
            self._show_face = show_face
        if animate is not None:
            self._animate_enabled = bool(animate)
            if animate and not self._timer.isActive() and self.isVisible():
                self._timer.start(33)
            elif not animate:
                self._timer.stop()
                self.update()

    # Pause the animation timer whenever the orb is not on screen (minimised
    # window, hidden overlay) — invisible pixels should not cost CPU/battery.
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if getattr(self, "_animate_enabled", True) and not self._timer.isActive():
            self._timer.start(33)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        self._phase += 0.05 * self._pulse_speed * (1.5 if self._speaking else 2.5 if self._thinking else 1.8 if self._listening else 1.0)
        # ease colour toward target
        r = self._color.red() + (self._target.red() - self._color.red()) * 0.08
        g = self._color.green() + (self._target.green() - self._color.green()) * 0.08
        b = self._color.blue() + (self._target.blue() - self._color.blue()) * 0.08
        self._color = QColor(int(r), int(g), int(b))
        self.update()

    # -- painting -----------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        breathe = 1 + 0.06 * self._intensity * math.sin(self._phase)
        if self._speaking:
            breathe += 0.05 * math.sin(self._phase * 4.0)
        elif self._listening:
            breathe += 0.025 * math.sin(self._phase * 2.0)
        radius = self._size / 2 * breathe

        # outer glow — breathes harder while speaking or listening
        glow_boost = 1.35 if (self._speaking or self._listening) else 1.0
        glow = QRadialGradient(QPointF(cx, cy), radius * 1.6)
        c = QColor(self._color)
        c.setAlphaF(min(1.0, 0.55 * self._glow * glow_boost))
        glow.setColorAt(0.55, c)
        c2 = QColor(self._color)
        c2.setAlphaF(0.0)
        glow.setColorAt(1.0, c2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(QPointF(cx, cy), radius * 1.6, radius * 1.6)

        # body
        body = QRadialGradient(QPointF(cx - radius * 0.3, cy - radius * 0.3), radius * 1.4)
        body.setColorAt(0.0, self._color.lighter(160))
        body.setColorAt(0.6, self._color)
        body.setColorAt(1.0, self._color.darker(180))
        painter.setBrush(QBrush(body))
        painter.drawEllipse(QPointF(cx, cy), radius, radius)

        # thinking ring (thought-colour) / listening ripple (green = ears open)
        if self._thinking or self._listening:
            ring = self._color.lighter(170) if self._thinking else QColor("#22c55e").lighter(130)
            pen = QPen(ring, 2.5)
            pen.setDashPattern([3, 4])
            pen.setDashOffset(self._phase * (6 if self._thinking else 3.5))
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(cx, cy), radius + 6, radius + 6)

        if self._show_face:
            self._draw_face(painter, cx, cy, radius)

    def _draw_face(self, painter: QPainter, cx: float, cy: float, r: float) -> None:
        pen = QPen(QColor(255, 255, 255, 230), max(2.0, r * 0.09), Qt.SolidLine, Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        eye_y = cy - r * 0.15
        eye_dx = r * 0.32
        blink = (math.sin(self._phase * 0.7) > 0.985)
        if self._face == "laughing" or blink:
            # closed happy eyes ^ ^
            for sx in (-1, 1):
                path = QPainterPath()
                path.moveTo(cx + sx * eye_dx - r * 0.12, eye_y + r * 0.06)
                path.quadTo(cx + sx * eye_dx, eye_y - r * 0.12, cx + sx * eye_dx + r * 0.12, eye_y + r * 0.06)
                painter.drawPath(path)
        elif self._face == "surprised":
            painter.setBrush(QColor(255, 255, 255, 230))
            for sx in (-1, 1):
                painter.drawEllipse(QPointF(cx + sx * eye_dx, eye_y), r * 0.12, r * 0.16)
            painter.setBrush(Qt.NoBrush)
        elif self._face == "thinking":
            painter.setBrush(QColor(255, 255, 255, 230))
            painter.drawEllipse(QPointF(cx - eye_dx, eye_y), r * 0.09, r * 0.09)
            painter.drawEllipse(QPointF(cx + eye_dx, eye_y - r * 0.06), r * 0.09, r * 0.09)
            painter.setBrush(Qt.NoBrush)
            painter.drawLine(QPointF(cx + eye_dx - r * 0.15, eye_y - r * 0.22), QPointF(cx + eye_dx + r * 0.15, eye_y - r * 0.28))
        else:
            painter.setBrush(QColor(255, 255, 255, 230))
            for sx in (-1, 1):
                painter.drawEllipse(QPointF(cx + sx * eye_dx, eye_y), r * 0.1, r * 0.1)
            painter.setBrush(Qt.NoBrush)

        mouth_y = cy + r * 0.3
        mouth_w = r * 0.45
        path = QPainterPath()
        if self._face in ("smiling", "laughing"):
            depth = r * (0.28 if self._face == "laughing" else 0.2)
            path.moveTo(cx - mouth_w, mouth_y)
            path.quadTo(cx, mouth_y + depth, cx + mouth_w, mouth_y)
            if self._face == "laughing":
                path.closeSubpath()
                painter.setBrush(QColor(255, 255, 255, 200))
        elif self._face == "frowning":
            path.moveTo(cx - mouth_w, mouth_y + r * 0.1)
            path.quadTo(cx, mouth_y - r * 0.15, cx + mouth_w, mouth_y + r * 0.1)
        elif self._face == "surprised":
            painter.drawEllipse(QPointF(cx, mouth_y), r * 0.14, r * 0.18)
            return
        else:  # thinking
            path.moveTo(cx - mouth_w * 0.6, mouth_y)
            path.lineTo(cx + mouth_w * 0.5, mouth_y + r * 0.05)
        if self._speaking:
            painter.setBrush(QColor(255, 255, 255, 200))
            openness = abs(math.sin(self._phase * 4)) * r * 0.18
            painter.drawEllipse(QPointF(cx, mouth_y + r * 0.04), mouth_w * 0.6, max(2.0, openness))
        else:
            painter.drawPath(path)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.doubleClicked.emit()


class WaveformWidget(QWidget):
    """Siri-style visualiser that dances while Vidit speaks or listens."""

    def __init__(self, parent: Optional[QWidget] = None, bars: int = 28):
        super().__init__(parent)
        self._bars = bars
        self._levels: List[float] = [0.1] * bars
        self._active = False
        self._idle_ticks = 0
        self._color = QColor("#4f7cff")
        self._phase = 0.0
        self.setMinimumHeight(40)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def set_active(self, active: bool) -> None:
        self._idle_ticks = 0
        if active and not self._timer.isActive() and self.isVisible():
            self._timer.start(40)
        self._active = active

    def set_color(self, color: str) -> None:
        self._color = QColor(color)

    # Same rule as the orb: a hidden waveform must not repaint.
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start(40)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        self._phase += 0.25
        for i in range(self._bars):
            if self._active:
                target = 0.3 + 0.7 * abs(math.sin(self._phase + i * 0.45)) * random.uniform(0.5, 1.0)
            else:
                target = 0.08 + 0.05 * math.sin(self._phase * 0.5 + i * 0.3)
            self._levels[i] += (target - self._levels[i]) * 0.3
        if not self._active:
            # Fully idle: stop repainting after ~2s of settled bars (CPU saver).
            self._idle_ticks += 1
            if self._idle_ticks > 50:
                self._timer.stop()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        gap = w / self._bars
        painter.setPen(Qt.NoPen)
        for i, level in enumerate(self._levels):
            bar_h = max(3.0, level * h * 0.9)
            c = QColor(self._color)
            c.setAlphaF(0.35 + 0.65 * level)
            painter.setBrush(c)
            painter.drawRoundedRect(QRectF(i * gap + gap * 0.25, (h - bar_h) / 2, gap * 0.5, bar_h), 3, 3)


class MoodBadge(QWidget):
    """Small coloured pill with the mood name (for the chat header / HUD)."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._text = "happy"
        self._color = QColor(EMOTION_COLORS["happy"])
        self._bg = QColor("#0b1020")  # what the pill sits on (set by the window)
        self.setFixedHeight(24)
        self.setMinimumWidth(110)

    def set_mood(self, emotion: str, intensity: float) -> None:
        self._text = f"{emotion.replace('_', ' ')} {intensity:.0%}"
        self._color = QColor(EMOTION_COLORS.get(emotion, "#3B82F6"))
        self.update()

    def set_bg(self, color: str) -> None:
        """Tell the badge what surface it paints on, so the label always has
        contrast (a 25%-alpha tint reads completely differently on the light
        theme than on the cyberpunk one)."""
        self._bg = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        c = QColor(self._color)
        c.setAlphaF(0.25)
        painter.setPen(QPen(self._color, 1))
        painter.setBrush(c)
        painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 12, 12)
        # Contrast against the *blended* pill (tint over the window surface).
        blended = QColor(
            int(self._color.red() * 0.25 + self._bg.red() * 0.75),
            int(self._color.green() * 0.25 + self._bg.green() * 0.75),
            int(self._color.blue() * 0.25 + self._bg.blue() * 0.75),
        )
        lum = (0.299 * blended.red() + 0.587 * blended.green() + 0.114 * blended.blue()) / 255.0
        painter.setPen(self._color.lighter(150) if lum < 0.5 else self._color.darker(300))
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, self._text)


# ============================================================================
# Cyber-glass component kit (Settings redesign, concept-style)
# ============================================================================

class GlassCard(QFrame):
    """A floating translucent card with a neon border (and optional glow)."""

    def __init__(self, parent: Optional[QWidget] = None, glow: bool = False,
                 glow_color: str = "#7b5cff", soft: bool = False):
        super().__init__(parent)
        self.setObjectName("softCard" if soft else "glassCard")
        if glow:
            eff = QGraphicsDropShadowEffect(self)
            eff.setBlurRadius(28)
            c = QColor(glow_color)
            c.setAlphaF(0.45)
            eff.setColor(c)
            eff.setOffset(0, 0)
            self.setGraphicsEffect(eff)


class NeonToggle(QAbstractButton):
    """Animated iOS-style toggle with a cyan→violet neon track."""

    def __init__(self, checked: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 1.0 if checked else 0.0  # knob position 0..1
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self.setFixedSize(54, 28)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        knob_r = h // 2 - 4
        knob_x = 4 + self._pos * (w - 8 - 2 * knob_r)

        track = QRectF(1, 1, w - 2, h - 2)
        if self.isChecked():
            grad = QLinearGradient(0, 0, w, 0)
            grad.setColorAt(0.0, QColor("#00e5ff"))
            grad.setColorAt(1.0, QColor("#a855f7"))
            p.setBrush(QBrush(grad))
            p.setPen(QPen(QColor(0, 229, 255, 120), 1))
        else:
            p.setBrush(QColor(30, 42, 80, 200))
            p.setPen(QPen(QColor(80, 100, 150, 120), 1))
        p.drawRoundedRect(track, h / 2, h / 2)

        # knob (soft white with a slight neon halo when on)
        if self.isChecked():
            halo = QRadialGradient(QPointF(knob_x + knob_r, h / 2), knob_r * 2)
            halo.setColorAt(0.0, QColor(0, 229, 255, 90))
            halo.setColorAt(1.0, QColor(0, 229, 255, 0))
            p.setBrush(QBrush(halo))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(knob_x + knob_r, h / 2), knob_r * 2, knob_r * 2)
        p.setBrush(QColor(255, 255, 255) if self.isChecked() else QColor(190, 200, 225))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(knob_x + knob_r, h / 2), knob_r, knob_r)

    def _animate(self) -> None:
        target = 1.0 if self.isChecked() else 0.0
        self._pos += (target - self._pos) * 0.35
        if abs(target - self._pos) < 0.01:
            self._pos = target
            self._timer.stop()
        self.update()

    def nextCheckState(self) -> None:  # noqa: N802
        super().nextCheckState()
        self._timer.start(16)


class GradientSlider(QSlider):
    """Horizontal slider with a cyan→violet gradient groove and neon handle."""

    def __init__(self, min_v: int, max_v: int, value: int, parent: Optional[QWidget] = None):
        super().__init__(Qt.Horizontal, parent)
        self.setRange(min_v, max_v)
        self.setValue(value)
        self.setFixedHeight(26)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cy = h / 2
        groove_w = w - 20
        x0, x1 = 10, 10 + groove_w

        # track (dim) + filled gradient portion
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(30, 42, 80, 210))
        p.drawRoundedRect(QRectF(x0, cy - 3, groove_w, 6), 3, 3)
        frac = (self.value() - self.minimum()) / max(1, self.maximum() - self.minimum())
        if frac > 0:
            grad = QLinearGradient(x0, 0, x1, 0)
            grad.setColorAt(0.0, QColor("#00e5ff"))
            grad.setColorAt(1.0, QColor("#a855f7"))
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(QRectF(x0, cy - 3, max(6.0, groove_w * frac), 6), 3, 3)

        # handle: white core + neon ring
        hx = x0 + groove_w * frac
        halo = QRadialGradient(QPointF(hx, cy), 14)
        halo.setColorAt(0.0, QColor(0, 229, 255, 70))
        halo.setColorAt(1.0, QColor(0, 229, 255, 0))
        p.setBrush(QBrush(halo))
        p.drawEllipse(QPointF(hx, cy), 14, 14)
        p.setBrush(QColor("#0b1230"))
        p.setPen(QPen(QColor("#00e5ff"), 2))
        p.drawEllipse(QPointF(hx, cy), 8, 8)
        p.setBrush(QColor("#eaf6ff"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(hx, cy), 3.2, 3.2)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            frac = (event.x() - 10) / max(1, self.width() - 20)
            self.setValue(round(self.minimum() + frac * (self.maximum() - self.minimum())))
            event.accept()
        super().mousePressEvent(event)


class ModeChip(QPushButton):
    """Segmented-control chip: Chill / Balanced / Energetic."""

    def __init__(self, text: str, parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self.setObjectName("modeChip")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)


class AvatarCircle(QWidget):
    """Circular portrait (local asset, or painted gradient glyph fallback).
    Click to select — shows a neon ring + soft glow when selected."""

    selected = pyqtSignal(str)

    def __init__(self, style_id: str, size: int = 96, selectable: bool = True, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.style_id = style_id
        self._size = size
        self._selectable = selectable
        self._selected = False
        self._hover = False
        self.setFixedSize(size + 16, size + 16)
        self.setCursor(Qt.PointingHandCursor if selectable else Qt.ArrowCursor)
        self.setMouseTracking(selectable)

    def set_selected(self, on: bool) -> None:
        self._selected = on
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx = self.width() / 2
        cy = self.height() / 2
        r = self._size / 2
        centre = QPointF(cx, cy)

        info = AVATAR_STYLES.get(self.style_id, AVATAR_STYLES["nebula"])

        # selection glow
        if self._selected:
            halo = QRadialGradient(centre, r * 1.55)
            halo.setColorAt(0.62, QColor(0, 229, 255, 0))
            halo.setColorAt(0.78, QColor(0, 229, 255, 90))
            halo.setColorAt(1.0, QColor(0, 229, 255, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(halo))
            p.drawEllipse(centre, r * 1.55, r * 1.55)

        p.save()
        path = QPainterPath()
        path.addEllipse(centre, r, r)
        p.setClipPath(path)

        pix = avatar_image(self.style_id)
        if pix is not None:
            scaled = pix.scaled(int(self._size), int(self._size),
                                Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            p.drawPixmap(int(cx - scaled.width() / 2), int(cy - scaled.height() / 2), scaled)
        else:
            grad = QLinearGradient(cx - r, cy - r, cx + r, cy + r)
            grad.setColorAt(0.0, QColor(info["a"]))
            grad.setColorAt(1.0, QColor(info["b"]))
            p.setBrush(QBrush(grad))
            p.setPen(Qt.NoPen)
            p.drawEllipse(centre, r, r)
            # soft top highlight for the glass feel
            shine = QRadialGradient(QPointF(cx - r * 0.3, cy - r * 0.45), r * 0.9)
            shine.setColorAt(0.0, QColor(255, 255, 255, 70))
            shine.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setBrush(QBrush(shine))
            p.drawEllipse(centre, r, r)
            font = QFont()
            font.setPixelSize(int(r * 0.8))
            font.setBold(True)
            p.setFont(font)
            p.setPen(QColor(255, 255, 255, 235))
            p.drawText(QRectF(cx - r, cy - r, 2 * r, 2 * r), Qt.AlignCenter, info["letter"])
        p.restore()

        # rim
        if self._selected:
            p.setPen(QPen(QColor("#00e5ff"), 2.4))
        elif self._hover and self._selectable:
            p.setPen(QPen(QColor(0, 229, 255, 140), 1.6))
        else:
            p.setPen(QPen(QColor(140, 160, 210, 90), 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(centre, r, r)

        if self._selectable:
            label = QFont()
            label.setPointSize(8)
            p.setFont(label)
            p.setPen(QColor("#8ea3d0") if not self._selected else QColor("#00e5ff"))
            p.drawText(QRectF(0, self.height() - 16, self.width(), 14), Qt.AlignCenter, info["label"])

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._selectable and event.button() == Qt.LeftButton:
            self.selected.emit(self.style_id)
        super().mousePressEvent(event)


class AvatarPicker(QWidget):
    """The avatar style carousel (row of circular selectable portraits)."""

    changed = pyqtSignal(str)

    def __init__(self, current: str = "nebula", size: int = 84, parent: Optional[QWidget] = None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 12)
        lay.setSpacing(14)
        self._circles: Dict[str, AvatarCircle] = {}
        for style_id in AVATAR_STYLES:
            circle = AvatarCircle(style_id, size=size)
            circle.selected.connect(self._on_pick)
            lay.addWidget(circle)
            self._circles[style_id] = circle
        lay.addStretch()
        self.set_selected(current)

    def _on_pick(self, style_id: str) -> None:
        self.set_selected(style_id)
        self.changed.emit(style_id)

    def set_selected(self, style_id: str) -> None:
        for sid, circle in self._circles.items():
            circle.set_selected(sid == style_id)

    def selected(self) -> str:
        for sid, circle in self._circles.items():
            if circle._selected:
                return sid
        return "nebula"


class StatusToast(QLabel):
    """The little status line at the bottom of Settings — green when saved,
    red on errors; clears itself after a few seconds."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.clear)
        self.setMinimumHeight(22)

    def show_message(self, text: str, kind: str = "ok", seconds: int = 4) -> None:
        color = "#34d399" if kind == "ok" else "#f87171"
        self.setText(text)
        self.setStyleSheet(
            f"color: {color}; background: rgba(52, 211, 153, 0.08); border: 1px solid {color};"
            "border-radius: 10px; padding: 6px 14px; font-weight: 600;"
        )
        self._timer.start(seconds * 1000)

    def clear(self) -> None:
        super().clear()
        self.setStyleSheet("")


class OnlinePill(QLabel):
    """The 'ONLINE' badge under the avatar / in the header."""

    def __init__(self, text: str = "● ONLINE", parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self.setObjectName("onlinePill")
