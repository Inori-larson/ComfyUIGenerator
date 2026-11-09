import json
from pathlib import Path

from comfyui_generator.core.project import (
    add_plot_history, load_plot_history, plot_history_file)


def test_plot_history_dedupe_and_order(tmp_path):
    add_plot_history(tmp_path, "1.第一段")
    add_plot_history(tmp_path, "2.第二段")
    add_plot_history(tmp_path, "1.第一段")  # duplicate, moves to top
    items = load_plot_history(tmp_path)
    assert [i["plot"] for i in items] == ["1.第一段", "2.第二段"]
    assert items[0]["time"]
    raw = json.loads(plot_history_file(tmp_path).read_text(encoding="utf-8"))
    assert len(raw["items"]) == 2


def test_plot_history_limit(tmp_path):
    for i in range(60):
        add_plot_history(tmp_path, "剧情%02d" % i, max_items=50)
    items = load_plot_history(tmp_path)
    assert len(items) == 50
    assert items[0]["plot"] == "剧情59"
    assert items[-1]["plot"] == "剧情10"


def test_empty_plot_not_recorded(tmp_path):
    add_plot_history(tmp_path, "   ")
    assert load_plot_history(tmp_path) == []


def test_missing_history_returns_empty(tmp_path):
    assert load_plot_history(tmp_path) == []
