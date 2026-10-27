"""Desktop application entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from comfyui_generator.ui.main_window import MainWindow
from comfyui_generator.ui.style import APP_QSS


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("ComfyUI Generator")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_QSS)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
