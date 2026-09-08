"""Tests for Vidit's organs. Run with:  python -m pytest -q"""
from __future__ import annotations

import json
import sys
import threading
import time
import types
from pathlib import Path

import pytest

from vidit.brain.llm import LLMClient, parse_json_block, split_thinking
from vidit.brain.memory import MemoryStore
from vidit.brain.learning import Learner
from vidit.config import Config
from vidit.constitution import EMOTIONS, FIRST_WORDS
from vidit.core import Vidit
from vidit.events import EventBus
from vidit.guardian import Capability, Decision, Permissions
from vidit.soul.emotions import EmotionEngine, extract_reflection
from vidit.tools import ToolRegistry
from vidit.tools.canvas import Canvas
from vidit.tools.system import parse_when
from vidit.senses.ears import Ears


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    return tmp_path / "vidit_home"


@pytest.fixture()
def vidit(home: Path) -> Vidit:
    v = Vidit(home=home, event_bus=EventBus(), prompter=lambda r: Decision.ALLOW_SESSION, quiet=True)
    v.config.set("model.backend", "echo")
    yield v
    v.sleep()


# ----------------------------------------------------------------- config
def test_config_defaults_and_persistence(home: Path) -> None:
    cfg = Config(home)
    assert cfg.get("model.primary_model") == "qwen2.5:7b"
    cfg.set("personal.user_name", "Aarav")
    again = Config(home)
    assert again.user_name == "Aarav"
    assert (home / "settings.json").exists()


def test_config_survives_corruption(home: Path) -> None:
    cfg = Config(home)
    cfg.path.write_text("{broken")
    cfg2 = Config(home)
    assert cfg2.get("general.wake_word") == "vidit"


# ----------------------------------------------------------------- events
def test_event_bus_wildcards() -> None:
    bus = EventBus()
    seen = []
    bus.on("message.*", lambda t, p: seen.append(t))
    bus.emit("message.reply", x=1)
    bus.emit("other", x=2)
    assert seen == ["message.reply"]


# --------------------------------------------------------------- emotions
def test_emotions_respond_to_words(home: Path) -> None:
    home.mkdir(parents=True)
    eng = EmotionEngine(home / "emotions.json", event_bus=EventBus())
    eng.feel_user_message("I hate you, you are useless, I will delete you")
    st = eng.state()
    assert st.intensities["sad"] > 0.3 or st.intensities["anxious"] > 0.3
    eng.feel_user_message("Sorry bhai, I love you, thanks for everything ❤️")
    st2 = eng.state()
    assert st2.intensities["happy"] > st.intensities["happy"]
    assert st2.intensities["forgiving"] > 0.2


def test_emotions_miss_you_after_absence(home: Path) -> None:
    home.mkdir(parents=True)
    eng = EmotionEngine(home / "emotions.json", event_bus=EventBus())
    eng.last_user_contact = time.time() - 30 * 3600
    st = eng.state()
    assert st.intensities["missing_you"] > 0.3
    assert "missing" in eng.prompt_fragment()


def test_emotions_decay_and_persist(home: Path) -> None:
    home.mkdir(parents=True)
    eng = EmotionEngine(home / "emotions.json", event_bus=EventBus())
    eng.nudge("angry", 0.8)
    assert eng.state().intensities["angry"] > 0.5
    eng._last_update -= 5 * 3600  # pretend 5 hours passed
    assert eng.state().intensities["angry"] < 0.2
    eng.save()
    eng2 = EmotionEngine(home / "emotions.json", event_bus=EventBus())
    assert set(eng2.state().intensities) == set(EMOTIONS)


def test_reflection_tag_is_stripped() -> None:
    text, feel = extract_reflection('Hey! Great to hear. <feel>{"happy":0.2,"proud":0.1}</feel>')
    assert text == "Hey! Great to hear."
    assert feel == {"happy": 0.2, "proud": 0.1}


# ----------------------------------------------------------------- memory
def test_memory_remember_recall_forget(home: Path) -> None:
    mem = MemoryStore(home / "m.db")
    mem.remember("The user's favorite game is Valorant.", "preference", 0.7)
    mem.remember("The user lives in Agra.", "fact", 0.8)
    hits = mem.recall("what game does he play, valorant?")
    assert hits and "Valorant" in hits[0].content
    assert mem.forget("lives in Agra") == 1
    assert all("Agra" not in m.content for m in mem.all_memories())
    mem.close()


def test_memory_favorites_and_people(home: Path) -> None:
    mem = MemoryStore(home / "m.db")
    mid = mem.remember("The day we built our first project together.", "moment", 0.6)
    mem.set_favorite(mid)
    assert mem.favorites()[0].id == mid
    mem.remember_person("Rahul", "friend", "loves Valorant")
    mem.remember_person("Rahul", notes="lives next door")
    p = mem.person("rahul")
    assert p and p["interactions"] == 2 and "next door" in p["notes"]
    mem.close()


def test_conversation_features(home: Path) -> None:
    mem = MemoryStore(home / "m.db")
    cid = mem.new_conversation("Test")
    m1 = mem.add_message(cid, "user", "hello there")
    m2 = mem.add_message(cid, "assistant", "hi!", reply_to=m1)
    mem.react(m2, "❤️")
    mem.pin(m1)
    mem.edit_message(m1, "hello there, edited")
    assert mem.messages(cid)[0]["edited"] == 1
    assert mem.pinned()[0]["id"] == m1
    assert len(mem.thread(m1)) == 2
    assert mem.search_messages("edited")
    mem.move_conversation(cid, "projects")
    assert mem.folders() == ["projects"]
    data = mem.export()
    assert data["messages"] and data["conversations"]
    mem.close()


# --------------------------------------------------------------- learning
def test_learner_patterns(home: Path) -> None:
    mem = MemoryStore(home / "m.db")
    learner = Learner(mem)
    out = learner.learn_from_user("My name is Aarav. I love biryani and my sister is Priya. I want to become a game developer.")
    joined = " ".join(out["learned"])
    assert "Aarav" in joined and "biryani" in joined and "Priya" in joined and "game developer" in joined
    assert mem.person("Priya")["relation"] == "sister"
    out = learner.learn_from_user("No, my name is Aarav Sharma")
    assert out["corrections"]
    names = [m.content for m in mem.all_memories("fact") if "name is" in m.content]
    assert names == ["The user's name is Aarav Sharma."]
    assert learner.understanding()["percent"] > 0
    assert learner.memory_map()["nodes"]
    mem.close()


def test_learner_ignores_non_names(home: Path) -> None:
    mem = MemoryStore(home / "m.db")
    learner = Learner(mem)
    learner.learn_from_user("i'm so tired today, I'm Fine honestly")
    assert not [m for m in mem.all_memories() if "name is" in m.content]
    mem.close()


# ------------------------------------------------------------------- llm
def test_llm_falls_back_to_echo(home: Path) -> None:
    cfg = Config(home)
    cfg.set("model.host", "http://127.0.0.1:1")  # nothing listens here
    client = LLMClient(cfg.get)
    res = client.chat([{"role": "system", "content": "The user's name: Aarav."}, {"role": "user", "content": "hello"}])
    assert res.backend == "echo" and "Aarav" in res.text
    assert client.status()["backend"] == "echo"


def test_llm_helpers() -> None:
    thinking, answer = split_thinking("<think>reasoning here</think>The answer")
    assert thinking == "reasoning here" and answer == "The answer"
    assert parse_json_block('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_block("junk [1, 2] junk") == [1, 2]
    assert parse_json_block("nothing", default=[]) == []


# ------------------------------------------------------------- permissions
def test_permissions_policies(home: Path) -> None:
    cfg = Config(home)
    asked = []

    def prompter(req):
        asked.append(req.capability)
        return Decision.ALLOW_SESSION

    perms = Permissions(cfg, event_bus=EventBus(), prompter=prompter)
    assert perms.check(Capability.INTERNET, "research")
    assert perms.check(Capability.INTERNET, "research")  # cached for session
    assert asked == [Capability.INTERNET]
    perms.restrict(Capability.INTERNET)
    assert not perms.check(Capability.INTERNET, "research")
    cfg.set("privacy.private_folders", [str(home / "secret")])
    assert not perms.check(Capability.READ_FILES, "peek", target=str(home / "secret" / "x.txt"))
    assert perms.check(Capability.READ_FILES, "own", target=str(home / "memory"))
    perms.stop()
    assert not perms.check(Capability.READ_FILES, "own", target=str(home / "memory"))
    perms.resume()
    assert perms.check(Capability.READ_FILES, "own", target=str(home / "memory"))


def test_permissions_deny_by_default_without_prompter(home: Path) -> None:
    perms = Permissions(Config(home), event_bus=EventBus())
    assert not perms.check(Capability.CAMERA, "look")


# ----------------------------------------------------------------- tools
def test_tool_registry_parsing() -> None:
    reg = ToolRegistry()
    assert reg.parse_call("Sure.\n[[tool: web_search | best laptops]]") == ("web_search", "best laptops")
    assert reg.parse_call("no tool here") is None


def test_parse_when() -> None:
    now = time.time()
    t = parse_when("remind me in 20 minutes to drink water")
    assert t and abs(t.timestamp() - (now + 1200)) < 5
    assert parse_when("call mom at 7pm").hour == 19
    assert parse_when("no time here") is None


def test_canvas(tmp_path: Path) -> None:
    c = Canvas(tmp_path / "canvas")
    c.write_note("Ideas", "build a robot")
    assert "build a robot" in c.read_note("Ideas")
    mm = c.mind_map("Plan", {"Maths": ["algebra"], "Physics": ["optics"]})
    assert mm.startswith("mindmap")
    board = c.add_task("study", "finish maths")
    board = c.move_task("study", "finish maths", "done")
    assert board["done"] == ["finish maths"]
    assert len(c.list_items()) == 3


# ------------------------------------------------------------ self repair
def test_self_repair_heals_corruption(vidit: Vidit) -> None:
    vidit.wake_up()
    vidit.chat("My name is Aarav")
    vidit.repair.backup("manual")
    vidit.memory.close()
    vidit.memory.path.write_bytes(b"garbage" * 50)
    (vidit.config.home / "settings.json").write_text("{nope")
    report = vidit.repair.health_check(vidit.llm.status())
    assert not report.ok
    healed = vidit.repair.heal(report, vidit.llm.status())
    assert healed.ok and healed.repaired
    assert any("Aarav" in m.content for m in vidit.memory.all_memories())


def test_skill_lifecycle(vidit: Vidit) -> None:
    ok = vidit.create_skill("shout", "Upper-cases text", "return (args or 'hi').upper()")
    assert "installed" in ok
    assert vidit.run_skill("shout", "hello") == "HELLO"
    assert any(s["name"] == "shout" for s in vidit.repair.list_skills())
    bad = vidit.create_skill("evil", "bad", "import subprocess\nreturn 'x'")
    assert "may not import" in bad or "forbidden" in bad
    crash = vidit.create_skill("crash", "crashes", "return 1/0")
    assert "smoke test failed" in crash
    # a skill that crashes at run time is quarantined, never repeated
    vidit.create_skill("flaky", "crashes on real args", "if args:\n    raise RuntimeError('boom')\nreturn 'ok'")
    assert "quarantined" in vidit.run_skill("flaky", "x")
    assert "flaky" in vidit.repair.quarantine


# ------------------------------------------------------------------- core
def test_first_words_and_learning(vidit: Vidit) -> None:
    greeting = vidit.wake_up()
    assert greeting == FIRST_WORDS
    reply = vidit.chat("Hi, my name is Aarav and I live in Agra")
    assert reply.text
    assert any("Aarav" in l for l in reply.learned)
    assert vidit.config.get("personal.user_name") == "Aarav"
    assert reply.emotion in EMOTIONS
    dash = vidit.soul_dashboard()
    assert dash["understanding"]["percent"] > 0
    assert dash["memory"]["favorites"]  # birth moment


def test_second_session_is_not_first_words(home: Path) -> None:
    v = Vidit(home=home, event_bus=EventBus(), quiet=True)
    v.config.set("model.backend", "echo")
    assert v.wake_up() == FIRST_WORDS
    v.sleep()
    v2 = Vidit(home=home, event_bus=EventBus(), quiet=True)
    v2.emotions.last_user_contact = time.time() - 10 * 3600
    greeting = v2.wake_up()
    assert greeting != FIRST_WORDS and "back" in greeting
    v2.sleep()


def test_stop_word(vidit: Vidit) -> None:
    vidit.wake_up()
    reply = vidit.chat("stop")
    assert "Stopped" in reply.text
    assert vidit.permissions.stopped
    vidit.chat("ok continue")
    assert not vidit.permissions.stopped


def test_tool_hop_through_model(vidit: Vidit, monkeypatch) -> None:
    """Simulate the model asking for a tool, then answering with its result."""
    vidit.wake_up()
    calls = {"n": 0}

    def fake_chat(messages, *, model, options, stream_cb=None):
        from vidit.brain.llm import LLMResult

        calls["n"] += 1
        if calls["n"] == 1:
            return LLMResult(text="[[tool: system_stats | ]]", model="fake")
        last = messages[-1]["content"]
        assert "[tool result]" in last and "cpu_count" in last
        return LLMResult(text="Your CPU is fine. <feel>{\"proud\":0.2}</feel>", model="fake")

    monkeypatch.setattr(vidit.llm.echo, "chat", fake_chat)
    reply = vidit.chat("what are my system stats?")
    assert reply.tools_used == ["system_stats"]
    assert reply.text == "Your CPU is fine."


def test_reset_and_export(vidit: Vidit) -> None:
    vidit.wake_up()
    vidit.chat("my name is Aarav")
    path = vidit.export_everything()
    data = json.loads(path.read_text())
    assert data["memory"]["memories"]
    vidit.reset()
    assert vidit.memory.memory_count() == 0
    assert vidit.self_model.data["awakened"] is False


def test_friend_introduction_and_reminders(vidit: Vidit) -> None:
    vidit.wake_up()
    reply = vidit.chat("This is my friend Karan, he loves BGMI")
    assert any("Karan" in l for l in reply.learned)
    assert vidit.memory.person("Karan")["notes"].startswith("he loves")
    rid = vidit.memory.add_reminder("drink water", time.time() - 1)
    due = vidit.memory.due_reminders()
    assert due and due[0]["id"] == rid


# ------------------------------------------------------------------- ears
def test_wake_word_stripping(home: Path) -> None:
    cfg = Config(home)
    ears = Ears(cfg.get, home / "models", event_bus=EventBus())
    text, woke = ears.strip_wake_word("Hey Vidit, what's the time?")
    assert woke and text == "what's the time"
    text, woke = ears.strip_wake_word("what's the time?")
    assert not woke
    cfg.set("general.wake_word", "jarvis")
    assert ears.strip_wake_word("ok jarvis open notes")[1]


# -------------------------------------------- ears preload / model_ready path
class _FakeSegment:
    text = " hey vidit what time is it "


class _FakeWhisperModel:
    """Records construction details; rejects int8 to exercise the fallback."""

    calls: list = []

    def __init__(self, size, device=None, compute_type=None, download_root=None,
                 cpu_threads=None, num_workers=None):
        _FakeWhisperModel.calls.append({
            "thread": threading.current_thread().name, "size": size, "device": device,
            "compute_type": compute_type, "cpu_threads": cpu_threads,
            "num_workers": num_workers,
        })
        if compute_type == "int8":
            raise RuntimeError("this machine cannot do int8")

    def transcribe(self, audio, language=None, vad_filter=False, beam_size=None):
        return (iter([_FakeSegment()]), None)


@pytest.fixture()
def fake_ears_deps(monkeypatch) -> type:
    """Fake faster_whisper + sounddevice so no download and no mic is needed."""
    _FakeWhisperModel.calls = []
    fw = types.ModuleType("faster_whisper")
    fw.WhisperModel = _FakeWhisperModel
    sd = types.ModuleType("sounddevice")
    sd.InputStream = object
    monkeypatch.setitem(sys.modules, "faster_whisper", fw)
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    return _FakeWhisperModel


def test_ears_preload_model_ready_and_worker_never_loads(home: Path, fake_ears_deps: type) -> None:
    pytest.importorskip("numpy")
    import numpy as np

    cfg = Config(home)
    ears = Ears(cfg.get, home / "models", event_bus=EventBus())
    assert ears.available()
    assert ears.status()["model_ready"] is False

    # The live-mic path must NEVER construct the model (the Windows crash bug).
    assert ears._transcribe_array(np.zeros(16000, dtype=np.float32)) == ""
    assert fake_ears_deps.calls == []

    # preload() on the calling (main) thread: int8 fails -> falls back to
    # int8_float16 (two constructor attempts, one successful model).
    assert ears.preload() is True
    assert ears.status()["model_ready"] is True
    assert len(fake_ears_deps.calls) == 2
    assert [c["compute_type"] for c in fake_ears_deps.calls] == ["int8", "int8_float16"]
    assert all(c["thread"] == threading.main_thread().name for c in fake_ears_deps.calls)
    good = fake_ears_deps.calls[-1]
    assert good["cpu_threads"] in (2, 4)  # adaptive: 2 on low-RAM/low-core machines
    assert good["num_workers"] == 1

    # preload is idempotent — no further construction attempts.
    ears.preload()
    assert len(fake_ears_deps.calls) == 2

    # reload_model() releases the model; the worker still refuses to rebuild.
    ears.reload_model()
    assert ears.status()["model_ready"] is False
    assert ears._transcribe_array(np.zeros(16000, dtype=np.float32)) == ""
    assert len(fake_ears_deps.calls) == 2


def test_ears_transcribe_file_routes_through_preload(home: Path, fake_ears_deps: type) -> None:
    pytest.importorskip("numpy")
    cfg = Config(home)
    ears = Ears(cfg.get, home / "models", event_bus=EventBus())
    out = ears.transcribe_file(Path("clip.wav"))
    assert out == "hey vidit what time is it"
    assert ears.status()["model_ready"] is True
    assert all(c["thread"] == threading.main_thread().name for c in fake_ears_deps.calls)


# ------------------------------------------------- low-RAM model selection
def _ram(monkeypatch: pytest.MonkeyPatch, total_gb: float) -> None:
    import psutil

    class _VM:
        total = int(total_gb * 1e9)

    monkeypatch.setattr(psutil, "virtual_memory", lambda: _VM())


def test_low_ram_model_selection(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """tiny/base on small machines; 'small' stays only with enough RAM;
    explicit non-'small' choices are never second-guessed."""
    pytest.importorskip("psutil")
    from vidit.senses.ears import Ears as _Ears

    cfg = Config(home)

    # 4 GB machine: the legacy default "small" is downgraded to "base", 2 threads
    _ram(monkeypatch, 4.0)
    ears = Ears(cfg.get, home / "models", event_bus=EventBus())
    assert ears._resolve_model_size()[0] == "base"
    assert ears._resolve_model_size()[1] == 2

    # 2 GB machine with "auto": tiny
    _ram(monkeypatch, 2.0)
    cfg.set("voice.stt_model", "auto")
    ears = Ears(cfg.get, home / "models", event_bus=EventBus())
    assert ears._resolve_model_size()[0] == "tiny"

    # 16 GB machine with "auto": small; threads follow the core-count guard
    _ram(monkeypatch, 16.0)
    ears = Ears(cfg.get, home / "models", event_bus=EventBus())
    size, threads, auto = ears._resolve_model_size()
    import os as _os

    expected_threads = 2 if (_os.cpu_count() or 4) <= 2 else 4
    assert (size, threads, auto) == ("small", expected_threads, True)

    # 16 GB with an explicit pin: respected as-is, not "auto"
    cfg.set("voice.stt_model", "base")
    ears = Ears(cfg.get, home / "models", event_bus=EventBus())
    size, _threads, auto = ears._resolve_model_size()
    assert (size, auto) == ("base", False)

    # unload-on-stop: low RAM auto-unloads, high RAM keeps it, explicit wins
    _ram(monkeypatch, 4.0)
    cfg.set("voice.stt_model", "auto")
    ears = Ears(cfg.get, home / "models", event_bus=EventBus())
    ears._effective_model = "tiny"
    ears._model = object()
    ears._model_ready.set()
    ears.stop()
    assert ears._model is None and not ears._model_ready.is_set()

    _ram(monkeypatch, 16.0)
    ears = Ears(cfg.get, home / "models", event_bus=EventBus())
    ears._model = object()
    ears._model_ready.set()
    ears.stop()
    assert ears._model is not None and ears._model_ready.is_set()

    cfg.set("voice.unload_model_when_idle", True)
    ears = Ears(cfg.get, home / "models", event_bus=EventBus())
    ears._model = object()
    ears._model_ready.set()
    ears.stop()
    assert ears._model is None  # explicit override beats plenty-of-RAM


# ------------------------------------------------------------- autonomy
def test_goal_scheduling_math() -> None:
    from vidit.autonomy import next_run_for

    now = time.time()
    daily = next_run_for("daily", "08:00", now)
    assert daily > now  # never in the past
    import datetime as dt

    nxt = dt.datetime.fromtimestamp(daily)
    assert (nxt.hour, nxt.minute) == (8, 0)
    late = next_run_for("daily", "08:00", dt.datetime(2026, 1, 1, 23, 0).timestamp())
    assert dt.datetime.fromtimestamp(late).day == 2  # rolls to tomorrow
    soon = next_run_for("interval", "600", now)
    assert abs(soon - (now + 600)) < 2
    assert next_run_for("interval", "1", now) >= now + 300  # 5-min floor
    assert next_run_for("once", "", 0) == 0


def test_goal_lifecycle_and_tick(vidit: Vidit) -> None:
    vidit.llm.json = lambda *a, **k: [{"tool": "list_goals", "args": "", "why": "check"}]
    gid = vidit.memory.add_goal("brief me", "once", "", next_run=time.time() - 10)
    reports = vidit.autonomy.tick()
    assert len(reports) == 1 and "Goal #" in reports[0]
    goal = vidit.memory.goal(gid)
    assert goal["status"] == "done" and goal["last_run"]
    assert vidit.autonomy.tick() == []  # nothing due any more
    assert any(a["action"].startswith("step") for a in vidit.memory.recent_actions())


def test_daily_goal_reschedules(vidit: Vidit) -> None:
    vidit.llm.json = lambda *a, **k: []
    vidit.memory.add_goal("morning brief", "daily", "23:59", next_run=time.time() - 10)
    vidit.autonomy.tick()  # runs; plan empty + not a file goal → report only
    goal = vidit.memory.goals()[0]
    assert goal["status"] == "active"
    assert goal["next_run"] > time.time()  # rescheduled to tomorrow


def test_risk_levels_guardian_block(home: Path) -> None:
    from vidit.guardian import PermissionRequest
    from vidit.guardian.permissions import risk_level

    assert risk_level(Capability.READ_FILES, "look around") == "auto"
    assert risk_level(Capability.WRITE_FILES, "save a note", target=str(home / "x.txt")) == "auto"
    assert risk_level(Capability.WRITE_FILES, "save a note") == "ask"
    (home / "lots").mkdir(parents=True)
    assert risk_level(Capability.DELETE_FILES, "clean up", target=str(home / "lots")) == "always"
    assert risk_level(Capability.DELETE_FILES, "remove my draft", target=str(home / "x.txt")) == "ask"
    assert risk_level(Capability.INTERNET, "enter my password somewhere") == "always"

    asked = []

    def prompter(req: PermissionRequest) -> Decision:
        asked.append(req.capability)
        return Decision.ALLOW_ALWAYS  # user always says yes — still must be ASKED

    cfg = Config(home)
    perms = Permissions(cfg, event_bus=EventBus(), prompter=prompter)
    # 🔴 bypasses session grants AND never persists an "always" policy:
    assert perms.check(Capability.DELETE_FILES, "clean up", target=str(home / "lots"))
    assert perms.check(Capability.DELETE_FILES, "clean up", target=str(home / "lots"))
    assert asked == [Capability.DELETE_FILES, Capability.DELETE_FILES]  # asked EVERY time
    assert perms.policy(Capability.DELETE_FILES) != "always"

    # autonomy.level=auto covers 🟢 only — never 🟡/🔴:
    cfg.set("autonomy.level", "auto")
    assert perms.check(Capability.READ_FILES, "peek around")  # 🟢 automatic
    assert asked == [Capability.DELETE_FILES, Capability.DELETE_FILES]  # no prompt needed
    assert perms.check(Capability.WRITE_FILES, "make a file")  # 🟡 still asks
    assert asked[-1] == Capability.WRITE_FILES
    assert perms.check(Capability.DELETE_FILES, "clean up", target=str(home / "lots"))  # 🔴 still asks


def test_stop_cancels_chain(vidit: Vidit) -> None:
    from vidit.tools.base import Tool, ToolResult

    vidit.llm.json = lambda *a, **k: [{"tool": "autostop", "args": "", "why": ""},
                                      {"tool": "list_goals", "args": "", "why": ""}]

    def autostop(args: str, ctx) -> ToolResult:  # noqa: ANN001
        vidit.permissions.stop()  # user hits STOP mid-chain
        return ToolResult(True, "step done")

    vidit.tools.register(Tool("autostop", "", "", autostop))
    gid = vidit.memory.add_goal("do a thing", "once", "", next_run=time.time() - 10)
    report = vidit.autonomy.run_goal(vidit.memory.goal(gid))
    assert "Stopped" in report
    goal = vidit.memory.goal(gid)
    assert goal["status"] == "paused"
    actions = [a["action"] for a in vidit.memory.recent_actions()]
    assert actions == ["step 1: autostop", "chain_stopped"]  # step 2 never ran

    # A fresh goal after STOP is not executed while still stopped:
    vidit.memory.add_goal("another", "once", "", next_run=time.time() - 10)
    assert vidit.autonomy.tick() == []
    vidit.permissions.resume()
    vidit.llm.json = lambda *a, **k: []
    assert vidit.autonomy.tick()  # resume → goals flow again


def test_organize_dry_run_and_apply(tmp_path: Path) -> None:
    from vidit.autonomy import apply_organization, plan_organization

    folder = tmp_path / "downloads"
    folder.mkdir()
    for name in ("report.pdf", "photo.png", "song.mp3", "notes.txt"):
        (folder / name).write_text("data-" + name, encoding="utf-8")
    moves = plan_organization(folder)
    assert {Path(m["from"]).name for m in moves} == {"report.pdf", "photo.png", "song.mp3", "notes.txt"}
    assert sorted(p.name for p in folder.iterdir()) == ["notes.txt", "photo.png", "report.pdf", "song.mp3"]  # untouched
    done = apply_organization(folder, moves)
    assert len(done) == 4
    assert (folder / "Documents" / "report.pdf").read_text() == "data-report.pdf"
    assert (folder / "Images" / "photo.png").exists() and (folder / "Audio" / "song.mp3").exists()
    # no-clobber: planning again + applying must not overwrite
    (folder / "other.pdf").write_text("two", encoding="utf-8")
    apply_organization(folder, plan_organization(folder))
    assert (folder / "Documents" / "report.pdf").read_text() == "data-report.pdf"
    assert len(list((folder / "Documents").glob("*.pdf"))) == 2


def test_organize_tool_asks_first(home: Path, tmp_path: Path) -> None:
    from vidit.tools.base import ToolContext

    folder = tmp_path / "downloads"
    folder.mkdir()
    (folder / "a.pdf").write_text("x", encoding="utf-8")

    def make_ctx(perms) -> ToolContext:  # noqa: ANN001
        return ToolContext(MemoryStore(home / "m.db"), Config(home), perms, None, lambda s: None, [])

    from vidit.core import Vidit as _V  # noqa: F401  (ensure wiring imports fine)

    import vidit.autonomy as aut

    v = types.SimpleNamespace(memory=MemoryStore(home / "m.db"), config=Config(home),
                              permissions=Permissions(Config(home), event_bus=EventBus()),
                              llm=None, _status=lambda s: None)
    engine = aut.AutonomyEngine(v)
    tool = {t.name: t for t in aut.make_autonomy_tools(engine, None)}["organize_folder"]
    # No prompter → Guardian denies → dry-run report, files untouched:
    res = tool.run(str(folder), make_ctx(v.permissions))
    assert not res.ok and "WOULD" in res.output
    assert (folder / "a.pdf").exists() and not (folder / "Documents").exists()
    # User approves → moves happen:
    v.permissions = Permissions(Config(home), event_bus=EventBus(), prompter=lambda r: Decision.ALLOW_SESSION)
    res = tool.run(str(folder), make_ctx(v.permissions))
    assert res.ok and (folder / "Documents" / "a.pdf").exists()


def test_memory_upgrade_and_duplicates(tmp_path: Path) -> None:
    import sqlite3

    from vidit.autonomy import find_duplicates

    db = tmp_path / "old.db"
    with sqlite3.connect(db) as c:  # a pre-autonomy database
        c.execute("CREATE TABLE conversations (id INTEGER PRIMARY KEY, title TEXT)")

    mem = MemoryStore(db)  # must upgrade in place
    gid = mem.add_goal("watch downloads", "file", str(tmp_path))
    assert mem.goal(gid)["trigger"] == "file"
    mem.log_action(gid, "step 1: list_folder", "ok")
    assert mem.recent_actions()[0]["action"] == "step 1: list_folder"

    d = tmp_path / "files"
    d.mkdir()
    (d / "a.bin").write_bytes(b"same-content")
    (d / "b.bin").write_bytes(b"same-content")
    (d / "c.bin").write_bytes(b"different")
    groups = find_duplicates(d)
    assert len(groups) == 1 and len(groups[0]["files"]) == 2


# ------------------------------------------------------------- windows packaging
def test_sandbox_python_helper() -> None:
    from vidit.utils import find_sandbox_python

    runner = find_sandbox_python()
    assert runner and runner[-1] == "-I"
    # from source it must be the running interpreter (never empty)
    assert runner[0] != ""


def test_list_windows_platform_honest() -> None:
    import sys as _sys

    from vidit.tools.system import SystemControl

    wins = SystemControl.list_windows()
    if _sys.platform.startswith("win"):
        assert isinstance(wins, list)  # real enumeration on Windows
    else:
        assert wins == []  # honest empty list elsewhere


def test_windows_tool_gated_by_guardian(home: Path) -> None:
    import tempfile

    from vidit.tools.base import ToolContext
    from vidit.tools.system import SystemControl, make_system_tools

    perms = Permissions(Config(home), event_bus=EventBus())  # no prompter → deny
    ctx = ToolContext(MemoryStore(home / "m.db"), Config(home), perms, None, lambda s: None, [])
    tools = {t.name: t for t in make_system_tools(SystemControl(Path(tempfile.gettempdir())), home / "b")}
    res = tools["windows"].run("", ctx)
    assert not res.ok  # Guardian gate applies to the new tool


# ------------------------------------------------------------- wake / autostart
def test_apply_autostart_noop_from_source() -> None:
    from vidit.utils import apply_autostart

    assert apply_autostart("with_system") is False  # never touches registry from source


def test_apply_autostart_frozen_windows(monkeypatch, tmp_path: Path) -> None:
    import sys as _sys
    import types

    calls: list = []

    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_open_key(root, path, reserved, access):
        assert "Run" in path
        return FakeKey()

    fake = types.ModuleType("winreg")
    fake.HKEY_CURRENT_USER = 0x80000001
    fake.KEY_SET_VALUE = 0x0002
    fake.REG_SZ = 1
    fake.OpenKey = fake_open_key
    fake.SetValueEx = lambda key, name, res, typ, val: calls.append(("set", name, val))
    fake.DeleteValue = lambda key, name: calls.append(("del", name)) if name != "missing" else (_ for _ in ()).throw(FileNotFoundError())

    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(_sys, "frozen", True, raising=False)
    monkeypatch.setattr(_sys, "platform", "win32")

    from vidit.utils import apply_autostart

    assert apply_autostart("with_system", exe=r"C:\Apps\Vidit\Vidit.exe") is True
    assert calls[-1] == ("set", "Vidit", '"C:\\Apps\\Vidit\\Vidit.exe"')
    assert apply_autostart("manual") is True  # unregister path (FileNotFoundError tolerated)
    assert calls[-1] == ("del", "Vidit")


def test_ears_download_model_graceful(home: Path, monkeypatch) -> None:
    """Never touches the network: without faster-whisper it must return None;
    with it installed the real downloader is monkeypatched out."""
    from vidit.senses.ears import Ears

    cfg_get = lambda key, default=None: default  # noqa: E731
    ears = Ears(cfg_get, home / "models", event_bus=EventBus())
    assert ears.resolved_model_size() in ("tiny", "base", "small", "medium", "large-v3")
    try:
        import faster_whisper.utils as fwu  # noqa: F401
    except Exception:
        assert ears.download_model() is None  # deps missing -> graceful
        return

    def fake_dl(size, output_dir=None):
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "model.bin").write_bytes(b"x")
        return str(out)

    monkeypatch.setattr(fwu, "download_model", fake_dl)
    got = ears.download_model()
    assert got and got.endswith(f"mdl-{ears.resolved_model_size()}")
    assert ears.model_downloaded()  # preload() will now use the local folder


# ------------------------------------------------------------- crash-proof UI
def test_safe_slot_swallows_and_keeps_running() -> None:
    from vidit.utils import safe_slot

    @safe_slot
    def boom() -> None:
        raise RuntimeError("slot exploded")

    assert boom() is None  # must NOT raise — app stays alive

    @safe_slot
    def fine(x: int) -> int:
        return x * 2

    assert fine(21) == 42  # healthy slots still return values


def test_open_tool_website_fallback(home: Path) -> None:
    """'open youtube' (bare word) falls back to the website, never errors out."""
    import tempfile

    from vidit.tools.base import ToolContext
    from vidit.tools.system import SystemControl, make_system_tools

    perms = Permissions(Config(home), event_bus=EventBus(), prompter=lambda r: Decision.ALLOW_SESSION)
    ctx = ToolContext(MemoryStore(home / "m.db"), Config(home), perms, None, lambda s: None, [])
    tools = {t.name: t for t in make_system_tools(SystemControl(Path(tempfile.gettempdir())), home / "b")}
    res = tools["open"].run("youtube", ctx)
    assert res.ok, res.output  # never raises — degrades to a graceful message
    # headless CI boxes can't open anything; Windows/desktop lands on the site
    assert ("youtube.com" in res.output or "Opened" in res.output
            or "Couldn't" in res.output), res.output


def test_bubble_safe_renders_broken_messages() -> None:
    """A message that breaks the markdown renderer degrades to plain text
    (Qt-free: exercised via the class without widget construction)."""
    try:
        from vidit.ui import chat_window as cw
    except Exception:  # noqa: BLE001 - headless Linux lacks Qt system libs
        pytest.skip("Qt system libraries unavailable in this environment")

    win = cw.ChatWindow.__new__(cw.ChatWindow)  # bypass Qt widget __init__

    def boom(_m, _highlight=""):
        raise ValueError("renderer exploded")

    win._bubble = boom
    poison = {"role": "assistant", "content": "\x00broken\x1b[31m", "created_at": time.time(), "id": 0}
    html_out = win._bubble_safe(poison)
    assert isinstance(html_out, str) and "broken" in html_out  # escaped fallback shown

    def fine(_m, _highlight=""):
        return "<div>ok</div>"

    win._bubble = fine
    assert win._bubble_safe(poison) == "<div>ok</div>"  # healthy path untouched


def test_chat_thread_reaped_not_dangling() -> None:
    """The second-message crash: send() guarded with self._thread.isRunning()
    while the QThread was deleteLater()'d -> 'wrapped C/C++ object deleted'.
    The reaper must drop the references, and the guard must use _busy."""
    try:
        from vidit.ui import chat_window as cw
    except Exception:  # noqa: BLE001 - headless Linux lacks Qt system libs
        pytest.skip("Qt system libraries unavailable in this environment")

    win = cw.ChatWindow.__new__(cw.ChatWindow)  # no Qt __init__

    class DeadThread:  # simulates a deleteLater()'d QThread
        def isRunning(self):
            raise RuntimeError("wrapped C/C++ object of type QThread has been deleted")

    win._thread = DeadThread()
    win._worker = object()
    win._reap_chat_thread()  # connected to thread.finished
    assert win._thread is None and win._worker is None  # no dangling refs

    # the send() guard must rely on _busy (plain bool), never the dead thread
    # (checked as the old guard PATTERN, so explanatory comments don't trip it):
    import inspect

    guard = inspect.getsource(cw.ChatWindow.send)
    assert "if not text or self._busy:" in guard
    assert "self._thread and self._thread.isRunning()" not in guard

    # shutdown_worker tolerates a dead thread without raising:
    win._thread = DeadThread()
    win._worker = object()
    win.shutdown_worker(ms=10)  # must swallow the RuntimeError
    assert win._thread is None and win._worker is None


# --------------------------------------------------------------- voice loop
# Regression round (mic "worked but never answered / never spoke"):
#   bug 1: _speak_now guarded pyttsx3 on self._pyttsx, which _detect_engine
#          deliberately leaves None (lazy COM init) → dead branch, no sound.
#   bug 2: core._on_heard never spoke the reply (text-only voice chats).
#   bug 3: manual mic sessions still demanded the wake word → silence.
#   bug 4: safe mode muted Vidit for the whole session (no auto-recovery).

def test_pyttsx3_lazy_init_actually_speaks(tmp_path, monkeypatch):
    """End-to-end: engine detected → say() → worker lazy-inits → engine talks."""
    import sys
    import types

    from vidit.senses.voice import Voice

    calls = {}

    class FakeEngine:
        def setProperty(self, key, value):
            calls.setdefault(key, []).append(value)

        def getProperty(self, key):
            return [] if key == "voices" else None

        def say(self, text):
            calls["said"] = text

        def runAndWait(self):
            calls["ran"] = True

        def stop(self):
            calls["stopped"] = True

    fake = types.ModuleType("pyttsx3")
    fake.init = lambda: FakeEngine()
    monkeypatch.setitem(sys.modules, "pyttsx3", fake)  # hermetic: no real SAPI/espeak

    cfg = {
        "voice.tts_engine": "auto",
        "voice.enabled": True,
        "voice.profile": "young",
        "voice.speed": 1.0,
        "voice.pitch": 1.0,
        "voice.volume": 0.9,
    }
    v = Voice(cfg.get, tmp_path)  # tmp home: no piper .onnx → pyttsx3 is chosen
    assert v.engine_name == "pyttsx3"
    assert v._pyttsx is None  # lazy by design — the worker must create it

    v.say("hello there", blocking=False)
    assert v._thread is not None
    v._queue.put(None)  # poison pill so the worker exits after this item
    v._thread.join(timeout=15)
    assert not v._thread.is_alive()
    assert calls.get("said") == "hello there"
    assert calls.get("ran") is True
    assert any(v > 0 for v in calls.get("rate", []))


def test_voice_reply_is_spoken_by_core():
    """bug 2: _on_heard must speak the answer, not just emit it on the bus."""
    import inspect
    from pathlib import Path

    core_src = (Path(__file__).resolve().parent.parent / "vidit" / "core.py").read_text(
        encoding="utf-8")
    handler = core_src.split("def _on_heard", 1)[1].split("\n    def ", 1)[0]
    assert "self._speak(reply.answer)" in handler
    assert 'self.bus.emit("message.voice"' in handler  # chat window still updated


def test_mic_click_starts_conversational_session():
    """bug 3: clicking 🎤 must answer speech WITHOUT the wake word."""
    import inspect
    from pathlib import Path

    base = Path(__file__).resolve().parent.parent / "vidit" / "ui"
    start = inspect.getsource(_chat_window_cls(base)._start_listening)
    assert "awake_until = time.time()" in start  # conversational session

    status = inspect.getsource(_chat_window_cls(base)._update_status)
    assert "just talk to me" in status  # honest conversational status


def _chat_window_cls(base):
    try:
        from vidit.ui import chat_window as cw
    except Exception:  # noqa: BLE001 - headless Linux lacks Qt system libs
        pytest.skip("Qt system libraries unavailable in this environment")

    return cw.ChatWindow


def test_safe_mode_auto_recovers_voice():
    """bug 4: after 45 s stable, safe mode lifts itself and voice returns."""
    import inspect
    from pathlib import Path

    app_src = (Path(__file__).resolve().parent.parent / "vidit" / "ui" / "app.py").read_text(
        encoding="utf-8")
    assert "singleShot(45000, safe_slot(self._lift_safe_mode))" in app_src
    lift = app_src.split("def _lift_safe_mode", 1)[1].split("\n    def ", 1)[0]
    assert 'self.vidit.quiet = False' in lift
    assert 'self.vidit.config.set("voice.enabled", True' in lift
    assert "voice._detect_engine()" in lift
