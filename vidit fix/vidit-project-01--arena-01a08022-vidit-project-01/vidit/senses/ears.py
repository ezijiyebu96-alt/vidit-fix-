"""Vidit's ears (Constitution section 6): offline speech-to-text and wake word.

* STT: faster-whisper running locally/offline.
* Audio capture: sounddevice + energy-based voice activity detection.
* Wake word: transcript-based wake word detection.
* No cloud, no API keys.

Every piece is optional. Without a microphone or required libraries,
Ears reports itself unavailable and the chat window keeps working.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..events import EventBus, bus as global_bus

log = logging.getLogger("vidit.senses.ears")

SAMPLE_RATE = 16000
FRAME_MS = 30


class Ears:
    def __init__(
        self,
        config_get: Callable[[str, Any], Any],
        models_dir: Path,
        event_bus: EventBus | None = None,
    ):
        self._get = config_get
        self.models_dir = Path(models_dir) / "whisper"
        self.bus = event_bus or global_bus

        self._model = None
        self._stream = None

        # CTranslate2 (faster-whisper) must be *constructed* exactly once, on the
        # main/UI thread — see the note on preload(). The lock serialises any
        # (re)construction; the event tells worker threads the model is usable
        # so they never have to build it themselves.
        self._model_lock = threading.Lock()
        self._model_ready = threading.Event()

        self._listening = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._transcribe_thread: Optional[threading.Thread] = None

        # Bounded audio frame queue (prevents unbounded growth if something stalls)
        self._audio_q: queue.Queue = queue.Queue(maxsize=200)

        # Bounded queue for complete utterances → transcription worker.
        # If the STT worker falls behind we drop the oldest utterance rather
        # than letting latency (and memory) grow without bound.
        self._utterance_q: queue.Queue = queue.Queue(maxsize=8)

        self.on_transcript: Optional[Callable[[str, bool], None]] = None

        self.last_error = ""
        self.awake_until = 0.0

    # ------------------------------------------------------------
    # status
    # ------------------------------------------------------------

    def available(self) -> bool:
        try:
            import faster_whisper  # type: ignore
            import sounddevice  # type: ignore
            import numpy  # type: ignore
            return True
        except ImportError:
            return False

    def status(self) -> Dict[str, Any]:
        return {
            "available": self.available(),
            "listening": self._listening.is_set(),
            "model": self._get("voice.stt_model", "small"),
            "model_ready": self._model_ready.is_set(),
            "error": self.last_error,
            "awake": time.time() < self.awake_until,
        }

    # ------------------------------------------------------------
    # whisper model
    # ------------------------------------------------------------

    # Tried in order; "int8" is the fast/safe CPU default, the rest are
    # fallbacks for machines whose runtimes reject it.
    _COMPUTE_TYPES = ("int8", "int8_float16", "float32", "default")

    def _load_model(self):
        """Build the WhisperModel if needed. Caller MUST hold ``self._model_lock``.

        Tries compute_type in _COMPUTE_TYPES order and never runs on a worker
        thread's initiative — the public entry points are preload() (main/UI
        thread) and transcribe_file() (user action).
        """
        if self._model is not None:
            return self._model

        from faster_whisper import WhisperModel

        size = self._get("voice.stt_model", "small")
        self.models_dir.mkdir(parents=True, exist_ok=True)

        log.info("Loading Whisper model on CPU: %s", size)

        last_exc: Optional[Exception] = None
        for compute_type in self._COMPUTE_TYPES:
            try:
                self._model = WhisperModel(
                    size,
                    device="cpu",
                    compute_type=compute_type,
                    download_root=str(self.models_dir),
                    cpu_threads=4,
                    num_workers=1,
                )
                log.info(
                    "Whisper model loaded successfully (compute_type=%s)",
                    compute_type,
                )
                return self._model
            except Exception as exc:
                last_exc = exc
                log.warning(
                    "Whisper load failed with compute_type=%s: %s",
                    compute_type,
                    exc,
                )

        self.last_error = f"Whisper model error: {last_exc}"
        log.error("Failed to load Whisper model with any compute_type")
        raise last_exc  # type: ignore[misc]

    def preload(self) -> bool:
        """Load the Whisper model ahead of the first transcription.

        WHY THIS MUST RUN ON THE MAIN/UI THREAD
        ---------------------------------------
        ``WhisperModel()`` is a CTranslate2 object whose first construction
        initialises the process-wide OpenMP/MKL/CTranslate2 thread pools. On
        Windows, doing that for the *first time* from a Python worker thread
        (the old VAD/STT loops) frequently access-violates and kills the whole
        process — see vidit_crash.txt:  faster_whisper/transcribe.py __init__
        ← ears._load_model ← ears._transcribe_array ← ears._loop.

        So: call preload() from the main/UI thread *before* start() spawns the
        audio/VAD/STT threads (Vidit.start_listening does exactly that). After
        ``_model_ready`` is set, worker threads only *use* the model (running
        inference on a ready model from a worker is safe); they never construct
        it — if it is not ready they log and skip instead of loading.

        Returns True when the model is ready for use.
        """
        if not self.available():
            self.last_error = "faster-whisper / sounddevice / numpy not installed"
            return False
        try:
            with self._model_lock:
                self._load_model()
            self._model_ready.set()
            return True
        except Exception:
            # last_error already carries the message; keep the UI alive and
            # let start_listening()/status() surface it.
            log.exception("Whisper preload failed")
            return False

    # ------------------------------------------------------------
    # transcription
    # ------------------------------------------------------------

    def transcribe_file(
        self,
        path: Path,
        language: Optional[str] = None,
    ) -> str:
        """Transcribe an audio/video file locally."""
        if not self.available():
            return (
                "(speech recognition not installed — "
                "pip install faster-whisper sounddevice numpy)"
            )

        try:
            # File transcription is a user action on the main thread: it may
            # build the model here if start()/preload() never ran. Workers
            # (microphone path) can NOT — see _transcribe_array.
            if not self.preload():
                log.error("File transcription skipped: model not ready (%s)", self.last_error)
                return ""
            model = self._model
            assert model is not None  # guaranteed by preload() success
            segments, _ = model.transcribe(
                str(path),
                language=language,
                vad_filter=True,
            )
            return " ".join(s.text.strip() for s in segments).strip()
        except Exception as exc:
            self.last_error = f"transcription error: {exc}"
            log.exception("File transcription failed")
            return ""

    def _transcribe_array(self, audio) -> str:
        """Safely transcribe a live microphone audio array (float32, already normalised)."""
        import numpy as np

        try:
            audio = np.asarray(audio, dtype=np.float32).flatten()
            if audio.size == 0:
                return ""

            # Defensive normalisation (handles both int16 leftovers and float)
            max_abs = float(np.max(np.abs(audio))) if audio.size else 0.0
            if max_abs > 1.0 + 1e-6:
                # Assume original was int16-scale
                audio = audio / 32768.0
            audio = np.ascontiguousarray(audio, dtype=np.float32)

            duration = audio.size / SAMPLE_RATE
            log.info("Transcribing microphone audio: %.2f seconds", duration)
            if duration < 0.4:
                return ""

            # NEVER construct the model here. Building WhisperModel for the
            # first time on this worker thread access-violates on Windows
            # (OpenMP/MKL/CTranslate2 init) — the model must have been
            # preloaded on the main/UI thread (see preload()). If it wasn't,
            # skip the utterance instead of crashing.
            if not self._model_ready.is_set() or self._model is None:
                log.info(
                    "Whisper model not preloaded yet — skipping %.2fs utterance "
                    "(call ears.preload() on the main thread before start())",
                    duration,
                )
                return ""

            model = self._model
            segments, _ = model.transcribe(
                audio,
                language=None,
                vad_filter=True,
                beam_size=3,
            )

            text = " ".join(
                segment.text.strip()
                for segment in segments
                if segment.text and segment.text.strip()
            ).strip()

            log.info("Transcription result: %r", text)
            return text
        except Exception as exc:
            self.last_error = f"transcription error: {exc}"
            log.exception("Microphone transcription failed")
            return ""

    # ------------------------------------------------------------
    # listening
    # ------------------------------------------------------------

    def start(self) -> bool:
        if self._listening.is_set():
            return True

        if not self.available():
            self.last_error = "faster-whisper / sounddevice / numpy not installed"
            return False

        # Drain any leftover frames from a previous run
        while not self._audio_q.empty():
            try:
                self._audio_q.get_nowait()
            except queue.Empty:
                break
        while not self._utterance_q.empty():
            try:
                self._utterance_q.get_nowait()
            except queue.Empty:
                break

        try:
            import sounddevice as sd  # type: ignore

            device = self._get("voice.microphone", "default")
            kwargs: Dict[str, Any] = {
                "samplerate": SAMPLE_RATE,
                "channels": 1,
                "dtype": "int16",
                "blocksize": int(SAMPLE_RATE * FRAME_MS / 1000),
                "callback": self._on_audio,
            }
            if device and device != "default":
                kwargs["device"] = device

            self._stream = sd.InputStream(**kwargs)
            self._stream.start()
        except Exception as exc:
            self.last_error = f"microphone error: {exc}"
            log.exception("Failed to start microphone")
            return False

        self._listening.set()

        # Light VAD / frame-collection thread
        self._thread = threading.Thread(
            target=self._loop,
            name="vidit-ears-vad",
            daemon=True,
        )
        self._thread.start()

        # Separate transcription worker (never blocks the VAD)
        self._transcribe_thread = threading.Thread(
            target=self._transcribe_loop,
            name="vidit-ears-stt",
            daemon=True,
        )
        self._transcribe_thread.start()

        self.bus.emit("ears.started")
        log.info("Vidit ears started")
        return True

    def stop(self) -> None:
        self._listening.clear()

        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        # Wake the worker so it can exit cleanly (make room if it is full)
        try:
            self._utterance_q.put_nowait(None)
        except queue.Full:
            try:
                self._utterance_q.get_nowait()
                self._utterance_q.put_nowait(None)
            except (queue.Empty, queue.Full):
                pass

        self.bus.emit("ears.stopped")
        log.info("Vidit ears stopped")

    def _on_audio(self, indata, frames, time_info, status) -> None:
        if status:
            log.debug("Audio callback status: %s", status)
        try:
            self._audio_q.put_nowait(indata.copy())
        except queue.Full:
            # Drop oldest frames if the queue is full (protects against
            # pathological stalls). The VAD will simply miss a few frames.
            try:
                self._audio_q.get_nowait()
                self._audio_q.put_nowait(indata.copy())
            except queue.Empty:
                pass

    # ------------------------------------------------------------
    # voice activity detection (lightweight – never blocks on STT)
    # ------------------------------------------------------------

    def _loop(self) -> None:
        """Collect speech and hand complete utterances to the STT worker."""
        import numpy as np  # type: ignore

        buffer: List[Any] = []
        silence_frames = 0
        speaking = False
        noise_floor = 300.0
        max_silence = int(700 / FRAME_MS)

        while self._listening.is_set():
            try:
                frame = self._audio_q.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                energy = float(np.abs(frame).mean())

                if not speaking:
                    noise_floor = 0.95 * noise_floor + 0.05 * energy

                threshold = max(350.0, noise_floor * 2.5)

                if energy > threshold:
                    speaking = True
                    silence_frames = 0
                    buffer.append(frame)
                elif speaking:
                    buffer.append(frame)
                    silence_frames += 1

                    if silence_frames >= max_silence:
                        audio = (
                            np.concatenate(buffer)
                            .flatten()
                            .astype(np.float32)
                            / 32768.0
                        )
                        buffer = []
                        speaking = False
                        silence_frames = 0

                        if len(audio) < SAMPLE_RATE * 0.4:
                            continue

                        seconds = len(audio) / SAMPLE_RATE
                        self.bus.emit("ears.utterance", seconds=seconds)

                        # Hand off to the dedicated transcription thread.
                        # The queue is bounded: if STT is behind, drop the
                        # oldest utterance so latency cannot grow forever.
                        try:
                            self._utterance_q.put_nowait(audio)
                        except queue.Full:
                            try:
                                self._utterance_q.get_nowait()
                                self._utterance_q.put_nowait(audio)
                            except (queue.Empty, queue.Full):
                                pass
                            log.warning("Utterance queue full – dropped oldest utterance")

            except Exception as exc:
                self.last_error = f"audio processing error: {exc}"
                log.exception("Audio processing failed")

    def _transcribe_loop(self) -> None:
        """Dedicated worker that never blocks the VAD / microphone callback.

        It only *uses* the preloaded model (via _transcribe_array, which logs
        and returns "" if the model was never preloaded). It must never
        construct WhisperModel itself — first-time construction on a worker
        thread access-violates on Windows (see preload()).
        """
        while self._listening.is_set() or not self._utterance_q.empty():
            try:
                item = self._utterance_q.get(timeout=0.5)
            except queue.Empty:
                continue

            if item is None:  # poison pill from stop()
                break

            try:
                text = self._transcribe_array(item)
                if text:
                    self._handle_transcript(text)
            except Exception as exc:
                self.last_error = f"transcription error: {exc}"
                log.exception("Live transcription failed")

    # ------------------------------------------------------------
    # wake word
    # ------------------------------------------------------------

    def wake_words(self) -> List[str]:
        word = str(self._get("general.wake_word", "vidit")).lower().strip()

        variants = {
            word,
            f"hey {word}",
            f"ok {word}",
            f"okay {word}",
        }

        if word == "vidit":
            variants |= {
                "vidhit",
                "vidith",
                "vidid",
                "widit",
                "video",
                "vidi",
            }

        return sorted(variants, key=len, reverse=True)

    def strip_wake_word(self, text: str) -> tuple[str, bool]:
        lowered = text.lower()

        for word in self.wake_words():
            match = re.search(
                rf"\b{re.escape(word)}\b[,!. ]*",
                lowered,
            )
            if match:
                stripped = (
                    text[: match.start()] + text[match.end() :]
                ).strip(" ,.!?")
                return stripped, True

        return text, False

    # ------------------------------------------------------------
    # transcript handling
    # ------------------------------------------------------------

    def _handle_transcript(self, text: str) -> None:
        activation = self._get("voice.activation", "wake_word")

        stripped, woke = self.strip_wake_word(text)

        if woke:
            self.awake_until = time.time() + 45
            self.bus.emit("ears.wake")

        awake = (
            activation in ("always", "push_to_talk", "button")
            or woke
            or time.time() < self.awake_until
        )

        self.bus.emit(
            "ears.transcript",
            text=text,
            woke=woke,
            awake=awake,
        )

        if awake and self.on_transcript:
            self.on_transcript(stripped or text, woke)