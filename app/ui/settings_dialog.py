"""Settings dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSlider, QSpinBox, QVBoxLayout,
)
from PySide6.QtCore import Qt

from .. import credential_store
from ..i18n import t
from ..settings import AppSettings
from ..site_sync import SiteConnection, SiteSyncError, test_connection


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("settings.title"))
        self._settings = settings

        form = QFormLayout(self)
        form.setContentsMargins(20, 20, 20, 20)
        form.setVerticalSpacing(12)

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

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        form.addRow(separator)

        section_label = QLabel(t("settings.site_connection"))
        section_label.setStyleSheet("font-weight: 600;")
        form.addRow(section_label)

        help_label = QLabel(t("settings.site_connection_help"))
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #666;")
        form.addRow(help_label)

        self.site_url_input = QLineEdit(settings.site_url)
        self.site_url_input.setPlaceholderText("https://example.com")
        form.addRow(t("settings.site_url"), self.site_url_input)

        self.site_username_input = QLineEdit(settings.site_username)
        form.addRow(t("settings.site_username"), self.site_username_input)

        self.site_password_input = QLineEdit(credential_store.load_application_password() or "")
        self.site_password_input.setEchoMode(QLineEdit.Password)
        self.site_password_input.setPlaceholderText(t("settings.site_password_placeholder"))
        form.addRow(t("settings.site_password"), self.site_password_input)

        test_row = QHBoxLayout()
        self.test_connection_button = QPushButton(t("settings.test_connection"))
        self.test_connection_button.clicked.connect(self._on_test_connection)
        test_row.addWidget(self.test_connection_button)
        self.connection_status_label = QLabel("")
        self.connection_status_label.setWordWrap(True)
        test_row.addWidget(self.connection_status_label, 1)
        form.addRow("", test_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, t("settings.output_folder"), self.folder_input.text())
        if folder:
            self.folder_input.setText(folder)

    def _current_connection(self) -> SiteConnection:
        return SiteConnection(
            site_url=self.site_url_input.text().strip(),
            username=self.site_username_input.text().strip(),
            application_password=self.site_password_input.text().strip(),
        )

    def _on_test_connection(self):
        connection = self._current_connection()
        if not connection.site_url or not connection.username or not connection.application_password:
            self.connection_status_label.setText(t("settings.connection_missing_fields"))
            self.connection_status_label.setStyleSheet("color: #b00020;")
            return

        self.test_connection_button.setEnabled(False)
        self.connection_status_label.setText(t("settings.testing_connection"))
        self.connection_status_label.setStyleSheet("color: #666;")

        try:
            result = test_connection(connection)
        except SiteSyncError as e:
            self.connection_status_label.setText(str(e))
            self.connection_status_label.setStyleSheet("color: #b00020;")
            return
        finally:
            self.test_connection_button.setEnabled(True)

        self.connection_status_label.setText(
            t("settings.connection_success", site=result.get("site_name", ""), version=result.get("plugin_version", "?"))
        )
        self.connection_status_label.setStyleSheet("color: #1a7a1a;")

    def get_settings(self) -> AppSettings:
        return AppSettings(
            database_path=self._settings.database_path,
            output_images_folder=self.folder_input.text().strip(),
            compression_format=self.format_combo.currentData(),
            compression_quality=self.quality_slider.value(),
            compression_max_dimension=self.max_dimension_spin.value(),
            language=self.language_combo.currentData(),
            site_url=self.site_url_input.text().strip(),
            site_username=self.site_username_input.text().strip(),
        )

    def get_site_password(self) -> str:
        return self.site_password_input.text().strip()
