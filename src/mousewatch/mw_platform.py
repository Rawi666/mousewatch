import sys

try:
    if sys.platform.startswith("linux"):
        import hidraw as hid
        HID_BACKEND = "hidraw"
    else:
        import hid
        HID_BACKEND = "hid"
except ImportError:
    import hid
    HID_BACKEND = "hid"

IS_WINDOWS = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")

if not IS_WINDOWS:
    from PySide6.QtCore import QObject, Qt, Signal
    from PySide6.QtGui import QAction, QIcon, QImage, QPixmap
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QDialog,
        QFormLayout,
        QHBoxLayout,
        QMenu,
        QPlainTextEdit,
        QPushButton,
        QSpinBox,
        QSystemTrayIcon,
        QVBoxLayout,
    )
else:
    QObject = None
    Qt = None
    Signal = None
    QAction = None
    QIcon = None
    QImage = None
    QPixmap = None
    QApplication = None
    QCheckBox = None
    QDialog = None
    QFormLayout = None
    QHBoxLayout = None
    QMenu = None
    QPlainTextEdit = None
    QPushButton = None
    QSpinBox = None
    QSystemTrayIcon = None
    QVBoxLayout = None
