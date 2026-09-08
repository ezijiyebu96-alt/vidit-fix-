"""Tool plumbing.

A *tool* is something Vidit can decide to use while thinking. Tools are
described to the local model in plain language; when the model wants one it
answers with a single line ``[[tool: name | args]]`` which the orchestrator
executes (after checking permissions) and feeds back. Simple, offline, and
works with any local model — no function-calling API required.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("vidit.tools")

TOOL_CALL_RE = re.compile(r"\[\[\s*tool\s*:\s*([a-z_]+)\s*(?:\|\s*(.*?))?\s*\]\]", re.IGNORECASE | re.DOTALL)


@dataclass
class ToolResult:
    ok: bool
    output: str
    data: Dict[str, Any] = field(default_factory=dict)
    seconds: float = 0.0

    def for_model(self, limit: int = 4000) -> str:
        out = self.output if len(self.output) <= limit else self.output[:limit] + "\n…(truncated)"
        return f"[tool result{' (error)' if not self.ok else ''}]\n{out}"


@dataclass
class ToolContext:
    """What tools may reach: memory, config, permissions, llm, a way to say things."""
    memory: Any
    config: Any
    permissions: Any
    llm: Any
    say: Callable[[str], None]
    attachments: List[str] = field(default_factory=list)


@dataclass
class Tool:
    name: str
    description: str
    usage: str
    handler: Callable[[str, ToolContext], ToolResult]
    dangerous: bool = False

    def run(self, args: str, ctx: ToolContext) -> ToolResult:
        started = time.time()
        try:
            result = self.handler(args, ctx)
        except Exception as exc:  # noqa: BLE001
            log.exception("tool %s failed", self.name)
            result = ToolResult(False, f"{type(exc).__name__}: {exc}")
        result.seconds = time.time() - started
        return result


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name.lower())

    def names(self) -> List[str]:
        return sorted(self._tools)

    def __len__(self) -> int:
        return len(self._tools)

    def prompt_fragment(self) -> str:
        if not self._tools:
            return ""
        lines = ["\nTOOLS: When you genuinely need one, reply with ONLY a single line in this exact form and nothing else:",
                 "[[tool: name | arguments]]",
                 "You will receive the result and can then answer normally. Available tools:"]
        for tool in sorted(self._tools.values(), key=lambda t: t.name):
            lines.append(f"- {tool.name}: {tool.description} Usage: [[tool: {tool.name} | {tool.usage}]]")
        lines.append("Do not use a tool for casual conversation, feelings, or things you already know.")
        return "\n".join(lines)

    @staticmethod
    def parse_call(text: str) -> Optional[tuple[str, str]]:
        match = TOOL_CALL_RE.search(text or "")
        if not match:
            return None
        return match.group(1).lower(), (match.group(2) or "").strip()
