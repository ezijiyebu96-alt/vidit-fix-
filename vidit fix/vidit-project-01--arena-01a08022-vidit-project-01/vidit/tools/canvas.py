"""Canvas (Constitution section 5F): notes, mind maps, diagrams, kanban boards.

The canvas is a folder of small JSON/Markdown documents inside Vidit's home.
Diagrams are stored as Mermaid text so they render in the chat window's
markdown view and can be exported anywhere. Vidit can create and edit these
through tools; the UI's Canvas tab shows and edits them too.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils import safe_filename
from .base import Tool, ToolContext, ToolResult


class Canvas:
    def __init__(self, canvas_dir: Path):
        self.dir = Path(canvas_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- notes
    def write_note(self, title: str, body: str) -> Path:
        path = self.dir / f"{safe_filename(title)}.md"
        stamp = time.strftime("%Y-%m-%d %H:%M")
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            path.write_text(existing.rstrip() + f"\n\n---\n_{stamp}_\n\n{body}\n", encoding="utf-8")
        else:
            path.write_text(f"# {title}\n\n_{stamp}_\n\n{body}\n", encoding="utf-8")
        return path

    def read_note(self, title: str) -> Optional[str]:
        path = self.dir / f"{safe_filename(title)}.md"
        return path.read_text(encoding="utf-8") if path.exists() else None

    def list_items(self) -> List[Dict[str, Any]]:
        items = []
        for p in sorted(self.dir.iterdir()):
            if p.suffix in (".md", ".json", ".mmd"):
                items.append({"name": p.stem, "type": {".md": "note", ".json": "board", ".mmd": "diagram"}[p.suffix],
                              "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime))})
        return items

    # ------------------------------------------------------------- diagrams
    def mind_map(self, title: str, tree: Dict[str, Any]) -> str:
        """Render a nested dict into a Mermaid mindmap and store it."""
        lines = ["mindmap", f"  root(({title}))"]

        def walk(node: Dict[str, Any], depth: int) -> None:
            for key, value in node.items():
                lines.append("  " * (depth + 1) + str(key))
                if isinstance(value, dict):
                    walk(value, depth + 1)
                elif isinstance(value, list):
                    for leaf in value:
                        lines.append("  " * (depth + 2) + str(leaf))

        walk(tree, 1)
        text = "\n".join(lines)
        (self.dir / f"{safe_filename(title)}.mmd").write_text(text, encoding="utf-8")
        return text

    def flowchart(self, title: str, steps: List[str]) -> str:
        lines = ["flowchart TD"]
        for i, step in enumerate(steps):
            lines.append(f"  s{i}[\"{step}\"]")
            if i:
                lines.append(f"  s{i - 1} --> s{i}")
        text = "\n".join(lines)
        (self.dir / f"{safe_filename(title)}.mmd").write_text(text, encoding="utf-8")
        return text

    # ---------------------------------------------------------------- board
    def board(self, name: str) -> Dict[str, List[str]]:
        path = self.dir / f"{safe_filename(name)}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return {"todo": [], "doing": [], "done": []}

    def save_board(self, name: str, board: Dict[str, List[str]]) -> None:
        (self.dir / f"{safe_filename(name)}.json").write_text(json.dumps(board, indent=1, ensure_ascii=False), encoding="utf-8")

    def add_task(self, name: str, task: str, column: str = "todo") -> Dict[str, List[str]]:
        board = self.board(name)
        board.setdefault(column, []).append(task)
        self.save_board(name, board)
        return board

    def move_task(self, name: str, task: str, to_column: str) -> Dict[str, List[str]]:
        board = self.board(name)
        for col in board.values():
            if task in col:
                col.remove(task)
        board.setdefault(to_column, []).append(task)
        self.save_board(name, board)
        return board

    @staticmethod
    def board_markdown(board: Dict[str, List[str]]) -> str:
        out = []
        for col, tasks in board.items():
            out.append(f"**{col.title()}**")
            out += [f"- [{'x' if col == 'done' else ' '}] {t}" for t in tasks] or ["- (empty)"]
        return "\n".join(out)


def make_canvas_tools(canvas: Canvas) -> List[Tool]:
    def _note(args: str, ctx: ToolContext) -> ToolResult:
        if "|" not in args:
            return ToolResult(False, "Usage: title | body")
        title, body = args.split("|", 1)
        path = canvas.write_note(title.strip(), body.strip())
        return ToolResult(True, f"Saved note '{title.strip()}' at {path}")

    def _mindmap(args: str, ctx: ToolContext) -> ToolResult:
        if "|" not in args:
            return ToolResult(False, "Usage: title | topic1: a, b; topic2: c")
        title, spec = args.split("|", 1)
        tree: Dict[str, Any] = {}
        for branch in spec.split(";"):
            if ":" in branch:
                key, leaves = branch.split(":", 1)
                tree[key.strip()] = [l.strip() for l in leaves.split(",") if l.strip()]
            elif branch.strip():
                tree[branch.strip()] = []
        return ToolResult(True, "```mermaid\n" + canvas.mind_map(title.strip(), tree) + "\n```")

    def _flow(args: str, ctx: ToolContext) -> ToolResult:
        if "|" not in args:
            return ToolResult(False, "Usage: title | step 1 -> step 2 -> step 3")
        title, spec = args.split("|", 1)
        steps = [s.strip() for s in spec.split("->") if s.strip()]
        return ToolResult(True, "```mermaid\n" + canvas.flowchart(title.strip(), steps) + "\n```")

    def _board(args: str, ctx: ToolContext) -> ToolResult:
        parts = [p.strip() for p in args.split("|")]
        name = parts[0] or "tasks"
        if len(parts) >= 3 and parts[1].lower() == "add":
            board = canvas.add_task(name, parts[2], parts[3] if len(parts) > 3 else "todo")
        elif len(parts) >= 4 and parts[1].lower() == "move":
            board = canvas.move_task(name, parts[2], parts[3])
        else:
            board = canvas.board(name)
        return ToolResult(True, canvas.board_markdown(board), {"board": board})

    return [
        Tool("note", "Save a rich-text note on the canvas.", "title | body", _note),
        Tool("mind_map", "Create a mind map diagram.", "title | branch: leaf, leaf; branch2: leaf", _mindmap),
        Tool("flowchart", "Create a flowchart diagram.", "title | step -> step -> step", _flow),
        Tool("board", "Kanban board: view, add or move tasks.", "board | add | task | todo", _board),
    ]
