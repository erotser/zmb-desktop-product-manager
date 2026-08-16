"""
Zombee Product Manager Desktop -- entry point.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.db import Database
from app.i18n import set_language
from app.settings import SettingsStore
from app.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Zombee Product Manager")

    settings_store = SettingsStore()
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
