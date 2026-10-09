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

MODES = ("orchestre", "conversation")

# Models that accept adaptive thinking + output_config.effort + server fallbacks.
EFFORT_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5"}


@dataclass(frozen=True)
class Tier:
    model: str
    effort: str | None  # None for models without effort support (Haiku)
    max_tokens: int


@dataclass
class Settings:
    agency_root: Path = field(
        default_factory=lambda: Path(
            os.environ.get("J3_AGENCY_ROOT", Path(__file__).resolve().parents[2])
        )
    )
    data_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("J3_DATA_DIR", "./j3anclaud3-data"))
    )

    # --- model tiers -------------------------------------------------------
    tiers: dict[str, Tier] = field(
        default_factory=lambda: {
            "L": Tier(os.environ.get("J3_MODEL_LITE", "claude-haiku-4-5"), None, 4000),
            "S": Tier(
                os.environ.get("J3_MODEL_STD", "claude-sonnet-5-5"),
                os.environ.get("J3_EFFORT_STD", "low"),
                16000,
            ),
            "M": Tier(
                os.environ.get("J3_MODEL_MAX", "claude-opus-5-5"),
                os.environ.get("J3_EFFORT_MAX", "medium"),
                32000,
            ),
        }
    )
    chat_tier: str = os.environ.get("J3_CHAT_TIER", "S")  # French dialogue with humans
    plan_tier: str = os.environ.get("J3_PLAN_TIER", "M")  # plan quality matters most
    summary_tier: str = os.environ.get("J3_SUMMARY_TIER", "L")  # FR delivery summary
    server_fallbacks: bool = os.environ.get("J3_SERVER_FALLBACKS", "1") == "1"

    # --- economy knobs ------------------------------------------------------
    skill_prompt_tokens: int = int(os.environ.get("J3_SKILL_PROMPT_TOKENS", "900"))
    shortlist_size: int = int(os.environ.get("J3_SHORTLIST", "10"))
    chat_window: int = int(os.environ.get("J3_CHAT_WINDOW", "6"))  # raw turns kept
    max_steps: int = int(os.environ.get("J3_MAX_STEPS", "8"))
    default_budget_tokens: int = int(os.environ.get("J3_BUDGET_TOKENS", "120000"))
    budget_slack: float = float(os.environ.get("J3_BUDGET_SLACK", "1.5"))
    parallelism: int = int(os.environ.get("J3_PARALLELISM", "3"))

    # --- mode -------------------------------------------------------------
    # "orchestre": cadrage -> plan -> validation -> production with the lite skills.
    # "conversation": plain natural-language chat, no skills, no plans.
    mode: str = os.environ.get("J3_MODE", "orchestre")
    chat_history: int = int(os.environ.get("J3_CHAT_HISTORY", "20"))  # messages kept in conversation mode

    # --- governance ---------------------------------------------------------
    # Everyone may talk to the bot. The admin account is enabled by J3_ADMIN_PASSWORD:
    # its name is then reserved, and it alone can launch production (if J3_ADMIN_APPROVAL=1),
    # see usage and block people.
    admin_name: str = os.environ.get("J3_ADMIN_NAME", "admin").strip().lower()
    admin_password: str = os.environ.get("J3_ADMIN_PASSWORD", "")
    admin_approval: bool = os.environ.get("J3_ADMIN_APPROVAL", "1") == "1"
    required_approvals: int = int(os.environ.get("J3_REQUIRED_APPROVALS", "1"))
    allow_self_approval: bool = os.environ.get("J3_ALLOW_SELF_APPROVAL", "1") == "1"
    secret: str = os.environ.get("J3_SECRET", "")  # signs session cookies; generated if empty

    @property
    def admin_enabled(self) -> bool:
        return bool(self.admin_password)

    def is_admin(self, user: str) -> bool:
        return self.admin_enabled and user == self.admin_name

    @property
    def approval_by_admin_only(self) -> bool:
        return self.admin_enabled and self.admin_approval

    def tier(self, name: str) -> Tier:
        return self.tiers.get(name, self.tiers["S"])


def cost_usd(model: str, inp: int, out: int, cache_read: int = 0, cache_write: int = 0) -> float:
    pi, po = PRICES.get(model, (4.0, 20.0))
    return (inp * pi + cache_read * pi * 0.1 + cache_write * pi * 1.25 + out * po) / 1e6
