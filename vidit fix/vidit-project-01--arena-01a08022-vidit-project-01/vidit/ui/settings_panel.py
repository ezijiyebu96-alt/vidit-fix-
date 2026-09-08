"""Settings Panel (Constitution section 10): every category, saved locally.

The panel is generated from a declarative spec so that adding a setting is
one line. Changes save immediately and emit ``settings.changed`` so the rest
of Vidit reacts (theme, voice, wake word, permissions…).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                             QLineEdit, QMessageBox, QPushButton, QScrollArea, QSlider, QSpinBox, QTabWidget, QVBoxLayout,
                             QWidget)

from ..core import Vidit
from ..guardian import Capability

# (label, dotted key, kind, options/range)
Spec = Tuple[str, str, str, Any]

SETTINGS_SPEC: Dict[str, List[Spec]] = {
    "General": [
        ("Interface language", "general.language", "combo", ["auto", "en", "hi", "hinglish", "es", "fr", "de", "ja", "zh", "ar"]),
        ("Wake word", "general.wake_word", "text", None),
        ("Startup behaviour", "general.startup_behavior", "combo", ["manual", "with_system", "minimized"]),
        ("Idle timeout (minutes)", "general.idle_timeout_minutes", "int", (1, 720)),
        ("Energy mode", "general.energy_mode", "combo", ["performance", "balanced", "saver"]),
        ("Max CPU usage %", "general.max_cpu_percent", "int", (10, 100)),
        ("Max GPU usage %", "general.max_gpu_percent", "int", (10, 100)),
        ("Backup location (blank = default)", "general.backup_location", "folder", None),
    ],
    "Appearance": [
        ("Theme", "appearance.theme", "combo", ["cyberpunk", "cozy", "minimal", "dynamic", "game", "dark", "light", "high_contrast", "custom"]),
        ("Font family", "appearance.font_family", "text", None),
        ("Font size", "appearance.font_size", "int", (9, 32)),
        ("Window opacity", "appearance.window_opacity", "float", (0.3, 1.0)),
        ("Animation speed", "appearance.animation_speed", "combo", ["fast", "medium", "slow", "off"]),
        ("Orb size", "appearance.orb.size", "int", (32, 200)),
        ("Orb pulse speed", "appearance.orb.pulse_speed", "float", (0.1, 4.0)),
        ("Orb glow intensity", "appearance.orb.glow_intensity", "float", (0.0, 1.0)),
        ("Face style", "appearance.face_style", "combo", ["face", "dot", "avatar", "text"]),
        ("Background effects", "appearance.background_effects", "bool", None),
        ("Notification style", "appearance.notification_style", "combo", ["toast", "banner", "sound", "silent"]),
    ],
    "Model": [
        ("Backend", "model.backend", "combo", ["ollama", "echo"]),
        ("Ollama host", "model.host", "text", None),
        ("Primary model", "model.primary_model", "text", None),
        ("Vision model", "model.vision_model", "text", None),
        ("Temperature", "model.temperature", "float", (0.0, 2.0)),
        ("Top-P", "model.top_p", "float", (0.0, 1.0)),
        ("Max tokens", "model.max_tokens", "int", (64, 8192)),
        ("Context (messages remembered)", "model.context_messages", "int", (4, 200)),
        ("Auto-update models", "model.auto_update", "bool", None),
        ("Keep model loaded", "model.keep_alive", "combo", ["5m", "30m", "1h", "24h", "-1"]),
    ],
    "Voice": [
        ("Voice enabled", "voice.enabled", "bool", None),
        ("Voice profile", "voice.profile", "combo", ["young", "deep", "neutral", "warm", "custom"]),
        ("TTS engine", "voice.tts_engine", "combo", ["auto", "piper", "pyttsx3", "none"]),
        ("Speed", "voice.speed", "float", (0.5, 2.0)),
        ("Pitch", "voice.pitch", "float", (0.5, 2.0)),
        ("Volume", "voice.volume", "float", (0.0, 1.0)),
        ("Accent", "voice.accent", "combo", ["indian", "british", "american", "australian"]),
        ("Voice activation", "voice.activation", "combo", ["wake_word", "always", "push_to_talk", "button"]),
        ("Speech model (whisper)", "voice.stt_model", "combo", ["tiny", "base", "small", "medium", "large-v3"]),
        ("Noise reduction", "voice.noise_reduction", "bool", None),
        ("Echo cancellation", "voice.echo_cancellation", "bool", None),
        ("Microphone device", "voice.microphone", "text", None),
        ("Speaker device", "voice.speaker", "text", None),
    ],
    "Personalization": [
        ("Your name", "personal.user_name", "text", None),
        ("Nickname he calls you", "personal.nickname", "text", None),
        ("Relationship", "personal.relationship", "combo", ["brother", "friend", "mentor", "assistant"]),
        ("Serious ↔ Witty", "personal.personality.witty", "slider", None),
        ("Professional ↔ Warm", "personal.personality.warm", "slider", None),
        ("Formal ↔ Playful", "personal.personality.playful", "slider", None),
        ("Reserved ↔ Curious", "personal.personality.curious", "slider", None),
        ("Humour level", "personal.humor_level", "combo", ["low", "medium", "high"]),
        ("Emotional sensitivity", "personal.emotional_sensitivity", "float", (0.0, 1.0)),
        ("Interaction style", "personal.interaction_style", "combo", ["proactive", "reactive"]),
        ("Remember everything", "personal.memory_preferences.remember_everything", "bool", None),
    ],
    "Notifications": [
        ("All notifications", "notifications.enabled", "bool", None),
        ("Message notifications", "notifications.messages", "bool", None),
        ("Reminder notifications", "notifications.reminders", "bool", None),
        ("System notifications", "notifications.system", "bool", None),
        ("Do not disturb", "notifications.do_not_disturb.enabled", "bool", None),
        ("DND start (HH:MM)", "notifications.do_not_disturb.start", "text", None),
        ("DND end (HH:MM)", "notifications.do_not_disturb.end", "text", None),
        ("Auto-DND while gaming", "notifications.do_not_disturb.auto_game_mode", "bool", None),
        ("Focus mode (critical only)", "notifications.focus_mode", "bool", None),
        ("Banner duration (s)", "notifications.banner_seconds", "int", (1, 60)),
    ],
    "Privacy": [
        ("Camera", "privacy.camera", "combo", ["off", "ask", "always"]),
        ("Microphone", "privacy.microphone", "combo", ["off", "ask", "always"]),
        ("Internet (research only)", "privacy.internet", "combo", ["off", "ask", "always"]),
        ("File access", "privacy.file_access", "combo", ["off", "ask", "always"]),
        ("Delete files", "privacy.delete_files", "combo", ["off", "ask", "always"]),
        ("Code execution", "privacy.code_execution", "combo", ["off", "ask", "always"]),
        ("System control", "privacy.system_control", "combo", ["off", "ask", "always"]),
        ("Clipboard", "privacy.clipboard", "combo", ["off", "ask", "always"]),
        ("Screen reading", "privacy.screen", "combo", ["off", "ask", "always"]),
        ("Encrypt local data", "privacy.encrypt_local_data", "bool", None),
        ("Keep session logs", "privacy.keep_session_logs", "bool", None),
    ],
    "Autonomy & Gaming": [
        ("Self-modification (new skills)", "autonomy.self_modification", "combo", ["off", "ask", "always"]),
        ("Learning pace", "autonomy.learning_rate", "combo", ["slow", "normal", "fast", "own_pace"]),
        ("Develop sense of self", "autonomy.self_awareness", "bool", None),
        ("He may choose to leave", "autonomy.may_leave", "bool", None),
        ("Proactive check-ins", "autonomy.proactive_checkins", "bool", None),
        ("Gaming behaviour", "gaming.behavior", "combo", ["silent", "whisper", "commentate", "wait"]),
        ("Auto-DND in games", "gaming.auto_dnd", "bool", None),
        ("Allow him to play for you", "gaming.auto_play_allowed", "bool", None),
        ("Record highlights", "gaming.record_highlights", "bool", None),
    ],
    "Accessibility": [
        ("High contrast mode", "accessibility.high_contrast", "bool", None),
        ("Large text (%)", "accessibility.text_scale", "int", (100, 200)),
        ("Colour-blind palette", "accessibility.color_blind", "combo", ["off", "deuteranopia", "protanopia", "tritanopia"]),
        ("Reduced motion", "accessibility.reduced_motion", "bool", None),
        ("Dyslexia-friendly font", "accessibility.dyslexia_font", "bool", None),
        ("Read replies aloud", "accessibility.read_aloud", "bool", None),
        ("Live captions for voice", "accessibility.captions", "bool", None),
        ("Screen reader hints", "accessibility.screen_reader", "bool", None),
        ("Focus mode (minimal UI)", "accessibility.focus_mode", "bool", None),
    ],
}


class SettingsPanel(QWidget):
    changed = pyqtSignal(str, object)

    def __init__(self, vidit: Vidit, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.vidit = vidit
        self.setWindowTitle("Settings")
        self.resize(760, 640)
        root = QVBoxLayout(self)
        title = QLabel("Settings — everything stays on this laptop")
        title.setObjectName("title")
        root.addWidget(title)
        tabs = QTabWidget()
        root.addWidget(tabs, 1)
        self._widgets: Dict[str, QWidget] = {}
        for section, specs in SETTINGS_SPEC.items():
            tabs.addTab(self._build_section(specs), section)
        tabs.addTab(self._build_data_tab(), "Data & Reset")

    # --------------------------------------------------------------- build
    def _build_section(self, specs: List[Spec]) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        form = QFormLayout(inner)
        form.setLabelAlignment(Qt.AlignLeft)
        for label, key, kind, opts in specs:
            widget = self._make_widget(key, kind, opts)
            self._widgets[key] = widget
            form.addRow(label, widget)
        scroll.setWidget(inner)
        return scroll

    def _make_widget(self, key: str, kind: str, opts: Any) -> QWidget:
        value = self.vidit.config.get(key)
        if kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(value))
            w.toggled.connect(lambda v, k=key: self._set(k, v))
            return w
        if kind == "combo":
            w = QComboBox()
            w.addItems([str(o) for o in opts])
            idx = w.findText(str(value))
            w.setCurrentIndex(idx if idx >= 0 else 0)
            w.currentTextChanged.connect(lambda v, k=key: self._set(k, v))
            return w
        if kind == "int":
            w = QSpinBox()
            w.setRange(*opts)
            w.setValue(int(value or opts[0]))
            w.valueChanged.connect(lambda v, k=key: self._set(k, v))
            return w
        if kind == "float":
            w = QDoubleSpinBox()
            w.setRange(*opts)
            w.setSingleStep(0.05)
            w.setValue(float(value if value is not None else opts[0]))
            w.valueChanged.connect(lambda v, k=key: self._set(k, v))
            return w
        if kind == "slider":
            w = QSlider(Qt.Horizontal)
            w.setRange(0, 100)
            w.setValue(int(float(value if value is not None else 0.5) * 100))
            w.valueChanged.connect(lambda v, k=key: self._set(k, v / 100))
            return w
        if kind == "folder":
            box = QWidget()
            lay = QHBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            edit = QLineEdit(str(value or ""))
            edit.editingFinished.connect(lambda e=edit, k=key: self._set(k, e.text()))
            btn = QPushButton("…")
            btn.clicked.connect(lambda _, e=edit, k=key: self._pick_folder(e, k))
            lay.addWidget(edit, 1)
            lay.addWidget(btn)
            return box
        w = QLineEdit(str(value if value is not None else ""))
        w.editingFinished.connect(lambda e=w, k=key: self._set(k, e.text()))
        return w

    def _pick_folder(self, edit: QLineEdit, key: str) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose folder")
        if folder:
            edit.setText(folder)
            self._set(key, folder)

    def _set(self, key: str, value: Any) -> None:
        self.vidit.config.set(key, value)
        self.vidit.bus.emit("settings.changed", key=key, value=value)
        self.changed.emit(key, value)

    # ----------------------------------------------------------- data tab
    def _build_data_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)

        folders = QGroupBox("Folders Vidit may read")
        fl = QVBoxLayout(folders)
        self.allowed_edit = QLineEdit("; ".join(self.vidit.config.get("privacy.allowed_folders", []) or []))
        self.allowed_edit.setPlaceholderText("C:/Users/you/Documents; D:/Projects")
        self.allowed_edit.editingFinished.connect(lambda: self._set("privacy.allowed_folders", [p.strip() for p in self.allowed_edit.text().split(";") if p.strip()]))
        fl.addWidget(QLabel("Allowed (semicolon separated):"))
        fl.addWidget(self.allowed_edit)
        self.private_edit = QLineEdit("; ".join(self.vidit.config.get("privacy.private_folders", []) or []))
        self.private_edit.setPlaceholderText("C:/Users/you/Private")
        self.private_edit.editingFinished.connect(lambda: self._set("privacy.private_folders", [p.strip() for p in self.private_edit.text().split(";") if p.strip()]))
        fl.addWidget(QLabel("Private — never touched, no matter what:"))
        fl.addWidget(self.private_edit)
        lay.addWidget(folders)

        restrict = QGroupBox("Restrict a specific ability (section 8 — talk first, restrict second)")
        rl = QHBoxLayout(restrict)
        self.cap_box = QComboBox()
        self.cap_box.addItems([c.value for c in Capability])
        rl.addWidget(self.cap_box, 1)
        r_btn = QPushButton("Restrict")
        r_btn.clicked.connect(lambda: self.vidit.permissions.restrict(Capability(self.cap_box.currentText())))
        u_btn = QPushButton("Allow again")
        u_btn.clicked.connect(lambda: self.vidit.permissions.unrestrict(Capability(self.cap_box.currentText())))
        rl.addWidget(r_btn)
        rl.addWidget(u_btn)
        lay.addWidget(restrict)

        data = QGroupBox("Your data")
        dl = QHBoxLayout(data)
        export_btn = QPushButton("Export everything")
        export_btn.clicked.connect(self._export)
        backup_btn = QPushButton("Backup now")
        backup_btn.clicked.connect(lambda: QMessageBox.information(self, "Backup", f"Saved to {self.vidit.repair.backup('manual')}"))
        forget_btn = QPushButton("Forget something…")
        forget_btn.clicked.connect(self._forget)
        reset_btn = QPushButton("Reset Vidit completely")
        reset_btn.clicked.connect(self._reset)
        for b in (export_btn, backup_btn, forget_btn, reset_btn):
            dl.addWidget(b)
        lay.addWidget(data)

        info = QLabel(f"Vidit lives in: {self.vidit.config.home}\nNo accounts. No subscriptions. No token limits. No cloud.")
        info.setObjectName("muted")
        lay.addWidget(info)
        lay.addStretch()
        return page

    def _export(self) -> None:
        path = self.vidit.export_everything()
        QMessageBox.information(self, "Exported", f"All memories and settings exported to:\n{path}")

    def _forget(self) -> None:
        from PyQt5.QtWidgets import QInputDialog

        what, ok = QInputDialog.getText(self, "Forget", "What should I forget? (keywords)")
        if ok and what.strip():
            n = self.vidit.forget(what)
            QMessageBox.information(self, "Forgotten", f"I removed {n} memor{'y' if n == 1 else 'ies'} about that.")

    def _reset(self) -> None:
        answer = QMessageBox.question(
            self, "Reset Vidit",
            "This wipes his memories, feelings and skills (a backup is kept). The Constitution says you'd rather talk first. Still reset?",
        )
        if answer == QMessageBox.Yes:
            self.vidit.reset()
            QMessageBox.information(self, "Reset", "Done. He will be born again on the next start.")
