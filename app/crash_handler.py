"""
The packaged .exe runs with no console window (console=False in build.spec,
so the app doesn't flash a black terminal behind it). That means any
unhandled Python exception has nowhere to print to -- it just vanishes,
and the app appears to do nothing. This installs a global handler so that
instead:
  1. The error is written to a timestamped log file the user can find and
     send back if something goes wrong.
  2. A message box shows what happened, so "nothing happens" never occurs
     silently again.
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path


def install_global_exception_handler(log_dir: Path):
    log_dir.mkdir(parents=True, exist_ok=True)

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))

        log_path = log_dir / f"crash-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        try:
            log_path.write_text(text, encoding="utf-8")
        except OSError:
            log_path = None

        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            if QApplication.instance() is not None:
                message = f"Something went wrong:\n\n{exc_type.__name__}: {exc_value}"
                if log_path:
                    message += f"\n\nDetails saved to:\n{log_path}"
                QMessageBox.critical(None, "Error", message)
        except Exception:
            pass  # if even showing the error dialog fails, at least the log file was written

    sys.excepthook = handle_exception
