"""
Zombee Product Manager Desktop -- entry point.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.crash_handler import install_global_exception_handler
from app.db import Database
from app.i18n import set_language
from app.settings import SettingsStore
from app.ui.image_picker import set_download_cache_dir
from app.ui.main_window import MainWindow


def _resource_path(relative_path: str) -> Path:
    """Works both running from source and as a PyInstaller-frozen .exe,
    where bundled data files are extracted under sys._MEIPASS instead of
    living next to this script."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base / relative_path


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Zombee Product Manager")

    icon_path = _resource_path("app/assets/icon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    settings_store = SettingsStore()
    install_global_exception_handler(settings_store.config_dir / "logs")
    set_download_cache_dir(str(settings_store.config_dir / "downloaded-images"))

    settings = settings_store.load()

    try:
        set_language(settings.language)
    except FileNotFoundError:
        pass  # fall back to whatever i18n.py already loaded by default (English)

    db = Database(settings.database_path)

    window = MainWindow(db, settings_store, settings)
    window.show()

    exit_code = app.exec()
    db.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
