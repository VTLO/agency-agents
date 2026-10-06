"""Runs a human-validated plan: DAG levels in parallel, digest hand-offs, budget guard."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from .config import Settings
from .llm import LLM
from .prompts import SUMMARY_SYSTEM, WORKER_PROTOCOL
from .protocol import dumps, split_digest, topo_levels
from .skills import SkillRegistry
from .store import Store

log = logging.getLogger("m3lvin.exec")

Progress = Callable[[str], Awaitable[None]]


class BudgetExceeded(RuntimeError):
    pass


class RunStopped(RuntimeError):
    pass


@dataclass
class RunResult:
    deliverables: list[Path]
    summary: str
    tokens: int
    cost: float
    failed: list[str] = field(default_factory=list)


class Executor:
    def __init__(self, settings: Settings, store: Store, skills: SkillRegistry, llm: LLM):
        self.s, self.store, self.skills, self.llm = settings, store, skills, llm
        self.stop_flags: dict[str, asyncio.Event] = {}

    def run_dir(self, pid: str, version: int) -> Path:
        d = self.s.data_dir / "runs" / f"{pid}-v{version}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def stop(self, pid: str) -> bool:
        ev = self.stop_flags.get(pid)
        if ev:
            ev.set()
        return ev is not None

    async def run(self, pid: str, version: int, progress: Progress) -> RunResult:
        rec = self.store.plan(pid, version)
        plan = rec["body"]
        brief = plan.get("brief", {})
        outdir = self.run_dir(pid, version)
        stop = self.stop_flags.setdefault(pid, asyncio.Event())
        sem = asyncio.Semaphore(self.s.parallelism)
        done: dict[str, dict] = {}  # step id -> {"t","digest","path"}
        titles = {st["i"]: st["t"] for st in plan["s"]}
        # Resume: steps finished by an earlier (stopped/crashed) run are reused as-is.
        for sid, row in self.store.steps(pid, version).items():
            if row["status"] in ("done", "truncated") and row["path"] and Path(row["path"]).exists():
                done[sid] = {"t": titles.get(sid, sid), "digest": row["digest"], "path": row["path"]}
        levels = topo_levels(plan["s"])
        total = len(plan["s"])
        est_left = {st["i"]: st["b"] + 1800 for st in plan["s"]}
        start_spent, _ = self.store.spent(pid, "step:")

        async def run_step(st: dict) -> None:
            async with sem:
                if stop.is_set():
                    raise RunStopped()
                skill = self.skills.get(st["k"])
                ctx = []
                for dep in st["in"]:
                    d = done[dep]
                    item = {"i": dep, "t": d["t"]}
                    if st["ctx"] == "f":
                        item["full"] = Path(d["path"]).read_text(encoding="utf-8")
                    else:
                        item["s"] = d["digest"]["s"]
                        if d["digest"].get("k"):
                            item["k"] = d["digest"]["k"]
                    ctx.append(item)
                payload = dumps({"g": plan["g"], "do": st["do"], "lang": plan.get("lang", "fr"), "brief": brief, "ctx": ctx})
                tier = self.s.tier(st["m"])
                max_out = min(tier.max_tokens, st["b"] * 2 + 1200)  # headroom for thinking + digest
                self.store.save_step(pid, version, st["i"], "running")
                last_err: Exception | None = None
                for attempt in range(2):
                    try:
                        res = await self.llm.complete(
                            st["m"], [skill.prompt, WORKER_PROTOCOL], payload,
                            max_tokens=max_out, purpose=f"{pid}:{st['i']}:{st['k']}",
                        )
                        break
                    except Exception as e:  # noqa: BLE001 - retried once, then surfaced
                        last_err = e
                        log.warning("step %s attempt %d failed: %s", st["i"], attempt + 1, e)
                else:
                    self.store.save_step(pid, version, st["i"], "failed")
                    raise RuntimeError(f"étape {st['i']} en échec : {last_err}")
                self.store.log_usage(pid, f"step:{st['i']}", res)
                out = split_digest(res.text)
                path = outdir / st["out"]
                path.write_text(out.body + "\n", encoding="utf-8")
                status = "truncated" if res.stop_reason == "max_tokens" else "done"
                self.store.save_step(pid, version, st["i"], status, out.digest, str(path), res.total_tokens, res.cost)
                done[st["i"]] = {"t": st["t"], "digest": out.digest, "path": str(path)}
                await progress(f"✅ {len(done)}/{total} · {st['t']}")

        allowed = int(sum(v for k, v in est_left.items() if k not in done) * self.s.budget_slack)
        try:
            for level in levels:
                todo = [st for st in level if st["i"] not in done]
                spent = self.store.spent(pid, "step:")[0] - start_spent
                if todo and spent > allowed:
                    raise BudgetExceeded(f"{spent} > {allowed} tokens")
                if stop.is_set():
                    raise RunStopped()
                await asyncio.gather(*(run_step(st) for st in todo))
        finally:
            self.stop_flags.pop(pid, None)

        deliverables = [Path(done[st["i"]]["path"]) for st in plan["s"] if st["dl"]]
        summary_in = dumps({"goal": plan.get("fr") or plan["g"], "steps": [
            {"t": st["t"], "s": done[st["i"]]["digest"]["s"], "k": done[st["i"]]["digest"].get("k", [])[:3]}
            for st in plan["s"] if st["dl"]
        ]})
        try:
            res = await self.llm.complete(self.s.summary_tier, [SUMMARY_SYSTEM], summary_in, max_tokens=900, purpose=f"{pid}:summary")
            self.store.log_usage(pid, "summary", res)
            summary = res.text.strip()
        except Exception as e:  # noqa: BLE001 - delivery must not fail on the summary
            log.warning("summary failed: %s", e)
            summary = "Voici les livrables produits."
        tokens, cost = self.store.spent(pid)
        return RunResult(deliverables, summary, tokens, cost)
