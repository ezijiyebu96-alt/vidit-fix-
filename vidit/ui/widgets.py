"""Reusable visual pieces: the Orb, the Face, the Waveform, emotion badges."""
from __future__ import annotations

import math
import random
from typing import List, Optional

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt5.QtWidgets import QWidget

from ..constitution import EMOTION_COLORS


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
            if animate and not self._timer.isActive():
                self._timer.start(33)
            elif not animate:
                self._timer.stop()
                self.update()

    def _tick(self) -> None:
        self._phase += 0.05 * self._pulse_speed * (1.5 if self._speaking else 2.5 if self._thinking else 1.0)
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
        radius = self._size / 2 * breathe

        # outer glow
        glow = QRadialGradient(QPointF(cx, cy), radius * 1.6)
        c = QColor(self._color)
        c.setAlphaF(0.55 * self._glow)
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

        # thinking ring
        if self._thinking:
            pen = QPen(self._color.lighter(170), 2.5)
            pen.setDashPattern([3, 4])
            pen.setDashOffset(self._phase * 6)
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
        self._color = QColor("#4f7cff")
        self._phase = 0.0
        self.setMinimumHeight(40)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def set_active(self, active: bool) -> None:
        self._active = active

    def set_color(self, color: str) -> None:
        self._color = QColor(color)

    def _tick(self) -> None:
        self._phase += 0.25
        for i in range(self._bars):
            if self._active:
                target = 0.3 + 0.7 * abs(math.sin(self._phase + i * 0.45)) * random.uniform(0.5, 1.0)
            else:
                target = 0.08 + 0.05 * math.sin(self._phase * 0.5 + i * 0.3)
            self._levels[i] += (target - self._levels[i]) * 0.3
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
        self.setFixedHeight(24)
        self.setMinimumWidth(110)

    def set_mood(self, emotion: str, intensity: float) -> None:
        self._text = f"{emotion.replace('_', ' ')} {intensity:.0%}"
        self._color = QColor(EMOTION_COLORS.get(emotion, "#3B82F6"))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        c = QColor(self._color)
        c.setAlphaF(0.25)
        painter.setPen(QPen(self._color, 1))
        painter.setBrush(c)
        painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 12, 12)
        painter.setPen(self._color.lighter(150))
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, self._text)
