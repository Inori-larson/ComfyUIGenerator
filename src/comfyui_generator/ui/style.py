APP_QSS = """
* {
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 9.5pt;
}
QMainWindow, QDialog { background: #f4f6f9; }
QWidget#TopBar { background: #ffffff; border-bottom: 1px solid #dfe3e8; }
QLabel#Title { font-size: 15pt; font-weight: 700; color: #1f2d3d; }
QLabel#Section { font-weight: 600; color: #34495e; }
QLabel#Hint { color: #7f8c8d; }
QLabel#Preview {
    background: #20242c;
    border-radius: 8px;
    color: #aab3c0;
}
QTabWidget::pane { border: 1px solid #dfe3e8; background: #ffffff; border-radius: 6px; }
QTabBar::tab {
    background: transparent; padding: 7px 14px; color: #5b6773;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected { color: #2d6cdf; border-bottom: 2px solid #2d6cdf; font-weight: 600; }
QGroupBox {
    border: 1px solid #e1e5ea; border-radius: 6px; margin-top: 12px;
    background: #ffffff; padding: 8px;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #5b6773; }
QPushButton {
    background: #ffffff; border: 1px solid #cfd6de; border-radius: 6px;
    padding: 6px 12px; color: #2f3a46;
}
QPushButton:hover { border-color: #2d6cdf; color: #2d6cdf; }
QPushButton:disabled { color: #b0b8c1; border-color: #e5e9ee; background: #f8f9fb; }
QPushButton#Primary {
    background: #2d6cdf; border: 1px solid #2d6cdf; color: #ffffff; font-weight: 600;
}
QPushButton#Primary:hover { background: #245bc0; }
QPushButton#Primary:disabled { background: #a9c1ee; border-color: #a9c1ee; }
QPushButton#Mode {
    background: #eef2f7; border: none; border-radius: 15px; padding: 5px 18px; color: #5b6773;
}
QPushButton#Mode:checked { background: #2d6cdf; color: #ffffff; font-weight: 600; }
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #ffffff; border: 1px solid #d5dbe3; border-radius: 5px; padding: 4px 6px;
    selection-background-color: #cfe0ff;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus { border-color: #2d6cdf; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QLineEdit { background: transparent; border: none; padding: 0 2px; }
QCompleter QAbstractItemView {
    background: #ffffff; border: 1px solid #d5dbe3; selection-background-color: #e3eeff;
    selection-color: #1f2d3d; outline: 0;
}
QTableWidget, QListWidget { background: #ffffff; border: 1px solid #dfe3e8; border-radius: 6px; }
QHeaderView::section {
    background: #f2f5f9; border: none; border-bottom: 1px solid #dfe3e8;
    padding: 5px; color: #5b6773; font-weight: 600;
}
QTableWidget::item:selected, QListWidget::item:selected { background: #e3eeff; color: #1f2d3d; }
QProgressBar {
    background: #eef1f5; border: none; border-radius: 4px; height: 8px; text-align: center;
    color: transparent;
}
QProgressBar::chunk { background: #2d6cdf; border-radius: 4px; }
QScrollArea { border: none; background: transparent; }
QSplitter::handle { background: #e6eaef; width: 3px; height: 3px; }
QStatusBar { background: #ffffff; border-top: 1px solid #dfe3e8; color: #7f8c8d; }
"""
