"""Headless end-to-end UI smoke: connect, LLM prompt, render, screenshot.

Usage:
    python scripts/smoke_ui_render.py out.png [single|story]
"""

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from comfyui_generator.ui.main_window import MainWindow  # noqa: E402
from comfyui_generator.ui.style import APP_QSS  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "ui_render_smoke.png"
MODE = sys.argv[2] if len(sys.argv) > 2 else "single"


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_QSS)
    window = MainWindow()
    window.resize(1480, 940)
    window.show()

    state = {"phase": "wait", "t0": time.time()}

    def tick() -> None:
        if state["phase"] == "wait":
            if not window.connected:
                if time.time() - state["t0"] > 120:
                    print("CONNECT_TIMEOUT")
                    app.quit()
                return
            window.hires_check.setChecked(False)
            window.variants_spin.setValue(1)
            window.res_combo.setCurrentIndex(0)
            window.steps_spin.setValue(8)
            if MODE == "story":
                window.btn_mode_story.setChecked(True)
                window.btn_mode_single.setChecked(False)
                window._switch_mode(1)
                window.story_premise.setPlainText("晴天，少女和猫在天台晒太阳")
                window.story_shots.setValue(2)
                window.generate_story()
                state["phase"] = "story_prompt"
            else:
                window.single_desc.setPlainText("晴天，仪玄在公园长椅上吃冰淇淋，微笑看镜头")
                window.generate_single(then_render=True)
                state["phase"] = "single_render"
            return

        if state["phase"] == "story_prompt":
            busy = window.prompt_worker is not None and window.prompt_worker.isRunning()
            if not busy and window.shot_table.rowCount() >= 2:
                window.start_render("story")
                state["phase"] = "story_render"
            elif time.time() - state["t0"] > 180:
                print("STORY_PROMPT_TIMEOUT")
                app.quit()
            return

        expected = 2 if MODE == "story" else 1
        if len(window.final_bytes) >= expected:
            window.grab().save(OUT)
            print("SUCCESS", OUT, MODE)
            print("gallery:", window.gallery.count())
            print("done tasks:", len(window.final_bytes))
            print("queue rows:", window.queue_table.rowCount())
            print("last log:", window.log_view.toPlainText().splitlines()[-3:])
            app.quit()
            return
        if time.time() - state["t0"] > 300:
            print("RENDER_TIMEOUT")
            print(window.log_view.toPlainText()[-2000:])
            app.quit()

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(500)
    app.exec()


if __name__ == "__main__":
    main()
