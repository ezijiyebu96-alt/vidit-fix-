# WINDOWS11_BUILD.md — building & running Vidit on Windows 11 (x64)

Vidit is packaged as a native Windows desktop application: **`Vidit.exe`**.
The user never sees Python.

---

## 1. Requirements

| What | Minimum |
| --- | --- |
| OS | Windows 11 (22H2 or newer), 64-bit |
| RAM | 4 GB (8 GB comfortable with the whisper `small` model) |
| Disk | ~2 GB app + models (ears model downloads once on first listening use) |
| Local brain | [Ollama](https://ollama.com) + `ollama pull qwen2.5:7b` (or 3b on 4 GB) — *optional: without it Vidit runs on his simple fallback mind* |
| Microphone | any — only for voice commands (optional) |
| To BUILD | Python 3.11 x64 from [python.org](https://python.org) (tick "Add to PATH"), internet for pip |

## 2. Build instructions

### One command (recommended)
```bat
build_windows.bat
```
It creates `.venv-win`, installs `requirements.txt` + `requirements-senses.txt` +
PyInstaller, runs the test suite as a quality gate, builds, copies the result to
**`release\Vidit\`**, and reports BUILD OK / BUILD FAILED.

### Manual
```bat
py -m venv .venv-win
.venv-win\Scripts\python -m pip install -r requirements.txt -r requirements-senses.txt "pyinstaller>=6.0"
.venv-win\Scripts\python -m pytest tests -q
.venv-win\Scripts\python -m PyInstaller --noconfirm --clean Vidit.spec
```

### EXE location
- Local build: **`release\Vidit\Vidit.exe`** (copy the whole `Vidit` folder).
- CI build: artifact **`Vidit-Windows11-x64.zip`** from the `build-windows`
  GitHub Actions run (workflow `.github/workflows/build-windows.yml`,
  `windows-latest`) — unzip anywhere and double-click `Vidit.exe`.

`Vidit.spec` is **onedir** (fast start, clean updates, no temp-extract), windowed
(`console=False`), UPX disabled (avoids antivirus false positives).

## 3. First launch

1. Double-click `Vidit.exe`.
2. **SmartScreen**: the exe is unsigned → "Windows protected your PC" →
   *More info → Run anyway* (sign it with your own cert to remove this).
3. Vidit's data lives in **`%LOCALAPPDATA%\Vidit`** (memory DB, settings.json,
   logs, skills, whisper models) — never in the install folder, so a
   read-only `Program Files` install is fine.
4. Voice: on first listening use, the offline whisper model downloads once
   (needs internet **once**), then everything runs 100 % offline.
5. Check health anytime: `Vidit.exe --doctor` from a terminal (Command
   Prompt / PowerShell — the app attaches to the console and prints the
   report there; exit code 0 = healthy). `Vidit.exe --version` works the
   same way. If the app ever crashes on start, the traceback is written to
   `%LOCALAPPDATA%\Vidit\logs\vidit_crash.log` instead of dying silently.

## 4. Windows permissions & accessibility

| Feature | What Windows asks / needs |
| --- | --- |
| Microphone (ears) | Settings → Privacy & security → Microphone → allow desktop apps |
| Mouse/keyboard automation (`computer_act`) | nothing special — normal user-level input via pyautogui; **no accessibility/sticky-keys hacks used** |
| Screenshots (`screen_look`) | normal desktop session (not required: admin/UAC-elevated windows are invisible to a non-elevated app) |
| App launching (`open`) | normal user launch; **UAC-elevated apps cannot be launched or driven** by design |
| Clipboard | normal user clipboard |
| Nothing | administrator rights, driver installs, Defender exclusions — never required |

**Emergency STOP: `Ctrl+Alt+S`** inside any Vidit window (Esc in chat works
too). It halts speech, denies tool permission checks and aborts any running
autonomous chain between steps. pyautogui's FAILSAFE (fling mouse to a screen
corner) is an extra brake.

## 5. Browser, Adobe, WhatsApp — what's real and what isn't

Vidit's computer-control layer is **generic desktop + browser**: it opens apps
and URLs, lists window titles, reads the foreground window, takes single
screenshots, and can click/type/hotkey **behind the Guardian** (off by
default; per-task budget of 5 actions / 30 s).

| Target | Status | Detail |
| --- | --- | --- |
| Default browser (Edge/Chrome/Firefox) | launch + `open <URL>` — **works** | "Vidit, open youtube.com" opens the default browser. No embedded form-filling engine. |
| File Explorer / general apps | **works** | `open` tool (`os.startfile`/ShellExecute), window listing, clipboard, delete-with-backup, organize folders |
| Adobe Photoshop / Illustrator | **launch + surface-level only** | Vidit can launch them and drive visible UI (menus via clicks/hotkeys) when you enable computer control — but there is **no Adobe UXP/ scripting integration**, no knowledge of PSD layers. Complex edits are NOT supported. |
| WhatsApp Business | **launch + surface-level only** | same: launch, click/type at the visible UI level. No WhatsApp API integration; message-sending always sits behind 🟡 Guardian confirmation. |
| MS Office | launch + file-level | Vidit reads/writes DOCX/XLSX with the local file stack; GUI automation is generic clicks only. |

If you need true app-specific automation, that is a separate integration
(Adobe UXP plugins, WhatsApp Business API) — not present in this codebase and
not claimed here.

## 6. Voice commands

Real, in the source (`vidit/senses/ears.py`): wake word **"Vidit"** → offline
faster-whisper STT → the brain plans and uses tools. Examples that work with
existing tools: *"Vidit, open Photoshop"*, *"remind me…", "organize my
Downloads", "summarize the new PDF in Downloads"*. Multi-step GUI goals (e.g.
*"take the image from Downloads and make a 1080×1080 Instagram post"*) are
planned as 1–5-step tool chains, but executing them depends on computer
control being enabled and are **not verified for reliability** — treat as
experimental.

## 7. Troubleshooting

| Symptom | Fix |
| --- | --- |
| SmartScreen warning | More info → Run anyway (unsigned build) |
| App starts then closes instantly | run `Vidit.exe --doctor`; check `%LOCALAPPDATA%\Vidit\logs\vidit.log` |
| "GUI unavailable" | reinstall with `build_windows.bat` (PyQt5 must be bundled) |
| No voice output | Settings → Voice engine: pyttsx3 (built-in Windows SAPI). Piper needs a standalone `piper.exe` on PATH in the packaged build |
| Ears disabled | `pip` deps are bundled; check mic privacy setting + that the whisper model downloaded |
| "Couldn't find an app called X" | use the exe name (`mspaint`, `Photoshop`) or full path; ShellExecute resolves App Paths registry entries |
| Code sandbox says "No system Python found" | the packaged app intentionally doesn't run scripts on itself — install Python 3 (or `py` launcher) for the `run_code`/skills sandbox |
| Antivirus flags the exe | UPX is disabled; rebuild yourself or sign the binary |
| High RAM | Settings → Model → `qwen2.5:3b`; Energy mode → saver; ears whisper stays `auto` |

## 8. Known limitations (honest)

- `Vidit.exe` produced by **CI**; this Linux dev environment **cannot execute
  Windows binaries**, so an interactive Windows 11 smoke test is
  **NOT VERIFIED IN THIS ENVIRONMENT** — the GitHub Actions workflow performs
  automated packaging checks (`--version`, `--doctor` exit codes, asset
  presence) on real `windows-latest` runners instead.
- No code-signing certificate → SmartScreen prompt on first run.
- The code-execution sandbox and skills smoke-test need a system Python in the
  packaged build (documented, honest failure otherwise).
- Piper TTS needs a standalone `piper.exe`; pyttsx3 (Windows SAPI) is the default.
- Photoshop/Illustrator/WhatsApp: launch + generic desktop control only (see §5).
- Window listing shows titles/app names only — no pixel-level window content
  beyond single screenshots behind permission.

## 9. Security notes (never removed for packaging)

- **Guardian** risk classification: 🟢 auto / 🟡 ask / 🔴 always-ask (money,
  passwords, mass deletion, installs, sharing sensitive data — asked EVERY
  time, a saved "always allow" never covers them).
- Every tool call goes through `Permissions.check`; decisions, grants and the
  action log are in the local DB; `python -m vidit --doctor` (or the doctor in
  source mode) prints recent autonomous actions.
- STOP (`Ctrl+Alt+S`) always wins — chains abort between steps.
- No cloud services, no telemetry: everything local except optional Ollama on
  127.0.0.1 and the one-time whisper model download.

## 10. Verification status of this build (see final report)

| Item | Status |
| --- | --- |
| Test suite (this repo, Python 3.11) | **VERIFIED** — 42 passed / 0 failed / 0 skipped |
| Spec logic (hidden imports, datas, frozen entry) | **VERIFIED** via a Linux PyInstaller build of the same spec running `--doctor` from the frozen bundle |
| Windows CI build + packaging checks | **VERIFIED BY CI DESIGN** — runs automatically on `windows-latest`; check the latest `build-windows` run |
| Windows 11 interactive smoke (GUI, mic, voice) | **NOT VERIFIED IN THIS ENVIRONMENT** |
| Photoshop / Illustrator / WhatsApp automation | **NOT VERIFIED** (launch + generic control only, §5) |
| Mouse/keyboard control | **VERIFIED IN SOURCE** (pyautogui behind Guardian, budgeted); runtime on Win11 **NOT VERIFIED HERE** |
