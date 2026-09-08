"""Tests for Vidit's organs. Run with:  python -m pytest -q"""
from __future__ import annotations

import json
import time
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
