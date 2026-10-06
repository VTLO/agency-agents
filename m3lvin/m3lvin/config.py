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


def _env_list(name: str) -> set[str]:
    raw = os.environ.get(name, "")
    return {x.strip().lstrip("+") for x in raw.split(",") if x.strip()}


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
    team: set[str] = field(default_factory=lambda: _env_list("M3_TEAM"))
    approvers: set[str] = field(default_factory=lambda: _env_list("M3_APPROVERS"))
    required_approvals: int = int(os.environ.get("M3_REQUIRED_APPROVALS", "1"))
    allow_self_approval: bool = os.environ.get("M3_ALLOW_SELF_APPROVAL", "1") == "1"

    # --- WhatsApp Cloud API -------------------------------------------------
    wa_token: str = os.environ.get("WHATSAPP_TOKEN", "")
    wa_phone_id: str = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
    wa_verify_token: str = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
    wa_app_secret: str = os.environ.get("WHATSAPP_APP_SECRET", "")
    wa_api_version: str = os.environ.get("WHATSAPP_API_VERSION", "v21.0")

    def tier(self, name: str) -> Tier:
        return self.tiers.get(name, self.tiers["S"])

    def is_member(self, phone: str) -> bool:
        return not self.team or phone in self.team or phone in self.approvers

    def is_approver(self, phone: str) -> bool:
        # No approver list configured -> any team member can approve.
        return phone in self.approvers if self.approvers else self.is_member(phone)


def cost_usd(model: str, inp: int, out: int, cache_read: int = 0, cache_write: int = 0) -> float:
    pi, po = PRICES.get(model, (4.0, 20.0))
    return (inp * pi + cache_read * pi * 0.1 + cache_write * pi * 1.25 + out * po) / 1e6
