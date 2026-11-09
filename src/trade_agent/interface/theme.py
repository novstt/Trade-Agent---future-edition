APP_STYLE = """
QMainWindow, QWidget { background: #10111a; color: #e7e7f1; font-family: 'Segoe UI'; font-size: 13px; }
QFrame#sidebar { background: #171724; border-right: 1px solid #29283a; }
QFrame#card { background: #1a1b28; border: 1px solid #2a2b3b; border-radius: 12px; }
QLabel#brand { color: #c7a9ff; font-size: 20px; font-weight: 700; letter-spacing: 1px; }
QLabel#pageTitle { font-size: 24px; font-weight: 700; color: #f4f1fb; }
QLabel#subtle { color: #9e9eaf; }
QLabel#metric { font-size: 21px; font-weight: 700; color: #f4f1fb; }
QLabel#profit { color: #55dc9a; font-size: 20px; font-weight: 700; }
QLabel#loss { color: #ff727d; font-size: 20px; font-weight: 700; }
QPushButton { background: #2a2b3d; color: #e8e6ef; border: 1px solid #3b3d52; border-radius: 7px; padding: 8px 12px; font-weight: 600; }
QPushButton:hover { background: #35374d; border-color: #9c70e7; }
QPushButton:pressed { background: #252638; }
QPushButton#primary { background: #6f43b3; border-color: #9864ef; color: white; }
QPushButton#primary:hover { background: #8251cc; }
QPushButton#danger { background: #5c2731; border-color: #a64d5a; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #13141f; border: 1px solid #35364a; border-radius: 6px; padding: 7px; color: #f2f0f7; selection-background-color: #7546bd; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border: 1px solid #9c70e7; }
QListWidget { background: transparent; border: 0; outline: 0; color: #bfbcca; }
QListWidget::item { padding: 11px 14px; border-radius: 7px; margin: 2px 8px; }
QListWidget::item:selected { background: #523483; color: white; }
QListWidget::item:hover { background: #292a3a; }
QTableWidget { background: #151621; border: 1px solid #2d2f40; gridline-color: #2a2c3c; alternate-background-color: #1a1c28; }
QHeaderView::section { background: #252638; padding: 7px; border: 0; color: #aaa8b7; font-weight: 700; }
QProgressBar { border: 1px solid #3a3c50; border-radius: 5px; text-align: center; background: #141520; }
QProgressBar::chunk { background: #7950bf; border-radius: 4px; }
QCheckBox { spacing: 7px; color: #bbb9c8; }
QStatusBar { background: #151620; color: #aaa9b6; }
"""
