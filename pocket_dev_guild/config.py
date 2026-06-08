"""Configuration loading: app-level settings."""

from __future__ import annotations

import os
from pathlib import Path

import yaml


class Settings:
    """App-level settings, kept tiny on purpose.

    Reads top-level keys from `config.yaml` once at startup:
      agent_binary       (default "auggie")
      agent_prompt_param (default "--print")
      mongodb_url        (default None → in-memory stores)
    """

    def __init__(self, config_path: Path | str | None = None) -> None:
        if config_path is None:
            config_path = os.environ.get("POCKET_DEV_GUILD_CONFIG", "config.yaml")
        self.config_path = Path(config_path)

        data: dict = {}
        if self.config_path.exists():
            data = yaml.safe_load(self.config_path.read_text()) or {}
        self.agent_binary: str = data.get("agent_binary", "auggie")
        self.agent_prompt_param: str = data.get("agent_prompt_param", "--print")
        # MongoDB URL can be set via environment variable or config file
        # Environment variable takes precedence
        self.mongodb_url: str | None = (
            os.environ.get("MONGODB_URL")
            or data.get("mongodb_url")
            or None
        )
