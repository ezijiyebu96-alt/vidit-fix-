"""Permission pop-ups & notifications (Constitution section 8 & 10F)."""
from __future__ import annotations

import queue
import threading
from typing import Optional

from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..guardian import Decision, PermissionRequest


class PermissionDialog(QDialog):
    def __init__(self, request: PermissionRequest, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Vidit is asking")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.decision = Decision.DENY
        lay = QVBoxLayout(self)
        title = QLabel("May I?")
        title.setObjectName("title")
        lay.addWidget(title)
        q = QLabel(request.question)
        q.setWordWrap(True)
        lay.addWidget(q)
        if request.detail:
            detail = QLabel(request.detail[:600])
            detail.setObjectName("muted")
            detail.setWordWrap(True)
            lay.addWidget(detail)
        row = QHBoxLayout()
        for label, decision, primary in (("Yes, once", Decision.ALLOW_ONCE, True), ("Yes, this session", Decision.ALLOW_SESSION, False),
                                         ("Always", Decision.ALLOW_ALWAYS, False), ("No", Decision.DENY, False), ("Never", Decision.DENY_ALWAYS, False)):
            btn = QPushButton(label)
            if primary:
                btn.setObjectName("primary")
            btn.clicked.connect(lambda _, d=decision: self._choose(d))
            row.addWidget(btn)
        lay.addLayout(row)

    def _choose(self, decision: Decision) -> None:
        self.decision = decision
        self.accept()


class GuiPrompter(QObject):
    """Thread-safe bridge: worker threads ask, the GUI thread shows the dialog."""

    _ask = pyqtSignal(object, object)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._parent = parent
        self._ask.connect(self._show, Qt.QueuedConnection)

    def __call__(self, request: PermissionRequest) -> Decision:
        app = QApplication.instance()
        if app is None:
            return Decision.DENY
        if threading.current_thread() is threading.main_thread():
            return self._run_dialog(request)
        answer: "queue.Queue[Decision]" = queue.Queue()
        self._ask.emit(request, answer)
        try:
            return answer.get(timeout=180)
        except queue.Empty:
            return Decision.DENY

    def _show(self, request: PermissionRequest, answer: "queue.Queue[Decision]") -> None:
        answer.put(self._run_dialog(request))

    def _run_dialog(self, request: PermissionRequest) -> Decision:
        dialog = PermissionDialog(request, self._parent)
        dialog.exec_()
        return dialog.decision


class Toast(QWidget):
    """A small non-blocking notification in the corner."""

    def __init__(self, text: str, seconds: int = 5, color: str = "#4f7cff"):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        lay = QVBoxLayout(self)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"background: rgba(10,14,28,220); color: white; border: 1px solid {color}; border-radius: 12px; padding: 12px; font-size: 13px;")
        label.setMaximumWidth(360)
        lay.addWidget(label)
        self.adjustSize()
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 24, screen.bottom() - self.height() - 120)
        QTimer.singleShot(seconds * 1000, self.close)
