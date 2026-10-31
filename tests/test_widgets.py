import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from comfyui_generator.ui.style import APP_QSS
from comfyui_generator.ui.widgets import WrappingTabs


def test_tabs_wrap_without_clipping_at_min_width():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_QSS)
    tabs = WrappingTabs()
    for _ in range(12):
        tabs.addTab(QWidget(), "提示词")
    tabs.resize(380, 600)
    tabs.show()
    app.processEvents()
    tabs._relayout()
    assert tabs._grid.columnCount() == 4
    assert all(button.width() >= button.sizeHint().width()
               for button in tabs._buttons)
    tabs.close()
