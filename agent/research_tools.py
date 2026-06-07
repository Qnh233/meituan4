"""离线研究工具。

这些工具只服务 AutoResearch Agent 的离线 loop，严禁把联网或文件调研逻辑带入
线上提交的 solver.py。
"""

from __future__ import annotations

import html
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
PAPERS_DIR = REPO_ROOT / "papers"


class _TextHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            text = data.strip()
            if text:
                self.parts.append(text)

    def text(self) -> str:
        return " ".join(self.parts)


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _tokenize(query: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[A-Za-z0-9_\-\u4e00-\u9fff]+", query) if len(t) > 1]


def read_local_papers(query: str, *, max_files: int = 6, max_chars: int = 6000) -> dict[str, Any]:
    """检索 papers/*.txt，返回相关片段。"""
    terms = _tokenize(query)
    if not terms:
        terms = ["set", "packing", "heuristic", "search"]

    hits = []
    for path in sorted(PAPERS_DIR.glob("*.txt")):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        low = text.lower()
        score = sum(low.count(t) for t in terms)
        if score <= 0:
            continue

        snippets = []
        for term in terms:
            idx = low.find(term)
            if idx >= 0:
                start = max(0, idx - 450)
                end = min(len(text), idx + 900)
                snippets.append(_clip(text[start:end], 1200))
            if len(snippets) >= 2:
                break
        hits.append({
            "file": str(path.relative_to(REPO_ROOT)),
            "score": score,
            "snippets": snippets,
        })

    hits.sort(key=lambda x: x["score"], reverse=True)
    summary_lines = []
    for h in hits[:max_files]:
        summary_lines.append(f"- {h['file']} score={h['score']}")
        for s in h["snippets"]:
            summary_lines.append(f"  {s}")

    return {
        "tool": "read_local_papers",
        "query": query,
        "items": hits[:max_files],
        "summary": _clip("\n".join(summary_lines), max_chars),
    }


def arxiv_search(query: str, *, max_results: int = 5, timeout: float = 20.0) -> dict[str, Any]:
    """通过 arXiv Atom API 搜索论文。"""
    params = urllib.parse.urlencode({
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    })
    url = f"https://export.arxiv.org/api/query?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "meituan4-agent/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except Exception as e:
        return {
            "tool": "arxiv_search",
            "query": query,
            "error": f"{type(e).__name__}: {e}",
            "items": [],
            "summary": "",
        }

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        return {
            "tool": "arxiv_search",
            "query": query,
            "error": f"ParseError: {e}",
            "items": [],
            "summary": "",
        }

    items = []
    for entry in root.findall("atom:entry", ns):
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        abstract = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip()
        published = (entry.findtext("atom:published", default="", namespaces=ns) or "").strip()
        link = ""
        for link_node in entry.findall("atom:link", ns):
            if link_node.attrib.get("rel") == "alternate":
                link = link_node.attrib.get("href", "")
                break
        items.append({
            "title": _clip(title, 300),
            "published": published[:10],
            "url": link,
            "abstract": _clip(abstract, 1200),
        })

    lines = []
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. {item['title']} ({item['published']}) {item['url']}")
        lines.append(f"   {item['abstract']}")
    return {
        "tool": "arxiv_search",
        "query": query,
        "items": items,
        "summary": _clip("\n".join(lines), 7000),
    }


def web_fetch_url(url: str, *, timeout: float = 20.0, max_chars: int = 7000) -> dict[str, Any]:
    """抓取指定 URL 文本。只支持已知 URL，不做泛搜索。"""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return {
            "tool": "web_fetch_url",
            "url": url,
            "error": "只支持 http/https URL",
            "summary": "",
        }

    req = urllib.request.Request(url, headers={"User-Agent": "meituan4-agent/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(2_000_000)
            content_type = resp.headers.get("content-type", "")
    except Exception as e:
        return {
            "tool": "web_fetch_url",
            "url": url,
            "error": f"{type(e).__name__}: {e}",
            "summary": "",
        }

    text = raw.decode("utf-8", errors="ignore")
    if "html" in content_type.lower() or "<html" in text[:500].lower():
        parser = _TextHTMLParser()
        parser.feed(text)
        text = parser.text()
    text = html.unescape(text)
    return {
        "tool": "web_fetch_url",
        "url": url,
        "content_type": content_type,
        "summary": _clip(text, max_chars),
    }


def format_research_result(result: dict[str, Any]) -> str:
    """把工具结果压缩成可写入 prompt / markdown 的文本。"""
    header = f"### {result.get('tool', 'research')} — {result.get('query') or result.get('url') or ''}"
    if result.get("error"):
        return f"{header}\nERROR: {result['error']}\n"
    body = result.get("summary") or ""
    return f"{header}\n{body}\n"


def append_research_markdown(run_dir: Path, result: dict[str, Any]) -> None:
    path = run_dir / "research.md"
    chunk = (
        f"\n## {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"{format_research_result(result)}\n"
    )
    with open(path, "a", encoding="utf-8") as f:
        f.write(chunk)
