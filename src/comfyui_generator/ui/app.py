"""Desktop application entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from comfyui_generator.ui.branding import app_icon
from comfyui_generator.ui.main_window import MainWindow
from comfyui_generator.ui.style import APP_QSS


def main() -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "InoriLarson.ComfyUIGenerator")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("ComfyUI Generator")
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    app.setStyleSheet(APP_QSS)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
