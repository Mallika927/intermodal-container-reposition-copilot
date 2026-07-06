"""Agent-level settings: the replay-mode toggle.

Not cached: loop.py's API-key guard and routes.py's dispatch both need to
observe USE_REPLAY_MODE changes within a single process (e.g. in tests
that monkeypatch it), so each call re-reads current env state.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.env import ENV_FILE


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    use_replay_mode: bool = False


def get_agent_settings() -> AgentSettings:
    return AgentSettings()
