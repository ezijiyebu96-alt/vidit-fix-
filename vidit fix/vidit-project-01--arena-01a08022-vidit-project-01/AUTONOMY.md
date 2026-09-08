# AUTONOMY.md — Vidit's Real Autonomous Laptop layer

You → **Vidit Agent** → Computer (Apps · Browser · Files · Terminal)

Vidit now works in a **See → Think → Act → Verify** loop:

1. **See** — read/search your files, watch a folder for new arrivals, (optionally)
   look at the screen once (screenshot + window title + OCR if installed).
2. **Think** — your *goals* live in his memory database (`goals` table) and a
   lightweight planner turns a goal into a chain of **1–5 tool steps** (no more).
3. **Act** — every step runs through the same permissioned tools he uses in chat.
4. **Verify** — each step's result is checked; a failed step is retried **once**;
   if it still fails he tells you honestly instead of pretending.

Everything is **100 % offline** (the planner uses the local Ollama model; with no
model he falls back to safe defaults like folder tidy-up briefs).

---

## What he can do ALONE (🟢 green-light, no asking)

- Read, search, list files; read PDFs/DOCX/XLSX with the local file stack
- Open apps / folders / URLs (`open` tool)
- Create folders, save drafts (email drafts, notes, reports) inside his own folder
- Summarise documents; build local reports
- Run due goals: "brief me every morning", "when a PDF lands in Downloads,
  summarise it" — he runs them on the heartbeat **without re-asking** every time
- Organise Downloads/Desktop **after you approve the plan once** per session

If you set **Settings → Autonomy level = `auto`**, green-light actions above stop
prompting entirely ("I can do this automatically"). The default `standard` level
asks once per new kind of action, then remembers for the session.

## What he ASKS before doing (🟡 "I need your OK")

- Moving/renaming/deleting your files (organise always shows the exact move plan
  first — a dry-run — and asks; nothing is touched before you say yes)
- Sending anything (email is **draft-only**; he never sends — he saves a `.eml`
  draft and tells you where it is)
- Installing, changing system settings, uploads, posting online
- Code execution, screenshots/screen control

## What ALWAYS asks — no setting can silence it (🔴)

Mass deletion, money/purchases, passwords/security settings, sharing sensitive
data, installers. Even a past "always allow" or a session grant **never** covers
these; he asks **every single time**. Restricting an ability in Privacy settings
or pressing **STOP** overrides everything.

## The STOP switch (always wins)

- **Ctrl+Alt+S** works from any Vidit window (Esc still stops the chat reply).
- STOP instantly: halts speech, denies tool permission checks, and aborts any
  running autonomous chain **between steps** (the current step finishes, nothing
  new starts). The goal is marked *paused* — not lost.
- `Vidit.stop()` (used by the orb/CLI too) also pauses all standing goals via
  `Vidit.cancel_autonomy()` if you want a full quiet period; say "cancel goal N"
  (or `cancel_goal`) to drop one permanently.

## Goals — examples

Say any of these in chat (the planner picks them up) or use the tools directly:

| You say | He stores |
| --- | --- |
| "Every morning at 8, brief me on my Downloads folder" | `daily 08:00` goal |
| "When a PDF lands in Downloads, summarize it" | `watch <Downloads>` goal |
| "Every hour check for duplicate files in Projects" | `interval 3600` goal |
| "Prepare me for tomorrow" | `once` goal, runs on his next heartbeat pass |

Tools exposed to the model: `set_goal`, `list_goals`, `cancel_goal`,
`organize_folder`, `find_duplicates`, `summarize_new_file`, `screen_look`,
`computer_act`, `draft_email`. `python -m vidit --doctor` shows pending goals and
the last autonomous actions ("last autonomous actions" log).

## Enabling computer control (Phase 2 — OFF by default)

1. `pip install pyautogui` (and optionally `pip install pytesseract` for OCR of
   screenshots; screenshots themselves need no new dependency).
2. Settings → **Computer control (mouse/keyboard)** → on. It stays off after a
   reset unless you turn it on again.
3. Every use still asks (🟡), is capped at **5 actions / 30 s per task**, and
   pyautogui's FAILSAFE (fling the mouse to a screen corner) is an extra
   emergency brake on top of STOP.

Browser light / email: opening URLs is 🟢; form-filling or downloads are 🟡 and
only via the visible tools; there is **no** unrestricted purchasing path — the
draft-email flow never sends by itself, and unconfigured integrations say
"not configured" instead of faking success.

## Config keys (all under `autonomy.` in Settings/JSON)

| Key | Default | Meaning |
| --- | --- | --- |
| `autonomy.proactive` | `true` | may run due goals on his own heartbeat |
| `autonomy.level` | `standard` | `standard` asks once per action kind; `auto` runs 🟢 actions silently |
| `autonomy.computer_control` | `false` | mouse/keyboard automation master switch |
| `autonomy.max_steps` | `5` | max tool steps in one autonomous chain |
| `autonomy.self_modification` | `ask` | unchanged (new skills still ask) |
| `autonomy.proactive_checkins` | `true` | unchanged (idle check-ins) |

Low-RAM notes: the heartbeat's autonomy check is one indexed SQL query per
minute tick; there are **no** tight screen-capture loops (a screenshot happens
only when you or a goal explicitly ask, one frame at a time); energy-saver mode
halves all heartbeat cadences, autonomy included.

## Roadmap (Phase 3 — designed, not built)

- **J — Triggers:** time (done), folder-watch (done), app-open trigger (hook
  `gaming.detect()`'s foreground-title polling → `goal.trigger == "app"` with
  `trigger_arg` = window-title regex), condition triggers (e.g. "if battery < 20 %
  pause big goals" — a `condition` row in the same `goals` table evaluated in
  `AutonomyEngine._is_due`).
- **K — CV action loop:** screen → vision → click with **verification screenshot
  after each click** (`ComputerControl.act` already returns per-action results;
  the loop adds `screen_look` between actions and an LLM "did it work?" check,
  still capped by `max_steps`). Needs OCR/pyautogui installed; stays 🔴/🟡.
- **L — Office macro automation:** generate `.otd`/VBA or python-docx/openpyxl
  macros as *drafts* in `exports/drafts/`, run only after 🟡 approval via the
  existing code sandbox, never touching macro security settings.
