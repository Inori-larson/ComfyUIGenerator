import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from comfyui_generator.ui.main_window import MainWindow


def test_copy_natural_language_fields_between_modes(tmp_path, monkeypatch):
    monkeypatch.setenv("COMFYUI_GENERATOR_HOME", str(tmp_path))
    monkeypatch.setenv("CUI_NO_AUTOCONNECT", "1")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.single_role.setPlainText("yixuan")
        window.single_appearance.setPlainText("silver hair")
        window.single_clothing.setPlainText("black blazer")
        window.single_scene.setText("bedroom")
        window.single_desc.setPlainText("sitting on the bed")
        window.single_extra.setPlainText("night")

        window.copy_single_to_story()

        assert window.story_role.toPlainText() == "yixuan"
        assert window.story_appearance.toPlainText() == "silver hair"
        assert window.story_clothing.toPlainText() == "black blazer"
        assert window.story_scene.text() == "bedroom"
        assert window.story_premise.toPlainText() == "sitting on the bed"
        assert window.story_extra.toPlainText() == "night"

        window._set_single_fields({})
        window.copy_story_to_single()

        assert window.single_role.toPlainText() == "yixuan"
        assert window.single_desc.toPlainText() == "sitting on the bed"
    finally:
        window.close()
