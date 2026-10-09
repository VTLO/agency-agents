"""Compile The Agency's agent files into lightweight skills, and route to them.

Each agent markdown (often 3-8k tokens) becomes:
  * a *card*  (~40 tokens): slug, name, category, one-line description —
    the only thing the planner ever sees, and only for a shortlist;
  * a *lite prompt* (<= J3_SKILL_PROMPT_TOKENS): identity, mission, rules and
    workflow with code samples, emoji and boilerplate stripped — loaded only
    when a step actually runs, and sent as a cached system block.

Routing is local BM25 (zero LLM tokens): the brief's English keywords select
the shortlist handed to the planner.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

CATEGORIES = (
    "academic", "design", "engineering", "game-development", "marketing",
    "paid-media", "product", "project-management", "sales", "spatial-computing",
    "specialized", "support", "testing",
)

# Higher = kept first when the lite prompt is truncated; 0 = dropped.
SECTION_PRIORITY = [  # first match wins
    (re.compile(r"example|template|communication style|learning|memory|advanced|capabilit", re.I), 0),
    (re.compile(r"critical|rules|must|never", re.I), 5),
    (re.compile(r"mission|responsib|core", re.I), 4),
    (re.compile(r"identity|who you are|role", re.I), 3),
    (re.compile(r"workflow|process|method|approach", re.I), 3),
    (re.compile(r"deliverable|output|format", re.I), 2),
    (re.compile(r"success|metric", re.I), 1),
]

STOP = set(
    """a an and are as at be by for from has have in into is it its of on or that the
    their this to with you your who what when how all any can more most not our than
    then they will via using use used based expert specialist specializing specialized
    agent agents across build builds building help helps ensure ensures make makes
    without within while also both each every other such over under""".split()
)
_TOKEN = re.compile(r"[a-z][a-z0-9+#.-]{1,}")
_CODE = re.compile(r"```.*?```", re.S)
_FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


@dataclass
class Skill:
    slug: str
    name: str
    cat: str
    desc: str
    kw: list[str]
    prompt: str  # lite prompt, loaded only at execution time

    def card(self) -> str:
        """Single-line card for the planner (~30-50 tokens)."""
        return f"{self.slug}|{self.cat}|{self.desc}"


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _strip_symbols(text: str) -> str:
    return "".join(ch for ch in text if unicodedata.category(ch) not in {"So", "Sk", "Cs"} and ch != "️")


def _frontmatter(raw: str) -> tuple[dict, str]:
    m = _FRONT.match(raw)
    if not m:
        return {}, raw
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip("\"'")
    return meta, raw[m.end():]


def compress_body(body: str, max_tokens: int) -> str:
    """Keep the highest-value sections of an agent prompt within a token cap."""
    body = _CODE.sub("", body)
    body = _strip_symbols(body)
    body = re.sub(r"\*\*(.+?)\*\*", r"\1", body)
    sections: list[tuple[int, int, str]] = []  # (priority, original order, text)
    for order, chunk in enumerate(re.split(r"\n(?=#{1,3} )", body)):
        lines = [ln.rstrip() for ln in chunk.strip().splitlines()]
        lines = [ln for ln in lines if ln.strip() and not re.fullmatch(r"[-=|: ]+", ln.strip())]
        if not lines:
            continue
        head = lines[0]
        if head.startswith("# ") and order == 0 and len(lines) == 1:
            continue
        prio = 2
        for rx, p in SECTION_PRIORITY:
            if rx.search(head):
                prio = p
                break
        if prio == 0:
            continue
        text = "\n".join(re.sub(r"[ \t]+", " ", ln) for ln in lines)
        sections.append((prio, order, text))

    budget = int(max_tokens * 3.6)
    kept: list[tuple[int, str]] = []
    for prio, order, text in sorted(sections, key=lambda s: (-s[0], s[1])):
        if budget <= 0:
            break
        if len(text) > budget:
            cut = text[:budget].rsplit("\n", 1)[0]
            if len(cut) < 80:
                break
            text = cut
        kept.append((order, text))
        budget -= len(text) + 1
    return "\n".join(t for _, t in sorted(kept))


def _keywords(*texts: str, n: int = 14) -> list[str]:
    counts = Counter(
        t.strip(".-") for txt in texts for t in _TOKEN.findall(txt.lower()) if t.strip(".-") not in STOP and len(t) > 2
    )
    return [w for w, _ in counts.most_common(n)]


def compile_skill(path: Path, cat: str, max_tokens: int) -> Skill | None:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    meta, body = _frontmatter(raw)
    if not meta.get("name") or not meta.get("description"):
        return None
    desc = _strip_symbols(meta["description"]).strip()
    heads = " ".join(re.findall(r"^#{2,3} (.+)$", body, re.M))
    return Skill(
        slug=slugify(meta["name"]),
        name=meta["name"],
        cat=cat,
        desc=desc if len(desc) <= 180 else desc[:180].rsplit(" ", 1)[0] + "…",
        kw=_keywords(meta["name"], desc, desc, meta.get("vibe", ""), heads),
        prompt=compress_body(body, max_tokens),
    )


class SkillRegistry:
    def __init__(self, skills: list[Skill]):
        self.skills = {s.slug: s for s in skills}
        self._docs = {s.slug: _TOKEN.findall(f"{s.name} {s.cat} {s.desc} {' '.join(s.kw)}".lower()) for s in skills}
        self._avgdl = sum(map(len, self._docs.values())) / max(1, len(self._docs))
        df: Counter = Counter()
        for toks in self._docs.values():
            df.update(set(toks))
        n = len(self._docs)
        self._idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def __contains__(self, slug: str) -> bool:
        return slug in self.skills

    def __len__(self) -> int:
        return len(self.skills)

    def get(self, slug: str) -> Skill:
        return self.skills[slug]

    def route(self, query: str, k: int = 10, k1: float = 1.4, b: float = 0.75) -> list[Skill]:
        """BM25 shortlist of skills for a query (English keywords work best)."""
        q = [t.strip(".-") for t in _TOKEN.findall(query.lower()) if t not in STOP]
        scores: list[tuple[float, str]] = []
        for slug, toks in self._docs.items():
            tf = Counter(toks)
            dl = len(toks)
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self._idf.get(t, 0) * f * (k1 + 1) / (f + k1 * (1 - b + b * dl / self._avgdl))
            if s > 0:
                scores.append((s, slug))
        scores.sort(reverse=True)
        return [self.skills[slug] for _, slug in scores[:k]]

    # --- persistence --------------------------------------------------------
    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([asdict(s) for s in self.skills.values()], ensure_ascii=False))

    @classmethod
    def load(cls, path: Path) -> "SkillRegistry":
        return cls([Skill(**d) for d in json.loads(path.read_text())])

    @classmethod
    def compile(cls, root: Path, max_tokens: int = 900) -> "SkillRegistry":
        skills: dict[str, Skill] = {}
        for cat in CATEGORIES:
            base = root / cat
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*.md")):
                sk = compile_skill(path, cat, max_tokens)
                if sk and sk.slug not in skills:
                    skills[sk.slug] = sk
        if not skills:
            raise FileNotFoundError(f"no agent files found under {root}")
        return cls(list(skills.values()))

    @classmethod
    def open(cls, root: Path, cache: Path, max_tokens: int = 900) -> "SkillRegistry":
        """Load the compiled cache, recompiling when any agent file is newer."""
        newest = max((p.stat().st_mtime for c in CATEGORIES if (root / c).is_dir() for p in (root / c).rglob("*.md")), default=0)
        if cache.exists() and cache.stat().st_mtime >= newest:
            return cls.load(cache)
        reg = cls.compile(root, max_tokens)
        reg.save(cache)
        return reg
