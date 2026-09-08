"""Code tools (Constitution section 5E): generate, review, explain, run.

Execution is sandboxed as far as a laptop allows: a separate process, a
timeout, a scratch working directory inside Vidit's folder, and the
CODE_EXECUTION permission gate. He always shows you the code before it
runs — it is *your* laptop.
"""
from __future__ import annotations

import ast
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

from ..guardian import Capability
from .base import Tool, ToolContext, ToolResult

log = logging.getLogger("vidit.tools.code")

RUNNERS: Dict[str, List[str]] = {
    "python": [sys.executable, "-I"],
    "javascript": ["node"],
    "node": ["node"],
    "bash": ["bash"],
    "sh": ["sh"],
    "powershell": ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"],
}
EXTENSIONS = {"python": ".py", "javascript": ".js", "node": ".js", "bash": ".sh", "sh": ".sh", "powershell": ".ps1"}


class CodeTools:
    def __init__(self, llm, scratch_dir: Path):
        self.llm = llm
        self.scratch = Path(scratch_dir)
        self.scratch.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ analysis
    @staticmethod
    def python_static_check(source: str) -> Dict[str, Any]:
        """Instant offline feedback: syntax + a few smells."""
        issues: List[str] = []
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return {"ok": False, "issues": [f"SyntaxError line {exc.lineno}: {exc.msg}"]}
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                issues.append(f"line {node.lineno}: bare `except:` swallows everything, catch specific exceptions")
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "eval":
                issues.append(f"line {node.lineno}: `eval` is dangerous with untrusted input")
            if isinstance(node, ast.FunctionDef) and len(node.body) > 60:
                issues.append(f"line {node.lineno}: function `{node.name}` is very long; consider splitting it")
        functions = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        return {"ok": True, "issues": issues, "functions": functions, "classes": classes, "lines": source.count("\n") + 1}

    def review(self, source: str, language: str = "python") -> str:
        static = self.python_static_check(source) if language == "python" else {"issues": []}
        prompt = (f"Language: {language}\nStatic findings: {static.get('issues') or 'none'}\n\n```{language}\n{source[:10000]}\n```\n\n"
                  "Review this code: bugs, edge cases, readability, performance, security. Give concrete fixes.")
        return self.llm.quick(prompt, "You are Vidit, a sharp but friendly senior engineer reviewing your brother's code.")

    def explain(self, source: str, language: str = "python") -> str:
        return self.llm.quick(f"```{language}\n{source[:10000]}\n```\n\nExplain what this code does, step by step, in plain language.",
                              "You are Vidit explaining code to your brother. Be clear and friendly.")

    def generate(self, task: str, language: str = "python") -> str:
        return self.llm.quick(f"Write {language} code for: {task}\nReturn the code in one fenced block with brief comments, then 2-3 lines on how to run it.",
                              "You are Vidit, an expert programmer. Write clean, working, idiomatic code.")

    def translate(self, source: str, source_lang: str, target_lang: str) -> str:
        return self.llm.quick(f"Translate this {source_lang} code to {target_lang}, preserving behaviour:\n```{source_lang}\n{source[:10000]}\n```",
                              "You are Vidit, an expert polyglot programmer.")

    def document(self, source: str, language: str = "python") -> str:
        return self.llm.quick(f"```{language}\n{source[:10000]}\n```\n\nWrite documentation: overview, usage, each function/class with parameters and return values.",
                              "You are Vidit writing clear developer documentation.")

    # ----------------------------------------------------------- execution
    def run(self, source: str, language: str = "python", timeout: float = 30.0, stdin: str = "") -> Dict[str, Any]:
        language = language.lower()
        runner = RUNNERS.get(language)
        if not runner:
            return {"ok": False, "stdout": "", "stderr": f"I can't run {language} yet.", "seconds": 0.0}
        suffix = EXTENSIONS[language]
        with tempfile.NamedTemporaryFile("w", suffix=suffix, dir=self.scratch, delete=False, encoding="utf-8") as fh:
            fh.write(source)
            script = Path(fh.name)
        started = time.time()
        env = {k: v for k, v in os.environ.items() if k.upper() not in {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"}}
        try:
            proc = subprocess.run(runner + [str(script)], capture_output=True, text=True, timeout=timeout, cwd=str(self.scratch),
                                  input=stdin, env=env)
            return {"ok": proc.returncode == 0, "stdout": proc.stdout[-8000:], "stderr": proc.stderr[-4000:],
                    "returncode": proc.returncode, "seconds": round(time.time() - started, 2)}
        except subprocess.TimeoutExpired:
            return {"ok": False, "stdout": "", "stderr": f"Timed out after {timeout}s.", "seconds": timeout}
        except FileNotFoundError:
            return {"ok": False, "stdout": "", "stderr": f"{runner[0]} is not installed on this laptop.", "seconds": 0.0}
        finally:
            try:
                script.unlink()
            except OSError:
                pass


def _split_lang(args: str, default: str = "python") -> tuple[str, str]:
    if "|" in args:
        lang, code = args.split("|", 1)
        lang = lang.strip().lower()
        if lang in RUNNERS or lang in {"java", "c", "cpp", "go", "rust", "typescript"}:
            return lang, _dedent_code(code)
    return default, _dedent_code(args)


def _dedent_code(code: str) -> str:
    """Strip markdown fences and common indentation the model may add."""
    import textwrap

    code = code.strip("\n")
    fence = re.match(r"^```[a-zA-Z0-9]*\n(.*?)\n?```$", code.strip(), re.DOTALL)
    if fence:
        code = fence.group(1)
    if "\n" not in code:
        return code.strip()
    return textwrap.dedent(code).strip("\n")


def make_code_tools(code: CodeTools) -> List[Tool]:
    def _run(args: str, ctx: ToolContext) -> ToolResult:
        lang, source = _split_lang(args)
        if not ctx.permissions.check(Capability.CODE_EXECUTION, f"to run this {lang} snippet", detail=source[:500]):
            return ToolResult(False, "You haven't allowed me to run code right now.")
        result = code.run(source, lang)
        out = (result["stdout"] or "") + (("\n[stderr]\n" + result["stderr"]) if result["stderr"] else "")
        return ToolResult(result["ok"], out.strip() or "(no output)", result)

    def _review(args: str, ctx: ToolContext) -> ToolResult:
        lang, source = _split_lang(args)
        return ToolResult(True, code.review(source, lang))

    def _explain(args: str, ctx: ToolContext) -> ToolResult:
        lang, source = _split_lang(args)
        return ToolResult(True, code.explain(source, lang))

    def _check(args: str, ctx: ToolContext) -> ToolResult:
        _, source = _split_lang(args)
        return ToolResult(True, str(code.python_static_check(source)))

    return [
        Tool("run_code", "Execute a code snippet locally (asks permission). Prefix with the language.", "python | print(1+1)", _run, dangerous=True),
        Tool("review_code", "Review code for bugs and improvements.", "language | code", _review),
        Tool("explain_code", "Explain what a piece of code does.", "language | code", _explain),
        Tool("check_python", "Instant offline syntax/smell check for Python.", "code", _check),
    ]
