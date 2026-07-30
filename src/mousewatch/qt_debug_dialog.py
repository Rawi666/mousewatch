try:
    from .common import Common
    from .mw_platform import (
        IS_WINDOWS,
        QDialog,
        QHBoxLayout,
        QPlainTextEdit,
        QPushButton,
        Qt,
        QVBoxLayout,
    )
except ImportError:
    from common import Common
    from mw_platform import (
        IS_WINDOWS,
        QDialog,
        QHBoxLayout,
        QPlainTextEdit,
        QPushButton,
        Qt,
        QVBoxLayout,
    )


if not IS_WINDOWS:
    class QtDebugDialog(QDialog):
        """Qt debug dialog showing raw HID data."""

        def __init__(self, tray_app):
            super().__init__()
            self._tray_app = tray_app
            self.setWindowTitle("MouseWatch Debug")
            self.setModal(False)
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

            layout = QVBoxLayout(self)
            self._text = QPlainTextEdit()
            self._text.setReadOnly(True)
            self._text.setMinimumSize(640, 360)
            layout.addWidget(self._text)

            button_row = QHBoxLayout()
            self._refresh_button = QPushButton("Refresh")
            self._close_button = QPushButton("Close")
            self._refresh_button.clicked.connect(self.refresh)
            self._close_button.clicked.connect(self.close)
            button_row.addStretch(1)
            button_row.addWidget(self._refresh_button)
            button_row.addWidget(self._close_button)
            layout.addLayout(button_row)

            self.refresh()

        def refresh(self):
            app = self._tray_app
            snapshot = app.refresh_debug_snapshot()
            lines = Common.build_debug_lines(app, snapshot, section_title=app.protocol.input_section_title)
            self._text.setPlainText("\n".join(lines))
else:
    class QtDebugDialog:
        pass
