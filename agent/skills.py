"""Agent skill 动态加载。

Skill 是给 simple loop 的可复用能力说明，默认是 Markdown 文件：

---
id: scarce_repair
name: 稀缺场景修复
description: 只改稀缺场景，保持正常场景不变。
triggers: scarce, 稀缺, backup
---

正文会在 skill 被选中时注入 prompt。为了控制上下文，loop 会先预加载
description/triggers，只有匹配到的 skill 才加载完整正文。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent / "skills"


@dataclass
class Skill:
    id: str
    name: str
    description: str
    scope: str
    triggers: list[str]
    path: Path
    body: str = ""

    def catalog_line(self) -> str:
        trig = ", ".join(self.triggers[:6])
        return f"- {self.id}: [{self.scope}] {self.name} — {self.description} (triggers: {trig})"


def _infer_scope(sid: str) -> str:
    if sid in {"scarce_repair", "online_result_iteration"}:
        return "project"
    if sid in {"self_extend_skill"}:
        return "system"
    return "generic"


def _parse_skill_file(path: Path, *, load_body: bool) -> Skill | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    meta: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end >= 0:
            raw_meta = text[3:end].strip()
            body = text[end + 4:].lstrip()
            for line in raw_meta.splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                meta[key.strip().lower()] = value.strip()

    sid = meta.get("id") or path.stem
    name = meta.get("name") or sid
    desc = meta.get("description") or ""
    scope = (meta.get("scope") or _infer_scope(sid)).strip().lower()
    triggers = [
        t.strip().lower()
        for t in (meta.get("triggers") or "").replace("，", ",").split(",")
        if t.strip()
    ]
    return Skill(
        id=sid,
        name=name,
        description=desc,
        scope=scope,
        triggers=triggers,
        path=path,
        body=body.strip() if load_body else "",
    )


def discover_skills(skills_dir: Path | None = None) -> list[Skill]:
    """预加载 skill 描述，不加载正文。"""
    root = skills_dir or DEFAULT_SKILLS_DIR
    if not root.exists():
        return []
    skills = []
    for path in sorted(root.glob("*.md")):
        skill = _parse_skill_file(path, load_body=False)
        if skill:
            skills.append(skill)
    return skills


def load_skill(skill: Skill) -> Skill:
    full = _parse_skill_file(skill.path, load_body=True)
    return full or skill


def select_skills(
    catalog: list[Skill],
    *,
    text: str,
    explicit_ids: list[str] | None = None,
    max_skills: int = 2,
) -> list[Skill]:
    """根据上下文关键词选择 skill，并支持 CLI 显式指定。"""
    explicit = set(explicit_ids or [])
    chosen: list[Skill] = []
    by_id = {s.id: s for s in catalog}

    for sid in explicit:
        if sid in by_id:
            chosen.append(load_skill(by_id[sid]))

    low = text.lower()
    scored: list[tuple[int, Skill]] = []
    for skill in catalog:
        if skill.id in explicit:
            continue
        score = 0
        for token in [skill.id.lower(), skill.name.lower(), *skill.triggers]:
            if token and token in low:
                score += 1
        if score:
            scored.append((score, skill))
    scored.sort(key=lambda x: x[0], reverse=True)

    for _score, skill in scored:
        if len(chosen) >= max_skills:
            break
        chosen.append(load_skill(skill))
    return chosen[:max_skills]


def format_skill_catalog(skills: list[Skill]) -> str:
    if not skills:
        return "无可用 skill。"
    return "\n".join(s.catalog_line() for s in skills)


def format_selected_skills(skills: list[Skill], *, max_chars: int = 9000) -> str:
    parts = []
    for skill in skills:
        parts.append(f"## Skill: {skill.id} — {skill.name}\n{skill.body}")
    text = "\n\n".join(parts).strip()
    if len(text) > max_chars:
        return text[:max_chars].rstrip() + "\n..."
    return text


def write_skill(
    skills_dir: Path,
    *,
    sid: str,
    name: str,
    description: str,
    triggers: list[str],
    body: str,
    scope: str = "generic",
) -> Path:
    """写入一个新 skill 文件。只在显式允许时由外层调用。"""
    skills_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in sid).strip("_")
    if not safe:
        raise ValueError("skill id 为空")
    path = skills_dir / f"{safe}.md"
    header = (
        "---\n"
        f"id: {safe}\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"scope: {scope or 'generic'}\n"
        f"triggers: {', '.join(triggers)}\n"
        "---\n\n"
    )
    path.write_text(header + body.strip() + "\n", encoding="utf-8")
    return path
