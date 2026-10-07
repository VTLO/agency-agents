"""Runtime configuration, read once from environment variables.

Model tiers are the main token-economy lever: every LLM call names a tier
(L = lite, S = standard, M = max), never a model id, so the cost profile of
the whole bot can be retuned from the environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# USD per 1M tokens: (input, output). Cache reads bill at ~10% of input.
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
}

# Models that accept adaptive thinking + output_config.effort + server fallbacks.
EFFORT_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5"}


@dataclass(frozen=True)
class User:
    name: str
    role: str  # "approver" | "member"
    code: str  # access code (also usable as a Bearer token for the HTTP API)


def parse_users(raw: str) -> dict[str, User]:
    """M3_USERS="alice:approver:code-a,bob:member:code-b" -> {name: User}."""
    users: dict[str, User] = {}
    for item in raw.split(","):
        parts = [p.strip() for p in item.split(":", 2)]
        if len(parts) != 3 or not all(parts):
            continue
        name, role, code = parts
        users[name.lower()] = User(name.lower(), "approver" if role.lower().startswith("approv") else "member", code)
    return users


@dataclass(frozen=True)
class Tier:
    model: str
    effort: str | None  # None for models without effort support (Haiku)
    max_tokens: int


@dataclass
class Settings:
    agency_root: Path = field(
        default_factory=lambda: Path(
            os.environ.get("M3_AGENCY_ROOT", Path(__file__).resolve().parents[2])
        )
    )
    data_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("M3_DATA_DIR", "./m3lvin-data"))
    )

    # --- model tiers -------------------------------------------------------
    tiers: dict[str, Tier] = field(
        default_factory=lambda: {
            "L": Tier(os.environ.get("M3_MODEL_LITE", "claude-haiku-4-5"), None, 4000),
            "S": Tier(
                os.environ.get("M3_MODEL_STD", "claude-sonnet-5-5"),
                os.environ.get("M3_EFFORT_STD", "low"),
                16000,
            ),
            "M": Tier(
                os.environ.get("M3_MODEL_MAX", "claude-opus-5-5"),
                os.environ.get("M3_EFFORT_MAX", "medium"),
                32000,
            ),
        }
    )
    chat_tier: str = os.environ.get("M3_CHAT_TIER", "S")  # French dialogue with humans
    plan_tier: str = os.environ.get("M3_PLAN_TIER", "M")  # plan quality matters most
    summary_tier: str = os.environ.get("M3_SUMMARY_TIER", "L")  # FR delivery summary
    server_fallbacks: bool = os.environ.get("M3_SERVER_FALLBACKS", "1") == "1"

    # --- economy knobs ------------------------------------------------------
    skill_prompt_tokens: int = int(os.environ.get("M3_SKILL_PROMPT_TOKENS", "900"))
    shortlist_size: int = int(os.environ.get("M3_SHORTLIST", "10"))
    chat_window: int = int(os.environ.get("M3_CHAT_WINDOW", "6"))  # raw turns kept
    max_steps: int = int(os.environ.get("M3_MAX_STEPS", "8"))
    default_budget_tokens: int = int(os.environ.get("M3_BUDGET_TOKENS", "120000"))
    budget_slack: float = float(os.environ.get("M3_BUDGET_SLACK", "1.5"))
    parallelism: int = int(os.environ.get("M3_PARALLELISM", "3"))

    # --- governance ---------------------------------------------------------
    # Empty M3_USERS = open single-team mode (local use): anyone is member and approver.
    users: dict[str, User] = field(default_factory=lambda: parse_users(os.environ.get("M3_USERS", "")))
    required_approvals: int = int(os.environ.get("M3_REQUIRED_APPROVALS", "1"))
    allow_self_approval: bool = os.environ.get("M3_ALLOW_SELF_APPROVAL", "1") == "1"
    secret: str = os.environ.get("M3_SECRET", "")  # signs session cookies; generated if empty

    def tier(self, name: str) -> Tier:
        return self.tiers.get(name, self.tiers["S"])

    @property
    def open_mode(self) -> bool:
        return not self.users

    def is_member(self, user: str) -> bool:
        return self.open_mode or user in self.users

    def is_approver(self, user: str) -> bool:
        if self.open_mode:
            return True
        u = self.users.get(user)
        if not u:
            return False
        # No approver declared at all -> every member may approve.
        return u.role == "approver" or not any(x.role == "approver" for x in self.users.values())

    def approvers(self) -> set[str]:
        return {u.name for u in self.users.values() if u.role == "approver"}


def cost_usd(model: str, inp: int, out: int, cache_read: int = 0, cache_write: int = 0) -> float:
    pi, po = PRICES.get(model, (4.0, 20.0))
    return (inp * pi + cache_read * pi * 0.1 + cache_write * pi * 1.25 + out * po) / 1e6
