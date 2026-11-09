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


def test_hires_preference_not_overridden_by_preset_migration(tmp_path, monkeypatch):
    from comfyui_generator.core.project import save_session

    monkeypatch.setenv("COMFYUI_GENERATOR_HOME", str(tmp_path))
    monkeypatch.setenv("CUI_NO_AUTOCONNECT", "1")
    app = QApplication.instance() or QApplication([])

    # A prior session explicitly disabled hires.
    save_session({
        "version": 1,
        "options": {
            "hires_enabled": False,
            "width": 832, "height": 1216, "steps": 28,
            "cfg": 5.0, "clip_skip": -1,
        },
    }, tmp_path)

    window = MainWindow()
    try:
        # Force the NoobAI migration path with a matching checkpoint.
        window.ckpt_combo.setEditText("noobaiXLNAIXL_epsilonPred11Version")
        window.width_spin.setValue(832)
        window.height_spin.setValue(1216)
        window.steps_spin.setValue(28)
        window.cfg_spin.setValue(5.0)
        window.clip_skip.setValue(-1)
        window._apply_model_preset_migration()
        assert window.hires_check.isChecked() is False
    finally:
        window.close()


def test_hires_default_enabled_on_first_run_migration(tmp_path, monkeypatch):
    monkeypatch.setenv("COMFYUI_GENERATOR_HOME", str(tmp_path))
    monkeypatch.setenv("CUI_NO_AUTOCONNECT", "1")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        assert window._session_hires_preference is None
        window.ckpt_combo.setEditText("noobaiXLNAIXL_epsilonPred11Version")
        window.width_spin.setValue(832)
        window.height_spin.setValue(1216)
        window.steps_spin.setValue(28)
        window.cfg_spin.setValue(5.0)
        window.clip_skip.setValue(-1)
        window._apply_model_preset_migration()
        assert window.hires_check.isChecked() is True
    finally:
        window.close()


def test_hires_preference_not_overridden_by_model_config(tmp_path, monkeypatch):
    from comfyui_generator.core.project import save_session
    from comfyui_generator.core.model_configs import (
        load_model_configs, find_model_config)

    monkeypatch.setenv("COMFYUI_GENERATOR_HOME", str(tmp_path))
    monkeypatch.setenv("CUI_NO_AUTOCONNECT", "1")
    app = QApplication.instance() or QApplication([])

    save_session({
        "version": 1,
        "options": {"hires_enabled": False},
    }, tmp_path)

    window = MainWindow()
    try:
        config = find_model_config(
            load_model_configs(), r"WAI\waiIllustriousSDXL_v170.safetensors")
        assert config and config.get("hires", {}).get("enabled") is True
        window._apply_model_config(config)
        assert window.hires_check.isChecked() is False
    finally:
        window.close()

