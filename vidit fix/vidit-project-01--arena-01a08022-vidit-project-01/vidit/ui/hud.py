"""HUD Overlay (Constitution section 3A): Iron-Man style translucent panels.

A click-through-ish, frameless, always-on-top window covering the screen
with a few glowing panels: system stats, Vidit's mood, the last exchange,
and a quick command line. Meant for gaming/working; the *game* theme keeps
it transparent.
"""
from __future__ import annotations

import logging
from typing import Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from ..core import Vidit
from .widgets import MoodBadge, OrbWidget, WaveformWidget

log = logging.getLogger("vidit.ui.hud")


class _Panel(QFrame):
    def __init__(self, title: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.setStyleSheet("QFrame#panel { background: rgba(8, 12, 24, 170); border: 1px solid rgba(80, 140, 255, 140); border-radius: 12px; }")
        lay = QVBoxLayout(self)
        head = QLabel(title.upper())
        head.setStyleSheet("color: #7cc4ff; font-weight: 700; letter-spacing: 2px; font-size: 11px; background: transparent;")
        lay.addWidget(head)
        self.body = QLabel("")
        self.body.setWordWrap(True)
        self.body.setStyleSheet("color: #e6f2ff; background: transparent; font-family: Consolas, monospace; font-size: 12px;")
        lay.addWidget(self.body)
        lay.addStretch()


class HudOverlay(QWidget):
    closed = pyqtSignal()
    command = pyqtSignal(str)

    def __init__(self, vidit: Vidit, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.vidit = vidit
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(2000)
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)
        top = QHBoxLayout()
        self.sys_panel = _Panel("System")
        self.sys_panel.setFixedWidth(300)
        top.addWidget(self.sys_panel, 0, Qt.AlignTop)
        top.addStretch()
        centre = QVBoxLayout()
        self.orb = OrbWidget(size=96)
        centre.addWidget(self.orb, 0, Qt.AlignHCenter)
        self.mood = MoodBadge()
        self.mood.set_bg("#080c18")
        centre.addWidget(self.mood, 0, Qt.AlignHCenter)
        top.addLayout(centre)
        top.addStretch()
        self.mind_panel = _Panel("Vidit")
        self.mind_panel.setFixedWidth(320)
        top.addWidget(self.mind_panel, 0, Qt.AlignTop)
        root.addLayout(top)
        root.addStretch()
        bottom = QHBoxLayout()
        self.chat_panel = _Panel("Last exchange")
        self.chat_panel.setFixedHeight(150)
        bottom.addWidget(self.chat_panel, 1)
        root.addLayout(bottom)
        self.wave = WaveformWidget()
        self.wave.setFixedHeight(28)
        root.addWidget(self.wave)
        self.cmd = QLineEdit()
        self.cmd.setPlaceholderText("Type to Vidit… (Esc closes the HUD)")
        self.cmd.setStyleSheet("QLineEdit { background: rgba(8,12,24,200); color: #e6f2ff; border: 1px solid rgba(80,140,255,160); border-radius: 10px; padding: 8px; }")
        self.cmd.returnPressed.connect(self._send)
        root.addWidget(self.cmd)

    def _send(self) -> None:
        text = self.cmd.text().strip()
        if text:
            self.cmd.clear()
            self.command.emit(text)

    # Don't burn CPU polling stats while the HUD is hidden.
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start(2000)
            self.refresh()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def refresh(self) -> None:
        try:
            self._refresh()
        except Exception:  # noqa: BLE001  — a bad refresh must never kill the HUD
            log.exception("HUD refresh failed")

    def _refresh(self) -> None:
        s = self.vidit.system.stats()
        lines = [f"CPU  {s.get('cpu_percent', '?')}%", f"RAM  {s.get('ram_percent', '?')}%  ({s.get('ram_used', '?')}/{s.get('ram_total', '?')})"]
        if s.get("gpu"):
            g = s["gpu"]
            lines.append(f"GPU  {g['util_percent']:.0f}%  VRAM {g['vram_used_mb']:.0f}/{g['vram_total_mb']:.0f}MB  {g['temp_c']:.0f}°C")
        if "battery_percent" in s:
            lines.append(f"BAT  {s['battery_percent']}%{' ⚡' if s.get('plugged_in') else ''}")
        lines.append(f"DISK {s.get('disk_free', '?')} free")
        lines.append(s.get("time", ""))
        self.sys_panel.body.setText("\n".join(lines))

        st = self.vidit.emotions.state()
        self.orb.set_emotion(st.dominant, st.intensity, st.face)
        self.mood.set_mood(st.dominant, st.intensity)
        self.wave.set_color(st.color)
        und = self.vidit.learner.understanding()
        brain = self.vidit.llm.status()
        game = self.vidit.gaming
        ears = self.vidit.ears.status()
        ears_state = "listening" if ears["listening"] else ("ready" if ears["model_ready"] else "idle")
        mind = [f"mood      {st.describe()}", f"knows you {und['percent']:.0f}%", f"brain     {brain['backend']}/{brain['model']}",
                f"memories  {self.vidit.memory.memory_count()}", f"game mode {game.behavior()}{' · in game: ' + game.current_game if game.in_game else ''}",
                f"ears      {ears_state}"]
        self.mind_panel.body.setText("\n".join(mind))

        msgs = self.vidit.memory.messages(self.vidit.conversation_id, limit=2) if self.vidit.conversation_id > 0 else []
        self.chat_panel.body.setText("\n".join(("You: " if m["role"] == "user" else "Vidit: ") + m["content"][:220] for m in msgs))

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(80, 140, 255, 90), 2)
        painter.setPen(pen)
        r = self.rect().adjusted(10, 10, -10, -10)
        # corner brackets
        L = 40
        for (x, y, dx, dy) in ((r.left(), r.top(), 1, 1), (r.right(), r.top(), -1, 1), (r.left(), r.bottom(), 1, -1), (r.right(), r.bottom(), -1, -1)):
            painter.drawLine(x, y, x + dx * L, y)
            painter.drawLine(x, y, x, y + dy * L)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.hide()
            self.closed.emit()
        super().keyPressEvent(event)
