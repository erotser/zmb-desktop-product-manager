"""
A single image slot: shows a thumbnail (or a placeholder), a "Choose
Image..." button, and an alt-text field.

Distinguishes two states that matter for the "import, edit, re-export"
workflow:
  - A NEW local file the user just picked in this app (has a thumbnail,
    will be compressed/renamed on export).
  - An EXISTING reference from an earlier CSV import (a URL or filename
    already on the site) -- shown as text by default, since the app has no
    local copy to preview. A "Download" button (shown only when the
    reference is an actual URL) fetches it so it can be previewed and,
    if the user picks a replacement, edited. Leaving it alone (not
    downloading, not replacing) still preserves the original reference on
    export -- downloading is purely for preview/editing convenience.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ..i18n import t
from ..image_downloader import ImageDownloadError, download_image, is_downloadable_url

THUMBNAIL_SIZE = 96
IMAGE_FILE_FILTER = "Images (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.gif)"

# Set by the application at startup (see main.py) to a folder under the
# user's config directory. Module-level so every ImagePickerWidget instance
# shares one cache without needing it threaded through every constructor.
_download_cache_dir: Optional[str] = None


def set_download_cache_dir(path: str):
    global _download_cache_dir
    _download_cache_dir = path


class ImagePickerWidget(QWidget):
    changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None, label: str = ""):
        super().__init__(parent)
        self._local_path: Optional[str] = None
        self._existing_ref: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if label:
            layout.addWidget(QLabel(label))

        row = QHBoxLayout()
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE)
        self.thumbnail_label.setStyleSheet("border: 1px solid #999; background: #f2f2f2;")
        self.thumbnail_label.setAlignment(Qt.AlignCenter)
        row.addWidget(self.thumbnail_label)

        col = QVBoxLayout()
        self.status_label = QLabel(t("image_picker.no_image"))
        self.status_label.setWordWrap(True)
        col.addWidget(self.status_label)

        button_row = QHBoxLayout()
        self.choose_button = QPushButton(t("product_form.choose_image"))
        self.choose_button.clicked.connect(self._on_choose_clicked)
        button_row.addWidget(self.choose_button)

        self.download_button = QPushButton(t("image_picker.download"))
        self.download_button.clicked.connect(self._on_download_clicked)
        self.download_button.hide()
        button_row.addWidget(self.download_button)

        self.clear_button = QPushButton(t("common.clear"))
        self.clear_button.clicked.connect(self._on_clear_clicked)
        button_row.addWidget(self.clear_button)
        col.addLayout(button_row)

        self.alt_input = QLineEdit()
        self.alt_input.setPlaceholderText(t("product_form.image_alt"))
        self.alt_input.textChanged.connect(lambda _: self.changed.emit())
        col.addWidget(self.alt_input)

        row.addLayout(col)
        layout.addLayout(row)

        self._refresh_display()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def set_value(self, local_path: Optional[str], alt: str = "", existing_ref: Optional[str] = None):
        self._local_path = local_path
        self._existing_ref = existing_ref
        self.alt_input.setText(alt or "")
        self._refresh_display()

    def get_local_path(self) -> Optional[str]:
        return self._local_path

    def get_existing_ref(self) -> Optional[str]:
        return self._existing_ref

    def get_alt(self) -> str:
        return self.alt_input.text()

    def has_image(self) -> bool:
        return bool(self._local_path or self._existing_ref)

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    def _on_choose_clicked(self):
        path, _ = QFileDialog.getOpenFileName(self, t("product_form.choose_image"), "", IMAGE_FILE_FILTER)
        if path:
            self._local_path = path
            self._refresh_display()
            self.changed.emit()

    def _on_download_clicked(self):
        if not self._existing_ref or not _download_cache_dir:
            return
        self.download_button.setEnabled(False)
        self.download_button.setText(t("image_picker.downloading"))
        try:
            local_path = download_image(self._existing_ref, _download_cache_dir)
        except ImageDownloadError as e:
            QMessageBox.warning(self, t("common.warning"), str(e))
            return
        finally:
            self.download_button.setEnabled(True)
            self.download_button.setText(t("image_picker.download"))

        # Downloading fills in a local, previewable copy but keeps the
        # original reference too (harmless -- get_local_path() takes
        # priority on export, so this doesn't change what gets exported,
        # it just makes the image visible/editable now).
        self._local_path = local_path
        self._refresh_display()
        self.changed.emit()

    def _on_clear_clicked(self):
        self._local_path = None
        self._existing_ref = None
        self._refresh_display()
        self.changed.emit()

    def _refresh_display(self):
        if self._local_path and Path(self._local_path).exists():
            pixmap = QPixmap(self._local_path)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(
                    THUMBNAIL_SIZE, THUMBNAIL_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self.thumbnail_label.setPixmap(pixmap)
            else:
                self.thumbnail_label.setText(t("image_picker.preview_unavailable"))
            self.status_label.setText(Path(self._local_path).name)
            self.download_button.hide()
        elif self._existing_ref:
            self.thumbnail_label.clear()
            self.thumbnail_label.setText(t("image_picker.no_preview"))
            self.status_label.setText(t("image_picker.existing_image", ref=self._existing_ref))
            self.download_button.setVisible(is_downloadable_url(self._existing_ref))
        else:
            self.thumbnail_label.clear()
            self.thumbnail_label.setText(t("image_picker.no_preview"))
            self.status_label.setText(t("image_picker.no_image"))
            self.download_button.hide()
