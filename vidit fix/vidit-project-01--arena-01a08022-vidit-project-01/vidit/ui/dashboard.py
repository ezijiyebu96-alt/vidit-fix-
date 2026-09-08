"""Soul Dashboard (Constitution section 10H).

Memory map (graph), emotion timeline (24 h), learning progress, system
stats, current mood, active time, session count, memory size — plus the
things he is proud of and worried about, and his favourite memories.
"""
from __future__ import annotations

import logging
import math
import random
import time
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget, QProgressBar, QPushButton, QTabWidget,
                             QTextBrowser, QVBoxLayout, QWidget)

from ..constitution import EMOTION_COLORS
from ..core import Vidit
from ..utils import human_size
from .widgets import OrbWidget


class EmotionTimeline(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.points: List[Dict[str, Any]] = []
        self.setMinimumHeight(180)

    def set_points(self, points: List[Dict[str, Any]]) -> None:
        self.points = points
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        painter.setPen(QPen(QColor(120, 120, 160, 90), 1))
        for frac in (0.25, 0.5, 0.75):
            painter.drawLine(0, int(h * frac), w, int(h * frac))
        if not self.points:
            painter.setPen(QColor(150, 150, 170))
            painter.drawText(self.rect(), Qt.AlignCenter, "No mood history yet — talk to me a bit.")
            return
        now = time.time()
        start = now - 24 * 3600
        last_x = None
        for p in self.points:
            x = (p["t"] - start) / (24 * 3600) * w
            y = h - p["intensity"] * (h - 10) - 5
            c = QColor(EMOTION_COLORS.get(p["dominant"], "#888"))
            painter.setPen(Qt.NoPen)
            painter.setBrush(c)
            painter.drawEllipse(QPointF(x, y), 3.5, 3.5)
            if last_x is not None:
                painter.setPen(QPen(c, 1.5))
                painter.drawLine(QPointF(last_x[0], last_x[1]), QPointF(x, y))
            last_x = (x, y)
        painter.setPen(QColor(150, 150, 170))
        painter.drawText(4, h - 4, "24h ago")
        painter.drawText(w - 30, h - 4, "now")


class MemoryMap(QWidget):
    """A simple force-directed graph of what he remembers."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.graph: Dict[str, Any] = {"nodes": [], "edges": []}
        self.pos: Dict[str, List[float]] = {}
        self.setMinimumHeight(320)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._steps = 0

    def set_graph(self, graph: Dict[str, Any]) -> None:
        self.graph = graph
        w, h = max(300, self.width()), max(300, self.height())
        for n in graph["nodes"]:
            if n["id"] not in self.pos:
                if n["id"] == "you":
                    self.pos[n["id"]] = [w / 2, h / 2]
                else:
                    self.pos[n["id"]] = [w / 2 + random.uniform(-150, 150), h / 2 + random.uniform(-120, 120)]
        self._steps = 0
        self._timer.start(30)

    def _step(self) -> None:
        nodes = self.graph["nodes"]
        edges = self.graph["edges"]
        if not nodes:
            self._timer.stop()
            return
        ids = [n["id"] for n in nodes]
        forces = {i: [0.0, 0.0] for i in ids}
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                dx = self.pos[a][0] - self.pos[b][0]
                dy = self.pos[a][1] - self.pos[b][1]
                d2 = dx * dx + dy * dy + 0.01
                f = 2200 / d2
                d = math.sqrt(d2)
                forces[a][0] += f * dx / d
                forces[a][1] += f * dy / d
                forces[b][0] -= f * dx / d
                forces[b][1] -= f * dy / d
        for e in edges:
            a, b = e["source"], e["target"]
            if a not in self.pos or b not in self.pos:
                continue
            dx = self.pos[b][0] - self.pos[a][0]
            dy = self.pos[b][1] - self.pos[a][1]
            d = math.sqrt(dx * dx + dy * dy) + 0.01
            f = (d - 70) * 0.02
            forces[a][0] += f * dx / d
            forces[a][1] += f * dy / d
            forces[b][0] -= f * dx / d
            forces[b][1] -= f * dy / d
        w, h = self.width(), self.height()
        for i in ids:
            if i == "you":
                self.pos[i] = [w / 2, h / 2]
                continue
            self.pos[i][0] = min(w - 20, max(20, self.pos[i][0] + forces[i][0] * 0.4))
            self.pos[i][1] = min(h - 20, max(20, self.pos[i][1] + forces[i][1] * 0.4))
        self._steps += 1
        if self._steps > 250:
            self._timer.stop()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.graph["nodes"]:
            painter.setPen(QColor(150, 150, 170))
            painter.drawText(self.rect(), Qt.AlignCenter, "Empty for now. Everything you teach me will appear here.")
            return
        painter.setPen(QPen(QColor(120, 140, 200, 110), 1))
        for e in self.graph["edges"]:
            a, b = self.pos.get(e["source"]), self.pos.get(e["target"])
            if a and b:
                painter.drawLine(QPointF(*a), QPointF(*b))
        colours = {"root": "#f59e0b", "hub": "#4f7cff", "person": "#22c55e", "preference": "#a855f7", "fact": "#3b82f6",
                   "goal": "#eab308", "moment": "#f472b6", "lesson": "#fb923c", "correction": "#ef4444", "note": "#94a3b8",
                   "event": "#2dd4bf", "skill": "#84cc16"}
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        for n in self.graph["nodes"]:
            p = self.pos.get(n["id"])
            if not p:
                continue
            c = QColor(colours.get(n["kind"], "#94a3b8"))
            painter.setPen(QPen(c.lighter(150), 1))
            painter.setBrush(c)
            r = n["size"] / 2
            painter.drawEllipse(QPointF(*p), r, r)
            if n["kind"] in ("root", "hub") or n.get("favorite"):
                painter.setPen(QColor(230, 236, 255))
                painter.drawText(QRectF(p[0] - 80, p[1] + r + 2, 160, 14), Qt.AlignCenter, n["label"][:28])


class SoulDashboard(QWidget):
    def __init__(self, vidit: Vidit, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.vidit = vidit
        self.setWindowTitle("Soul Dashboard")
        self.resize(1000, 720)
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    # Only poll stats/memories while the dashboard is actually visible.
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start(5000)
            self.refresh()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        head = QHBoxLayout()
        self.orb = OrbWidget(size=64)
        head.addWidget(self.orb)
        col = QVBoxLayout()
        self.title = QLabel("Vidit's soul")
        self.title.setObjectName("title")
        self.mood_label = QLabel("")
        col.addWidget(self.title)
        col.addWidget(self.mood_label)
        head.addLayout(col)
        head.addStretch()
        self.understanding = QProgressBar()
        self.understanding.setFormat("I understand you %p%")
        self.understanding.setFixedWidth(260)
        head.addWidget(self.understanding)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        head.addWidget(refresh_btn)
        root.addLayout(head)

        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        # Overview
        overview = QWidget()
        grid = QGridLayout(overview)
        self.stats_box = QTextBrowser()
        self.system_box = QTextBrowser()
        self.brain_box = QTextBrowser()
        self.feelings_box = QTextBrowser()
        for i, (label, widget) in enumerate((("Self", self.stats_box), ("System", self.system_box), ("Brain and senses", self.brain_box), ("Feelings right now", self.feelings_box))):
            frame = QFrame()
            frame.setObjectName("panel")
            lay = QVBoxLayout(frame)
            t = QLabel(label)
            t.setObjectName("title")
            lay.addWidget(t)
            lay.addWidget(widget)
            grid.addWidget(frame, i // 2, i % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        tabs.addTab(overview, "Overview")

        # Emotion timeline
        tl = QWidget()
        tl_lay = QVBoxLayout(tl)
        tl_lay.addWidget(QLabel("Mood over the last 24 hours (colour = emotion, height = intensity)"))
        self.timeline = EmotionTimeline()
        tl_lay.addWidget(self.timeline, 1)
        self.timeline_log = QListWidget()
        tl_lay.addWidget(self.timeline_log, 1)
        tabs.addTab(tl, "Emotion timeline")

        # Memory map
        mm = QWidget()
        mm_lay = QVBoxLayout(mm)
        self.memory_map = MemoryMap()
        mm_lay.addWidget(self.memory_map, 2)
        self.favorites = QTextBrowser()
        mm_lay.addWidget(QLabel("Favorite memories"))
        mm_lay.addWidget(self.favorites, 1)
        tabs.addTab(mm, "Memory map")

        # Learning
        learn = QWidget()
        learn_lay = QVBoxLayout(learn)
        self.learning_bars: Dict[str, QProgressBar] = {}
        for dim in ("identity", "people", "preferences", "goals", "shared_moments", "lessons"):
            row = QHBoxLayout()
            row.addWidget(QLabel(dim.replace("_", " ").title()))
            bar = QProgressBar()
            self.learning_bars[dim] = bar
            row.addWidget(bar, 1)
            learn_lay.addLayout(row)
        self.goals_box = QTextBrowser()
        learn_lay.addWidget(QLabel("Goals, achievements & worries"))
        learn_lay.addWidget(self.goals_box, 1)
        tabs.addTab(learn, "Learning progress")

        # Permissions & skills
        perm = QWidget()
        perm_lay = QVBoxLayout(perm)
        self.perm_box = QTextBrowser()
        perm_lay.addWidget(QLabel("Permissions in effect"))
        perm_lay.addWidget(self.perm_box, 1)
        self.skills_box = QTextBrowser()
        perm_lay.addWidget(QLabel("Skills he has built for himself"))
        perm_lay.addWidget(self.skills_box, 1)
        tabs.addTab(perm, "Permissions && skills")

    def refresh(self) -> None:
        try:
            self._refresh()
        except Exception:  # noqa: BLE001  — one bad refresh must not kill the dashboard
            log.exception("dashboard refresh failed")

    def _refresh(self) -> None:
        d = self.vidit.soul_dashboard()
        mood = d["mood"]
        self.orb.set_emotion(mood["dominant"], mood["intensity"], mood["face"])
        self.title.setText(f"{d['name']}'s soul")
        self.mood_label.setText(f"Feeling {mood['describe']} · {d['hours_since_contact']:.1f}h since we last talked")
        self.understanding.setValue(int(d["understanding"]["percent"]))

        s = d["self"]
        self.stats_box.setHtml(
            f"<b>Age:</b> {s['age']}<br><b>Sessions:</b> {s['sessions']}<br><b>Active time:</b> {s['active_time']}<br>"
            f"<b>Messages:</b> {s['messages']}<br><b>Lessons learned:</b> {s['lessons']}<br>"
            f"<b>Mistakes:</b> {s['mistakes']} (corrected {s['mistakes_corrected']})<br>"
            f"<b>Memories:</b> {d['memory']['count']} ({human_size(d['memory']['size_bytes'])})"
        )
        sy = d["system"]
        gpu = sy.get("gpu")
        self.system_box.setHtml(
            f"<b>OS:</b> {sy.get('os')}<br><b>CPU:</b> {sy.get('cpu_percent', '?')}%<br><b>RAM:</b> {sy.get('ram_percent', '?')}% "
            f"({sy.get('ram_used', '?')} / {sy.get('ram_total', '?')})<br>"
            + (f"<b>GPU:</b> {gpu['name']} {gpu['util_percent']:.0f}% · VRAM {gpu['vram_used_mb']:.0f}/{gpu['vram_total_mb']:.0f} MB · {gpu['temp_c']:.0f}°C<br>" if gpu else "<b>GPU:</b> n/a<br>")
            + f"<b>Disk free:</b> {sy.get('disk_free', '?')}<br><b>Uptime:</b> {sy.get('uptime', '?')}"
        )
        b, v, e, ey = d["brain"], d["voice"], d["ears"], d["eyes"]
        if not e["available"]:
            ears_line = "<b>⚠ Ears:</b> not installed (pip install faster-whisper sounddevice numpy)"
        else:
            mark = "✓" if e["model_ready"] else "…"
            ears_line = (f"<b>{mark} Ears:</b> {'listening' if e['listening'] else 'idle'} · "
                         f"whisper model {'ready' if e['model_ready'] else 'not loaded yet'}"
                         + (f" — <i>{e['error']}</i>" if e["error"] else ""))
        self.brain_box.setHtml(
            f"<b>Model:</b> {b['backend']} / {b['model']}<br><b>Ollama reachable:</b> {b['ollama_reachable']}<br>"
            f"<b>Installed models:</b> {', '.join(b['installed_models']) or '—'}<br><b>Calls:</b> {b['calls']} (failed {b['failures']})<br>"
            f"<b>Last error:</b> {b['last_error'] or '—'}<br><b>Voice:</b> {v['engine']} ({v['profile']})<br>"
            f"{ears_line}<br>"
            f"<b>Eyes:</b> {'available' if ey['available'] else 'not installed'}"
        )
        self.feelings_box.setHtml("<br>".join(
            f"<span style='color:{EMOTION_COLORS.get(k, '#888')}'>●</span> {k.replace('_', ' ')}: {v:.0%}" for k, v in mood["top"]))

        self.timeline.set_points(d["timeline"])
        self.timeline_log.clear()
        for p in d["timeline"][-40:][::-1]:
            self.timeline_log.addItem(f"{time.strftime('%H:%M', time.localtime(p['t']))}  {p['dominant']:<12} {p['intensity']:.0%}  ({p['why']})")

        self.memory_map.set_graph(d["memory_map"])
        self.favorites.setHtml("<br>".join(f"★ {f}" for f in d["memory"]["favorites"]) or "None yet.")

        for dim, bar in self.learning_bars.items():
            bar.setValue(int(d["understanding"]["breakdown"].get(dim, 0)))
        self.goals_box.setHtml(
            "<b>Goals</b><br>" + "<br>".join(f"• {g}" for g in s["goals"]) +
            "<br><br><b>Proud of</b><br>" + ("<br>".join(f"• {a}" for a in s["achievements"]) or "—") +
            "<br><br><b>Worries</b><br>" + ("<br>".join(f"• {w}" for w in s["worries"]) or "nothing right now")
        )
        self.perm_box.setHtml("<br>".join(f"<b>{k}</b>: {v}" for k, v in d["permissions"].items()))
        self.skills_box.setHtml("<br>".join(f"<b>{sk['name']}</b> — {sk['description']}" for sk in d["skills"]) or "None yet.")
