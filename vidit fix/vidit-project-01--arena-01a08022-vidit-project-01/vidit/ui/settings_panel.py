"""Settings Panel (Constitution section 10) — cyber-glass redesign.

Layout follows the concept art: a left vertical nav with neon icons, a
General ("profile") page with the large avatar card, companion-mode chips,
gradient sliders, neon toggles and an avatar carousel, the classic
spec-driven pages for everything else, and a bottom status toast with a big
Save Changes button.

The General page is draft-until-Save; every other page still saves instantly
(unchanged behaviour). All data stays in config.py sections — no cloud.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                             QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
                             QSlider, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from ..core import Vidit
from ..guardian import Capability
from .widgets import (AvatarCircle, AvatarPicker, GlassCard, GradientSlider, ModeChip, NeonToggle, OnlinePill,
                      StatusToast, avatar_image)

# (label, dotted key, kind, options/range)
Spec = Tuple[str, str, str, Any]

SETTINGS_SPEC: Dict[str, List[Spec]] = {
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
        ("Speech model (whisper)", "voice.stt_model", "combo", ["auto", "tiny", "base", "small", "medium", "large-v3"]),
        ("Microphone device", "voice.microphone", "text", None),
        ("Noise reduction", "voice.noise_reduction", "bool", None),
        ("Echo cancellation", "voice.echo_cancellation", "bool", None),
        ("Speaker device", "voice.speaker", "text", None),
    ],
    "Personal": [
        ("Nickname he calls you", "personal.nickname", "text", None),
        ("Relationship", "personal.relationship", "combo", ["brother", "friend", "mentor", "assistant"]),
        ("Serious ↔ Witty", "personal.personality.witty", "slider", None),
        ("Professional ↔ Warm", "personal.personality.warm", "slider", None),
        ("Formal ↔ Playful", "personal.personality.playful", "slider", None),
        ("Reserved ↔ Curious", "personal.personality.curious", "slider", None),
        ("Humour level", "personal.humor_level", "combo", ["low", "medium", "high"]),
        ("Emotional sensitivity", "personal.emotional_sensitivity", "float", (0.0, 1.0)),
        ("Interaction style", "personal.interaction_style", "combo", ["proactive", "reactive"]),
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
        ("Run due goals on his own (Autonomy)", "autonomy.proactive", "bool", None),
        ("Autonomy level (standard = ask, auto = green actions)", "autonomy.level", "combo", ["standard", "auto"]),
        ("Computer control (mouse/keyboard, off by default)", "autonomy.computer_control", "bool", None),
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
    "System": [
        ("Wake word", "general.wake_word", "text", None),
        ("Startup behaviour", "general.startup_behavior", "combo", ["manual", "with_system", "minimized"]),
        ("Idle timeout (minutes)", "general.idle_timeout_minutes", "int", (1, 720)),
        ("Energy mode", "general.energy_mode", "combo", ["performance", "balanced", "saver"]),
        ("Max CPU usage %", "general.max_cpu_percent", "int", (10, 100)),
        ("Max GPU usage %", "general.max_gpu_percent", "int", (10, 100)),
        ("Backup location (blank = default)", "general.backup_location", "folder", None),
    ],
}

# Sidebar order: General (concept profile page) first, then everything else.
NAV_ITEMS: List[Tuple[str, str]] = [
    ("👤", "General"),          # concept profile page (avatar, mode, sliders…)
    ("🎨", "Appearance"),
    ("🧠", "Model"),
    ("🎙", "Voice"),
    ("💛", "Personal"),
    ("🔔", "Notifications"),
    ("🛡", "Privacy"),
    ("🎮", "Autonomy & Gaming"),
    ("♿", "Accessibility"),
    ("⚙", "System"),            # wake word, startup, resource caps, backups
    ("💾", "Data & Reset"),
]

# Companion-mode presets: chip -> (personality overlay, temperature, max_tokens, quote)
COMPANION_MODES: Dict[str, Dict[str, Any]] = {
    "chill": {"witty": 0.4, "playful": 0.35, "temperature": 0.55, "max_tokens": 768,
              "quote": "Take it easy — I'm right here whenever you need me."},
    "balanced": {"witty": 0.7, "playful": 0.6, "temperature": 0.8, "max_tokens": 1024,
                 "quote": "Always around, never in the way. That's the deal."},
    "energetic": {"witty": 0.9, "playful": 0.85, "temperature": 1.1, "max_tokens": 1536,
                  "quote": "Big day ahead. Let's build something together!"},
}

LANGUAGES = ["auto", "en", "hi", "hinglish", "es", "fr", "de", "ja", "zh", "ar"]
TIMEZONES = ["auto", "Asia/Kolkata", "Asia/Dubai", "Asia/Tokyo", "Europe/London", "Europe/Berlin",
             "America/New_York", "America/Los_Angeles", "Australia/Sydney", "UTC"]


class SettingsPanel(QWidget):
    changed = pyqtSignal(str, object)

    def __init__(self, vidit: Vidit, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.vidit = vidit
        self.setWindowTitle("Settings")
        self.resize(1080, 700)
        self.setMinimumSize(860, 560)
        self._widgets: Dict[str, QWidget] = {}
        # General-page draft state
        self._mode = str(vidit.config.get("personal.companion_mode", "balanced"))
        self._sliders_touched = False
        self._build()
        self._refresh_voice_status()

    # ================================================================ build
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # --- header: planet icon + ONLINE pill + tagline ---------------------
        head = QHBoxLayout()
        self.header_avatar = AvatarCircle(self._current_avatar(), size=30, selectable=False)
        head.addWidget(self.header_avatar)
        title = QLabel("Vidit")
        title.setObjectName("title")
        head.addWidget(title)
        head.addWidget(OnlinePill())
        tag = QLabel("your offline brother — tweak me until I feel like family")
        tag.setObjectName("tagline")
        head.addSpacing(8)
        head.addWidget(tag)
        head.addStretch()
        root.addLayout(head)

        # --- body: left nav + stacked pages ---------------------------------
        body = QHBoxLayout()
        body.setSpacing(12)

        nav_card = GlassCard()
        nav_lay = QVBoxLayout(nav_card)
        nav_lay.setContentsMargins(6, 12, 6, 12)
        self.nav_list = QListWidget()
        self.nav_list.setObjectName("navList")
        for icon, label in NAV_ITEMS:
            QListWidgetItem(f"  {icon}   {label}", self.nav_list)
        self.nav_list.setCurrentRow(0)
        nav_lay.addWidget(self.nav_list)
        body.addWidget(nav_card)

        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        root.addLayout(body, 1)

        # page order mirrors NAV_ITEMS
        self.pages.addWidget(self._build_general_page())
        self.pages.addWidget(self._build_section(SETTINGS_SPEC["Appearance"]))
        self.pages.addWidget(self._build_section(SETTINGS_SPEC["Model"]))
        self.pages.addWidget(self._build_voice_tab(SETTINGS_SPEC["Voice"]))
        self.pages.addWidget(self._build_section(SETTINGS_SPEC["Personal"]))
        self.pages.addWidget(self._build_section(SETTINGS_SPEC["Notifications"]))
        self.pages.addWidget(self._build_section(SETTINGS_SPEC["Privacy"]))
        self.pages.addWidget(self._build_section(SETTINGS_SPEC["Autonomy & Gaming"]))
        self.pages.addWidget(self._build_section(SETTINGS_SPEC["Accessibility"]))
        self.pages.addWidget(self._build_section(SETTINGS_SPEC["System"]))
        self.pages.addWidget(self._build_data_tab())
        self.nav_list.currentRowChanged.connect(self.pages.setCurrentIndex)

        # --- bottom: status toast + Save Changes ----------------------------
        bottom = QHBoxLayout()
        self.status_toast = StatusToast()
        bottom.addWidget(self.status_toast, 1)
        self.save_btn = QPushButton("Save Changes")
        self.save_btn.setObjectName("primary")
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.clicked.connect(self._save_general)
        bottom.addWidget(self.save_btn)
        root.addLayout(bottom)

    # ======================================================= General (profile)
    def _build_general_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(12)

        # --- left: big avatar card ------------------------------------------
        avatar_card = GlassCard(glow=True)
        av = QVBoxLayout(avatar_card)
        av.setContentsMargins(18, 18, 18, 18)
        av.setAlignment(Qt.AlignHCenter)
        self.avatar_big = AvatarCircle(self._current_avatar(), size=168, selectable=False)
        av.addWidget(self.avatar_big, 0, Qt.AlignHCenter)
        pill_row = QHBoxLayout()
        pill_row.addStretch()
        self.avatar_pill = OnlinePill("● " + COMPANION_MODES[self._mode]["quote"][:0] + "ONLINE")
        pill_row.addWidget(self.avatar_pill)
        pill_row.addStretch()
        av.addLayout(pill_row)
        self.quote_label = QLabel("“" + COMPANION_MODES[self._mode]["quote"] + "”")
        self.quote_label.setObjectName("quote")
        self.quote_label.setWordWrap(True)
        self.quote_label.setAlignment(Qt.AlignCenter)
        self.quote_label.setMaximumWidth(220)
        av.addWidget(self.quote_label)
        av.addStretch()
        lay.addWidget(avatar_card)

        # --- right: the concept controls -------------------------------------
        col = QVBoxLayout()
        col.setSpacing(12)

        # identity
        id_card = GlassCard()
        form = QFormLayout(id_card)
        form.setLabelAlignment(Qt.AlignLeft)
        self.name_edit = QLineEdit(str(self.vidit.config.get("personal.user_name") or ""))
        self.name_edit.setPlaceholderText("What should I call you?")
        form.addRow("Display name", self.name_edit)
        self.language_combo = QComboBox()
        self.language_combo.addItems(LANGUAGES)
        self._pick_combo(self.language_combo, str(self.vidit.config.get("general.language", "auto")))
        form.addRow("Language", self.language_combo)
        self.tz_combo = QComboBox()
        self.tz_combo.setEditable(True)
        self.tz_combo.addItems(TIMEZONES)
        self._pick_combo(self.tz_combo, str(self.vidit.config.get("general.timezone", "auto")))
        form.addRow("Time zone", self.tz_combo)
        col.addWidget(id_card)

        # companion mode chips
        mode_card = GlassCard()
        mv = QVBoxLayout(mode_card)
        mv.addWidget(QLabel("Companion Mode"))
        chips = QHBoxLayout()
        self.mode_chips: Dict[str, ModeChip] = {}
        for mode, label in (("chill", "Chill"), ("balanced", "Balanced (recommended)"), ("energetic", "Energetic")):
            chip = ModeChip(label)
            chip.setChecked(mode == self._mode)
            chip.clicked.connect(lambda _, m=mode: self._set_mode(m))
            chips.addWidget(chip)
            self.mode_chips[mode] = chip
        chips.addStretch()
        mv.addLayout(chips)
        hint = QLabel("Chill = calmer tone, shorter answers · Balanced = the sweet spot · "
                      "Energetic = bolder, longer, more playful (applies on Save)")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        mv.addWidget(hint)
        col.addWidget(mode_card)

        # sliders
        len_card = GlassCard()
        lv = QVBoxLayout(len_card)
        len_head = QHBoxLayout()
        len_head.addWidget(QLabel("Response Length"))
        len_head.addStretch()
        self.len_value = QLabel(self._len_label())
        self.len_value.setObjectName("muted")
        len_head.addWidget(self.len_value)
        lv.addLayout(len_head)
        self.len_slider = GradientSlider(256, 4096, int(self.vidit.config.get("model.max_tokens", 1024)))
        self.len_slider.valueChanged.connect(lambda v: (setattr(self, "_sliders_touched", True),
                                                        self.len_value.setText(self._len_label())))
        lv.addWidget(self.len_slider)
        col.addWidget(len_card)

        cre_card = GlassCard()
        cv = QVBoxLayout(cre_card)
        cre_head = QHBoxLayout()
        cre_head.addWidget(QLabel("Creativity Level"))
        cre_head.addStretch()
        self.cre_value = QLabel(self._cre_label())
        self.cre_value.setObjectName("muted")
        cre_head.addWidget(self.cre_value)
        cv.addLayout(cre_head)
        self.cre_slider = GradientSlider(0, 200, int(float(self.vidit.config.get("model.temperature", 0.8)) * 100))
        self.cre_slider.valueChanged.connect(lambda v: (setattr(self, "_sliders_touched", True),
                                                        self.cre_value.setText(self._cre_label())))
        cv.addWidget(self.cre_slider)
        col.addWidget(cre_card)

        # toggles
        tog_card = GlassCard()
        tv = QVBoxLayout(tog_card)
        tv.addWidget(QLabel("Behaviour"))
        self.memory_toggle = NeonToggle(bool(self.vidit.config.get("personal.memory_preferences.remember_everything", True)))
        tv.addLayout(self._toggle_row("🧠", "Memory", "remember what matters between our chats", self.memory_toggle))
        self.proactive_toggle = NeonToggle(bool(self.vidit.config.get("autonomy.proactive_checkins", True)))
        tv.addLayout(self._toggle_row("🔔", "Proactive Suggestions", "he may check in when it makes sense", self.proactive_toggle))
        self.autocont_toggle = NeonToggle(bool(self.vidit.config.get("general.auto_continue", True)))
        tv.addLayout(self._toggle_row("⏩", "Auto-Continue", "keep going after tool results without pausing", self.autocont_toggle))
        col.addWidget(tog_card)

        # avatar carousel
        av_card = GlassCard()
        avv = QVBoxLayout(av_card)
        avv.addWidget(QLabel("Avatar style"))
        self.avatar_picker = AvatarPicker(self._current_avatar(), size=76)
        self.avatar_picker.changed.connect(self._preview_avatar)
        avv.addWidget(self.avatar_picker)
        col.addWidget(av_card)

        col.addStretch()
        lay.addLayout(col, 1)
        scroll.setWidget(page)
        return scroll

    @staticmethod
    def _toggle_row(icon: str, title: str, hint: str, toggle: NeonToggle) -> QHBoxLayout:
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(QLabel(f"{icon}  {title}"))
        h = QLabel(hint)
        h.setObjectName("hint")
        col.addWidget(h)
        row.addLayout(col, 1)
        row.addWidget(toggle)
        return row

    def _current_avatar(self) -> str:
        return str(self.vidit.config.get("appearance.avatar_style", "nebula") or "nebula")

    @staticmethod
    def _pick_combo(combo: QComboBox, value: str) -> None:
        idx = combo.findText(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        else:
            combo.setEditText(value)

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        # Picking a mode arms its preset (temperature / length); touching a
        # slider afterwards means the user's fine-tuning wins on Save.
        self._sliders_touched = False
        for m, chip in self.mode_chips.items():
            chip.setChecked(m == mode)
        self.quote_label.setText("“" + COMPANION_MODES[mode]["quote"] + "”")
        self.status_toast.show_message(f"Companion mode: {mode} — press Save Changes to apply", "ok", 3)

    def _len_label(self) -> str:
        v = self.len_slider.value() if hasattr(self, "len_slider") else int(self.vidit.config.get("model.max_tokens", 1024))
        word = "Short" if v <= 640 else "Detailed" if v >= 2560 else "Balanced"
        return f"{word} · ~{v} tokens"

    def _cre_label(self) -> str:
        v = self.cre_slider.value() if hasattr(self, "cre_slider") else int(float(self.vidit.config.get("model.temperature", 0.8)) * 100)
        word = "Precise" if v <= 40 else "Wild" if v >= 150 else "Balanced"
        return f"{word} · {v / 100:.2f}"

    def _preview_avatar(self, style_id: str) -> None:
        self.avatar_big.style_id = style_id
        self.avatar_big.update()
        self.header_avatar.style_id = style_id
        self.header_avatar.update()
        self.status_toast.show_message(f"Avatar: {style_id} — press Save Changes to apply", "ok", 3)

    def _save_general(self) -> None:
        cfg = self.vidit.config
        # A freshly picked mode applies its preset (temperature / length);
        # once the user touches a slider their fine-tuning wins instead.
        if not self._sliders_touched:
            preset = COMPANION_MODES[self._mode]
            self.len_slider.setValue(int(preset["max_tokens"]))
            self.cre_slider.setValue(int(preset["temperature"] * 100))
        cfg.set("personal.companion_mode", self._mode)
        cfg.set("model.max_tokens", self.len_slider.value(), save=False)
        cfg.set("model.temperature", self.cre_slider.value() / 100.0, save=False)
        cfg.set("personal.memory_preferences.remember_everything", self.memory_toggle.isChecked(), save=False)
        cfg.set("autonomy.proactive_checkins", self.proactive_toggle.isChecked(), save=False)
        cfg.set("general.auto_continue", self.autocont_toggle.isChecked(), save=False)
        cfg.set("appearance.avatar_style", self.avatar_picker.selected(), save=False)
        cfg.set("general.language", self.language_combo.currentText(), save=False)
        cfg.set("general.timezone", self.tz_combo.currentText(), save=False)
        name = self.name_edit.text().strip()
        cfg.set("personal.user_name", name.title() if name else "", save=False)
        cfg.save()
        # let the app react (theme, voice, …) through the usual channel
        for key in ("personal.companion_mode", "model.max_tokens", "model.temperature",
                    "personal.memory_preferences.remember_everything", "autonomy.proactive_checkins",
                    "general.auto_continue", "appearance.avatar_style", "general.language",
                    "general.timezone", "personal.user_name"):
            self.vidit.bus.emit("settings.changed", key=key, value=cfg.get(key))
            self.changed.emit(key, cfg.get(key))
        self.status_toast.show_message("Settings saved. Vidit is now even more you.", "ok", 5)

    # ======================================================= spec-driven pages
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
        if key.startswith("voice."):
            self._refresh_voice_status()

    # ------------------------------------------------------------ voice tab
    @staticmethod
    def _mic_devices() -> Optional[List[str]]:
        """Real input device names (offline, from PortAudio) — None if the
        sounddevice package is missing."""
        try:
            import sounddevice as sd  # type: ignore

            return ["default"] + [d["name"] for d in sd.query_devices()
                                  if d.get("max_input_channels", 0) > 0]
        except Exception:  # noqa: BLE001
            return None

    def _build_voice_tab(self, specs: List[Spec]) -> QWidget:
        """The Voice tab, grouped by sense: hearing (STT) / speaking (TTS) /
        audio processing, plus a live status line."""
        by_key = {key: (label, kind, opts) for label, key, kind, opts in specs}

        def group(title: str, keys: List[str], after: Optional[callable] = None) -> GlassCard:
            box = GlassCard(soft=True)
            form = QFormLayout(box)
            for key in keys:
                label, kind, opts = by_key[key]
                if key == "voice.microphone":
                    w = self._mic_widget(kind, opts)
                else:
                    w = self._make_widget(key, kind, opts)
                self._widgets[key] = w
                form.addRow(label, w)
            if after is not None:
                after(form)
            return box

        def stt_hint(form: "QFormLayout") -> None:
            hint = QLabel("The model downloads once, fully offline, into <home>/models/whisper "
                          "and is preloaded on the main thread when listening starts "
                          "(required on Windows — never built on a worker thread).")
            hint.setObjectName("hint")
            hint.setWordWrap(True)
            form.addRow(hint)

        stt = group("Hearing you — offline speech-to-text",
                    ["voice.activation", "voice.stt_model", "voice.microphone"], stt_hint)
        tts = group("Speaking — offline text-to-speech",
                    ["voice.enabled", "voice.tts_engine", "voice.profile", "voice.accent",
                     "voice.speed", "voice.pitch", "voice.volume"])
        audio = group("Audio devices && processing",
                      ["voice.noise_reduction", "voice.echo_cancellation", "voice.speaker"])

        status_box = GlassCard()
        sv = QVBoxLayout(status_box)
        self.voice_status = QLabel("")
        self.voice_status.setObjectName("muted")
        self.voice_status.setWordWrap(True)
        sv.addWidget(self.voice_status)
        row = QHBoxLayout()
        test_btn = QPushButton("Test voice")
        test_btn.setToolTip("Say a short line through the current offline voice")
        test_btn.clicked.connect(lambda: self.vidit.voice.say("Testing, testing… can you hear me?"))
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_voice_status)
        row.addWidget(test_btn)
        row.addWidget(refresh_btn)
        row.addStretch()
        sv.addLayout(row)

        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(stt)
        lay.addWidget(tts)
        lay.addWidget(audio)
        lay.addWidget(status_box)
        lay.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        return scroll

    def _mic_widget(self, kind: str, opts: Any) -> QWidget:
        devices = self._mic_devices()
        if devices:
            w = QComboBox()
            w.setEditable(True)
            w.addItems(devices)
            w.setToolTip("Pick the microphone Vidit listens through")
        else:
            w = QLineEdit()
            w.setToolTip("Microphone device name (install sounddevice to get a list)")
        current = self.vidit.config.get("voice.microphone", "default")
        if isinstance(w, QComboBox):
            idx = w.findText(str(current or "default"))
            w.setCurrentIndex(idx if idx >= 0 else 0)
            w.currentTextChanged.connect(lambda v, k="voice.microphone": self._set(k, v))
        else:
            w.setText(str(current or "default"))
            w.editingFinished.connect(lambda e=w, k="voice.microphone": self._set(k, e.text()))
        return w

    def _refresh_voice_status(self) -> None:
        if not hasattr(self, "voice_status"):
            return
        e = self.vidit.ears.status()
        v = self.vidit.voice.status()
        if not e["available"]:
            text = "ears: NOT installed — pip install faster-whisper sounddevice numpy"
        else:
            text = (f"ears: available · whisper model {'ready' if e['model_ready'] else 'not loaded yet'} · "
                    f"{'listening' if e['listening'] else 'idle'} · voice engine: {v['engine']}")
        if e["error"]:
            text += f"\n⚠ last error: {e['error']}"
        self.voice_status.setText(text)

    # ----------------------------------------------------------- data tab
    def _build_data_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        lay = QVBoxLayout(page)

        folders = GlassCard(soft=True)
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

        restrict = GlassCard(soft=True)
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

        data = GlassCard(soft=True)
        dl = QHBoxLayout(data)
        export_btn = QPushButton("Export everything")
        export_btn.clicked.connect(self._export)
        backup_btn = QPushButton("Backup now")
        backup_btn.clicked.connect(lambda: QMessageBox.information(self, "Backup", f"Saved to {self.vidit.repair.backup('manual')}"))
        forget_btn = QPushButton("Forget something…")
        forget_btn.clicked.connect(self._forget)
        reset_btn = QPushButton("Reset Vidit completely")
        reset_btn.setObjectName("danger")
        reset_btn.clicked.connect(self._reset)
        for b in (export_btn, backup_btn, forget_btn, reset_btn):
            dl.addWidget(b)
        lay.addWidget(data)

        info = QLabel(f"Vidit lives in: {self.vidit.config.home}\nNo accounts. No subscriptions. No token limits. No cloud.")
        info.setObjectName("muted")
        lay.addWidget(info)
        lay.addStretch()

        scroll.setWidget(page)
        return scroll

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

