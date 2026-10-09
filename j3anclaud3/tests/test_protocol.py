import copy

import pytest

from j3anclaud3.protocol import (
    PlanError, extract_json, parse_command, plan_budget, plan_hash, split_digest, topo_levels, validate_plan,
)

from .conftest import PLAN

KNOWN = {"ux-architect", "content-creator", "linkedin-content-creator"}


def test_validate_plan_normalises():
    p = validate_plan(copy.deepcopy(PLAN), KNOWN, 8)
    s1, s2, s3 = p["s"]
    assert s1["ctx"] == "d" and s1["in"] == [] and s1["dl"] is False
    assert s2["out"] == "landing-copy.md"
    assert [len(lv) for lv in topo_levels(p["s"])] == [1, 2]  # s2 and s3 run in parallel
    assert plan_budget(p) == 1500 + 2000 + 1200 + 3 * 1800
    assert plan_hash(p) == plan_hash(copy.deepcopy(p))


@pytest.mark.parametrize("mutate,err", [
    (lambda p: p["s"][0].update(k="nope"), "unknown skill"),
    (lambda p: p["s"][0].update(**{"in": ["s3"]}), "cycle"),
    (lambda p: p["s"][1].update(**{"in": ["s9"]}), "unknown step"),
    (lambda p: p["s"].extend(copy.deepcopy(p["s"]) * 3), "too many"),
])
def test_validate_plan_rejects(mutate, err):
    p = copy.deepcopy(PLAN)
    mutate(p)
    with pytest.raises(PlanError, match=err):
        validate_plan(p, KNOWN, 8)


def test_last_step_delivered_by_default():
    p = copy.deepcopy(PLAN)
    for st in p["s"]:
        st.pop("dl", None)
    assert validate_plan(p, KNOWN, 8)["s"][-1]["dl"] is True


def test_extract_json_tolerates_fences_and_prose():
    assert extract_json('Voici :\n```json\n{"a": "x}y", "b": {"c": 1}}\n```') == {"a": "x}y", "b": {"c": 1}}


def test_split_digest():
    out = split_digest('# Doc\nbody\n§DIGEST§ {"s":"summary","k":["a","b"]}')
    assert out.body == "# Doc\nbody" and out.digest == {"s": "summary", "k": ["a", "b"]}
    fallback = split_digest("no digest here")
    assert fallback.digest["s"] == "no digest here"


@pytest.mark.parametrize("text,name,pid,ver,arg", [
    ("VALIDER P-7K2Q v2", "approve", "P-7K2Q", 2, ""),
    ("valide p-7k2q", "approve", "P-7K2Q", None, ""),
    ("✅ x", None, None, None, None),
    ("Modifier : ajoute une version anglaise", "revise", None, None, "ajoute une version anglaise"),
    ("statut", "status", None, None, ""),
    ("État P-ABCD", "status", "P-ABCD", None, ""),
    ("Plan marketing pour notre lancement", None, None, None, None),  # conversation, not a command
    ("Valide le plan mais change le ton", None, None, None, None),  # never an implicit approval
    ("go", None, None, None, None),  # approval is never implicit
])
def test_parse_command(text, name, pid, ver, arg):
    cmd = parse_command(text)
    if name is None:
        assert cmd is None
    else:
        assert (cmd.name, cmd.plan_id, cmd.version, cmd.arg) == (name, pid, ver, arg)
