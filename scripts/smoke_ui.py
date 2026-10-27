"""Headless-ish UI smoke test: render the window to a PNG without connecting.

Usage:
    python scripts/smoke_ui.py out.png
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["CUI_NO_AUTOCONNECT"] = "1"

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from comfyui_generator.ui.main_window import MainWindow  # noqa: E402
from comfyui_generator.ui.style import APP_QSS  # noqa: E402


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_QSS)
    window = MainWindow()
    window.resize(1480, 940)
    window.show()
    app.processEvents()
    out = sys.argv[1] if len(sys.argv) > 1 else "ui_smoke.png"
    ok = window.grab().save(out)
    print("saved:", out, ok)
    QTimer.singleShot(100, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
