"""Vidit's ears (Constitution section 6): offline speech-to-text and wake word.

* STT: faster-whisper running locally/offline.
* Audio capture: sounddevice + energy-based voice activity detection.
* Wake word: transcript-based wake word detection.
* No cloud, no API keys.

Every piece is optional. Without a microphone or required libraries,
Ears reports itself unavailable and the chat window keeps working.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..events import EventBus, bus as global_bus

log = logging.getLogger("vidit.senses.ears")

SAMPLE_RATE = 16000
FRAME_MS = 30

# Ordered compute-type candidates used when voice.stt_compute_type == "auto".
# int8 is fastest on CPU; on a few CPUs/wheel combos ctranslate2 cannot use it
# (ValueError) or, on some Windows builds, crashes natively — so we try it in a
# subprocess first and fall back to the less exotic types.
DEFAULT_COMPUTE_TYPES = ("int8", "int8_float32", "float32")

# Identifiers of models that can be auto-downloaded by faster-whisper.
AUTO_SIZES = ("tiny", "tiny.en", "base", "base.en", "small", "small.en",
              "medium", "medium.en", "large-v1", "large-v2", "large-v3", "large-v3-turbo")


class EarsModelError(RuntimeError):
    """The speech model could not be made ready.

    Raised instead of letting a native faster-whisper / ctranslate2 failure
    escape as a process-killing crash. The message is user-facing guidance.
    """


# Runs inside a throwaway subprocess so that a native crash inside
# faster-whisper / ctranslate2 (seen on some Windows setups) kills only the
# probe, never Vidit. It writes a tiny JSON result to <result_file>.
_CHILD_CODE = r"""
import json, os, sys, time, traceback
result_file, task = sys.argv[1], sys.argv[2]

def done(obj):
    try:
        with open(result_file, "w", encoding="utf-8") as fh:
            json.dump(obj, fh)
    except Exception:
        pass
    sys.exit(0)

try:
    if task == "download":
        size, cache_dir = sys.argv[3], sys.argv[4]
        try:
            from faster_whisper.utils import download_model  # type: ignore
        except Exception:
            download_model = None
        if download_model is None:
            # fall back to huggingface_hub directly (older/newer faster-whisper)
            from huggingface_hub import snapshot_download  # type: ignore
            repo = size if "/" in size else "Systran/faster-whisper-" + size
            path = snapshot_download(repo_id=repo, cache_dir=cache_dir)
        else:
            path = download_model(size, cache_dir=cache_dir)
        if not os.path.isdir(path) or not os.path.isfile(os.path.join(path, "model.bin")):
            done({"ok": False, "error": "download finished but model files are incomplete; run the doctor and reset the speech model cache"})
        done({"ok": True, "path": path})
    elif task == "probe":
        model_path, compute_type, threads = sys.argv[3], sys.argv[4], int(sys.argv[5])
        from faster_whisper import WhisperModel  # type: ignore
        t0 = time.time()
        model = WhisperModel(model_path, device="cpu", compute_type=compute_type, cpu_threads=threads)
        # Touch every weight once so lazy native init happens inside the probe.
        _ = model.model  # noqa
        done({"ok": True, "compute_type": compute_type, "seconds": round(time.time() - t0, 1)})
    else:
        done({"ok": False, "error": "unknown probe task: " + task})
except BaseException:
    done({"ok": False, "error": traceback.format_exc(limit=2)[-2500:]})
"""


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

        # Speech-model lifecycle -------------------------------------------------
        # state: idle | warming | ready | error
        self._model_state = "idle"
        self._model_error = ""
        self._compute_used = ""
        self._model_lock = threading.Lock()
        self._warm_thread: Optional[threading.Thread] = None

        self._listening = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._transcribe_thread: Optional[threading.Thread] = None

        # Bounded audio frame queue (prevents unbounded growth if something stalls)
        self._audio_q: queue.Queue = queue.Queue(maxsize=200)

        # Separate queue for complete utterances → transcription worker
        self._utterance_q: queue.Queue = queue.Queue()

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
            "model_state": self._model_state,
            "compute_type": self._compute_used or self._get("voice.stt_compute_type", "auto"),
            "error": self._model_error or self.last_error,
            "awake": time.time() < self.awake_until,
        }

    # ------------------------------------------------------------
    # whisper model — robust, thread-safe, crash-isolated
    # ------------------------------------------------------------

    def warmup(self) -> bool:
        """Start loading the speech model in the background (non-blocking).

        Called automatically when the microphone starts (see :meth:`start`).
        First use may download the model, so this runs off the UI and audio
        threads and can never block the chat.
        """
        if not self.available():
            return False
        if not bool(self._get("voice.stt_warmup", True)):
            return False
        with self._model_lock:
            if self._model is not None or self._model_state == "warming":
                return True
            if self._warm_thread and self._warm_thread.is_alive():
                return True
            self._warm_thread = threading.Thread(
                target=self._warm_worker,
                name="vidit-ears-warm",
                daemon=True,
            )
            self._warm_thread.start()
        return True

    def _warm_worker(self) -> None:
        try:
            self._ensure_model()
        except EarsModelError:
            pass  # guidance already recorded in self._model_error / last_error
        except Exception as exc:  # noqa: BLE001 — never let warm-up take the app down
            log.exception("Whisper warm-up failed")
            self._model_error = f"speech model error: {exc}"
        if self._model is not None:
            self.bus.emit("ears.model_ready", size=self._stt_size(), compute_type=self._compute_used)
        else:
            self.bus.emit("ears.model_error", error=(self._model_error or "speech model unavailable")[:400])

    def model_ready(self) -> bool:
        return self._model is not None

    def reset_model_cache(self, clear_downloads: bool = False) -> str:
        """Drop broken state / probes and (optionally) the downloaded models.

        Handy when a model download was interrupted: a half-written snapshot
        can make ctranslate2 fail (or crash) on load. Returns a human message.
        """
        with self._model_lock:
            self._model = None
            self._model_state = "idle"
            self._model_error = ""
            self.last_error = ""
            self._compute_used = ""
            try:
                self._probe_cache_path().unlink(missing_ok=True)
            except OSError:
                pass
            if clear_downloads:
                for p in self.models_dir.glob("models--*"):
                    try:
                        import shutil

                        shutil.rmtree(p, ignore_errors=True)
                    except OSError:
                        pass
        return (
            "Speech model state reset. The model will be re-checked / re-downloaded "
            "the next time the microphone starts."
        )

    # -- internal plumbing -------------------------------------------------

    def _probe_enabled(self) -> bool:
        return bool(self._get("voice.stt_safe_probe", True))

    def _probe_cache_path(self) -> Path:
        return self.models_dir / "_probe.json"

    def _stt_size(self) -> str:
        size = str(self._get("voice.stt_model", "small") or "small").strip()
        if not size:
            raise EarsModelError("No speech model configured (voice.stt_model is empty).")
        return size

    def _stt_threads(self) -> int:
        n = int(self._get("voice.stt_cpu_threads", 0) or 0)
        if n > 0:
            return n
        return max(1, min(4, os.cpu_count() or 4))

    def _probe_timeout(self) -> float:
        try:
            return max(60.0, float(self._get("voice.stt_probe_timeout", 900)))
        except (TypeError, ValueError):
            return 900.0

    def _configured_compute_types(self) -> List[str]:
        chosen = str(self._get("voice.stt_compute_type", "auto") or "auto").strip().lower()
        if chosen == "auto":
            return list(DEFAULT_COMPUTE_TYPES)
        return [chosen] + [c for c in DEFAULT_COMPUTE_TYPES if c != chosen]

    def _versions(self) -> Dict[str, str]:
        try:
            from importlib import metadata

            return {
                "faster_whisper": metadata.version("faster-whisper"),
                "ctranslate2": metadata.version("ctranslate2"),
            }
        except Exception:  # noqa: BLE001
            return {}

    def _cache_entry(self) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(self._probe_cache_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if data.get("size") != self._stt_size():
            return None
        if data.get("platform") != sys.platform:
            return None
        if data.get("versions") != self._versions():
            return None
        if not data.get("snapshot") or not Path(data["snapshot"]).is_dir():
            return None
        return data

    def _write_cache(self, size: str, snapshot: str, compute_type: str) -> None:
        try:
            self.models_dir.mkdir(parents=True, exist_ok=True)
            self._probe_cache_path().write_text(
                json.dumps({
                    "size": size,
                    "snapshot": snapshot,
                    "compute_type": compute_type,
                    "platform": sys.platform,
                    "versions": self._versions(),
                    "cached_at": time.time(),
                }),
                encoding="utf-8",
            )
        except OSError as exc:
            log.warning("Could not write whisper probe cache: %s", exc)

    def _run_child(self, args: List[str], timeout: float) -> Optional[Dict[str, Any]]:
        """Run the probe snippet in a subprocess; never crashes the parent."""
        out = self.models_dir / f"_probe_{os.getpid()}_{int(time.time() * 1000)}.json"
        try:
            self.models_dir.mkdir(parents=True, exist_ok=True)
            cmd = [sys.executable, "-c", _CHILD_CODE, str(out), *args]
            kwargs: Dict[str, Any] = {
                "capture_output": True,
                "text": True,
                "timeout": timeout,
                "cwd": str(self.models_dir),
            }
            if os.name == "nt":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # type: ignore[attr-defined]
            proc = subprocess.run(cmd, **kwargs)  # noqa: PLW1510
            if proc.returncode < 0:
                # Killed by a signal — the classic native-crash signature.
                return {"ok": False, "error": f"probe process crashed (exit code {proc.returncode})"}
            try:
                data = json.loads(out.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {"ok": False, "error": (proc.stderr or proc.stdout or "")[-1000:] or "probe produced no result"}
            return data
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"timed out after {int(timeout)}s (first download can be slow)"}
        except OSError as exc:
            return {"ok": False, "error": f"could not run probe: {exc}"}
        finally:
            try:
                out.unlink(missing_ok=True)
            except OSError:
                pass

    def _local_model_dir(self, size: str) -> Optional[str]:
        """Return `size` itself when it points at an existing ct2 model folder."""
        p = Path(size).expanduser()
        if p.is_dir():
            return str(p)
        if size in AUTO_SIZES or "/" in size:
            return None
        # A bare name that is not a known auto-size and not a folder:
        # not something we can safely fetch.
        return None

    def _resolve_snapshot(self, size: str) -> str:
        """Make sure the model weights exist locally; return their folder path.

        Reuses faster-whisper's own download cache, so a re-run after a failed
        download resumes instead of starting over.
        """
        local = self._local_model_dir(size)
        if local:
            return local

        cached = self._cache_entry()
        if cached and cached.get("snapshot"):
            snap = Path(cached["snapshot"])
            if (snap / "model.bin").is_file():
                return str(snap)
            # stale cache entry -> ignore below
        self._model_state = "warming"
        self.last_error = (
            "Downloading the speech model for the first time (one-time, ~460 MB for 'small'). "
            "Vidit stays fully offline after this."
        )
        self.bus.emit("ears.model_downloading", size=size)
        log.info("Downloading whisper model %r into %s", size, self.models_dir)
        result = self._run_child(["download", size, str(self.models_dir)], self._probe_timeout())
        if not result or not result.get("ok"):
            err = (result or {}).get("error") or "unknown download error"
            raise EarsModelError(
                "Could not download the speech model. " + err +
                " Check your internet once, then try again — or reset the model cache from the doctor."
            )
        snap = str(result["path"])
        if not (Path(snap) / "model.bin").is_file():
            raise EarsModelError(
                "The speech model download is incomplete/corrupt. Run `python -m vidit --doctor` "
                "or reset the speech model cache and try again."
            )
        return snap

    def _pick_compute_type(self, snapshot: str) -> str:
        """Choose a compute type that actually loads on this machine.

        With the safe probe enabled the model is loaded once inside a
        subprocess *before* we load it here, so a native crash in ctranslate2
        (a known Windows issue) can never take Vidit down with it.
        """
        candidates = self._configured_compute_types()
        cached = self._cache_entry()
        if cached and cached.get("compute_type") and cached["snapshot"] == snapshot:
            chosen = str(cached["compute_type"])
            if chosen in candidates:
                candidates = [chosen] + [c for c in candidates if c != chosen]

        if self._probe_enabled():
            self._model_state = "warming"
            errors: List[str] = []
            for compute in candidates:
                log.info("Probing whisper model load with compute_type=%s", compute)
                result = self._run_child(
                    ["probe", snapshot, compute, str(self._stt_threads())],
                    min(600.0, self._probe_timeout()),
                )
                if result and result.get("ok"):
                    log.info("Whisper probe OK with compute_type=%s", compute)
                    return compute
                errors.append(f"{compute}: {(result or {}).get('error', 'failed')}")
            raise EarsModelError(
                "The speech model could not be loaded with any compute type "
                "(int8 / int8_float32 / float32). This usually means the faster-whisper "
                "build does not match this CPU, or the model cache is corrupt. Try:\n"
                "  1. Settings → Voice → STT compute type → float32\n"
                "  2. `pip install -U faster-whisper` (or pin `ctranslate2==4.4.0`)\n"
                "  3. reset the speech model cache (doctor)\n"
                "Probe details: " + "; ".join(errors[-3:])
            )

        return candidates[0]

    def _build_model(self, snapshot: str, compute: str, threads: int):
        """Load ctranslate2's Whisper model in-process (after a successful probe)."""
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise EarsModelError(
                "Speech recognition is not installed (pip install faster-whisper)."
            ) from exc

        self._model_state = "warming"
        last_exc: Optional[Exception] = None
        tried: List[str] = []
        for candidate in [compute] + [c for c in self._configured_compute_types() if c != compute]:
            if candidate in tried:
                continue
            tried.append(candidate)
            try:
                log.info("Loading Whisper model on CPU (compute_type=%s): %s", candidate, snapshot)
                model = WhisperModel(
                    snapshot,
                    device="cpu",
                    compute_type=candidate,
                    cpu_threads=threads,
                    download_root=str(self.models_dir),
                )
                self._model = model
                self._compute_used = candidate
                self._model_state = "ready"
                self._model_error = ""
                self.last_error = ""
                self._write_cache(self._stt_size(), snapshot, candidate)
                log.info("Whisper model loaded successfully (%s)", candidate)
                return model
            except EarsModelError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                log.warning("Whisper load failed with compute_type=%s: %s", candidate, exc)
        err = f"{type(last_exc).__name__}: {last_exc}" if last_exc else "unknown error"
        self._model_state = "error"
        self._model_error = (
            "The speech model failed to load: " + err +
            " (tried " + ", ".join(tried) + "). See Settings → Voice → STT compute type."
        )
        raise EarsModelError(self._model_error)

    def _ensure_model(self):
        """Idempotent, single-flight model loader used by every caller."""
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is not None:
                return self._model
            if self._model_state == "error":
                raise EarsModelError(self._model_error or "speech model unavailable")
            size = self._stt_size()
            threads = self._stt_threads()
            self.models_dir.mkdir(parents=True, exist_ok=True)
            try:
                snapshot = self._resolve_snapshot(size)
                compute = self._pick_compute_type(snapshot)
                return self._build_model(snapshot, compute, threads)
            except EarsModelError:
                if self._model_state != "error":
                    self._model_state = "error"
                    self._model_error = str(sys.exc_info()[1])
                raise
            except Exception as exc:  # noqa: BLE001
                self._model_state = "error"
                self._model_error = f"speech model error: {exc}"
                log.exception("Failed to load Whisper model")
                raise EarsModelError(self._model_error)

    def _load_model(self):
        """Back-compat entry point (same as :meth:`_ensure_model`)."""
        return self._ensure_model()

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
            model = self._load_model()
            segments, _ = model.transcribe(
                str(path),
                language=language,
                vad_filter=True,
            )
            return " ".join(s.text.strip() for s in segments).strip()
        except EarsModelError:
            return f"(speech model unavailable: {self._model_error})"
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

            model = self._load_model()
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
        except EarsModelError:
            # Model failed to load earlier (see self._model_error for why).
            # Swallow quietly — the chat UI already shows the reason.
            return ""
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

        # Each time the user switches the mic on we allow one fresh attempt at
        # loading the speech model (e.g. after a transient network failure).
        with self._model_lock:
            if self._model_state == "error" and self._model is None:
                self._model_state = "idle"
                self._model_error = ""

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

        # Start loading the whisper model in the background so the first real
        # utterance never triggers a slow / risky first-time download on the
        # audio path (and so transcription is ready when speech arrives).
        if bool(self._get("voice.stt_warmup", True)):
            self.warmup()

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

        # Wake the worker so it can exit cleanly
        try:
            self._utterance_q.put_nowait(None)
        except queue.Full:
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

                        # Hand off to the dedicated transcription thread
                        try:
                            self._utterance_q.put_nowait(audio)
                        except queue.Full:
                            log.warning("Utterance queue full – dropping utterance")

            except Exception as exc:
                self.last_error = f"audio processing error: {exc}"
                log.exception("Audio processing failed")

    def _transcribe_loop(self) -> None:
        """Dedicated worker that never blocks the VAD / microphone callback."""
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