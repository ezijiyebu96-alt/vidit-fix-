"""Vidit's memory (Constitution section 2).

* **Short-term memory** – the current conversation, kept in RAM and mirrored
  to the ``messages`` table.
* **Long-term memory** – distilled facts, preferences, lessons and moments
  in the ``memories`` table, with an importance score, access counts and a
  "favorite" flag. Everything is searchable with SQLite FTS5 (falls back to
  LIKE if FTS is unavailable).
* **Forgetting** – ``forget()`` removes anything on request (section 10E/10G).
* **Priorities** – importance decays slowly unless the memory is recalled,
  which is how "favorite memories" emerge naturally.

All of it is a single SQLite file inside Vidit's own folder. Nothing leaves
the laptop.
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..utils import keywords, now_iso, truncate

log = logging.getLogger("vidit.brain.memory")

KINDS = ("fact", "preference", "person", "event", "lesson", "moment", "goal", "correction", "skill", "note")


@dataclass
class Memory:
    id: int
    kind: str
    content: str
    importance: float
    created_at: float
    last_accessed: float
    access_count: int
    favorite: bool
    tags: List[str] = field(default_factory=list)
    source: str = "conversation"
    score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = self.__dict__.copy()
        d["created"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(self.created_at))
        return d


class MemoryStore:
    def __init__(self, db_path: Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._fts = False
        self._init_schema()

    # -------------------------------------------------------------- schema
    def _init_schema(self) -> None:
        with self._lock, self._conn:
            c = self._conn
            c.execute("PRAGMA journal_mode=WAL")
            c.execute(
                """CREATE TABLE IF NOT EXISTS conversations (
                       id INTEGER PRIMARY KEY,
                       title TEXT,
                       folder TEXT DEFAULT '',
                       created_at REAL,
                       updated_at REAL
                   )"""
            )
            c.execute(
                """CREATE TABLE IF NOT EXISTS messages (
                       id INTEGER PRIMARY KEY,
                       conversation_id INTEGER,
                       role TEXT,
                       content TEXT,
                       created_at REAL,
                       emotion TEXT DEFAULT '',
                       pinned INTEGER DEFAULT 0,
                       reaction TEXT DEFAULT '',
                       reply_to INTEGER,
                       edited INTEGER DEFAULT 0,
                       meta TEXT DEFAULT '{}'
                   )"""
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id)")
            c.execute(
                """CREATE TABLE IF NOT EXISTS memories (
                       id INTEGER PRIMARY KEY,
                       kind TEXT,
                       content TEXT UNIQUE,
                       importance REAL,
                       created_at REAL,
                       last_accessed REAL,
                       access_count INTEGER DEFAULT 0,
                       favorite INTEGER DEFAULT 0,
                       tags TEXT DEFAULT '[]',
                       source TEXT DEFAULT 'conversation'
                   )"""
            )
            c.execute(
                """CREATE TABLE IF NOT EXISTS people (
                       id INTEGER PRIMARY KEY,
                       name TEXT UNIQUE,
                       relation TEXT DEFAULT '',
                       notes TEXT DEFAULT '',
                       voice_id TEXT DEFAULT '',
                       face_id TEXT DEFAULT '',
                       first_seen REAL,
                       last_seen REAL,
                       interactions INTEGER DEFAULT 0
                   )"""
            )
            c.execute(
                """CREATE TABLE IF NOT EXISTS reminders (
                       id INTEGER PRIMARY KEY,
                       text TEXT,
                       due_at REAL,
                       created_at REAL,
                       done INTEGER DEFAULT 0
                   )"""
            )
            try:
                c.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(content, tags, content='memories', content_rowid='id')"
                )
                c.execute(
                    """CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                         INSERT INTO memories_fts(rowid, content, tags) VALUES (new.id, new.content, new.tags);
                       END"""
                )
                c.execute(
                    """CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                         INSERT INTO memories_fts(memories_fts, rowid, content, tags) VALUES ('delete', old.id, old.content, old.tags);
                       END"""
                )
                c.execute(
                    """CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                         INSERT INTO memories_fts(memories_fts, rowid, content, tags) VALUES ('delete', old.id, old.content, old.tags);
                         INSERT INTO memories_fts(rowid, content, tags) VALUES (new.id, new.content, new.tags);
                       END"""
                )
                c.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(content, content='messages', content_rowid='id')"
                )
                c.execute(
                    """CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                         INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
                       END"""
                )
                c.execute(
                    """CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
                         INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.id, old.content);
                       END"""
                )
                c.execute(
                    """CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
                         INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.id, old.content);
                         INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
                       END"""
                )
                self._fts = True
            except sqlite3.OperationalError:
                log.info("SQLite FTS5 unavailable; using LIKE search")
                self._fts = False

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass

    def reopen(self) -> None:
        """Re-attach to the database file (after self-repair restored/replaced it)."""
        with self._lock:
            self.close()
            self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._init_schema()

    def healthy(self) -> bool:
        with self._lock:
            try:
                return self._conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            except sqlite3.Error:
                return False

    # ------------------------------------------------------- conversations
    def new_conversation(self, title: str = "", folder: str = "") -> int:
        now = time.time()
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO conversations(title, folder, created_at, updated_at) VALUES (?,?,?,?)",
                (title or time.strftime("%d %b %Y, %H:%M"), folder, now, now),
            )
            return int(cur.lastrowid)

    def conversations(self, folder: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            if folder is None:
                rows = self._conn.execute("SELECT * FROM conversations ORDER BY updated_at DESC").fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM conversations WHERE folder=? ORDER BY updated_at DESC", (folder,)
                ).fetchall()
            return [dict(r) for r in rows]

    def rename_conversation(self, conversation_id: int, title: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE conversations SET title=? WHERE id=?", (title, conversation_id))

    def move_conversation(self, conversation_id: int, folder: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE conversations SET folder=? WHERE id=?", (folder, conversation_id))

    def folders(self) -> List[str]:
        with self._lock:
            rows = self._conn.execute("SELECT DISTINCT folder FROM conversations WHERE folder<>'' ORDER BY folder").fetchall()
            return [r[0] for r in rows]

    def delete_conversation(self, conversation_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM messages WHERE conversation_id=?", (conversation_id,))
            self._conn.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))

    # ------------------------------------------------------------ messages
    def add_message(self, conversation_id: int, role: str, content: str, *, emotion: str = "",
                    reply_to: Optional[int] = None, meta: Optional[Dict[str, Any]] = None) -> int:
        now = time.time()
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO messages(conversation_id, role, content, created_at, emotion, reply_to, meta) VALUES (?,?,?,?,?,?,?)",
                (conversation_id, role, content, now, emotion, reply_to, json.dumps(meta or {})),
            )
            self._conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))
            return int(cur.lastrowid)

    def edit_message(self, message_id: int, content: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE messages SET content=?, edited=1 WHERE id=?", (content, message_id))

    def react(self, message_id: int, emoji: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE messages SET reaction=? WHERE id=?", (emoji, message_id))

    def pin(self, message_id: int, pinned: bool = True) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE messages SET pinned=? WHERE id=?", (1 if pinned else 0, message_id))

    def pinned(self, conversation_id: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._lock:
            if conversation_id is None:
                rows = self._conn.execute("SELECT * FROM messages WHERE pinned=1 ORDER BY id DESC").fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM messages WHERE pinned=1 AND conversation_id=? ORDER BY id DESC", (conversation_id,)
                ).fetchall()
            return [dict(r) for r in rows]

    def messages(self, conversation_id: int, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._lock:
            if limit:
                rows = self._conn.execute(
                    "SELECT * FROM (SELECT * FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?) ORDER BY id ASC",
                    (conversation_id, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM messages WHERE conversation_id=? ORDER BY id ASC", (conversation_id,)
                ).fetchall()
            return [dict(r) for r in rows]

    def thread(self, message_id: int) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE id=? OR reply_to=? ORDER BY id ASC", (message_id, message_id)
            ).fetchall()
            return [dict(r) for r in rows]

    def search_messages(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        query = query.strip()
        if not query:
            return []
        with self._lock:
            if self._fts:
                try:
                    rows = self._conn.execute(
                        "SELECT m.* FROM messages_fts f JOIN messages m ON m.id=f.rowid WHERE messages_fts MATCH ? ORDER BY rank LIMIT ?",
                        (_fts_query(query), limit),
                    ).fetchall()
                    return [dict(r) for r in rows]
                except sqlite3.OperationalError:
                    pass
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE content LIKE ? ORDER BY id DESC LIMIT ?", (f"%{query}%", limit)
            ).fetchall()
            return [dict(r) for r in rows]

    def message_count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0])

    # ------------------------------------------------------------ memories
    def remember(self, content: str, kind: str = "fact", importance: float = 0.5, *,
                 tags: Optional[Iterable[str]] = None, source: str = "conversation", favorite: bool = False) -> int:
        content = " ".join(content.split())
        if not content:
            return -1
        kind = kind if kind in KINDS else "note"
        importance = max(0.0, min(1.0, importance))
        tag_list = sorted(set(list(tags or []) + keywords(content, 8)))
        now = time.time()
        with self._lock, self._conn:
            existing = self._conn.execute("SELECT id, importance, access_count FROM memories WHERE content=?", (content,)).fetchone()
            if existing:
                # Re-learning the same thing makes it stick harder.
                new_importance = min(1.0, max(existing["importance"], importance) + 0.05)
                self._conn.execute(
                    "UPDATE memories SET importance=?, last_accessed=?, access_count=access_count+1, favorite=MAX(favorite, ?) WHERE id=?",
                    (new_importance, now, 1 if favorite else 0, existing["id"]),
                )
                return int(existing["id"])
            cur = self._conn.execute(
                "INSERT INTO memories(kind, content, importance, created_at, last_accessed, access_count, favorite, tags, source) VALUES (?,?,?,?,?,?,?,?,?)",
                (kind, content, importance, now, now, 0, 1 if favorite else 0, json.dumps(tag_list), source),
            )
            return int(cur.lastrowid)

    def _row_to_memory(self, row: sqlite3.Row, score: float = 0.0) -> Memory:
        return Memory(
            id=row["id"], kind=row["kind"], content=row["content"], importance=row["importance"],
            created_at=row["created_at"], last_accessed=row["last_accessed"], access_count=row["access_count"],
            favorite=bool(row["favorite"]), tags=json.loads(row["tags"] or "[]"), source=row["source"], score=score,
        )

    def recall(self, query: str, limit: int = 8, kinds: Optional[Sequence[str]] = None) -> List[Memory]:
        """Retrieve the most relevant memories for a query, boosting important and favourite ones."""
        terms = keywords(query, 12)
        candidates: Dict[int, Memory] = {}
        with self._lock:
            rows: List[sqlite3.Row] = []
            if terms and self._fts:
                try:
                    rows = self._conn.execute(
                        "SELECT m.*, bm25(memories_fts) AS r FROM memories_fts f JOIN memories m ON m.id=f.rowid WHERE memories_fts MATCH ? ORDER BY r LIMIT ?",
                        (" OR ".join(_fts_escape(t) for t in terms), limit * 4),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            if not rows and terms:
                clauses = " OR ".join("content LIKE ?" for _ in terms)
                rows = self._conn.execute(
                    f"SELECT * FROM memories WHERE {clauses} ORDER BY importance DESC LIMIT ?",
                    tuple(f"%{t}%" for t in terms) + (limit * 4,),
                ).fetchall()
            for row in rows:
                mem = self._row_to_memory(row)
                overlap = len(set(terms) & set(keywords(mem.content))) / max(1, len(terms))
                recency = math.exp(-(time.time() - mem.created_at) / (30 * 86400))
                mem.score = overlap * 2 + mem.importance + 0.3 * recency + (0.5 if mem.favorite else 0) + 0.02 * mem.access_count
                if kinds and mem.kind not in kinds:
                    continue
                candidates[mem.id] = mem
            ranked = sorted(candidates.values(), key=lambda m: m.score, reverse=True)[:limit]
            if ranked:
                now = time.time()
                with self._conn:
                    self._conn.executemany(
                        "UPDATE memories SET last_accessed=?, access_count=access_count+1 WHERE id=?",
                        [(now, m.id) for m in ranked],
                    )
            return ranked

    def important(self, limit: int = 12, kinds: Optional[Sequence[str]] = None) -> List[Memory]:
        with self._lock:
            if kinds:
                marks = ",".join("?" for _ in kinds)
                rows = self._conn.execute(
                    f"SELECT * FROM memories WHERE kind IN ({marks}) ORDER BY favorite DESC, importance DESC, access_count DESC LIMIT ?",
                    tuple(kinds) + (limit,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM memories ORDER BY favorite DESC, importance DESC, access_count DESC LIMIT ?", (limit,)
                ).fetchall()
            return [self._row_to_memory(r) for r in rows]

    def favorites(self, limit: int = 20) -> List[Memory]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE favorite=1 ORDER BY importance DESC, access_count DESC LIMIT ?", (limit,)
            ).fetchall()
            return [self._row_to_memory(r) for r in rows]

    def all_memories(self, kind: Optional[str] = None) -> List[Memory]:
        with self._lock:
            if kind:
                rows = self._conn.execute("SELECT * FROM memories WHERE kind=? ORDER BY created_at DESC", (kind,)).fetchall()
            else:
                rows = self._conn.execute("SELECT * FROM memories ORDER BY created_at DESC").fetchall()
            return [self._row_to_memory(r) for r in rows]

    def set_favorite(self, memory_id: int, favorite: bool = True) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE memories SET favorite=?, importance=MAX(importance, 0.8) WHERE id=?", (1 if favorite else 0, memory_id))

    def promote_favorites(self) -> int:
        """Memories that keep being recalled become favourites on their own."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE memories SET favorite=1 WHERE favorite=0 AND kind IN ('moment','event','person') AND access_count>=5 AND importance>=0.6"
            )
            return cur.rowcount

    def decay(self, per_day: float = 0.01) -> None:
        """Slowly fade unimportant, unused memories. Favourites never fade."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE memories SET importance=MAX(0.05, importance - ? * ((? - last_accessed)/86400.0)) WHERE favorite=0 AND (? - last_accessed) > 86400",
                (per_day, time.time(), time.time()),
            )

    def forget(self, query: str) -> int:
        """Section 2: he can forget on request. Returns number of memories removed."""
        terms = [t for t in keywords(query, 12) if t not in {"user", "that", "about"}]
        if not terms:
            return 0
        # Light stemming so "live" matches "lives", "playing" matches "play".
        stems = [_stem(t) for t in terms]
        with self._lock, self._conn:
            clauses = " AND ".join("lower(content) LIKE ?" for _ in stems)
            cur = self._conn.execute(f"DELETE FROM memories WHERE {clauses}", tuple(f"%{s}%" for s in stems))
            return cur.rowcount

    def forget_id(self, memory_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))

    def memory_count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])

    # ------------------------------------------------------------- people
    def remember_person(self, name: str, relation: str = "", notes: str = "", *, voice_id: str = "", face_id: str = "") -> None:
        now = time.time()
        with self._lock, self._conn:
            row = self._conn.execute("SELECT id, notes FROM people WHERE name=?", (name,)).fetchone()
            if row:
                merged_notes = row["notes"]
                if notes and notes not in merged_notes:
                    merged_notes = (merged_notes + "\n" + notes).strip()
                self._conn.execute(
                    "UPDATE people SET relation=COALESCE(NULLIF(?, ''), relation), notes=?, voice_id=COALESCE(NULLIF(?, ''), voice_id), face_id=COALESCE(NULLIF(?, ''), face_id), last_seen=?, interactions=interactions+1 WHERE id=?",
                    (relation, merged_notes, voice_id, face_id, now, row["id"]),
                )
            else:
                self._conn.execute(
                    "INSERT INTO people(name, relation, notes, voice_id, face_id, first_seen, last_seen, interactions) VALUES (?,?,?,?,?,?,?,1)",
                    (name, relation, notes, voice_id, face_id, now, now),
                )
        relation_text = f"the user's {relation}" if relation else "someone the user knows"
        self.remember(f"{name} is {relation_text}." + (f" {notes}" if notes else ""), "person", 0.8, tags=[name.lower()])

    def people(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute("SELECT * FROM people ORDER BY interactions DESC").fetchall()]

    def person(self, name: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM people WHERE lower(name)=lower(?)", (name,)).fetchone()
            return dict(row) if row else None

    # ----------------------------------------------------------- reminders
    def add_reminder(self, text: str, due_at: float) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO reminders(text, due_at, created_at) VALUES (?,?,?)", (text, due_at, time.time())
            )
            return int(cur.lastrowid)

    def due_reminders(self) -> List[Dict[str, Any]]:
        with self._lock, self._conn:
            rows = self._conn.execute("SELECT * FROM reminders WHERE done=0 AND due_at<=?", (time.time(),)).fetchall()
            ids = [r["id"] for r in rows]
            if ids:
                self._conn.executemany("UPDATE reminders SET done=1 WHERE id=?", [(i,) for i in ids])
            return [dict(r) for r in rows]

    def pending_reminders(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute("SELECT * FROM reminders WHERE done=0 ORDER BY due_at").fetchall()]

    # ------------------------------------------------------------- export
    def export(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "exported_at": now_iso(),
                "conversations": self.conversations(),
                "messages": [dict(r) for r in self._conn.execute("SELECT * FROM messages ORDER BY id").fetchall()],
                "memories": [m.to_dict() for m in self.all_memories()],
                "people": self.people(),
                "reminders": [dict(r) for r in self._conn.execute("SELECT * FROM reminders").fetchall()],
            }

    def wipe(self) -> None:
        """Section 10G: Delete All Data."""
        with self._lock, self._conn:
            for table in ("messages", "conversations", "memories", "people", "reminders"):
                self._conn.execute(f"DELETE FROM {table}")

    def size_bytes(self) -> int:
        try:
            total = self.path.stat().st_size
            wal = self.path.with_name(self.path.name + "-wal")
            if wal.exists():
                total += wal.stat().st_size
            return total
        except OSError:
            return 0

    # --------------------------------------------------------- summarising
    def profile_fragment(self, query: str = "", limit: int = 14) -> str:
        """Compose the "what you know about them" block for the prompt."""
        picked: Dict[int, Memory] = {}
        for mem in self.important(limit // 2, kinds=("person", "preference", "fact", "goal", "correction")):
            picked[mem.id] = mem
        if query:
            for mem in self.recall(query, limit=limit // 2):
                picked[mem.id] = mem
        for mem in self.favorites(3):
            picked[mem.id] = mem
        lines = []
        for mem in list(picked.values())[:limit]:
            star = " (favorite memory)" if mem.favorite else ""
            lines.append(f"- [{mem.kind}] {truncate(mem.content, 220)}{star}")
        return "\n".join(lines)


def _stem(word: str) -> str:
    word = word.lower()
    for suffix in ("ing", "es", "ed", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _fts_escape(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def _fts_query(query: str) -> str:
    terms = keywords(query, 12) or [query]
    return " OR ".join(_fts_escape(t) for t in terms)
