import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QSpinBox, QWidget

from comfyui_generator.ui.main_window import MainWindow, merge_default_positive
from comfyui_generator.ui.style import APP_QSS
from comfyui_generator.ui.widgets import SearchComboBox, WrappingTabs
from comfyui_generator.ui.wheel_guard import WheelGuard


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


def test_combo_ignores_hover_wheel():
    app = QApplication.instance() or QApplication([])
    combo = SearchComboBox()
    combo.addItems(["a", "b"])

    class Event:
        ignored = False

        def ignore(self):
            self.ignored = True

    event = Event()
    combo.wheelEvent(event)
    assert event.ignored
    assert combo.currentIndex() == 0


def test_spinbox_ignores_wheel_without_focus():
    app = QApplication.instance() or QApplication([])
    spin = QSpinBox()
    spin.setRange(0, 10)
    spin.setValue(5)

    class Event:
        ignored = False

        def type(self):
            return QEvent.Type.Wheel

        def ignore(self):
            self.ignored = True

    event = Event()
    assert WheelGuard().eventFilter(spin, event)
    assert event.ignored
    assert spin.value() == 5


def test_spinbox_wheel_is_allowed_after_click():
    app = QApplication.instance() or QApplication([])
    spin = QSpinBox()
    guard = WheelGuard()

    class Press:
        def type(self):
            return QEvent.Type.MouseButtonPress

        def button(self):
            return Qt.MouseButton.LeftButton

    class Wheel:
        ignored = False

        def type(self):
            return QEvent.Type.Wheel

        def ignore(self):
            self.ignored = True

    guard.eventFilter(spin, Press())
    event = Wheel()
    assert not guard.eventFilter(spin, event)
    assert not event.ignored


def test_default_positive_prompt_is_merged_without_duplicates():
    en, zh, text = merge_default_positive(
        "masterpiece, best quality", "杰作、最佳质量", "杰作、最佳质量")
    assert en.count("masterpiece") == 1
    assert en.count("best quality") == 1
    assert "very aesthetic" in en
    assert "newest" in en
    assert "scenery" in en
    assert "volumetric lighting" in en
    assert text.count("杰作") == 1
    assert "非常有美感" in text
    assert "风景" in text
    assert "体积光" in text


def test_checked_shot_rows_accumulate_for_selected_generation():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    shots = [{"id": "01", "name": "a", "prompt": "p1"},
             {"id": "02", "name": "b", "prompt": "p2"},
             {"id": "03", "name": "c", "prompt": "p3"}]
    window._fill_shot_table(shots)
    window.chk_selected.setChecked(True)
    window._on_shot_cell_clicked(0, 0)
    window._on_shot_cell_clicked(2, 0)
    selected = window._collect_shots(True)
    assert [shot["id"] for shot in selected] == ["01", "03"]
    window.close()


def test_multiline_paste_keeps_browser_line_breaks():
    from PySide6.QtCore import QMimeData
    from comfyui_generator.ui.widgets import MultiLinePlainTextEdit

    app = QApplication.instance() or QApplication([])
    edit = MultiLinePlainTextEdit()
    mime = QMimeData()
    mime.setHtml("<div>第一行</div><div>第二行<br>第三行</div>")
    mime.setText("第一行第二行第三行")
    edit.insertFromMimeData(mime)
    assert edit.toPlainText() == "第一行\n第二行\n第三行"


def test_multiline_paste_prefers_text_with_newlines():
    from PySide6.QtCore import QMimeData
    from comfyui_generator.ui.widgets import MultiLinePlainTextEdit

    app = QApplication.instance() or QApplication([])
    edit = MultiLinePlainTextEdit()
    mime = QMimeData()
    mime.setHtml("<p>a</p><p>b</p>")
    mime.setText("a\nb")
    edit.insertFromMimeData(mime)
    assert edit.toPlainText() == "a\nb"
