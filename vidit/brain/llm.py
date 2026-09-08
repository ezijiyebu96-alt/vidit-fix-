"""The local language model (Constitution section 2 — ZERO external APIs).

Vidit thinks with a model running on *your* GPU through Ollama
(http://127.0.0.1:11434). Nothing here ever contacts a remote server.

Two backends:

* :class:`OllamaBackend` – the real brain (Qwen 2.5 7B by default on an
  RTX 4050; falls back to smaller local models if the primary is missing).
* :class:`EchoBackend`  – a tiny rule-based stand-in that lets the whole
  program run and be tested on a machine without Ollama. It is honest
  about being a fallback.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, Iterable, List, Optional, Protocol

log = logging.getLogger("vidit.brain.llm")

Message = Dict[str, Any]  # {"role": "system|user|assistant", "content": str, "images": [b64]}


@dataclass
class LLMResult:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    backend: str = "unknown"
    thinking: str = ""            # section 4: "Think / Reasoning" toggle
    extra: Dict[str, Any] = field(default_factory=dict)


class LLMBackend(Protocol):
    name: str

    def available(self) -> bool: ...
    def models(self) -> List[str]: ...
    def chat(self, messages: List[Message], *, model: str, options: Dict[str, Any],
             stream_cb: Optional[Callable[[str], None]] = None) -> LLMResult: ...


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------
class OllamaBackend:
    name = "ollama"

    def __init__(self, host: str = "http://127.0.0.1:11434", timeout: float = 600.0, keep_alive: str = "30m"):
        self.host = host.rstrip("/")
        self.timeout = timeout
        self.keep_alive = keep_alive
        self._models_cache: List[str] = []
        self._models_checked = 0.0

    # -- discovery ---------------------------------------------------------
    def available(self) -> bool:
        try:
            import requests  # local HTTP only

            r = requests.get(f"{self.host}/api/tags", timeout=2.5)
            return r.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    def models(self) -> List[str]:
        if time.time() - self._models_checked < 30 and self._models_cache:
            return list(self._models_cache)
        try:
            import requests

            r = requests.get(f"{self.host}/api/tags", timeout=5)
            r.raise_for_status()
            self._models_cache = [m["name"] for m in r.json().get("models", [])]
            self._models_checked = time.time()
        except Exception:  # noqa: BLE001
            self._models_cache = []
        return list(self._models_cache)

    def pull(self, model: str, progress_cb: Optional[Callable[[str], None]] = None) -> bool:
        """Download a model into Ollama's local store (needs internet once; user permission handled upstream)."""
        try:
            import requests

            with requests.post(f"{self.host}/api/pull", json={"name": model, "stream": True}, stream=True, timeout=None) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    status = data.get("status", "")
                    total, done = data.get("total"), data.get("completed")
                    if progress_cb:
                        if total and done:
                            progress_cb(f"{status} {done / total:.0%}")
                        else:
                            progress_cb(status)
                    if data.get("error"):
                        log.error("pull error: %s", data["error"])
                        return False
            self._models_checked = 0.0
            return True
        except Exception:  # noqa: BLE001
            log.exception("model pull failed")
            return False

    # -- inference ---------------------------------------------------------
    def chat(self, messages: List[Message], *, model: str, options: Dict[str, Any],
             stream_cb: Optional[Callable[[str], None]] = None) -> LLMResult:
        import requests

        payload = {
            "model": model,
            "messages": messages,
            "stream": stream_cb is not None,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": options.get("temperature", 0.8),
                "top_p": options.get("top_p", 0.9),
                "num_predict": options.get("max_tokens", 1024),
                "num_ctx": options.get("num_ctx", 8192),
            },
        }
        started = time.time()
        text_parts: List[str] = []
        prompt_tokens = completion_tokens = 0
        with requests.post(f"{self.host}/api/chat", json=payload, stream=stream_cb is not None, timeout=self.timeout) as r:
            r.raise_for_status()
            if stream_cb is None:
                try:
                    data = r.json()
                except ValueError:
                    # Some servers stream anyway (NDJSON); stitch the pieces together.
                    data = {"message": {"content": ""}}
                    for line in r.text.splitlines():
                        try:
                            piece = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        data["message"]["content"] += piece.get("message", {}).get("content", "")
                        if piece.get("done"):
                            data["prompt_eval_count"] = piece.get("prompt_eval_count", 0)
                            data["eval_count"] = piece.get("eval_count", 0)
                text_parts.append(data.get("message", {}).get("content", ""))
                prompt_tokens = data.get("prompt_eval_count", 0)
                completion_tokens = data.get("eval_count", 0)
            else:
                for line in r.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    chunk = data.get("message", {}).get("content", "")
                    if chunk:
                        text_parts.append(chunk)
                        stream_cb(chunk)
                    if data.get("done"):
                        prompt_tokens = data.get("prompt_eval_count", 0)
                        completion_tokens = data.get("eval_count", 0)
        text = "".join(text_parts)
        thinking, text = split_thinking(text)
        return LLMResult(text=text, model=model, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                         seconds=time.time() - started, backend=self.name, thinking=thinking)

    def embed(self, text: str, model: str = "nomic-embed-text") -> Optional[List[float]]:
        try:
            import requests

            r = requests.post(f"{self.host}/api/embeddings", json={"model": model, "prompt": text}, timeout=60)
            r.raise_for_status()
            return r.json().get("embedding")
        except Exception:  # noqa: BLE001
            return None


# ---------------------------------------------------------------------------
# Echo (offline stand-in)
# ---------------------------------------------------------------------------
class EchoBackend:
    """A tiny local heuristic brain used when no model is installed.

    It keeps Vidit alive — he can greet you, remember what you tell him,
    and explain how to install his real brain — without pretending to be
    smarter than he is.
    """

    name = "echo"

    def available(self) -> bool:
        return True

    def models(self) -> List[str]:
        return ["echo"]

    def chat(self, messages: List[Message], *, model: str, options: Dict[str, Any],
             stream_cb: Optional[Callable[[str], None]] = None) -> LLMResult:
        started = time.time()
        user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        name_match = re.search(r"The user's name: ([^\n.]+)", system)
        user_name = name_match.group(1).strip() if name_match and "don't know" not in name_match.group(1) else ""
        greeting = f"{user_name}, " if user_name else ""
        lowered = user.lower()

        if any(w in lowered for w in ("hello", "hi", "hey", "namaste", "yo")) and len(lowered) < 25:
            reply = f"Hey {greeting}I'm here. My full brain (the local model) isn't running yet, so I'm on my simple fallback mind — but I'm listening and remembering everything you tell me."
        elif "?" in user:
            reply = (f"Good question{', ' + user_name if user_name else ''}. Honestly, I can't reason properly until my local model is installed "
                     "(run `ollama pull qwen2.5:7b` and start Ollama). I've noted your question so we can revisit it.")
        elif any(w in lowered for w in ("thank", "shukriya", "dhanyavad")):
            reply = "Anytime. That's what brothers are for. 🙂"
        else:
            reply = f"Got it{', ' + user_name if user_name else ''} — I've saved that. Once my real brain is online I'll be able to talk about it properly."
        if stream_cb:
            for word in reply.split(" "):
                stream_cb(word + " ")
        return LLMResult(text=reply, model="echo", seconds=time.time() - started, backend=self.name)


# ---------------------------------------------------------------------------
# Client with fallbacks
# ---------------------------------------------------------------------------
class LLMClient:
    """Chooses a backend & model, retries with fallbacks, records health."""

    def __init__(self, config_get: Callable[[str, Any], Any]):
        self._get = config_get
        self._lock = threading.Lock()
        self.ollama = OllamaBackend(
            host=self._get("model.host", "http://127.0.0.1:11434"),
            keep_alive=self._get("model.keep_alive", "30m"),
        )
        self.echo = EchoBackend()
        self.last_error: str = ""
        self.active_model: str = ""
        self.active_backend: str = ""
        self.total_calls = 0
        self.failed_calls = 0

    # -- selection ---------------------------------------------------------
    def candidate_models(self) -> List[str]:
        primary = self._get("model.primary_model", "qwen2.5:7b")
        fallbacks = self._get("model.fallback_models", []) or []
        return [primary] + [m for m in fallbacks if m != primary]

    def resolve_model(self) -> tuple[LLMBackend, str]:
        backend_pref = self._get("model.backend", "ollama")
        if backend_pref == "ollama" and self.ollama.available():
            installed = self.ollama.models()
            for candidate in self.candidate_models():
                for name in installed:
                    if name == candidate or name.split(":")[0] == candidate.split(":")[0]:
                        return self.ollama, name
            if installed:  # anything is better than nothing
                return self.ollama, installed[0]
            self.last_error = "Ollama is running but no models are installed."
        elif backend_pref == "ollama":
            self.last_error = "Ollama is not reachable at " + self.ollama.host
        return self.echo, "echo"

    def status(self) -> Dict[str, Any]:
        backend, model = self.resolve_model()
        return {
            "backend": backend.name,
            "model": model,
            "ollama_reachable": self.ollama.available(),
            "installed_models": self.ollama.models() if backend.name == "ollama" else [],
            "last_error": self.last_error,
            "calls": self.total_calls,
            "failures": self.failed_calls,
        }

    # -- inference ---------------------------------------------------------
    def chat(self, messages: List[Message], *, stream_cb: Optional[Callable[[str], None]] = None,
             model: Optional[str] = None, **option_overrides: Any) -> LLMResult:
        options = {
            "temperature": self._get("model.temperature", 0.8),
            "top_p": self._get("model.top_p", 0.9),
            "max_tokens": self._get("model.max_tokens", 1024),
        }
        options.update(option_overrides)
        backend, resolved = self.resolve_model()
        model = model or resolved
        self.total_calls += 1
        try:
            result = backend.chat(messages, model=model, options=options, stream_cb=stream_cb)
            self.active_model, self.active_backend = result.model, result.backend
            return result
        except Exception as exc:  # noqa: BLE001
            self.failed_calls += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.warning("LLM call failed on %s/%s: %s", backend.name, model, exc)
            if backend is not self.echo:
                # Try the other installed models before giving up.
                for alt in self.ollama.models():
                    if alt == model:
                        continue
                    try:
                        result = self.ollama.chat(messages, model=alt, options=options, stream_cb=stream_cb)
                        self.active_model, self.active_backend = result.model, result.backend
                        return result
                    except Exception as exc2:  # noqa: BLE001
                        self.last_error = f"{type(exc2).__name__}: {exc2}"
                        continue
            result = self.echo.chat(messages, model="echo", options=options, stream_cb=stream_cb)
            result.extra["degraded"] = True
            return result

    def quick(self, prompt: str, system: str = "", **kw: Any) -> str:
        """One-shot helper for internal reasoning (summaries, extraction...)."""
        msgs: List[Message] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        kw.setdefault("temperature", 0.2)
        return self.chat(msgs, **kw).text

    def json(self, prompt: str, system: str = "", default: Any = None, **kw: Any) -> Any:
        text = self.quick(prompt, system, **kw)
        return parse_json_block(text, default)

    def describe_image(self, image_b64: str, question: str = "Describe this image in detail.") -> str:
        """Local vision via a multimodal model (e.g. llava), if installed."""
        vision = self._get("model.vision_model", "llava:7b")
        installed = self.ollama.models() if self.ollama.available() else []
        model = next((m for m in installed if m.split(":")[0] == vision.split(":")[0]), None)
        if not model:
            return "(I can't see images yet — install a local vision model such as `ollama pull llava:7b`.)"
        try:
            return self.ollama.chat(
                [{"role": "user", "content": question, "images": [image_b64]}],
                model=model, options={"temperature": 0.2, "max_tokens": 512},
            ).text
        except Exception as exc:  # noqa: BLE001
            return f"(My eyes glitched: {exc})"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)
_JSON_RE = re.compile(r"\{.*\}|\[.*\]", re.DOTALL)


def split_thinking(text: str) -> tuple[str, str]:
    """Separate <think>...</think> reasoning (DeepSeek/Qwen style) from the answer."""
    thoughts = _THINK_RE.findall(text)
    cleaned = _THINK_RE.sub("", text).strip()
    return "\n".join(t.strip() for t in thoughts), cleaned


class StreamFilter:
    """Wraps a stream callback and hides <think>…</think>, <feel>…</feel> and [[tool:…]] while streaming.

    Text is held back whenever a possible tag start (``<`` or ``[[``) is seen
    until it is clear whether it is a tag, so the user never sees half a tag.
    """

    HIDDEN = (("<think>", "</think>"), ("<feel>", "</feel>"), ("[[", "]]"))

    def __init__(self, cb: Callable[[str], None]):
        self._cb = cb
        self._buf = ""
        self._hiding: Optional[str] = None  # the closing marker we are waiting for

    def __call__(self, chunk: str) -> None:
        self._buf += chunk
        while self._buf:
            if self._hiding:
                end = self._buf.find(self._hiding)
                if end < 0:
                    return
                self._buf = self._buf[end + len(self._hiding):]
                self._hiding = None
                continue
            starts = [(self._buf.find(o), o, c) for o, c in self.HIDDEN if o in self._buf]
            if starts:
                pos, opener, closer = min(starts)
                if pos:
                    self._cb(self._buf[:pos])
                self._buf = self._buf[pos + len(opener):]
                self._hiding = closer
                continue
            # Hold back a partial opener at the end of the buffer.
            hold = 0
            for opener, _ in self.HIDDEN:
                for n in range(1, len(opener)):
                    if self._buf.endswith(opener[:n]):
                        hold = max(hold, n)
            emit, self._buf = (self._buf[:-hold], self._buf[-hold:]) if hold else (self._buf, "")
            if emit:
                self._cb(emit)
            return

    def flush(self) -> None:
        if self._buf and not self._hiding:
            self._cb(self._buf)
        self._buf = ""


def parse_json_block(text: str, default: Any = None) -> Any:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = _JSON_RE.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return default


def messages_to_text(messages: Iterable[Message]) -> str:
    return "\n".join(f"{m['role']}: {m['content']}" for m in messages)


def stream_words(text: str) -> Generator[str, None, None]:
    for word in text.split(" "):
        yield word + " "
