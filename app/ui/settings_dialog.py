"""Settings dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLineEdit, QPushButton, QSlider, QSpinBox, QVBoxLayout,
)
from PySide6.QtCore import Qt

from ..i18n import t
from ..settings import AppSettings


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("settings.title"))
        self._settings = settings

        form = QFormLayout(self)

        folder_row = QHBoxLayout()
        self.folder_input = QLineEdit(settings.output_images_folder)
        folder_row.addWidget(self.folder_input)
        browse_button = QPushButton(t("common.browse"))
        browse_button.clicked.connect(self._browse_folder)
        folder_row.addWidget(browse_button)
        form.addRow(t("settings.output_folder"), folder_row)

        self.format_combo = QComboBox()
        self.format_combo.addItem("WebP", "webp")
        self.format_combo.addItem("JPEG", "jpeg")
        index = self.format_combo.findData(settings.compression_format)
        self.format_combo.setCurrentIndex(max(index, 0))
        form.addRow(t("settings.compression_format"), self.format_combo)

        quality_row = QHBoxLayout()
        self.quality_slider = QSlider(Qt.Horizontal)
        self.quality_slider.setRange(1, 100)
        self.quality_slider.setValue(settings.compression_quality)
        self.quality_value_label = QLineEdit(str(settings.compression_quality))
        self.quality_value_label.setFixedWidth(40)
        self.quality_value_label.setReadOnly(True)
        self.quality_slider.valueChanged.connect(lambda v: self.quality_value_label.setText(str(v)))
        quality_row.addWidget(self.quality_slider)
        quality_row.addWidget(self.quality_value_label)
        form.addRow(t("settings.compression_quality"), quality_row)

        self.max_dimension_spin = QSpinBox()
        self.max_dimension_spin.setRange(200, 8000)
        self.max_dimension_spin.setSingleStep(100)
        self.max_dimension_spin.setValue(settings.compression_max_dimension)
        form.addRow(t("settings.compression_max_dimension"), self.max_dimension_spin)

        self.language_combo = QComboBox()
        self.language_combo.addItem("English", "en")
        index = self.language_combo.findData(settings.language)
        self.language_combo.setCurrentIndex(max(index, 0))
        form.addRow(t("settings.language"), self.language_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, t("settings.output_folder"), self.folder_input.text())
        if folder:
            self.folder_input.setText(folder)

    def get_settings(self) -> AppSettings:
        return AppSettings(
            database_path=self._settings.database_path,
            output_images_folder=self.folder_input.text().strip(),
            compression_format=self.format_combo.currentData(),
            compression_quality=self.quality_slider.value(),
            compression_max_dimension=self.max_dimension_spin.value(),
            language=self.language_combo.currentData(),
        )
