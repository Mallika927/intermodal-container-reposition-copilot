"""Public entrypoint for retrieving synthetic NetworkState snapshots."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.data.generator import generate_network_state
from app.data.models import NetworkState


class _DataSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    synthetic_data_seed: int = 42


def _default_snapshot_ts() -> datetime:
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0, tzinfo=None)


def get_network_state(
    seed: int | None = None,
    snapshot_ts: datetime | None = None,
) -> NetworkState:
    """Return the synthetic NetworkState for the given seed/snapshot hour.

    Defaults: seed from SYNTHETIC_DATA_SEED (env var, default 42);
    snapshot_ts = current UTC time truncated to the hour, so repeated
    calls within the same hour are deterministic.
    """
    resolved_seed = seed if seed is not None else _DataSettings().synthetic_data_seed
    resolved_snapshot_ts = snapshot_ts if snapshot_ts is not None else _default_snapshot_ts()
    return generate_network_state(resolved_seed, resolved_snapshot_ts)
