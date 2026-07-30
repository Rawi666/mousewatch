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
    try:
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
        QT_AVAILABLE = True
        QT_IMPORT_ERROR = None
    except ImportError as exc:
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
        QT_AVAILABLE = False
        QT_IMPORT_ERROR = str(exc)
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
    QT_AVAILABLE = False
    QT_IMPORT_ERROR = "Qt is only used on Linux"
