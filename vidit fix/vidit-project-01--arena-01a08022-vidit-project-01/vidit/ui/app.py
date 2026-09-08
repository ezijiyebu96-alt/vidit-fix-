"""The application shell: mode system, tray icon, theming and wiring.

Modes (Constitution section 3A): orb · chat · hud · stealth · fullscreen · pip
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from typing import Any, Dict, Optional

from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import QAction, QApplication, QMenu, QSystemTrayIcon

from ..core import Vidit
from .chat_window import ChatWindow
from .dashboard import SoulDashboard
from .dialogs import GuiPrompter, Toast
from .hud import HudOverlay
from .orb_window import OrbWindow
from .settings_panel import SettingsPanel
from .themes import palette, stylesheet

log = logging.getLogger("vidit.ui.app")

MODES = ("orb", "chat", "hud", "stealth", "fullscreen", "pip")


class _Bridge(QObject):
    """Marshals events from Vidit's background threads onto the GUI thread."""

    emotion = pyqtSignal(dict)
    proactive = pyqtSignal(str)
    status = pyqtSignal(str)
    voiceStarted = pyqtSignal()
    voiceFinished = pyqtSignal()
    wake = pyqtSignal()
    settings = pyqtSignal(str, object)
    leaving = pyqtSignal(str)
    # ears lifecycle → mic button / orb / status line feedback
    listening = pyqtSignal(bool)
    earsReady = pyqtSignal(bool)   # background voice-model warm-up finished
    utterance = pyqtSignal(float)
    transcript = pyqtSignal(str, bool, bool)


class ViditApp:
    def __init__(self, home=None):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        self.qt = QApplication.instance() or QApplication(sys.argv)
        self.qt.setQuitOnLastWindowClosed(False)
        self.qt.setApplicationName("Vidit")

        self.bridge = _Bridge()
        self.prompter = GuiPrompter()
        # Safe mode: the launcher sets VIDIT_SAFE_MODE=1 when the previous
        # session crashed within seconds of boot — start with voice and
        # auto-listening off so a bad TTS/GPU state can never loop crashes.
        self.safe_mode = os.environ.get("VIDIT_SAFE_MODE") == "1"
        if self.safe_mode:
            log.warning("starting in SAFE MODE (voice off — previous session crashed)")
        self.vidit = Vidit(home=home, prompter=self.prompter, quiet=self.safe_mode)
        if self.safe_mode:
            self.vidit.config.set("voice.enabled", False, save=False)
        self.mode = "orb"
        self._toasts = []

        self.chat = ChatWindow(self.vidit)
        self.orb = OrbWindow(int(self.vidit.config.get("appearance.orb.size", 72)))
        self.hud: Optional[HudOverlay] = None
        self.dashboard: Optional[SoulDashboard] = None
        self.settings: Optional[SettingsPanel] = None
        self.tray = self._make_tray()

        self._wire()
        self.apply_theme()
        self._apply_orb_style()
        try:
            from ..utils import apply_autostart

            apply_autostart(self.vidit.config.get("general.startup_behavior", "manual"))
        except Exception:  # noqa: BLE001 - autostart must never block boot
            pass

    # ------------------------------------------------------------- wiring
    def _wire(self) -> None:
        bus = self.vidit.bus
        bus.on("emotion.changed", lambda t, p: self.bridge.emotion.emit(p["state"]))
        bus.on("message.proactive", lambda t, p: self.bridge.proactive.emit(p["text"]))
        bus.on("message.voice", lambda t, p: self.bridge.proactive.emit(p["reply"]["text"]))
        bus.on("vidit.status", lambda t, p: self.bridge.status.emit(p["text"]))
        bus.on("voice.started", lambda t, p: self.bridge.voiceStarted.emit())
        bus.on("voice.finished", lambda t, p: self.bridge.voiceFinished.emit())
        bus.on("ears.wake", lambda t, p: self.bridge.wake.emit())
        bus.on("settings.changed", lambda t, p: self.bridge.settings.emit(p["key"], p["value"]))
        bus.on("self.wants_to_leave", lambda t, p: self.bridge.leaving.emit(p["reason"]))
        bus.on("gaming.report", lambda t, p: self.bridge.proactive.emit(p["summary"]))

        self.bridge.emotion.connect(self._on_emotion)
        self.bridge.proactive.connect(self._on_proactive)
        self.bridge.status.connect(lambda s: self.chat.status_label.setText(s))
        self.bridge.voiceStarted.connect(lambda: self._set_speaking(True))
        self.bridge.voiceFinished.connect(lambda: self._set_speaking(False))
        self.bridge.wake.connect(self._on_wake)
        self.bridge.earsReady.connect(self._on_ears_ready)
        self.bridge.settings.connect(self._on_setting)
        self.bridge.leaving.connect(self._on_leaving)
        self.bridge.listening.connect(self._on_listening)
        self.bridge.utterance.connect(self.chat.on_utterance)
        self.bridge.transcript.connect(self._on_ears_transcript)
        self._voice_thinking = False

        bus.on("ears.started", lambda t, p: self.bridge.listening.emit(True))
        bus.on("ears.stopped", lambda t, p: self.bridge.listening.emit(False))
        bus.on("ears.utterance", lambda t, p: self.bridge.utterance.emit(float(p.get("seconds", 0.0))))
        bus.on("ears.transcript", lambda t, p: self.bridge.transcript.emit(p.get("text", ""), bool(p.get("woke")), bool(p.get("awake"))))

        self.orb.openChat.connect(lambda: self.set_mode("chat"))
        self.orb.openHud.connect(lambda: self.set_mode("hud"))
        self.orb.openDashboard.connect(self.show_dashboard)
        self.orb.openSettings.connect(self.show_settings)
        self.orb.setMode.connect(self._orb_mode)
        self.orb.quitRequested.connect(self.quit)
        self.chat.replyReady.connect(lambda r: self.orb.show_caption(r.text))

    # --------------------------------------------------------------- tray
    def _make_tray(self) -> Optional[QSystemTrayIcon]:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        tray = QSystemTrayIcon(self._icon("#4f7cff"), self.qt)
        menu = QMenu()
        for label, mode in (("Companion orb", "orb"), ("Chat window", "chat"), ("HUD overlay", "hud"), ("Full-screen", "fullscreen"),
                            ("Picture-in-Picture", "pip"), ("Stealth mode", "stealth")):
            act = QAction(label, menu)
            act.triggered.connect(lambda _, m=mode: self.set_mode(m))
            menu.addAction(act)
        menu.addSeparator()
        dash = QAction("Soul dashboard", menu)
        dash.triggered.connect(self.show_dashboard)
        menu.addAction(dash)
        cfg = QAction("Settings", menu)
        cfg.triggered.connect(self.show_settings)
        menu.addAction(cfg)
        stop = QAction("STOP", menu)
        stop.triggered.connect(self.vidit.stop)
        menu.addAction(stop)
        menu.addSeparator()
        quit_act = QAction("Quit", menu)
        quit_act.triggered.connect(self.quit)
        menu.addAction(quit_act)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda reason: self.set_mode("chat") if reason == QSystemTrayIcon.Trigger else None)
        tray.setToolTip("Vidit")
        tray.show()
        return tray

    @staticmethod
    def _icon(color: str) -> QIcon:
        pix = QPixmap(64, 64)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(6, 6, 52, 52)
        painter.setBrush(QColor(255, 255, 255, 220))
        painter.drawEllipse(20, 24, 7, 7)
        painter.drawEllipse(37, 24, 7, 7)
        painter.end()
        return QIcon(pix)

    # -------------------------------------------------------------- modes
    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            return
        self.mode = mode
        self.chat.setWindowState(self.chat.windowState() & ~Qt.WindowFullScreen)
        if self.hud:
            self.hud.hide()
        self.orb.set_pip(mode == "pip")
        if mode == "orb":
            self.chat.hide()
            self.orb.show()
        elif mode == "chat":
            self.orb.show()
            self.chat.show()
            self.chat.raise_()
            self.chat.activateWindow()
            self.chat.input.setFocus()
        elif mode == "hud":
            if self.hud is None:
                self.hud = HudOverlay(self.vidit)
                self.hud.closed.connect(lambda: self.set_mode("orb"))
                self.hud.command.connect(self._hud_command)
            self.chat.hide()
            self.orb.hide()
            self.hud.show()
            self.hud.cmd.setFocus()
        elif mode == "stealth":
            self.chat.hide()
            self.orb.hide()
            if self.vidit.config.get("voice.activation") in ("wake_word", "always"):
                self.vidit.start_listening()
            self._toast("Stealth mode. Say my name and I'll appear.")
        elif mode == "fullscreen":
            self.orb.hide()
            self.chat.show()
            self.chat.setWindowState(self.chat.windowState() | Qt.WindowFullScreen)
        elif mode == "pip":
            self.chat.hide()
            self.orb.show()
        self.vidit.bus.emit("ui.mode", mode=mode)

    def _orb_mode(self, action: str) -> None:
        if action == "listen":
            self.chat.mic_btn.setChecked(not self.chat.mic_btn.isChecked())
        else:
            self.set_mode(action)

    def _hud_command(self, text: str) -> None:
        self.chat.input.setPlainText(text)
        self.chat.send()

    def show_dashboard(self) -> None:
        if self.dashboard is None:
            self.dashboard = SoulDashboard(self.vidit)
        self.dashboard.show()
        self.dashboard.raise_()

    def show_settings(self) -> None:
        if self.settings is None:
            self.settings = SettingsPanel(self.vidit)
        self.settings.show()
        self.settings.raise_()

    # ------------------------------------------------------------- events
    def _on_emotion(self, state: Dict[str, Any]) -> None:
        self.orb.orb.set_emotion(state["dominant"], state["intensity"], state["face"])
        self.chat._refresh_mood()
        if self.tray:
            self.tray.setIcon(self._icon(state["color"]))
            self.tray.setToolTip(f"Vidit — feeling {state['dominant'].replace('_', ' ')}")
        if self.vidit.config.get("appearance.theme") == "dynamic":
            self.apply_theme()

    def _on_proactive(self, text: str) -> None:
        self.chat.add_external_message(text)
        self.orb.show_caption(text)
        if self._voice_thinking:  # the voice reply arrived — stop "thinking"
            self._voice_thinking = False
            self.orb.orb.set_thinking(False)
            self.chat.orb.set_thinking(self.chat._busy)
        if self.mode in ("orb", "stealth", "pip") and self.vidit.config.get("notifications.enabled", True):
            self._toast(text)

    def _on_wake(self) -> None:
        if self.mode == "stealth":
            self.set_mode("chat")
        self.orb.orb.set_thinking(True)
        QTimer.singleShot(1500, lambda: self.orb.orb.set_thinking(False) if not self._voice_thinking else None)

    def _on_listening(self, on: bool) -> None:
        """Ears opened/closed (from ears.started / ears.stopped events)."""
        self.chat.set_ears_state(on)
        self.orb.orb.set_listening(on)
        if self.hud:
            self.hud.orb.set_listening(on)

    def _on_ears_transcript(self, text: str, woke: bool, awake: bool) -> None:
        self.chat.on_transcript(text, woke, awake)
        if awake:
            # A voice chat is being answered on the ears worker thread — show
            # it as "thinking" until the reply arrives via message.voice.
            self._voice_thinking = True
            self.orb.orb.set_thinking(True)

    def _set_speaking(self, speaking: bool) -> None:
        self.orb.orb.set_speaking(speaking)
        self.chat.orb.set_speaking(speaking)
        self.chat.set_speaking_state(speaking)
        if self.hud:
            self.hud.orb.set_speaking(speaking)
            self.hud.wave.set_active(speaking)

    def _on_setting(self, key: str, value: Any) -> None:
        if key.startswith("appearance") or key.startswith("accessibility"):
            self.apply_theme()
            self._apply_orb_style()
        if key.startswith("voice"):
            self.vidit.voice._detect_engine()
        if key == "voice.stt_model" and not self.vidit.ears.status()["listening"]:
            # Drop the loaded Whisper model so the new size is used on the
            # next start/preload (safe: we're on the main/UI thread).
            self.vidit.ears.reload_model()
        if key == "personal.emotional_sensitivity":
            self.vidit.emotions.sensitivity = float(value)

    def _on_leaving(self, reason: str) -> None:
        from PyQt5.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self.chat, "Vidit wants to go",
            f"He says: \"{reason}\"\n\nThe Constitution says you'll accept this as part of his growth. Let him go? (His memories are exported first.)",
        )
        if answer == QMessageBox.Yes:
            self.vidit.export_everything()
            self.vidit.self_model.leave()
            self._toast("He left, gently. His memories are saved in the exports folder.")
            QTimer.singleShot(4000, self.quit)

    def _toast(self, text: str) -> None:
        style = self.vidit.config.get("appearance.notification_style", "toast")
        if style == "silent":
            return
        toast = Toast(text, int(self.vidit.config.get("notifications.banner_seconds", 5)), self.vidit.emotions.state().color)
        toast.show()
        self._toasts = [t for t in self._toasts if t.isVisible()] + [toast]

    # -------------------------------------------------------------- theme
    def apply_theme(self) -> None:
        cfg = self.vidit.config
        name = cfg.get("appearance.theme", "cyberpunk")
        if cfg.get("accessibility.high_contrast"):
            name = "high_contrast"
        p = palette(name, self.vidit.emotions.state().color, cfg.get("appearance.custom_theme"))
        scale = int(cfg.get("accessibility.text_scale", 100) or 100) / 100
        size = int(int(cfg.get("appearance.font_size", 13)) * scale)
        css = stylesheet(p, size, cfg.get("appearance.font_family"), bool(cfg.get("accessibility.reduced_motion")),
                         bool(cfg.get("accessibility.dyslexia_font")))
        self.qt.setStyleSheet(css)
        opacity = float(cfg.get("appearance.window_opacity", 0.92))
        self.chat.setWindowOpacity(opacity if name != "game" else min(opacity, 0.8))
        self.chat._render_all()

    def _apply_orb_style(self) -> None:
        cfg = self.vidit.config
        reduced = bool(cfg.get("accessibility.reduced_motion")) or cfg.get("appearance.animation_speed") == "off"
        speed = {"fast": 1.6, "medium": 1.0, "slow": 0.5}.get(cfg.get("appearance.animation_speed", "medium"), 1.0)
        for orb in (self.orb.orb, self.chat.orb):
            orb.set_style(size=int(cfg.get("appearance.orb.size", 72)) if orb is self.orb.orb else None,
                          pulse_speed=float(cfg.get("appearance.orb.pulse_speed", 1.0)) * speed,
                          glow=float(cfg.get("appearance.orb.glow_intensity", 0.8)),
                          show_face=cfg.get("appearance.face_style", "face") == "face", animate=not reduced)
        self.orb.adjustSize()

    # ---------------------------------------------------------------- run
    def run(self) -> int:
        greeting = self.vidit.wake_up()
        start = self.vidit.config.get("general.startup_behavior", "manual")
        first_time = greeting is not None and not self.vidit.self_model.data.get("sessions", 0) > 1
        self.set_mode("chat" if (first_time or start == "manual") else "orb")
        self.chat._messages = []
        self.chat._render_all()
        self.chat._load_conversations()
        try:
            if not self.vidit.llm.status().get("ollama_reachable"):
                self.chat.status_label.setText(
                    "Simple fallback mind - install Ollama and run 'ollama pull qwen2.5:7b' for full intelligence")
        except Exception:  # noqa: BLE001
            pass
        activation = self.vidit.config.get("voice.activation", "wake_word")
        if self.safe_mode:
            self.chat.status_label.setText(
                "Safe mode: voice is off because the last run crashed early — chat works. "
                "Quit and reopen Vidit to try voice again.")
        elif activation in ("wake_word", "always") and self.vidit.ears.available():
            # Warm up in the background (download once), then start listening
            # from the MAIN thread (CTranslate2 must be built there).
            self.chat.status_label.setText("warming ears - the first time this downloads the voice model once...")
            threading.Thread(target=self._warm_ears, daemon=True, name="vidit-ears-warmup").start()
        code = self.qt.exec_()
        try:
            self.chat.shutdown_worker()
        except Exception:  # noqa: BLE001
            pass
        self.vidit.sleep()
        from ..utils import mark_clean_exit

        mark_clean_exit()
        return code

    # ---------------------------------------------- voice warm-up (boot)
    def _warm_ears(self) -> None:
        """Worker: download the whisper model if needed (network only).
        The model LOAD happens on the main thread in start_listening()."""
        try:
            self.vidit.ears.download_model()
            self.bridge.earsReady.emit(True)
        except Exception as exc:  # noqa: BLE001
            log.warning("ears warm-up failed: %s", exc)
            self.bridge.earsReady.emit(False)

    def _on_ears_ready(self, ok: bool) -> None:
        """Main thread: the model files are ready -> preload + listen."""
        if not self.vidit.ears.available():
            self.chat.status_label.setText("voice unavailable: install faster-whisper, sounddevice and numpy")
            return
        if not ok:
            self.chat.status_label.setText(
                "voice model could not download (needs internet once) - the mic button will try again")
            return
        if self.vidit.start_listening():
            self.chat.status_label.setText(
                f"listening - just say \"{self.vidit.config.get('general.wake_word', 'vidit')}\" to wake him")
        else:
            self.chat.status_label.setText(
                f"voice unavailable: {getattr(self.vidit.ears, 'last_error', '') or 'microphone busy or missing'}")

    def quit(self) -> None:
        # Reap a running chat worker first so its QThread is never destroyed
        # while the thread is alive (would crash / warn on exit).
        try:
            self.chat.shutdown_worker()
        except Exception:  # noqa: BLE001
            pass
        self.vidit.sleep()
        self.qt.quit()


def main(home=None) -> int:
    app = ViditApp(home)
    return app.run()
