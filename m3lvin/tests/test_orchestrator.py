import asyncio
import copy
import json

from m3lvin.config import parse_users

from .conftest import BRIEF, PLAN

OWNER, BOSS, STRANGER = "alice", "boss", "mallory"


async def _drain(bot):
    while bot.tasks:
        await asyncio.gather(*list(bot.tasks))


def _to_plan(llm, plan=None):
    llm.chat_replies.append({"r": "Parfait, je prépare le plan.", "a": "plan", "b": BRIEF})
    llm.plans.append(copy.deepcopy(plan or PLAN))


def test_full_lifecycle_requires_human_validation(make_bot):
    bot, llm, out = make_bot(shortlist_size=500)

    async def scenario():
        llm.chat_replies.append({"r": "Qui est la cible ?", "a": "chat", "b": {"goal": "landing"}})
        await bot.handle(OWNER, "Il nous faut une landing page pour notre SaaS", "m1")
        assert bot.store.conv(OWNER)["state"] == "cadrage"

        _to_plan(llm)
        await bot.handle(OWNER, "Des PME françaises, vas-y", "m2")
        conv = bot.store.conv(OWNER)
        assert conv["state"] == "validation"
        pid = conv["plan_id"]
        plan_msg = out.texts(OWNER)[-1]
        assert f"Plan {pid} · v1" in plan_msg and f"VALIDER {pid} v1" in plan_msg and "Estimation" in plan_msg
        # Nothing ran yet: no worker step was called before validation.
        assert not [p for p in llm.purposes() if p.startswith(pid)]

        await bot.handle(OWNER, f"VALIDER {pid} v1", "m3")
        await _drain(bot)
        rec = bot.store.plan(pid)
        assert rec["status"] == "delivered"
        assert bot.store.conv(OWNER)["state"] == "livraison"
        docs = [c for t, k, c in out.sent if k == "doc"]
        assert [d.rsplit("/", 1)[1] for d in docs] == ["landing-copy.md", "posts.md"]
        assert "§DIGEST§" not in open(docs[0]).read()

        await bot.handle(OWNER, "ACCEPTER", "m4")
        assert bot.store.plan(pid)["status"] == "accepted"
        assert bot.store.conv(OWNER)["state"] == "cadrage"

    asyncio.run(scenario())


def test_workers_get_lite_skill_and_digest_only(make_bot):
    bot, llm, out = make_bot(shortlist_size=500)

    async def scenario():
        _to_plan(llm)
        await bot.handle(OWNER, "landing page", "a")
        pid = bot.store.conv(OWNER)["plan_id"]
        await bot.handle(OWNER, f"VALIDER {pid} v1", "b")
        await _drain(bot)

    asyncio.run(scenario())
    steps = {c[0].split(":")[1]: c for c in llm.calls if c[0].count(":") == 2}
    _, tier, system, user = steps["s3"]
    assert tier == "L"  # planner-chosen tier honoured
    assert system[0] == bot.skills.get("linkedin-content-creator").prompt
    ctx = json.loads(user)["ctx"]
    assert ctx == [{"i": "s1", "t": "Structure de page", "s": "did Design landing page ", "k": ["fact"]}]
    # chat + plan + 3 steps + summary
    assert len(llm.calls) == 6


def test_duplicate_webhook_is_ignored(make_bot):
    bot, llm, out = make_bot()
    llm.chat_replies.append({"r": "Bonjour !", "a": "chat", "b": {}})

    async def scenario():
        await bot.handle(OWNER, "salut", "same")
        await bot.handle(OWNER, "salut", "same")

    asyncio.run(scenario())
    assert len(llm.calls) == 1 and len(out.sent) == 1


def test_unknown_sender_rejected_without_tokens(make_bot):
    bot, llm, out = make_bot(users=parse_users("alice:member:a"))
    asyncio.run(bot.handle(STRANGER, "VALIDER P-AAAA v1", "x"))
    assert llm.calls == [] and "pas autorisé" in out.texts(STRANGER)[0]


def test_approval_gate(make_bot):
    bot, llm, out = make_bot(shortlist_size=500, users=parse_users("alice:member:a,boss:approver:b"), allow_self_approval=False)

    async def scenario():
        _to_plan(llm)
        await bot.handle(OWNER, "landing", "1")
        pid = bot.store.conv(OWNER)["plan_id"]
        assert any(f"VALIDER {pid} v1" in t for t in out.texts(BOSS))  # approver notified

        await bot.handle(OWNER, f"VALIDER {pid} v1", "2")  # owner is not an approver
        assert bot.store.plan(pid)["status"] == "proposed"

        # A change request creates v2 and makes v1 un-approvable.
        llm.plans.append(copy.deepcopy(PLAN))
        await bot.handle(OWNER, "MODIFIER ajoute une version anglaise", "3")
        assert bot.store.plan(pid, 1)["status"] == "superseded"
        await bot.handle(BOSS, f"VALIDER {pid} v1", "4")
        assert "périmée" in out.texts(BOSS)[-1]
        assert bot.store.plan(pid)["status"] == "proposed"

        await bot.handle(BOSS, f"VALIDER {pid} v2", "5")
        await _drain(bot)
        assert bot.store.plan(pid)["status"] == "delivered"
        assert any("Livraison" in t for t in out.texts(BOSS))  # approver gets deliverables too

    asyncio.run(scenario())


def test_invalid_plan_is_retried_then_accepted(make_bot):
    bot, llm, out = make_bot(shortlist_size=500)
    bad = copy.deepcopy(PLAN)
    bad["s"][0]["k"] = "imaginary-agent"
    llm.chat_replies.append({"r": "ok", "a": "plan", "b": BRIEF})
    llm.plans += [bad, copy.deepcopy(PLAN)]
    asyncio.run(bot.handle(OWNER, "go", "1"))
    assert bot.store.conv(OWNER)["state"] == "validation"
    assert "imaginary-agent" in json.loads(llm.calls[-1][3])["err"]


def test_budget_guard_suspends_and_resume_skips_done_steps(make_bot):
    bot, llm, out = make_bot(shortlist_size=500, budget_slack=0.0001)

    async def scenario():
        _to_plan(llm)
        await bot.handle(OWNER, "landing", "1")
        pid = bot.store.conv(OWNER)["plan_id"]
        await bot.handle(OWNER, f"VALIDER {pid} v1", "2")
        await _drain(bot)
        assert bot.store.plan(pid)["status"] == "stopped"
        assert "budget" in out.texts(OWNER)[-1]
        assert bot.store.steps(pid, 1)["s1"]["status"] == "done"

        bot.s.budget_slack = 10
        before = len(llm.calls)
        await bot.handle(OWNER, f"VALIDER {pid} v1", "3")
        await _drain(bot)
        assert bot.store.plan(pid)["status"] == "delivered"
        resumed = [c[0] for c in llm.calls[before:]]
        assert not any(":s1:" in p for p in resumed)  # s1 not paid twice

    asyncio.run(scenario())


def test_commands_cost_zero_tokens(make_bot):
    bot, llm, out = make_bot()

    async def scenario():
        for i, cmd in enumerate(["AIDE", "STATUT", "PROJETS", "BUDGET", "NOUVEAU", "STOP"]):
            await bot.handle(OWNER, cmd, str(i))

    asyncio.run(scenario())
    assert llm.calls == [] and len(out.sent) == 6
