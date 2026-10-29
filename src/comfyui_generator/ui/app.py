"""Desktop application entry point."""

from __future__ import annotations

import faulthandler
import sys
import time
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox

from comfyui_generator.core.config import app_data_dir
from comfyui_generator.ui.branding import app_icon
from comfyui_generator.ui.main_window import MainWindow
from comfyui_generator.ui.style import APP_QSS


def _open_crash_log():
    folder = app_data_dir() / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "ui_crash.log"
    if path.is_file() and path.stat().st_size > 1_000_000:
        path.unlink()
    handle = open(path, "a", encoding="utf-8")
    handle.write("\n=== %s ===\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
    handle.flush()
    return handle


def main() -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "InoriLarson.ComfyUIGenerator")
        except Exception:
            pass
    log = _open_crash_log()
    faulthandler.enable(file=log, all_threads=True)

    def hook(exc_type, exc_value, exc_tb):
        traceback.print_exception(exc_type, exc_value, exc_tb, file=log)
        log.flush()

    sys.excepthook = hook
    app = QApplication(sys.argv)
    app.setApplicationName("ComfyUI Generator")
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    app.setStyleSheet(APP_QSS)
    try:
        window = MainWindow()
        window.show()
    except BaseException:
        traceback.print_exc(file=log)
        log.flush()
        QMessageBox.critical(None, "启动失败", "界面启动失败，详情已写入日志：\n%s" % log.name)
        raise
    try:
        sys.exit(app.exec())
    finally:
        log.flush()


if __name__ == "__main__":
    main()
