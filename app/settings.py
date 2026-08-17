"""
Application settings, persisted as JSON in a user config directory so they
survive between runs. Deliberately a flat, simple structure -- this is a
single-user desktop app, no need for anything fancier than a JSON file.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .image_manager import CompressionSettings


def _default_config_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA", str(Path.home()))
    else:
        base = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(base) / "ZombeeProductManager"


def _default_documents_dir() -> Path:
    if os.name == "nt":
        return Path.home() / "Documents" / "ZombeeProductManager"
    return Path.home() / "ZombeeProductManager"


@dataclass
class AppSettings:
    database_path: str = ""
    output_images_folder: str = ""
    compression_format: str = "webp"
    compression_quality: int = 82
    compression_max_dimension: int = 2000
    language: str = "en"
    site_url: str = ""
    site_username: str = ""
    # The application password itself is NOT stored here -- it lives in the
    # OS credential store via credential_store.py, never in this plaintext
    # settings file.

    def compression_settings(self) -> CompressionSettings:
        return CompressionSettings(
            output_format=self.compression_format,
            quality=self.compression_quality,
            max_dimension=self.compression_max_dimension,
        )

    @classmethod
    def with_defaults(cls) -> "AppSettings":
        docs = _default_documents_dir()
        return cls(
            database_path=str(docs / "products.sqlite3"),
            output_images_folder=str(docs / "upload-images"),
        )


class SettingsStore:
    def __init__(self, config_dir: Path | None = None):
        self.config_dir = config_dir or _default_config_dir()
        self.config_path = self.config_dir / "settings.json"

    def load(self) -> AppSettings:
        if not self.config_path.exists():
            settings = AppSettings.with_defaults()
            self.save(settings)
            return settings
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        defaults = asdict(AppSettings.with_defaults())
        defaults.update(data)
        return AppSettings(**defaults)

    def save(self, settings: AppSettings) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(asdict(settings), f, indent=2)
