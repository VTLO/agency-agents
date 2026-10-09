"""J3anClaud3: the only human-facing entry and exit point.

Lifecycle of a project (per user conversation, whatever the client: web, API, terminal):

    cadrage ──(brief ready)──▶ validation ──VALIDER Pxxx vN──▶ production ──▶ livraison
       ▲                         │  ▲ MODIFIER / free-text change                │
       │                         └──┘ (new frozen version, approval reset)       │
       └────────────── ACCEPTER / NOUVEAU / ANNULER ◀── REVOIR (new version) ◀───┘

Nothing reaches production without an explicit human approval of an exact
frozen plan version. Commands are parsed locally
(zero tokens); only open conversation goes through the chat model.
"""

from __future__ import annotations

import logging

from .base import BaseBot, Outbox
from .config import Settings, cost_usd
from .executor import BudgetExceeded, Executor, RunStopped
from .llm import LLM
from .prompts import CHAT_SYSTEM, PLAN_SYSTEM
from .protocol import Command, PlanError, dumps, extract_json, parse_command, plan_budget, plan_hash, validate_plan
from .skills import SkillRegistry
from .store import Store

log = logging.getLogger("j3anclaud3")

TIER_ICON = {"L": "⚡", "S": "⚙️", "M": "🧠"}

HELP = """👋 Je suis **J3anClaud3**, votre chef d'orchestre.
Décrivez-moi votre besoin en langage naturel : je le cadre avec vous, je vous propose un **plan** de production, et je ne lance rien sans validation.

Commandes :
• **PLAN** – générer le plan à partir du brief actuel
• **VALIDER P-XXXX v1** – lancer la production d'un plan
• **MODIFIER …** – demander un changement du plan
• **ANNULER** – abandonner le plan en cours
• **STATUT** / **BUDGET** – avancement et consommation
• **STOP** – interrompre une production
• **ACCEPTER** / **REVOIR …** – clôturer ou itérer après livraison
• **PROJETS** – plans actifs de l'équipe
• **NOUVEAU** – repartir de zéro"""


class J3anClaud3(BaseBot):
    """Mode "orchestre": cadrage, plan, human validation, production with the lite skills."""

    mode = "orchestre"

    def __init__(self, settings: Settings, store: Store, skills: SkillRegistry, llm: LLM, outbox: Outbox):
        super().__init__(settings, store, llm, outbox)
        self.skills = skills
        self.executor = Executor(settings, store, skills, llm)

    async def _dispatch(self, conv: dict, text: str) -> None:
        cmd = parse_command(text)
        if cmd:
            await self._command(conv, cmd)
        else:
            await self._chat(conv, text)

    # --------------------------------------------------------------- commands
    async def _command(self, conv: dict, cmd: Command) -> None:
        user = conv["user"]
        pid = cmd.plan_id or conv["plan_id"]
        handler = getattr(self, f"_cmd_{cmd.name}")
        self.store.audit(user, f"cmd:{cmd.name}", plan=pid, version=cmd.version)
        await handler(conv, cmd, pid)

    async def _cmd_help(self, conv, cmd, pid):
        await self.out.send_text(conv["user"], HELP)

    async def _cmd_new(self, conv, cmd, pid):
        conv.update(state="cadrage", brief={}, plan_id=None, history=[])
        await self.out.send_text(conv["user"], "🆕 Nouveau projet. Quel est votre besoin ?")

    async def _cmd_list(self, conv, cmd, pid):
        rows = self.store.active_plans()
        if not rows:
            await self.out.send_text(conv["user"], "Aucun plan actif pour l'instant.")
            return
        lines = [f"• {r['id']} v{r['version']} – {_STATUS_FR.get(r['status'], r['status'])} ({r['owner']})" for r in rows]
        await self.out.send_text(conv["user"], "📂 Plans actifs :\n" + "\n".join(lines))

    async def _cmd_plan(self, conv, cmd, pid):
        if not conv["brief"]:
            await self.out.send_text(conv["user"], "Décrivez-moi d'abord votre besoin, je construirai le plan ensuite 🙂")
            return
        prev = self.store.plan(pid) if pid and conv["state"] == "validation" else None
        await self._make_plan(conv, prev=prev)

    async def _cmd_revise(self, conv, cmd, pid):
        rec = self.store.plan(pid) if pid else None
        if not rec or rec["status"] not in ("proposed", "delivered", "stopped"):
            await self.out.send_text(conv["user"], "Il n'y a pas de plan modifiable en ce moment.")
            return
        if not cmd.arg:
            await self.out.send_text(conv["user"], "Que souhaitez-vous changer ? Ex. : **MODIFIER ajouter une version anglaise**")
            return
        await self._make_plan(conv, prev=rec, feedback=cmd.arg)

    _cmd_rework = _cmd_revise

    async def _cmd_approve(self, conv, cmd, pid):
        user = conv["user"]
        rec = self.store.plan(pid, cmd.version) if pid else None
        latest = self.store.plan(pid) if pid else None
        if not rec:
            await self.out.send_text(user, "Je ne trouve pas ce plan. Précisez-le, ex. **VALIDER P-7K2Q v1**.")
            return
        if cmd.version is None and latest["version"] > 1:
            await self.out.send_text(user, f"Plusieurs versions existent : confirmez avec **VALIDER {pid} v{latest['version']}**.")
            return
        if rec["version"] != latest["version"]:
            await self.out.send_text(user, f"La v{rec['version']} est périmée. La version courante est la v{latest['version']}.")
            return
        if rec["status"] not in ("proposed", "stopped"):
            await self.out.send_text(user, f"Ce plan est {_STATUS_FR.get(rec['status'], rec['status'])} : rien à valider.")
            return
        if self.s.approval_by_admin_only and not self.s.is_admin(user):
            await self.out.send_text(user, "Seul l'administrateur peut lancer la production. Je lui ai transmis la demande 👍")
            await self._notify_admin(rec, requested_by=user)
            return
        if user == rec["owner"] and not self.s.allow_self_approval and not self.s.is_admin(user):
            await self.out.send_text(user, f"La validation doit venir d'un autre membre de l'équipe (**VALIDER {pid} v{rec['version']}**).")
            return
        count = self.store.approve(pid, rec["version"], user) if rec["status"] == "proposed" else self.s.required_approvals
        self.store.audit(user, "approved", plan=pid, version=rec["version"], hash=rec["hash"])
        if count < self.s.required_approvals:
            await self.out.send_text(user, f"👍 Validation enregistrée ({count}/{self.s.required_approvals}).")
            return
        self.store.set_plan_status(pid, rec["version"], "approved")
        owner_conv = conv if rec["owner"] == user else self.store.conv(rec["owner"])
        owner_conv["state"] = "production"
        if owner_conv is not conv:
            self.store.save_conv(owner_conv)
        await self._broadcast(rec, f"🚀 Plan **{pid} v{rec['version']}** validé. Production lancée, je vous tiens informés.", user)
        self._spawn(self._run(pid, rec["version"], rec["owner"], user))

    async def _cmd_cancel(self, conv, cmd, pid):
        rec = self.store.plan(pid) if pid else None
        if not rec or rec["status"] not in ("proposed", "approved", "stopped", "delivered"):
            await self.out.send_text(conv["user"], "Rien à annuler.")
            return
        user = conv["user"]
        if user != rec["owner"] and not self.s.is_admin(user):
            await self.out.send_text(user, "Seul l'auteur du plan ou l'administrateur peut l'annuler.")
            return
        self.store.set_plan_status(pid, rec["version"], "cancelled")
        if conv["plan_id"] == pid:
            conv.update(state="cadrage", plan_id=None)
        if user != rec["owner"]:  # refused by the admin: tell the author
            owner_conv = self.store.conv(rec["owner"])
            if owner_conv["plan_id"] == pid:
                owner_conv.update(state="cadrage", plan_id=None)
                self.store.save_conv(owner_conv)
            await self.out.send_text(rec["owner"], f"❌ L'administrateur a refusé le plan {pid}. Vous pouvez reformuler votre besoin.")
        await self.out.send_text(user, f"❌ Plan {pid} annulé. On repart sur le cadrage quand vous voulez.")

    async def _cmd_stop(self, conv, cmd, pid):
        if pid and self.executor.stop(pid):
            await self.out.send_text(conv["user"], f"⏸️ Arrêt demandé pour {pid} (après les étapes en cours).")
        else:
            await self.out.send_text(conv["user"], "Aucune production en cours.")

    async def _cmd_accept(self, conv, cmd, pid):
        rec = self.store.plan(pid) if pid else None
        if not rec or rec["status"] != "delivered":
            await self.out.send_text(conv["user"], "Aucune livraison en attente d'acceptation.")
            return
        self.store.set_plan_status(pid, rec["version"], "accepted")
        conv.update(state="cadrage", brief={}, plan_id=None, history=[])
        await self.out.send_text(conv["user"], f"🎉 Livrables {pid} acceptés et archivés. Prochain projet ?")

    async def _cmd_status(self, conv, cmd, pid):
        rec = self.store.plan(pid, cmd.version) if pid else None
        if not rec:
            await self.out.send_text(conv["user"], f"État : **{conv['state']}**. Aucun plan en cours.")
            return
        steps = self.store.steps(pid, rec["version"])
        lines = [f"📊 **{pid} v{rec['version']}** – {_STATUS_FR.get(rec['status'], rec['status'])}"]
        for st in rec["body"]["s"]:
            icon = {"done": "✅", "running": "⏳", "failed": "⚠️", "truncated": "✂️"}.get(steps.get(st["i"], {}).get("status"), "▫️")
            lines.append(f"{icon} {st['t']}")
        tokens, cost = self.store.spent(pid)
        lines.append(f"💰 {tokens/1000:.1f}k tokens · ${cost:.3f} (estim. {rec['est_tokens']/1000:.0f}k)")
        await self.out.send_text(conv["user"], "\n".join(lines))

    _cmd_budget = _cmd_status

    # ----------------------------------------------------------------- dialog
    async def _chat(self, conv: dict, text: str) -> None:
        user = conv["user"]
        rec = self.store.plan(conv["plan_id"]) if conv["plan_id"] else None
        payload = dumps({
            "st": conv["state"],
            "brief": conv["brief"],
            "plan": _plan_digest(rec) if rec else None,
            "hist": conv["history"][-self.s.chat_window * 2:],
            "msg": text[:2000],
        })
        res = await self.llm.complete(self.s.chat_tier, [CHAT_SYSTEM], payload, max_tokens=2500, purpose="chat")
        self.store.log_usage(None, f"chat:{user}", res)
        try:
            data = extract_json(res.text)
        except PlanError:
            data = {"r": res.text.strip(), "a": "chat"}
        reply = str(data.get("r") or "").strip()
        if isinstance(data.get("b"), dict) and data["b"]:
            conv["brief"] = data["b"]
        conv["history"] = (conv["history"] + [["u", text[:400]], ["m", reply[:400]]])[-self.s.chat_window * 2:]
        if reply:
            await self.out.send_text(user, reply)

        action = data.get("a")
        if action == "plan" and conv["state"] in ("cadrage", "livraison") and conv["brief"]:
            await self._make_plan(conv)
        elif action == "revise" and rec and rec["status"] in ("proposed", "delivered", "stopped"):
            await self._make_plan(conv, prev=rec, feedback=str(data.get("fb") or text))

    # --------------------------------------------------------------- planning
    async def _make_plan(self, conv: dict, prev: dict | None = None, feedback: str | None = None) -> None:
        user = conv["user"]
        brief = conv["brief"] or (prev["body"].get("brief", {}) if prev else {})
        conv["brief"] = brief
        query = " ".join([brief.get("goal", ""), " ".join(brief.get("kw", [])), " ".join(brief.get("dl", []))])
        shortlist = self.skills.route(query, self.s.shortlist_size)
        if prev:  # keep the skills already in use available to the reviser
            used = [self.skills.get(st["k"]) for st in prev["body"]["s"] if st["k"] in self.skills]
            shortlist = list({sk.slug: sk for sk in used + shortlist}.values())
        if not shortlist:
            await self.out.send_text(user, "Je n'identifie pas encore les expertises nécessaires. Pouvez-vous préciser le domaine et les livrables attendus ?")
            return
        await self.out.send_text(user, "🧩 Je prépare le plan de production…")

        req = {"brief": brief, "skills": [sk.card() for sk in shortlist], "max_steps": self.s.max_steps}
        if prev:
            req["prev"] = {k: v for k, v in prev["body"].items() if k != "brief"}
            req["fb"] = feedback or ""
            if prev["status"] in ("delivered", "stopped"):
                req["done"] = [  # digests of what was already produced, so rework stays incremental
                    {"i": sid, "s": row["digest"].get("s", "")} for sid, row in self.store.steps(prev["id"], prev["version"]).items()
                ]
        known = {sk.slug for sk in shortlist}
        pid = prev["id"] if prev else self.store.new_plan_id()
        plan = None
        for _ in range(2):
            res = await self.llm.complete(self.s.plan_tier, [PLAN_SYSTEM], dumps(req), max_tokens=8000, purpose="plan")
            self.store.log_usage(pid, "plan", res)
            try:
                plan = validate_plan(extract_json(res.text), known, self.s.max_steps)
                break
            except PlanError as e:
                log.warning("invalid plan: %s", e)
                req["err"] = f"Previous output was rejected: {e}. Fix it."
        if plan is None:
            await self.out.send_text(user, "Je n'ai pas réussi à produire un plan valide. Pouvez-vous préciser le besoin ?")
            return

        plan["brief"] = brief
        version = prev["version"] + 1 if prev else 1
        est = plan_budget(plan)
        self.store.add_plan(pid, version, user, plan, plan_hash(plan), est, note=feedback or "")
        self.store.audit(user, "plan_proposed", plan=pid, version=version, est=est)
        conv.update(state="validation", plan_id=pid)

        text = self.render_plan(pid, version, plan, est)
        if self.s.approval_by_admin_only and not self.s.is_admin(user):
            text += "\n🔐 La production sera lancée après validation par l'administrateur, qui a reçu ce plan."
            await self.out.send_buttons(user, text, [("MODIFIER", "✏️ Modifier"), (f"ANNULER {pid}", "❌ Annuler")])
            await self._notify_admin(self.store.plan(pid, version), requested_by=user)
        else:
            await self.out.send_buttons(
                user, text,
                [(f"VALIDER {pid} v{version}", "✅ Valider"), ("MODIFIER", "✏️ Modifier"), (f"ANNULER {pid}", "❌ Annuler")],
            )

    def render_plan(self, pid: str, version: int, plan: dict, est: int) -> str:
        """Deterministic French rendering: zero tokens spent on presentation."""
        lines = [f"📋 **Plan {pid} · v{version}**", f"🎯 {plan.get('fr') or plan['g']}", "", "**Étapes**"]
        num = {st["i"]: n for n, st in enumerate(plan["s"], 1)}
        cost = 0.0
        for n, st in enumerate(plan["s"], 1):
            sk = self.skills.get(st["k"])
            after = f" ↳ après {', '.join(str(num[d]) for d in st['in'])}" if st["in"] else ""
            lines.append(f"{n}. {st['t']} — _{sk.name}_ {TIER_ICON[st['m']]}{after}")
            cost += cost_usd(self.s.tier(st["m"]).model, 1800, st["b"])
        lines.append("")
        lines.append("📦 **Livrables** : " + ", ".join(st["out"] for st in plan["s"] if st["dl"]))
        if plan.get("h"):
            lines.append("🧪 **Hypothèses** :")
            lines += [f"• {h}" for h in plan["h"]]
        warn = " ⚠️ au-delà du budget par défaut" if est > self.s.default_budget_tokens else ""
        lines.append(f"💰 Estimation : ~{est/1000:.0f}k tokens (~${cost:.2f}){warn}")
        lines.append("")
        lines.append(f"👉 **VALIDER {pid} v{version}** pour lancer la production, **MODIFIER …** pour ajuster, **ANNULER** pour abandonner.")
        return "\n".join(lines)

    # -------------------------------------------------------------- execution
    async def _run(self, pid: str, version: int, owner: str, approver: str) -> None:
        recipients = list(dict.fromkeys([owner, approver]))

        async def progress(msg: str) -> None:
            await self.out.send_text(owner, msg)

        self.store.set_plan_status(pid, version, "running")
        try:
            result = await self.executor.run(pid, version, progress)
        except (BudgetExceeded, RunStopped) as e:
            self.store.set_plan_status(pid, version, "stopped")
            why = "budget dépassé" if isinstance(e, BudgetExceeded) else "arrêt demandé"
            for to in recipients:
                await self.out.send_text(to, f"⏸️ Production {pid} v{version} suspendue ({why}). "
                                             f"**VALIDER {pid} v{version}** pour reprendre là où on en était, ou **MODIFIER …**.")
            return
        except Exception as e:  # noqa: BLE001
            log.exception("run %s failed", pid)
            self.store.set_plan_status(pid, version, "stopped")
            for to in recipients:
                await self.out.send_text(to, f"⚠️ Production {pid} interrompue : {e}. **VALIDER {pid} v{version}** pour relancer les étapes restantes.")
            return

        self.store.set_plan_status(pid, version, "delivered")
        self.store.audit("j3anclaud3", "delivered", plan=pid, version=version, tokens=result.tokens, cost=result.cost)
        conv = self.store.conv(owner)
        if conv["plan_id"] == pid:
            conv["state"] = "livraison"
            self.store.save_conv(conv)
        for to in recipients:
            await self.out.send_text(to, f"📦 **Livraison {pid} v{version}**\n{result.summary}")
            for path in result.deliverables:
                await self.out.send_document(to, path, caption=path.name)
            await self.out.send_text(
                to, f"💰 {result.tokens/1000:.1f}k tokens · ${result.cost:.3f}\n"
                    f"👉 **ACCEPTER** pour clôturer, ou **REVOIR …** avec vos remarques (nouveau plan à valider)."
            )

    async def recover(self) -> None:
        """After a restart, runs that were in flight are suspended, never silently re-run."""
        for rec in self.store.plans_with_status("running", "approved"):
            self.store.set_plan_status(rec["id"], rec["version"], "stopped")
            try:
                await self.out.send_text(rec["owner"], f"🔄 J3anClaud3 a redémarré : production {rec['id']} v{rec['version']} suspendue. "
                                                       f"**VALIDER {rec['id']} v{rec['version']}** pour reprendre.")
            except Exception:  # noqa: BLE001
                log.warning("could not notify %s", rec["owner"])

    # ---------------------------------------------------------------- helpers
    async def _notify_admin(self, rec: dict, requested_by: str) -> None:
        """Put the plan, with its approval button, in the admin's own thread."""
        admin = self.s.admin_name
        text = self.render_plan(rec["id"], rec["version"], rec["body"], rec["est_tokens"])
        await self.out.send_buttons(
            admin, f"🔔 Validation demandée par **{requested_by}**\n\n{text}",
            [(f"VALIDER {rec['id']} v{rec['version']}", "✅ Valider"), (f"ANNULER {rec['id']}", "❌ Refuser")],
        )

    async def _broadcast(self, rec: dict, text: str, actor: str) -> None:
        for to in dict.fromkeys([actor, rec["owner"]]):
            await self.out.send_text(to, text)


_STATUS_FR = {
    "proposed": "en attente de validation", "superseded": "remplacé", "approved": "validé",
    "running": "en production", "stopped": "suspendu", "delivered": "livré", "accepted": "accepté",
    "cancelled": "annulé",
}


def _plan_digest(rec: dict) -> dict:
    b = rec["body"]
    return {"id": f"{rec['id']} v{rec['version']}", "status": rec["status"], "goal": b.get("g"),
            "steps": [f"{st['i']}:{st['k']}:{st['t']}" for st in b["s"]]}
