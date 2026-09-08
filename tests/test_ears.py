"""Tests for Ears' crash-isolated speech-model lifecycle.

These never touch a real microphone, faster-whisper or the network: the
native libraries are replaced with fakes so we can prove the *logic* —
single-flight loading, compute-type fallbacks, the subprocess probe, cache
handling and graceful degradation — on any machine.
"""
from __future__ import annotations

import json
import sys
import threading
import types
from pathlib import Path

import pytest

from vidit.events import EventBus
from vidit.senses.ears import Ears, EarsModelError

SETTINGS = {
    "voice.stt_model": "small",
    "voice.stt_compute_type": "auto",
    "voice.stt_cpu_threads": 2,
    "voice.stt_warmup": True,
    "voice.stt_safe_probe": True,
    "voice.stt_probe_timeout": 900,
    "voice.activation": "wake_word",
}


class _FakeWhisperModel:
    """Stands in for faster_whisper.WhisperModel."""

    instances = []
    fail_on = set()

    def __init__(self, *args, **kwargs):
        _FakeWhisperModel.instances.append((args, kwargs))
        compute = kwargs.get("compute_type", "int8")
        if compute in _FakeWhisperModel.fail_on:
            raise ValueError(f"int8/backend not supported (fake for {compute})")
        self.compute_type = compute
        self.model = object()  # the ctranslate2 model handle


@pytest.fixture()
def fake_faster_whisper(monkeypatch):
    """Make ``import faster_whisper`` resolve to the fake inside Ears."""
    _FakeWhisperModel.instances = []
    _FakeWhisperModel.fail_on = set()
    mod = types.ModuleType("faster_whisper")
    mod.WhisperModel = _FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", mod)
    return mod


@pytest.fixture()
def ears(tmp_path, monkeypatch):
    cfg = dict(SETTINGS)

    def config_get(key, default=None):
        return cfg.get(key, default)

    e = Ears(config_get, tmp_path, event_bus=EventBus())

    def fake_versions():
        return {"faster_whisper": "1.2.1", "ctranslate2": "4.8.2"}

    monkeypatch.setattr(e, "_versions", fake_versions)
    return e, cfg


def _local_model(tmp_path: Path) -> Path:
    """A fake already-downloaded ct2 model folder (no network needed)."""
    d = tmp_path / "whisper" / "mymodel"
    d.mkdir(parents=True)
    (d / "model.bin").write_bytes(b"fake")
    (d / "config.json").write_text("{}")
    return d


# ---------------------------------------------------------------- compute type


def test_compute_candidates_auto(ears):
    e, _ = ears
    assert e._configured_compute_types() == ["int8", "int8_float32", "float32"]


def test_compute_candidates_explicit(ears):
    e, cfg = ears
    cfg["voice.stt_compute_type"] = "float32"
    assert e._configured_compute_types() == ["float32", "int8", "int8_float32"]


# ---------------------------------------------------------------- building


def test_build_model_falls_back_on_python_error(ears, tmp_path, fake_faster_whisper):
    e, cfg = ears
    cfg["voice.stt_model"] = str(_local_model(tmp_path))
    _FakeWhisperModel.fail_on = {"int8"}  # the classic "int8 unsupported" CPU case
    model = e._build_model(cfg["voice.stt_model"], "int8", 2)
    assert model.compute_type == "int8_float32"
    assert e.model_ready()
    assert e.status()["model_state"] == "ready"


def test_build_model_gives_up_with_guidance(ears, tmp_path, fake_faster_whisper):
    e, cfg = ears
    cfg["voice.stt_model"] = str(_local_model(tmp_path))
    _FakeWhisperModel.fail_on = {"int8", "int8_float32", "float32"}
    with pytest.raises(EarsModelError) as exc:
        e._build_model(cfg["voice.stt_model"], "int8", 2)
    assert "float32" in str(exc.value)
    assert e.status()["model_state"] == "error"
    assert e.status()["error"]


# ------------------------------------------------------- safe subprocess probe


def test_probe_crash_falls_back_to_safe_compute_type(ears, tmp_path, fake_faster_whisper):
    """A native-crash signature for int8 must never reach the in-process load."""
    e, cfg = ears
    cfg["voice.stt_model"] = str(_local_model(tmp_path))
    calls = []

    def fake_run_child(args, timeout):
        assert args[0] == "probe"
        calls.append(args)
        if args[2] == "int8":
            return {"ok": False, "error": "probe process crashed (exit code -11)"}
        if args[2] == "int8_float32":
            return {"ok": False, "error": "probe process crashed (exit code -11)"}
        return {"ok": True, "compute_type": args[2]}

    e._run_child = fake_run_child  # type: ignore[method-assign]
    model = e._ensure_model()
    assert model is not None
    assert e._compute_used == "float32"
    assert len(calls) == 3  # tried int8, int8_float32, then float32
    assert e.status()["model_state"] == "ready"


def test_probe_total_failure_disables_ears_gracefully(ears, tmp_path):
    e, cfg = ears
    cfg["voice.stt_model"] = str(_local_model(tmp_path))

    def fake_run_child(args, timeout):
        return {"ok": False, "error": "probe process crashed (exit code -11)"}

    e._run_child = fake_run_child  # type: ignore[method-assign]
    with pytest.raises(EarsModelError):
        e._ensure_model()
    # Subsequent calls fail fast instead of re-probing.
    with pytest.raises(EarsModelError):
        e._ensure_model()
    assert e.status()["model_state"] == "error"
    assert "float32" in e.status()["error"] or e.status()["error"]


def test_probe_disabled_skips_subprocess(ears, tmp_path, fake_faster_whisper):
    e, cfg = ears
    cfg["voice.stt_model"] = str(_local_model(tmp_path))
    cfg["voice.stt_safe_probe"] = False

    def unexpected(*a, **k):
        raise AssertionError("subprocess should not run when probing is disabled")

    e._run_child = unexpected  # type: ignore[method-assign]
    model = e._ensure_model()
    assert model.compute_type == "int8"
    assert e.status()["model_state"] == "ready"


# ---------------------------------------------------------------- single flight


def test_concurrent_ensure_loads_once(fake_faster_whisper, ears, tmp_path):
    """Threads racing to load must only construct the model once."""
    e, cfg = ears
    cfg["voice.stt_model"] = str(_local_model(tmp_path))
    cfg["voice.stt_safe_probe"] = False

    results = []
    errors = []

    def worker():
        try:
            results.append(e._ensure_model())
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert not errors
    assert len(_FakeWhisperModel.instances) == 1
    assert all(m is results[0] for m in results)


# ------------------------------------------------------------------- caching


def test_probe_cache_roundtrip_and_version_gate(ears, tmp_path):
    e, cfg = ears
    snapshot = _local_model(tmp_path)
    e._write_cache(cfg["voice.stt_model"], str(snapshot), "float32")
    entry = e._cache_entry()
    assert entry and entry["compute_type"] == "float32"
    assert entry["snapshot"] == str(snapshot)

    # Version mismatch → cache is ignored (forces a fresh probe after upgrades).
    e._versions = lambda: {"faster_whisper": "9.9.9", "ctranslate2": "9.9.9"}  # type: ignore[method-assign]
    assert e._cache_entry() is None


def test_reset_model_cache(ears, tmp_path):
    e, cfg = ears
    snapshot = _local_model(tmp_path)
    whisper = snapshot.parent
    (whisper / "_probe.json").write_text(json.dumps({"size": "small"}), encoding="utf-8")
    snap_dir = whisper / "models--Systran--faster-whisper-small"
    snap_dir.mkdir()
    (snap_dir / "model.bin").write_bytes(b"x")

    e._model_error = "boom"
    e._model_state = "error"
    msg = e.reset_model_cache(clear_downloads=True)
    assert "reset" in msg
    assert e.status()["model_state"] == "idle"
    assert not (whisper / "_probe.json").exists()
    assert not snap_dir.exists()
    assert e.status()["error"] == ""


# ---------------------------------------------------------------- warm-up


def test_warmup_starts_exactly_once(ears, monkeypatch):
    e, cfg = ears
    started = []
    gate = threading.Event()

    def fake_warm_worker():
        started.append(1)
        gate.wait(5)  # keep the thread alive so we can observe the guard

    monkeypatch.setattr(e, "_warm_worker", fake_warm_worker)
    monkeypatch.setattr(e, "available", lambda: True)
    assert e.warmup() is True
    assert e.warmup() is True
    gate.set()
    if e._warm_thread:
        e._warm_thread.join(timeout=5)
    assert len(started) == 1


# ------------------------------------------------------------ transcribe paths


def test_transcribe_array_swallows_model_error(ears, tmp_path):
    pytest.importorskip("numpy")
    e, cfg = ears

    def boom(*a, **k):
        raise EarsModelError("speech model unavailable")

    e._load_model = boom  # type: ignore[method-assign]
    assert e._transcribe_array([0.0] * 16000) == ""


# ------------------------------------------------- integration (real subprocess)


def test_run_child_reports_failure_and_cleans_up(ears, tmp_path):
    """Real end-to-end probe subprocess: a broken model dir must fail inside
    the child and never crash/raise in the parent (paths with spaces too)."""
    pytest.importorskip("faster_whisper")
    e, cfg = ears
    snapshot = tmp_path / "with space" / "broken-model"
    snapshot.mkdir(parents=True)
    # No model.bin/config.json -> ctranslate2 fails inside the child.
    res = e._run_child(["probe", str(snapshot), "int8", "2"], 120)
    assert res is not None
    assert res.get("ok") is False
    assert res.get("error")
    assert not list(e.models_dir.glob("_probe_*.json"))
