from m3lvin.protocol import est_tokens
from m3lvin.skills import SkillRegistry, compress_body

from .conftest import AGENCY_ROOT


def test_registry_covers_agency(registry):
    assert len(registry) > 100
    sk = registry.get("backend-architect")
    assert sk.cat == "engineering" and "```" not in sk.prompt
    assert est_tokens(sk.prompt) <= 600 * 1.05
    raw = (AGENCY_ROOT / "engineering" / "engineering-backend-architect.md").read_text()
    assert est_tokens(sk.prompt) < est_tokens(raw) / 3  # the "lite" in lite skills


def test_router_finds_relevant_skills(registry):
    slugs = [s.slug for s in registry.route("mobile app backend api security", 6)]
    assert {"mobile-app-builder", "backend-architect", "security-engineer"} <= set(slugs)
    assert registry.route("zzzz qqqq") == []


def test_compress_prioritises_rules_and_drops_examples():
    body = "## Example output\nlong example\n## Critical Rules\n- never ship untested\n## Your Core Mission\n- build"
    out = compress_body(body, 400)
    assert "Critical Rules" in out and "Core Mission" in out and "long example" not in out


def test_cache_roundtrip(tmp_path):
    cache = tmp_path / "skills.json"
    a = SkillRegistry.open(AGENCY_ROOT, cache, 300)
    b = SkillRegistry.open(AGENCY_ROOT, cache, 300)
    assert cache.exists() and a.skills.keys() == b.skills.keys()
