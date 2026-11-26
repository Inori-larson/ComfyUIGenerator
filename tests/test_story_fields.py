import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["CUI_NO_AUTOCONNECT"] = "1"

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from comfyui_generator.core.jobs import Task
from comfyui_generator.ui.main_window import MainWindow


def _window():
    app = QApplication.instance() or QApplication([])
    return app, MainWindow()


def test_select_all_shots_marks_every_row():
    _app, window = _window()
    shots = [{"id": "%02d" % i, "name": "shot_%02d" % i,
              "prompt": "1girl, smile"} for i in range(1, 5)]
    window._fill_shot_table(shots)
    window.select_all_shots()
    rows = sorted({index.row()
                   for index in window.shot_table.selectedIndexes()})
    assert rows == [0, 1, 2, 3]
    assert all(window.shot_table.item(row, 0).checkState() == Qt.CheckState.Checked
               for row in range(4))
    assert window._selected_shot_ids == ["01", "02", "03", "04"]
    assert [s["id"] for s in window._collect_shots(True)] == [
        "01", "02", "03", "04"]


def test_output_entries_carry_shot_id():
    _app, window = _window()
    window.project = {"mode": "story", "shots": [], "outputs": []}
    task = Task(shot_id="01", shot_name="shot_01", variant=1, seed=123,
                shot={"id": "01", "prompt": "1girl"})
    task.image = "anime_story/task/a/01_shot_01_00001_.png"
    window._append_project_output(task)
    entry = window.project["outputs"][0]
    assert isinstance(entry, dict)
    assert entry["image"] == task.image
    assert entry["shot_id"] == "01"
    assert entry["variant"] == 1
    assert window._output_value(entry) == task.image


def test_output_entry_shot_lookup_uses_shot_id_not_index():
    _app, window = _window()
    shots = [{"id": "01", "name": "shot_01"}, {"id": "02", "name": "shot_02"}]
    entry = {"image": "x.png", "shot_id": "02", "variant": 1}
    assert window._output_entry_shot(entry, shots, 0)["id"] == "02"


def test_plot_label_not_duplicated():
    _app, window = _window()
    text = (
        "角色：girl\n"
        "大场景：电影院\n"
        "要求：服装只能用初始服装，不要脱鞋\n"
        "剧情：有相互口交、内射、吞精\n"
        "其它：画面明亮"
    )
    fields = window._parse_story_text(text)
    window._set_story_fields(fields)
    premise = window._story_premise_text()
    assert premise.count("剧情：") == 1
    assert "不要脱鞋" in premise
    assert "画面明亮" in premise


def test_plot_without_label_gets_header():
    _app, window = _window()
    fields = window._parse_story_text("女孩在房间里自拍")
    window._set_story_fields(fields)
    premise = window._story_premise_text()
    assert premise.strip() == "剧情：\n女孩在房间里自拍"


def test_repeated_label_does_not_overwrite_previous_content():
    _app, window = _window()
    fields = window._parse_story_text(
        "剧情：第一段\n要求：保留这句\n剧情：第二段")
    assert "第一段" in fields["plot"]
    assert "保留这句" in fields["plot"]
    assert "第二段" in fields["plot"]


def test_labeled_field_not_double_prefixed():
    _app, window = _window()
    fields = {"role": "角色：girl", "appearance": "", "clothing": "",
              "scene": "场景：教室", "plot": "", "extra": ""}
    window._set_story_fields(fields)
    premise = window._story_premise_text()
    assert premise.count("角色") == 1
    assert premise.count("场景") == 1


def test_show_shot_details_works_with_minimal_fields():
    from PySide6.QtWidgets import QDialog
    import comfyui_generator.ui.main_window as mw

    _app, window = _window()
    window._fill_shot_table([
        {"id": "01", "name": "shot_01", "prompt": "1girl, solo",
         "description": "女孩独处"},
    ])
    captured = {}

    class FakeDialog:
        def __init__(self, data, outlines, parent=None):
            captured["data"] = data
            captured["outlines"] = outlines

        def exec(self):
            return QDialog.DialogCode.Rejected

    original = mw.ShotDetailsDialog
    mw.ShotDetailsDialog = FakeDialog
    try:
        window.show_shot_details()
    finally:
        mw.ShotDetailsDialog = original
    shot = captured["data"][0]
    assert shot["prompt"] == "1girl, solo"
    assert shot["description"] == "女孩独处"
    assert captured["outlines"] == ["女孩独处"]


def test_model_suffix():
    _app, window = _window()
    assert window._model_suffix("kimi-k3") == "kimi-k3"
    assert window._model_suffix("glm-5.3") == "glm-5.3"
    assert window._model_suffix("huihui_ai/qwen2.5-abliterate:14b") == (
        "qwen2.5-abliterate")
    assert window._model_suffix("") == ""


def test_project_name_ends_with_source_suffix():
    _app, window = _window()
    window.output_name.setText("my_story")
    window._source_suffix = "kimi-k3"
    project = window._build_project("story", [], "角色：girl")
    assert project["name"] == "my_story_kimi-k3"

    window._source_suffix = "外部粘贴"
    project = window._build_project("story", [], "角色：girl")
    assert project["name"] == "my_story_外部粘贴"

