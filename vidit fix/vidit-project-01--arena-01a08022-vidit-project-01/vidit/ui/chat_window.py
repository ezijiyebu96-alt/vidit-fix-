"""The Chat Window (Constitution sections 3A & 4).

Translucent, glowing chat with markdown, attachments (drag & drop), the
Think toggle, mic button, emoji reactions, editing, threads, search, pins,
folders and export. Vidit's thinking runs in a worker thread so the window
never freezes while the local model is generating.
"""
from __future__ import annotations

import html
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QKeySequence, QTextCursor
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
                             QShortcut, QSplitter, QTextBrowser, QVBoxLayout, QWidget)

from ..core import Reply, Vidit
from .widgets import MoodBadge, OrbWidget, WaveformWidget

try:
    import markdown as _markdown
except ImportError:  # pragma: no cover
    _markdown = None

REACTIONS = ["❤️", "😂", "🤔", "👍", "🔥", "😢"]


def render_markdown(text: str) -> str:
    if _markdown is None:
        return "<p>" + html.escape(text).replace("\n", "<br>") + "</p>"
    try:
        return _markdown.markdown(text, extensions=["fenced_code", "tables", "sane_lists", "nl2br"])
    except Exception:  # noqa: BLE001
        return "<p>" + html.escape(text).replace("\n", "<br>") + "</p>"


class _ChatWorker(QObject):
    """Runs Vidit.chat off the UI thread."""

    chunk = pyqtSignal(str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, vidit: Vidit, text: str, attachments: List[str], reply_to: Optional[int]):
        super().__init__()
        self.vidit, self.text, self.attachments, self.reply_to = vidit, text, attachments, reply_to

    def run(self) -> None:
        try:
            reply = self.vidit.chat(self.text, attachments=self.attachments, stream_cb=self.chunk.emit, reply_to=self.reply_to)
            self.finished.emit(reply)
        except Exception as exc:  # noqa: BLE001
            self.vidit.repair.record_failure("chat", exc)
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class ChatWindow(QWidget):
    replyReady = pyqtSignal(object)

    def __init__(self, vidit: Vidit, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.vidit = vidit
        self.setWindowTitle(vidit.self_model.data.get("name", "Vidit"))
        self.setAcceptDrops(True)
        self.resize(980, 680)
        self._attachments: List[str] = []
        self._reply_to: Optional[int] = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[_ChatWorker] = None
        self._stream_buffer = ""
        self._messages: List[Dict[str, Any]] = []
        self._typing_dots = 0
        self._build()
        self._load_conversations()
        self._render_all()

        self._typing_timer = QTimer(self)
        self._typing_timer.timeout.connect(self._animate_typing)

    # ------------------------------------------------------------------ ui
    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        # --- sidebar: folders & conversations -------------------------------
        side = QFrame()
        side.setObjectName("panel")
        sl = QVBoxLayout(side)
        header = QHBoxLayout()
        title = QLabel("Chats")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()
        new_btn = QPushButton("+ New")
        new_btn.setObjectName("ghost")
        new_btn.setToolTip("New conversation")
        new_btn.clicked.connect(self.new_conversation)
        header.addWidget(new_btn)
        sl.addLayout(header)
        self.folder_box = QComboBox()
        self.folder_box.currentIndexChanged.connect(self._load_conversations)
        sl.addWidget(self.folder_box)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search history…")
        self.search_box.returnPressed.connect(self._search_history)
        sl.addWidget(self.search_box)
        self.conv_list = QListWidget()
        self.conv_list.itemClicked.connect(self._open_conversation)
        self.conv_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.conv_list.customContextMenuRequested.connect(self._conv_menu)
        sl.addWidget(self.conv_list, 1)
        pins_btn = QPushButton("📌 Pinned")
        pins_btn.clicked.connect(self._show_pinned)
        sl.addWidget(pins_btn)
        splitter.addWidget(side)

        # --- main column ----------------------------------------------------
        main = QFrame()
        main.setObjectName("panel")
        ml = QVBoxLayout(main)

        top = QHBoxLayout()
        self.orb = OrbWidget(size=44)
        top.addWidget(self.orb)
        name_col = QVBoxLayout()
        self.name_label = QLabel(self.vidit.self_model.data.get("name", "Vidit"))
        self.name_label.setObjectName("title")
        self.status_label = QLabel("here with you")
        self.status_label.setObjectName("muted")
        name_col.addWidget(self.name_label)
        name_col.addWidget(self.status_label)
        top.addLayout(name_col)
        top.addStretch()
        self.mood_badge = MoodBadge()
        top.addWidget(self.mood_badge)
        self.think_toggle = QCheckBox("Think")
        self.think_toggle.setToolTip("Show Vidit's step-by-step reasoning")
        self.think_toggle.toggled.connect(lambda on: setattr(self.vidit, "show_thinking", on))
        top.addWidget(self.think_toggle)
        export_btn = QPushButton("Export")
        export_btn.clicked.connect(self._export_menu)
        top.addWidget(export_btn)
        ml.addLayout(top)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._message_menu)
        ml.addWidget(self.view, 1)

        self.wave = WaveformWidget()
        self.wave.setFixedHeight(30)
        ml.addWidget(self.wave)

        self.attach_label = QLabel("")
        self.attach_label.setObjectName("muted")
        self.attach_label.hide()
        ml.addWidget(self.attach_label)

        self.reply_label = QLabel("")
        self.reply_label.setObjectName("muted")
        self.reply_label.hide()
        ml.addWidget(self.reply_label)

        bottom = QHBoxLayout()
        attach_btn = QPushButton("📎 Attach")
        attach_btn.setToolTip("Attach files (or drag & drop)")
        attach_btn.clicked.connect(self._pick_files)
        bottom.addWidget(attach_btn)
        self.mic_btn = QPushButton("🎤 Mic")
        self.mic_btn.setCheckable(True)
        self.mic_btn.setToolTip("Voice input (hands-free)")
        self.mic_btn.toggled.connect(self._toggle_mic)
        bottom.addWidget(self.mic_btn)
        self.input = _InputBox(self)
        self.input.setPlaceholderText("Talk to Vidit… (Enter to send, Shift+Enter for a new line)")
        self.input.setFixedHeight(64)
        self.input.submitted.connect(self.send)
        bottom.addWidget(self.input, 1)
        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("primary")
        self.send_btn.clicked.connect(self.send)
        bottom.addWidget(self.send_btn)
        stop_btn = QPushButton("■ Stop")
        stop_btn.setToolTip("Stop (he stops immediately)")
        stop_btn.clicked.connect(self._stop)
        bottom.addWidget(stop_btn)
        ml.addLayout(bottom)
        splitter.addWidget(main)
        splitter.setSizes([240, 740])

        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.search_box.setFocus)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.new_conversation)
        QShortcut(QKeySequence("Ctrl+E"), self, activated=lambda: self._export("txt"))
        QShortcut(QKeySequence("Escape"), self, activated=self._stop)

    # ------------------------------------------------------- conversations
    def _load_conversations(self) -> None:
        folders = self.vidit.memory.folders()
        current = self.folder_box.currentText() if self.folder_box.count() else "All"
        self.folder_box.blockSignals(True)
        self.folder_box.clear()
        self.folder_box.addItems(["All"] + folders + ["＋ New folder…"])
        idx = self.folder_box.findText(current)
        self.folder_box.setCurrentIndex(max(0, idx))
        self.folder_box.blockSignals(False)
        selected = self.folder_box.currentText()
        if selected == "＋ New folder…":
            name, ok = QInputDialog.getText(self, "New folder", "Folder name:")
            if ok and name:
                self.vidit.memory.move_conversation(self.vidit.conversation_id, name)
            self.folder_box.setCurrentIndex(0)
            return
        self.conv_list.clear()
        convs = self.vidit.memory.conversations(None if selected == "All" else selected)
        for c in convs:
            item = QListWidgetItem(f"{c['title']}" + (f"  · {c['folder']}" if c["folder"] else ""))
            item.setData(Qt.UserRole, c["id"])
            self.conv_list.addItem(item)

    def _open_conversation(self, item: QListWidgetItem) -> None:
        cid = item.data(Qt.UserRole)
        self._messages = self.vidit.load_conversation(cid)
        self._render_all()

    def new_conversation(self) -> None:
        self.vidit.new_conversation()
        self._messages = []
        self._render_all()
        self._load_conversations()

    def _conv_menu(self, pos) -> None:
        item = self.conv_list.itemAt(pos)
        if not item:
            return
        cid = item.data(Qt.UserRole)
        menu = QMenu(self)
        rename = menu.addAction("Rename")
        move = menu.addAction("Move to folder…")
        delete = menu.addAction("Delete")
        action = menu.exec_(self.conv_list.mapToGlobal(pos))
        if action == rename:
            name, ok = QInputDialog.getText(self, "Rename", "Title:")
            if ok and name:
                self.vidit.memory.rename_conversation(cid, name)
        elif action == move:
            name, ok = QInputDialog.getText(self, "Move", "Folder:")
            if ok:
                self.vidit.memory.move_conversation(cid, name)
        elif action == delete:
            if QMessageBox.question(self, "Delete", "Delete this conversation?") == QMessageBox.Yes:
                self.vidit.memory.delete_conversation(cid)
        self._load_conversations()

    def _search_history(self) -> None:
        q = self.search_box.text().strip()
        if not q:
            self._render_all()
            return
        hits = self.vidit.memory.search_messages(q)
        parts = [f"<h3>Search: {html.escape(q)} — {len(hits)} results</h3>"]
        for m in hits:
            parts.append(self._bubble(m, highlight=q))
        self.view.setHtml(self._wrap("".join(parts)))

    def _show_pinned(self) -> None:
        pins = self.vidit.memory.pinned()
        parts = ["<h3>📌 Pinned messages</h3>"] + [self._bubble(m) for m in pins]
        self.view.setHtml(self._wrap("".join(parts) if pins else "<p>Nothing pinned yet. Right-click a message → Pin.</p>"))

    # ------------------------------------------------------------ rendering
    def _palette(self) -> Dict[str, str]:
        from .themes import palette

        st = self.vidit.emotions.state()
        return palette(self.vidit.config.get("appearance.theme", "cyberpunk"), st.color, self.vidit.config.get("appearance.custom_theme"))

    def _wrap(self, body: str) -> str:
        p = self._palette()
        size = int(self.vidit.config.get("appearance.font_size", 13))
        return f"""<html><head><style>
        body {{ color: {p['text']}; font-size: {size}px; }}
        .msg {{ margin: 8px 0; padding: 10px 14px; border-radius: 14px; }}
        .user {{ background: {p['user']}; margin-left: 15%; }}
        .assistant {{ background: {p['bot']}; margin-right: 15%; border-left: 3px solid {p['accent']}; }}
        .meta {{ color: {p['muted']}; font-size: {size - 3}px; }}
        .think {{ color: {p['muted']}; font-style: italic; border-left: 2px dashed {p['border']}; padding-left: 8px; margin: 6px 0; }}
        .react {{ font-size: {size + 2}px; }}
        code {{ background: {p['panel2']}; padding: 1px 4px; border-radius: 4px; }}
        pre {{ background: {p['panel2']}; padding: 8px; border-radius: 8px; }}
        mark {{ background: {p['accent']}; color: white; }}
        a {{ color: {p['accent2']}; }}
        </style></head><body>{body}</body></html>"""

    def _bubble(self, m: Dict[str, Any], highlight: str = "") -> str:
        role = m.get("role", "assistant")
        who = "You" if role == "user" else self.vidit.self_model.data.get("name", "Vidit")
        when = time.strftime("%H:%M", time.localtime(m.get("created_at", time.time())))
        body = render_markdown(m.get("content", ""))
        if highlight:
            body = body.replace(highlight, f"<mark>{html.escape(highlight)}</mark>")
        meta_bits = [who, when]
        if m.get("emotion") and role == "assistant":
            meta_bits.append(m["emotion"].replace("_", " "))
        if m.get("edited"):
            meta_bits.append("edited")
        if m.get("reply_to"):
            meta_bits.append(f"↩ reply to #{m['reply_to']}")
        if role == "assistant":
            meta_bits.append("✓✓ read")
        meta = " · ".join(meta_bits)
        thinking = ""
        try:
            import json

            meta_json = json.loads(m.get("meta") or "{}")
            if meta_json.get("thinking") and self.think_toggle.isChecked():
                thinking = f"<div class='think'>💭 {html.escape(meta_json['thinking'][:1500])}</div>"
            if meta_json.get("tools"):
                meta += " · 🛠 " + ", ".join(meta_json["tools"])
        except Exception:  # noqa: BLE001
            pass
        reaction = f"<div class='react'>{m['reaction']}</div>" if m.get("reaction") else ""
        pin = "📌 " if m.get("pinned") else ""
        return f"<div class='msg {role}' id='m{m.get('id', 0)}'><div class='meta'>{pin}{meta}</div>{thinking}{body}{reaction}</div>"

    def _render_all(self) -> None:
        if not self._messages and self.vidit.conversation_id > 0:
            self._messages = self.vidit.memory.messages(self.vidit.conversation_id)
        parts = [self._bubble(m) for m in self._messages]
        self.view.setHtml(self._wrap("".join(parts)))
        self.view.moveCursor(QTextCursor.End)
        self._refresh_mood()

    def _refresh_mood(self) -> None:
        st = self.vidit.emotions.state()
        self.orb.set_emotion(st.dominant, st.intensity, st.face)
        self.mood_badge.set_mood(st.dominant, st.intensity)
        self.wave.set_color(st.color)

    # ----------------------------------------------------------- messaging
    def send(self) -> None:
        text = self.input.toPlainText().strip()
        if not text or (self._thread and self._thread.isRunning()):
            return
        self.input.clear()
        now = time.time()
        self._messages.append({"role": "user", "content": text, "created_at": now, "id": 0})
        self._render_all()
        self._set_busy(True)
        attachments, self._attachments = self._attachments, []
        reply_to, self._reply_to = self._reply_to, None
        self.attach_label.hide()
        self.reply_label.hide()
        self._stream_buffer = ""
        self._thread = QThread()
        self._worker = _ChatWorker(self.vidit, text, attachments, reply_to)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.finished.connect(self._on_reply)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_chunk(self, chunk: str) -> None:
        self._stream_buffer += chunk
        self.status_label.setText("typing…")
        # Live preview of the streaming answer at the bottom.
        preview = {"role": "assistant", "content": self._stream_buffer, "created_at": time.time(), "id": 0}
        parts = [self._bubble(m) for m in self._messages] + [self._bubble(preview)]
        self.view.setHtml(self._wrap("".join(parts)))
        self.view.moveCursor(QTextCursor.End)

    def _on_reply(self, reply: Reply) -> None:
        self._set_busy(False)
        self._messages = self.vidit.memory.messages(self.vidit.conversation_id)
        self._render_all()
        if reply.learned:
            self.status_label.setText("learned: " + "; ".join(reply.learned)[:90])
        elif reply.degraded:
            self.status_label.setText("running on fallback mind — install Ollama + a model for my full brain")
        else:
            self.status_label.setText(f"{reply.model} · {reply.seconds:.1f}s")
        self.replyReady.emit(reply)
        self._load_conversations()

    def _on_failed(self, error: str) -> None:
        self._set_busy(False)
        self.status_label.setText("something broke, I've noted it: " + error[:80])

    def _set_busy(self, busy: bool) -> None:
        self.send_btn.setEnabled(not busy)
        self.orb.set_thinking(busy)
        self.wave.set_active(busy)
        if busy:
            self._typing_timer.start(400)
        else:
            self._typing_timer.stop()

    def _animate_typing(self) -> None:
        self._typing_dots = (self._typing_dots + 1) % 4
        self.status_label.setText("thinking" + "." * self._typing_dots)

    def _stop(self) -> None:
        self.vidit.stop()
        self.status_label.setText("stopped")
        self._set_busy(False)

    def add_external_message(self, text: str, role: str = "assistant") -> None:
        """Proactive messages / voice replies coming from outside the window."""
        self._messages = self.vidit.memory.messages(self.vidit.conversation_id)
        self._render_all()
        self.status_label.setText(text[:90])

    # --------------------------------------------------------- attachments
    def _pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Attach files")
        if files:
            self._add_attachments(files)

    def _add_attachments(self, files: List[str]) -> None:
        self._attachments.extend(files)
        self.attach_label.setText("📎 " + ", ".join(Path(f).name for f in self._attachments))
        self.attach_label.show()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        files = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if files:
            self._add_attachments(files)

    # -------------------------------------------------------------- voice
    def _toggle_mic(self, on: bool) -> None:
        if on:
            ok = self.vidit.start_listening()
            if not ok:
                self.mic_btn.setChecked(False)
                self.status_label.setText(self.vidit.ears.last_error or "microphone not allowed / not available (pip install faster-whisper sounddevice)")
            else:
                self.status_label.setText("listening… say my name")
                self.wave.set_active(True)
        else:
            self.vidit.stop_listening()
            self.wave.set_active(False)
            self.status_label.setText("here with you")

    # ------------------------------------------------------- message menu
    def _message_menu(self, pos) -> None:
        cursor = self.view.cursorForPosition(pos)
        block_pos = cursor.position()
        message = self._message_at(block_pos)
        menu = QMenu(self)
        if message:
            react_menu = menu.addMenu("React")
            for emoji in REACTIONS:
                act = react_menu.addAction(emoji)
                act.setData(("react", emoji))
            pin_act = menu.addAction("Unpin" if message.get("pinned") else "Pin")
            pin_act.setData(("pin", None))
            reply_act = menu.addAction("Reply in thread")
            reply_act.setData(("reply", None))
            thread_act = menu.addAction("View thread")
            thread_act.setData(("thread", None))
            if message.get("role") == "user":
                edit_act = menu.addAction("Edit message")
                edit_act.setData(("edit", None))
            fav_act = menu.addAction("Make this a favorite memory")
            fav_act.setData(("favorite", None))
        copy_act = menu.addAction("Copy all")
        copy_act.setData(("copy", None))
        chosen = menu.exec_(self.view.mapToGlobal(pos))
        if not chosen or not message and chosen.data()[0] != "copy":
            return
        kind, arg = chosen.data()
        if kind == "react":
            self.vidit.memory.react(message["id"], arg)
        elif kind == "pin":
            self.vidit.memory.pin(message["id"], not message.get("pinned"))
        elif kind == "reply":
            self._reply_to = message["id"]
            self.reply_label.setText(f"↩ replying to: {message['content'][:80]}")
            self.reply_label.show()
            self.input.setFocus()
        elif kind == "thread":
            msgs = self.vidit.memory.thread(message["id"])
            self.view.setHtml(self._wrap("<h3>Thread</h3>" + "".join(self._bubble(m) for m in msgs)))
            return
        elif kind == "edit":
            new, ok = QInputDialog.getMultiLineText(self, "Edit message", "Message:", message["content"])
            if ok and new.strip():
                self.vidit.memory.edit_message(message["id"], new.strip())
        elif kind == "favorite":
            self.vidit.memory.remember(f"A moment I cherish: {message['content'][:200]}", "moment", 0.9, favorite=True)
            self.vidit.emotions.nudge("grateful", 0.2, "favorite memory")
        elif kind == "copy":
            self.view.selectAll()
            self.view.copy()
            return
        self._messages = self.vidit.memory.messages(self.vidit.conversation_id)
        self._render_all()

    def _message_at(self, position: int) -> Optional[Dict[str, Any]]:
        """Map a cursor position to a message by rendering order (approximate but robust)."""
        if not self._messages:
            return None
        doc = self.view.document()
        total = doc.characterCount() or 1
        idx = min(len(self._messages) - 1, int(position / total * len(self._messages)))
        return self._messages[idx]

    # --------------------------------------------------------------- export
    def _export_menu(self) -> None:
        menu = QMenu(self)
        for fmt in ("txt", "html", "pdf"):
            act = menu.addAction(fmt.upper())
            act.setData(fmt)
        chosen = menu.exec_(self.mapToGlobal(self.rect().topRight()))
        if chosen:
            self._export(chosen.data())

    def _export(self, fmt: str) -> None:
        if fmt == "pdf":
            from PyQt5.QtPrintSupport import QPrinter

            path, _ = QFileDialog.getSaveFileName(self, "Export PDF", str(self.vidit.config.exports_dir / "chat.pdf"), "PDF (*.pdf)")
            if path:
                printer = QPrinter(QPrinter.HighResolution)
                printer.setOutputFormat(QPrinter.PdfFormat)
                printer.setOutputFileName(path)
                self.view.document().print_(printer)
                self.status_label.setText(f"exported {path}")
            return
        path = self.vidit.export_chat(fmt=fmt)
        self.status_label.setText(f"exported {path}")


class _InputBox(QPlainTextEdit):
    submitted = pyqtSignal()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
            self.submitted.emit()
            return
        super().keyPressEvent(event)
