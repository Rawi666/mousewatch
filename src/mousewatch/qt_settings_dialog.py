from common import Common
from mw_platform import (
    IS_WINDOWS,
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    Qt,
    QVBoxLayout,
)
from settings_store import startup_shortcut_exists


if not IS_WINDOWS:
    class QtSettingsDialog(QDialog):
        """Qt settings dialog for MouseWatch."""

        def __init__(self, tray_app):
            super().__init__()
            self._tray_app = tray_app
            self.setWindowTitle("MouseWatch Settings")
            self.setModal(False)
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

            layout = QVBoxLayout(self)
            form = QFormLayout()

            self._threshold_spin = QSpinBox()
            self._threshold_spin.setRange(1, 100)
            self._threshold_spin.setValue(tray_app.threshold)
            form.addRow("Battery threshold (1-100%):", self._threshold_spin)

            self._reminder_spin = QSpinBox()
            self._reminder_spin.setRange(60, 3600)
            self._reminder_spin.setValue(tray_app.reminder_interval)
            form.addRow("Reminder interval (60-3600 s):", self._reminder_spin)

            self._poll_spin = QSpinBox()
            self._poll_spin.setRange(20, 3600)
            self._poll_spin.setValue(tray_app.interval)
            form.addRow("Poll interval (20-3600 s):", self._poll_spin)

            self._sound_check = QCheckBox("Notification sound")
            self._sound_check.setChecked(tray_app.notification_sound)
            form.addRow(self._sound_check)

            self._device_check = QCheckBox("Device connect/disconnect notifications")
            self._device_check.setChecked(tray_app.device_notifications)
            form.addRow(self._device_check)

            self._startup_check = QCheckBox(Common.startup_label())
            self._startup_check.setChecked(startup_shortcut_exists())
            form.addRow(self._startup_check)

            layout.addLayout(form)

            button_row = QHBoxLayout()
            self._save_button = QPushButton("Save")
            self._cancel_button = QPushButton("Cancel")
            self._save_button.clicked.connect(self._on_save)
            self._cancel_button.clicked.connect(self.close)
            button_row.addStretch(1)
            button_row.addWidget(self._save_button)
            button_row.addWidget(self._cancel_button)
            layout.addLayout(button_row)

        def _on_save(self):
            settings = {
                "threshold": self._threshold_spin.value(),
                "reminder_interval": self._reminder_spin.value(),
                "poll_interval": self._poll_spin.value(),
                "notification_sound": self._sound_check.isChecked(),
                "device_notifications": self._device_check.isChecked(),
                "start_with_windows": self._startup_check.isChecked(),
            }
            Common.persist_and_apply_settings(self._tray_app, settings)
            self.close()
else:
    class QtSettingsDialog:
        pass
