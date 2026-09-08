"""Web search & deep research (Constitution sections 5A and 5B).

The Constitution says: zero APIs, but internet *research* with permission
is fine — "if it uses the internet, it's for research only, not to phone
home". So Vidit uses plain HTTPS to a privacy-friendly public search page
(DuckDuckGo's HTML endpoint, no key, no tracking cookies) and fetches pages
directly. Every search is checked against the INTERNET permission and
logged locally. Nothing about *you* is sent — only the query.
"""
from __future__ import annotations

import html
import json
import logging
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urlparse

from ..guardian import Capability
from ..utils import truncate
from .base import Tool, ToolContext, ToolResult

log = logging.getLogger("vidit.tools.web")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Vidit/0.1 (local research assistant)"

# Rough credibility heuristics for "Source Evaluation" (5B).
_TRUSTED_TLDS = (".gov", ".edu", ".ac.in", ".nic.in", ".org")
_TRUSTED_HOSTS = ("wikipedia.org", "arxiv.org", "nature.com", "who.int", "nih.gov", "docs.python.org",
                  "developer.mozilla.org", "stackoverflow.com", "github.com", "bbc.com", "reuters.com",
                  "thehindu.com", "indianexpress.com")
_LOW_TRUST_HINTS = ("blogspot", "wordpress.com", "medium.com/@", "quora.com", "pinterest", "answers.com")


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    credibility: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


class _TextExtractor(HTMLParser):
    """Very small readable-text extractor (no external dependencies)."""

    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe"}

    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.parts: List[str] = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in ("p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        lines = [" ".join(line.split()) for line in raw.splitlines()]
        return "\n".join(l for l in lines if l)


def credibility(url: str) -> float:
    host = urlparse(url).netloc.lower()
    score = 0.5
    if any(host.endswith(t) for t in _TRUSTED_TLDS):
        score += 0.25
    if any(h in host for h in _TRUSTED_HOSTS):
        score += 0.3
    if any(h in url.lower() for h in _LOW_TRUST_HINTS):
        score -= 0.2
    if url.startswith("https://"):
        score += 0.05
    return max(0.05, min(0.99, round(score, 2)))


class WebSearch:
    def __init__(self, log_path: Optional[Path] = None, timeout: float = 15.0):
        self.log_path = log_path
        self.timeout = timeout

    # ------------------------------------------------------------- search
    def search(self, query: str, limit: int = 8) -> List[SearchHit]:
        import requests

        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=self.timeout)
            r.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            log.warning("web search failed: %s", exc)
            self._log(query, [], error=str(exc))
            return []
        hits = self._parse_ddg(r.text)[:limit]
        self._log(query, hits)
        return hits

    @staticmethod
    def _parse_ddg(page: str) -> List[SearchHit]:
        hits: List[SearchHit] = []
        for block in re.finditer(r'<a rel="nofollow" class="result__a" href="(.*?)">(.*?)</a>(.*?)(?=<div class="result |$)', page, re.DOTALL):
            href, title_html, rest = block.groups()
            href = html.unescape(href)
            if "uddg=" in href:
                from urllib.parse import parse_qs, unquote
                q = parse_qs(urlparse(href).query).get("uddg")
                if q:
                    href = unquote(q[0])
            snippet_match = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', rest, re.DOTALL)
            snippet = re.sub(r"<[^>]+>", "", snippet_match.group(1)) if snippet_match else ""
            title = re.sub(r"<[^>]+>", "", title_html)
            if href.startswith("http"):
                hits.append(SearchHit(html.unescape(title).strip(), href, html.unescape(snippet).strip(), credibility(href)))
        return hits

    # -------------------------------------------------------------- fetch
    def fetch(self, url: str, max_chars: int = 12000) -> Dict[str, Any]:
        import requests

        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=self.timeout)
            r.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            return {"url": url, "ok": False, "error": str(exc), "text": "", "title": ""}
        ctype = r.headers.get("content-type", "")
        if "html" in ctype or r.text.lstrip().startswith("<"):
            parser = _TextExtractor()
            try:
                parser.feed(r.text)
            except Exception:  # noqa: BLE001
                pass
            return {"url": url, "ok": True, "title": parser.title.strip(), "text": parser.text()[:max_chars]}
        return {"url": url, "ok": True, "title": url, "text": r.text[:max_chars]}

    def _log(self, query: str, hits: List[SearchHit], error: str = "") -> None:
        if not self.log_path:
            return
        try:
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"t": time.time(), "q": query, "n": len(hits), "error": error}) + "\n")
        except OSError:
            pass


@dataclass
class ResearchReport:
    topic: str
    summary: str
    sources: List[SearchHit] = field(default_factory=list)
    citations: List[str] = field(default_factory=list)
    follow_ups: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def markdown(self) -> str:
        out = [f"# Research: {self.topic}", "", self.summary, ""]
        if self.sources:
            out.append("## Sources (credibility)")
            for i, s in enumerate(self.sources, 1):
                out.append(f"{i}. [{s.title or s.url}]({s.url}) — {s.credibility:.0%}")
        if self.citations:
            out += ["", "## Citations"] + [f"- {c}" for c in self.citations]
        if self.follow_ups:
            out += ["", "## Follow-up questions"] + [f"- {q}" for q in self.follow_ups]
        return "\n".join(out)


class DeepResearch:
    """Multi-step research: search → pick credible sources → read → synthesise → cite."""

    def __init__(self, web: WebSearch, llm, exports_dir: Optional[Path] = None):
        self.web = web
        self.llm = llm
        self.exports_dir = exports_dir

    def run(self, topic: str, max_sources: int = 4, progress=None) -> ResearchReport:
        progress = progress or (lambda msg: None)
        progress(f"Searching for '{topic}'…")
        hits = self.web.search(topic, limit=10)
        if not hits:
            return ResearchReport(topic, "I couldn't reach the web or found nothing. Maybe try a different phrasing?")
        hits.sort(key=lambda h: h.credibility, reverse=True)
        chosen = hits[:max_sources]
        notes: List[str] = []
        for hit in chosen:
            progress(f"Reading {urlparse(hit.url).netloc}…")
            page = self.web.fetch(hit.url)
            if page["ok"] and page["text"]:
                digest = self.llm.quick(
                    f"Topic: {topic}\nSource: {hit.url}\n\n{page['text'][:6000]}\n\nExtract the facts relevant to the topic as bullet points. Be faithful; no speculation.",
                    "You are a careful research assistant.", max_tokens=400,
                )
                notes.append(f"Source: {hit.url}\n{digest}")
        progress("Writing the report…")
        joined = "\n\n".join(notes) if notes else "\n".join(f"- {h.title}: {h.snippet}" for h in chosen)
        summary = self.llm.quick(
            f"Topic: {topic}\n\nNotes from sources:\n{joined}\n\nWrite a clear, well-structured summary (use headings and bullets where helpful). Mention disagreements between sources if any. Reference sources as [1], [2]… in the order given.",
            "You are Vidit writing a research summary for your brother. Be concise but complete.", max_tokens=900,
        )
        follow = self.llm.json(
            f"Topic: {topic}\nSummary: {summary[:2000]}\n\nReturn a JSON list of 3 short follow-up research questions.",
            default=[], max_tokens=200,
        )
        citations = [f"[{i}] {h.title or h.url}. {h.url} (accessed {time.strftime('%Y-%m-%d')})" for i, h in enumerate(chosen, 1)]
        report = ResearchReport(topic, summary, chosen, citations, [str(q) for q in follow] if isinstance(follow, list) else [], notes)
        if self.exports_dir:
            try:
                self.exports_dir.mkdir(parents=True, exist_ok=True)
                fname = self.exports_dir / f"research-{int(time.time())}.md"
                fname.write_text(report.markdown(), encoding="utf-8")
            except OSError:
                pass
        return report


def make_web_tools(web: WebSearch, research: DeepResearch) -> List[Tool]:
    def _search(args: str, ctx: ToolContext) -> ToolResult:
        if not ctx.permissions.check(Capability.INTERNET, f"to search the web for '{truncate(args, 60)}'"):
            return ToolResult(False, "You haven't allowed me to go online right now.")
        hits = web.search(args)
        if not hits:
            return ToolResult(False, "The web search returned nothing (offline or blocked).")
        lines = [f"{i}. {h.title} — {h.url} (credibility {h.credibility:.0%})\n   {h.snippet}" for i, h in enumerate(hits, 1)]
        return ToolResult(True, "\n".join(lines), {"hits": [h.to_dict() for h in hits]})

    def _fetch(args: str, ctx: ToolContext) -> ToolResult:
        if not ctx.permissions.check(Capability.INTERNET, f"to open {truncate(args, 60)}"):
            return ToolResult(False, "You haven't allowed me to go online right now.")
        page = web.fetch(args.strip())
        if not page["ok"]:
            return ToolResult(False, f"Couldn't open the page: {page.get('error')}")
        return ToolResult(True, f"{page['title']}\n\n{page['text'][:6000]}")

    def _research(args: str, ctx: ToolContext) -> ToolResult:
        if not ctx.permissions.check(Capability.INTERNET, f"to research '{truncate(args, 60)}' across several sites"):
            return ToolResult(False, "You haven't allowed me to go online right now.")
        report = research.run(args, progress=lambda m: ctx.say(m))
        return ToolResult(True, report.markdown(), {"sources": [s.to_dict() for s in report.sources]})

    return [
        Tool("web_search", "Search the internet (asks permission).", "search query", _search),
        Tool("open_url", "Read a web page.", "https://…", _fetch),
        Tool("deep_research", "Multi-source research with credibility ratings, citations and follow-ups.", "topic", _research),
    ]
