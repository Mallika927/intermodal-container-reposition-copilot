"""Scoring parameters: tunable knobs for the deterministic scoring engine.

All fields are env-overridable (pydantic-settings matches env vars to
field names case-insensitively) so thresholds can be tuned without a
code change.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.env import ENV_FILE


class ScoringParams(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    no_show_rate: float = 0.08
    safety_floor_ratio: float = 0.5
    critical_threshold: int = -50
    warning_threshold: int = -15
    surplus_threshold: int = 100
    no_action_min_deficit: int = 25
    revenue_per_load_usd: int = 1850
    storage_cost_per_unit_day_usd: int = 8
    storage_savings_max_days: int = 3
    aggressive_multiplier: float = 1.2


# Safe to cache: this is only ever called lazily, from request handling,
# which happens well after main.py's module-level load_dotenv() call.
@lru_cache
def get_scoring_params() -> ScoringParams:
    return ScoringParams()
