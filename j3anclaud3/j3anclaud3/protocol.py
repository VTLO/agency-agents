"""Compact machine protocol shared by the planner, the executor and the workers.

Humans only ever see French text rendered by J3anClaud3. Everything that travels
between machine components is terse English JSON with one/two-letter keys:
English tokenizes ~20-30% cheaper than French, and short keys keep the
per-step overhead to a few dozen tokens.

Plan (produced by the planner, frozen once proposed):
    {"g":  goal, terse EN
     "fr": one-sentence goal in French (shown to humans)
     "lang": deliverable language, default "fr"
     "s": [ {"i": "s1",            step id
             "k": "backend-architect",  skill slug
             "t": "Titre FR",      short French title for humans
             "do": "...",          terse EN instruction for the worker
             "in": ["s0"],         dependency step ids
             "ctx": "d" | "f",     pass dependencies as digest (d) or full text (f)
             "m": "L" | "S" | "M", model tier
             "b": 3000,            output token budget for the step
             "dl": true,           is a deliverable sent to humans
             "out": "file.md"} ],  deliverable file name
     "h": ["hypothesis FR", ...]}  assumptions humans must confirm

Worker output = deliverable markdown, then a line DIGEST_MARK, then
{"s": "<=60 word summary", "k": ["key fact", ...]}. Only the digest flows to
dependent steps unless the plan asks for full context ("ctx": "f").
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass

DIGEST_MARK = "§DIGEST§"
TIERS = ("L", "S", "M")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.S)


class PlanError(ValueError):
    pass


def est_tokens(text: str) -> int:
    """Cheap local token estimate (no API call): ~3.6 chars/token."""
    return max(1, int(len(text) / 3.6))


def dumps(obj) -> str:
    """Canonical compact JSON: stable bytes keep prompt caches warm."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def extract_json(text: str) -> dict:
    """Parse the first JSON object in an LLM reply (tolerates code fences/prose)."""
    text = _FENCE.sub("", text.strip())
    start = text.find("{")
    if start < 0:
        raise PlanError("no JSON object in reply")
    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(text[start:], start):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError as e:
                    raise PlanError(f"invalid JSON: {e}") from e
    raise PlanError("unterminated JSON object")


def plan_hash(plan: dict) -> str:
    return hashlib.sha256(dumps(plan).encode()).hexdigest()[:10]


def _slug_file(name: str, fallback: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name or "").strip("-.")
    if not name:
        name = fallback
    return name if name.endswith(".md") else name + ".md"


def validate_plan(plan: dict, known_skills: set[str], max_steps: int, max_step_budget: int = 32000) -> dict:
    """Normalise and validate a planner reply. Raises PlanError on bad structure."""
    if not isinstance(plan, dict) or not isinstance(plan.get("s"), list) or not plan["s"]:
        raise PlanError("plan must contain a non-empty step list 's'")
    steps = plan["s"]
    if len(steps) > max_steps:
        raise PlanError(f"too many steps ({len(steps)} > {max_steps})")

    ids: list[str] = []
    for n, st in enumerate(steps, 1):
        if not isinstance(st, dict):
            raise PlanError("each step must be an object")
        st["i"] = str(st.get("i") or f"s{n}")
        if st["i"] in ids:
            raise PlanError(f"duplicate step id {st['i']}")
        ids.append(st["i"])
        if st.get("k") not in known_skills:
            raise PlanError(f"unknown skill '{st.get('k')}' in step {st['i']}")
        if not st.get("do"):
            raise PlanError(f"step {st['i']} has no instruction")
        st["t"] = str(st.get("t") or st["do"])[:80]
        st["in"] = [str(d) for d in st.get("in") or []]
        st["ctx"] = "f" if st.get("ctx") == "f" else "d"
        st["m"] = st.get("m") if st.get("m") in TIERS else "S"
        st["b"] = max(500, min(int(st.get("b") or 3000), max_step_budget))
        st["dl"] = bool(st.get("dl"))
        st["out"] = _slug_file(st.get("out", ""), f"{st['i']}-{st['k']}")

    known = set(ids)
    for st in steps:
        for d in st["in"]:
            if d not in known:
                raise PlanError(f"step {st['i']} depends on unknown step {d}")
    topo_levels(steps)  # raises on cycles
    if not any(st["dl"] for st in steps):
        steps[-1]["dl"] = True  # the last step is always delivered

    plan.setdefault("g", "")
    plan.setdefault("fr", plan["g"])
    plan.setdefault("lang", "fr")
    plan["h"] = [str(h) for h in plan.get("h") or []][:5]
    return plan


def topo_levels(steps: list[dict]) -> list[list[dict]]:
    """Group steps into levels; steps inside a level are independent (parallel)."""
    by_id = {s["i"]: s for s in steps}
    done: set[str] = set()
    levels: list[list[dict]] = []
    remaining = list(by_id)
    while remaining:
        level = [by_id[i] for i in remaining if set(by_id[i]["in"]) <= done]
        if not level:
            raise PlanError("dependency cycle in plan")
        levels.append(level)
        done |= {s["i"] for s in level}
        remaining = [i for i in remaining if i not in done]
    return levels


def plan_budget(plan: dict, overhead_per_step: int = 1800) -> int:
    """Estimated total tokens: declared outputs + prompt overhead per step."""
    return sum(s["b"] + overhead_per_step for s in plan["s"])


@dataclass
class StepOutput:
    body: str
    digest: dict


def split_digest(text: str) -> StepOutput:
    """Separate the deliverable body from the machine digest appended by workers."""
    if DIGEST_MARK in text:
        body, _, tail = text.rpartition(DIGEST_MARK)
        try:
            digest = extract_json(tail)
            digest = {"s": str(digest.get("s", ""))[:600], "k": [str(k)[:160] for k in digest.get("k", [])][:8]}
            return StepOutput(body.strip(), digest)
        except PlanError:
            pass
        text = body
    body = text.strip()
    return StepOutput(body, {"s": re.sub(r"\s+", " ", body[:500]), "k": []})


# --- deterministic human commands (no LLM call) ------------------------------

PLAN_ID = re.compile(r"\bP-[A-Z0-9]{4,6}\b", re.I)
VERSION = re.compile(r"\bv(\d+)\b", re.I)

COMMANDS = {
    "VALIDER": "approve", "VALIDE": "approve", "APPROUVER": "approve",
    "MODIFIER": "revise", "CORRIGER": "revise",
    "ANNULER": "cancel",
    "STATUT": "status", "STATUS": "status", "ETAT": "status",
    "STOP": "stop", "ARRETER": "stop",
    "PLAN": "plan", "PLANIFIER": "plan",
    "NOUVEAU": "new", "RESET": "new",
    "ACCEPTER": "accept",
    "REVOIR": "rework",
    "AIDE": "help", "HELP": "help", "MENU": "help",
    "PROJETS": "list",
    "BUDGET": "budget", "COUT": "budget",
}
FREE_TEXT_COMMANDS = {"revise", "rework"}


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


@dataclass
class Command:
    name: str
    plan_id: str | None
    version: int | None
    arg: str


def parse_command(text: str) -> Command | None:
    """Recognise a leading command keyword such as 'VALIDER P-7K2Q v2'."""
    stripped = text.strip()
    m = re.match(r"^[/!#]?\s*([A-Za-zÀ-ÿ]+)\b[\s:,-]*(.*)$", stripped, re.S)
    if not m:
        return None
    name = COMMANDS.get(_fold(m.group(1)).upper())
    if not name:
        return None
    rest = m.group(2).strip()
    pid = PLAN_ID.search(rest)
    ver = VERSION.search(rest)
    arg = rest
    if pid:
        arg = arg.replace(pid.group(0), "", 1)
    if ver and name not in FREE_TEXT_COMMANDS:
        arg = arg.replace(ver.group(0), "", 1)
    arg = arg.strip(" .!?")
    if arg and name not in FREE_TEXT_COMMANDS:
        # "Valide le plan mais change X" or "Plan marketing pour..." are
        # conversation, not commands: only bare keywords act deterministically.
        return None
    return Command(name, pid.group(0).upper() if pid else None, int(ver.group(1)) if ver else None, arg.strip())
