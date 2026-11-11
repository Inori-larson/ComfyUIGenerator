import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["CUI_NO_AUTOCONNECT"] = "1"

from PySide6.QtWidgets import QApplication

from comfyui_generator.ui.main_window import MainWindow


def _window():
    app = QApplication.instance() or QApplication([])
    return app, MainWindow()


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
