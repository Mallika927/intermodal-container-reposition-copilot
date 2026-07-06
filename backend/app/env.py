"""Single source of truth for the backend's .env file location.

Anchored to this file's own path so it resolves to backend/.env correctly
regardless of the working directory the process is launched from.
"""

from __future__ import annotations

from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
