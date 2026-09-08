# Vidit — GUI Overhaul Report: "Cyber-Glass" Settings + Visual System

Date: 2026-09-08 · Work tree only (not committed) · Tests: **30 passed** · 100% offline, PyQt5 only

---

## A. Health pass (quick — confirmed, minimal diffs)

| Check | Result |
|---|---|
| `ears.py` preload + `_model_lock` + `_model_ready` + compute fallback `int8 → int8_float16 → float32 → default` + `cpu_threads=4/num_workers=1` | ✅ intact (lines 48–170) |
| `core.py::start_listening()` calls `ears.preload()` on the main thread before `ears.start()` | ✅ intact |
| Ears public API | ✅ unchanged |
| Crashes / leaks found this round | none new — the tree already carries the previous round's fixes (voice COM init, eyes `_cap_lock`, chat worker reaping, HUD/dashboard timer pauses) |

---

## B. What changed (file → one-line reason)

| File | Change |
|---|---|
| `vidit/ui/settings_panel.py` | **Full redesign** (concept-matched): left neon-icon nav + stacked pages; new **General** profile page (avatar card, mode chips, gradient sliders, neon toggles, avatar carousel, name/language/timezone, status toast + Save Changes); Voice tab regrouped in glass cards; Data & Reset restyled; old General keys preserved on a new **System** page. |
| `vidit/ui/widgets.py` | New reusable cyber-glass kit: `GlassCard`, `NeonToggle` (animated), `GradientSlider` (painted gradient groove + neon handle), `ModeChip`, `AvatarCircle`/`AvatarPicker` (glowing selection ring), `StatusToast`, `OnlinePill`; `AVATAR_STYLES` registry + local asset loader with painted gradient-glyph fallback. |
| `vidit/ui/themes.py` | Cyberpunk palette rebased to the concept colours (`#00e5ff` / `#7b5cff` / `#a855f7`, glass `rgba` panels, `glow` key); stylesheet extended: `glassCard`/`softCard` frames, `navList` neon selection, `modeChip` checked state, gradient primary button, `onlinePill`, `quote`/`tagline` labels, `danger` button, transparent scroll areas. |
| `vidit/ui/chat_window.py` | Mic button **disabled with a clear message + tooltip** when speech isn't installed (no dead button). (Mic idle/listening/processing/error states from the previous round remain.) |
| `vidit/config.py` | 5 new keys wired through `DEFAULTS` (below); everything else reuses existing keys. |
| `vidit/ui/assets/avatars/*.png` | 4 local avatar portraits (nebula/aurora/ember/frost), 256×256, ~80 KB each — generated once, shipped in the repo, no runtime downloads. |

## New config keys → UI control mapping

| Key (section) | Control | Notes |
|---|---|---|
| `personal.companion_mode` (`chill\|balanced\|energetic`) | Mode chips | Preset: personality overlay (`witty`/`playful`), `model.temperature`, `model.max_tokens`, quote |
| `general.auto_continue` | "Auto-Continue" NeonToggle | behaviour flag (prompt layer can consume it later) |
| `general.timezone` | Time zone combo (editable) | `"auto"` = system zone |
| `appearance.avatar_style` | Avatar carousel + big portrait + header icon | id from `AVATAR_STYLES` |
| (existing) `model.max_tokens` / `model.temperature` | Response Length / Creativity sliders | overwritten by mode preset only while untouched |
| (existing) `personal.memory_preferences.remember_everything` | Memory toggle | |
| (existing) `autonomy.proactive_checkins` | Proactive Suggestions toggle | |
| (existing) `personal.user_name`, `general.language` | Display name / Language | |

**General page semantics:** draft-until-**Save Changes** (writes config, emits `settings.changed` per key, shows the green toast *"Settings saved. Vidit is now even more you."*). Every other page keeps the original instant-save behaviour.

**Companion Mode presets:** chill → temp 0.55 / 768 tokens / calm tone · balanced → 0.8 / 1024 · energetic → 1.1 / 1536. Picking a chip arms the preset; touching a slider means your value wins on Save (and the preset is never clobbered by stale slider positions — saving re-syncs the sliders visually).

## Before → After (Settings, General)

**Before:** a flat `QTabWidget` form — 8 equal tabs, checkbox/combobox rows, no identity, no feedback; voice settings buried in one undifferentiated list.

**After** (see `screenshots/settings_general.png`): dark glass window; header with avatar icon, **Vidit**, green **ONLINE** pill and tagline; left nav with neon icons and a cyan selected rail; the General page shows a **glowing circular avatar portrait** with its own ONLINE pill and a mode quote, **Chill / Balanced (recommended) / Energetic** chips (selected = cyan ring), **Response Length** and **Creativity Level** gradient sliders with live "Balanced · ~1024 tokens" / "Balanced · 0.80" labels, animated **Memory / Proactive Suggestions / Auto-Continue** neon toggles, an **avatar carousel** (4 styles, neon selection halo), name/language/timezone fields, and a bottom bar with status toast + gradient **Save Changes** button. Voice page: three glass groups (Hearing/Speaking/Audio) + live ears/voice status + Test voice.

## Verification
- `pytest`: **30 passed** (unchanged suite; Ears API untouched).
- Offscreen full-app smoke: theme sweep, 11 nav pages, General draft/save flow (mode preset + slider precedence + toggles + avatar + name), mic ON builds Whisper on MainThread only with int8→int8_float16 fallback, mic OFF, stt_model hot-release, clean quit.
- No UI-thread freezes added: all heavy work stays on existing workers; the only blocking call remains the intentional main-thread Whisper preload (painted feedback first).

## Still needs polish / assets
1. **Avatar art**: current four portraits are generated placeholders — swap higher-res/branded art into `vidit/ui/assets/avatars/<id>.png` anytime; a 5th style ("Sigil") exists as a painted fallback with no file yet.
2. **Nav icon glyphs** are emoji (render natively on Windows 11; the offscreen sandbox shows boxes). Swap to painted/SVG icons if pixel-perfect cross-platform parity matters.
3. `companion_mode` currently presets temperature/tokens/personality — the system-prompt tone overlay can be deepened in `personality.py` later (deliberately not touched per constraints).
4. `general.timezone` is stored but the scheduler still uses local time; wiring reminders to it is a natural follow-up.
5. High-contrast theme overrides the new glass look by design; a light-glass variant could be added later.
