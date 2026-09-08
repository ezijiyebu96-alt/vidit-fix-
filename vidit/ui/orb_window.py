"""Companion Orb & Picture-in-Picture forms (Constitution section 3A).

A frameless, always-on-top, draggable little window with the orb. Click it
to open the chat; double-click to talk; right-click for the mode menu.
PiP mode is the same window with a small transcript strip underneath.
"""
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QPoint, Qt, pyqtSignal
from PyQt5.QtWidgets import QApplication, QLabel, QMenu, QVBoxLayout, QWidget

from .widgets import OrbWidget


class OrbWindow(QWidget):
    openChat = pyqtSignal()
    openHud = pyqtSignal()
    openDashboard = pyqtSignal()
    openSettings = pyqtSignal()
    setMode = pyqtSignal(str)
    quitRequested = pyqtSignal()

    def __init__(self, size: int = 72, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._drag: Optional[QPoint] = None
        self._pip = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.orb = OrbWidget(size)
        layout.addWidget(self.orb, 0, Qt.AlignCenter)
        self.caption = QLabel("")
        self.caption.setAlignment(Qt.AlignCenter)
        self.caption.setWordWrap(True)
        self.caption.setStyleSheet("color: white; background: rgba(0,0,0,140); border-radius: 10px; padding: 6px; font-size: 12px;")
        self.caption.hide()
        layout.addWidget(self.caption)
        self.orb.clicked.connect(self.openChat.emit)
        self.orb.doubleClicked.connect(lambda: self.setMode.emit("listen"))
        self._place_bottom_right()

    def _place_bottom_right(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        self.adjustSize()
        self.move(screen.right() - self.width() - 24, screen.bottom() - self.height() - 24)

    # -- PiP -----------------------------------------------------------------
    def set_pip(self, enabled: bool) -> None:
        self._pip = enabled
        if enabled:
            self.caption.show()
            self.setFixedWidth(260)
        else:
            self.caption.hide()
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)
            self.adjustSize()

    def show_caption(self, text: str) -> None:
        if self._pip:
            self.caption.setText(text[:220])

    # -- drag ----------------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag = event.globalPos() - self.frameGeometry().topLeft()
        elif event.button() == Qt.RightButton:
            self._menu(event.globalPos())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag = None

    def _menu(self, pos) -> None:
        menu = QMenu(self)
        actions = {
            menu.addAction("💬 Chat window"): lambda: self.openChat.emit(),
            menu.addAction("🛰 HUD overlay"): lambda: self.openHud.emit(),
            menu.addAction("🖥 Full-screen"): lambda: self.setMode.emit("fullscreen"),
            menu.addAction("📺 Picture-in-Picture"): lambda: self.setMode.emit("pip"),
            menu.addAction("🕶 Stealth mode"): lambda: self.setMode.emit("stealth"),
        }
        menu.addSeparator()
        actions[menu.addAction("🧠 Soul dashboard")] = lambda: self.openDashboard.emit()
        actions[menu.addAction("⚙ Settings")] = lambda: self.openSettings.emit()
        menu.addSeparator()
        actions[menu.addAction("Quit")] = lambda: self.quitRequested.emit()
        chosen = menu.exec_(pos)
        if chosen in actions:
            actions[chosen]()
