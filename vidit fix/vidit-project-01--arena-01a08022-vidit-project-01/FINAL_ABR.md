# VIDIT — Final ABR (After-Action Report)

Date: 2026-09-08 · Branch `arena/01a080d1-vidit-fix` · Tests: **31 passed** · 100 % offline, PyQt5 only

---

## 1. What Vidit is

Vidit is a fully offline desktop companion ("digital brother") for Windows/Linux:
a glowing orb + chat interface with local speech-to-text (faster-whisper), local
text-to-speech (Piper/pyttsx3), a local brain (Ollama, echo fallback), memory,
emotions, wake-word listening and a gaming companion — no cloud, no API keys,
everything stored under the user's own folder.

## 2. What was fixed (summary of the whole effort)

- **STT crash (Windows access violation):** WhisperModel is now constructed only
  on the main/UI thread (`Ears.preload()`), guarded by `_model_lock` +
  `_model_ready`; compute_type falls back `int8 → int8_float16 → float32 →
  default`; VAD and STT run on separate threads with bounded queues; worker
  threads never build the model. `core.start_listening()` preloads before
  `ears.start()`.
- **Health pass:** pyttsx3 COM engine now initialised on the speech worker (was a
  main-thread/worker apartment bug); OpenCV `VideoCapture` access serialised
  with a lock; chat QThread reaped on quit; HUD/dashboard refresh timers pause
  while hidden; refresh calls hardened; empty debug files removed.
- **GUI overhaul ("cyber-glass"):** rebuilt Settings with a neon left-nav and a
  concept-matching General page (avatar card + ONLINE pill + quote, Companion
  Mode chips, gradient Response-Length/Creativity sliders, animated Memory /
  Proactive / Auto-Continue toggles, avatar carousel, name/language/timezone,
  status toast + Save Changes); new reusable widgets (`GlassCard`, `NeonToggle`,
  `GradientSlider`, `ModeChip`, `AvatarCircle/Picker`, `StatusToast`,
  `OnlinePill`); neon theme palette `#00e5ff / #7b5cff / #a855f7`; 4 local
  avatar portraits; mic button with idle/listening/processing/error states that
  degrades gracefully when speech isn't installed.

## 3. Hardware target and what changed for it (≈4 GB RAM, 2 cores, iGPU)

Measured on a real 4.1 GB / 2-core machine (this project's test box):

| Area | Change |
|---|---|
| Whisper size | `voice.stt_model` default is now **`auto`**: tiny ≤ 3 GB, **base ≤ 6 GB**, small above. A stored legacy `"small"` is auto-downgraded to `base` on ≤ 4.5 GB machines (log line tells you; pin any explicit value to override). |
| Whisper threads | `cpu_threads` adaptive: **2** on ≤ 4.5 GB RAM or ≤ 2 cores, else 4 (capped by cores); `num_workers` stays 1. |
| Idle RAM | `Ears.stop()` now **unloads the Whisper model** on ≤ 4.5 GB machines (config `voice.unload_model_when_idle`: null=auto / true / false) and drains the raw-frame queue. Next start re-preloads in ~1–3 s (base/tiny) with the usual main-thread rule. |
| Heartbeat | `general.energy_mode == "saver"` halves the cadence of mood ticks, game detection, hourly saves and check-ins (5 s wake-up unchanged and cheap). |
| UI idle | `OrbWidget` and `WaveformWidget` **stop their animation timers when hidden** (minimised/hidden windows cost zero repaint CPU); waveform already self-idles after ~2 s. |
| LLM guidance | `vidit --doctor` detects low RAM and recommends `qwen2.5:3b` / `phi3:mini` instead of a 7 B model (7 B + 4 GB = swapping); existing fallback chain unchanged. |
| GUI | no visual/layout/theme changes — only timer pauses and one added combo value (`auto`) in the existing whisper-model dropdown. |

## 4. How to run in the background / talk while working

- Start normally (`python -m vidit`). Switch to **orb / HUD / stealth / PiP** mode
  (tray menu or orb right-click) — the chat window can be closed/minimised; the
  mic, wake word, VAD and STT threads keep running independently of the UI.
- Say **"hey Vidit …"** anywhere. If stealth mode is on, the chat surfaces on the
  wake word; otherwise the reply arrives as a **toast + orb pulse** without
  stealing focus, and is spoken via TTS on the voice worker thread (UI never
  blocks).
- While a game is detected the existing gaming quiet rules apply (whisper/silent
  modes) — untouched, now lighter thanks to the saver cadence.
- The only intentional UI-thread block is the 1–3 s Whisper preload on mic
  start; the button paints its "Listening" state first, so it never feels dead.

## 5. Recommended settings for low RAM (4 GB)

| Setting | Value | Where |
|---|---|---|
| Speech model | `auto` (resolves to `base`) | Settings → Voice |
| Energy mode | `saver` | Settings → System |
| Ollama model | `qwen2.5:3b` or `phi3:mini` | Settings → Model (see doctor tip) |
| Keep model loaded | leave `voice.unload_model_when_idle` unset (auto-unload) | config (documented) |
| Context messages | ≤ 20 if you run many apps side-by-side | Settings → Model |

## 6. Known limits

- Whisper preload still happens on the main thread **by design** (Windows
  CTranslate2 constraint); on tiny/base it is 1–3 s.
- Auto-unload means the first utterance after a pause re-preloads; pin
  `voice.unload_model_when_idle: false` if you prefer instant re-listen and have
  RAM to spare.
- 7 B LLMs are not realistic on 4 GB — use the 3 B models (doctor now says so).
- Nav icons are emoji (native on Windows 11); avatar art is generated placeholder
  quality; `voice.speaker` and a few accessibility toggles remain future-facing.
- Wake-word listening requires OS microphone permission; nothing is sent anywhere.

## 7. Final zip

**`/home/user/vidit_gui_overhaul_complete.zip`** — complete project (source,
assets/avatars, report, screenshots), no `__pycache__`, no `.venv`, no `.git`.

## Verification (this round)

- `pytest`: **31 passed** (30 previous + new `test_low_ram_model_selection`
  covering tiny/base/small resolution, thread guard, explicit-pin respect and
  unload-on-stop auto/forced/kept).
- Smokes: settings (draft/save, chips, sliders, toggles, avatar), full app
  (themes, 11 pages, mic cycle, MainThread-only build, hot release), deep sweep
  (all widgets paint, hidden-timer pause verified, `base`+2 threads resolved on
  the 4.1 GB box, idle unload verified, dashboard 5 tabs), `--doctor` low-RAM
  tips, `--help`.
