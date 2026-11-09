APP_STYLE = """
QMainWindow, QWidget { background: #101923; color: #e9eef5; font-family: 'Segoe UI'; font-size: 10px; }
QWidget#topNav { background: #172434; border: 1px solid #31465a; border-radius: 5px; }
QLabel#brand { color: #c7a9ff; font-size: 11px; font-weight: 800; letter-spacing: 1px; }
QLabel#sectionTitle { color: #f2f6fa; font-size: 12px; font-weight: 800; letter-spacing: 0.8px; }
QLabel#subtle { color: #8fa0b2; font-size: 9px; }
QLabel#value { color: #f2f6fa; font-size: 13px; font-weight: 750; }
QLabel#neutralValue { color: #c1c0c6; font-size: 15px; font-weight: 800; }
QLabel#profit { color: #57de9a; font-size: 15px; font-weight: 800; }
QLabel#loss { color: #ff747f; font-size: 15px; font-weight: 800; }
QLabel#statusChip { color: #f7ca72; background: #2f2b20; border: 1px solid #685633; border-radius: 4px; padding: 3px 5px; font-size: 9px; font-weight: 700; }
QLabel#statusLine { color: #a9b8c7; background: #14202c; border: 1px solid #2b4154; border-radius: 4px; padding: 4px 5px; }
QLabel#hwndValue { color: #c8d4df; background: #14202c; border: 1px solid #2b4154; border-radius: 4px; padding: 5px 6px; font-size: 10px; font-weight: 700; }
QLabel#capturePreview { background: #0b0b11; border: 1px solid #2d2938; border-radius: 7px; color: #878392; }
QWidget#orderPanel { background: #1b2a3a; border: 1px solid #3c5870; border-left: 3px solid #f4a72d; border-radius: 5px; }
QLabel#orderCaption { color: #f9c365; font-size: 10px; font-weight: 800; letter-spacing: .4px; }
QWidget#lotsPanel { background: #14202c; border: 1px solid #2f465a; border-radius: 5px; }
QLabel#lotsCaption { color: #a7bed2; font-size: 9px; font-weight: 750; letter-spacing: .4px; }
QWidget#lotRow { background: #172535; border-radius: 3px; }
QLabel#lotLabel { color: #a8bacb; font-size: 9px; font-weight: 700; }
QLabel#currency { color: #f5bf59; font-size: 10px; font-weight: 800; }
QTabBar::tab { background: transparent; color: #a4b3c2; border: 0; border-radius: 4px; padding: 4px 2px; margin: 0; font-size: 8px; font-weight: 650; }
QTabBar::tab:selected { background: #52347e; color: white; }
QTabBar::tab:hover:!selected { background: #24384b; color: #edf3f8; }
QPushButton { background: #21364a; color: #e0e9f0; border: 1px solid #3d5971; border-radius: 4px; padding: 5px 8px; font-weight: 650; }
QPushButton:hover { background: #2c475e; border-color: #ad82ee; }
QPushButton:pressed { background: #152433; }
QPushButton#primary { background: #f3a832; border-color: #ffc15a; color: #1b2025; }
QPushButton#primary:hover { background: #ffc05a; }
QPushButton#alwaysOnTop { padding: 0; font-size: 11px; font-weight: 800; }
QPushButton#alwaysOnTop:checked { background: #52347e; border-color: #b188ef; }
QLineEdit, QSpinBox, QComboBox { background: #101a25; border: 1px solid #344e64; border-radius: 4px; padding: 4px 5px; color: #f2f6fa; selection-background-color: #7546bd; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #a77ae8; }
QLineEdit#requestPrice { min-width: 88px; background: #24303d; border: 2px solid #f2a529; color: #ffe0a3; font-size: 13px; font-weight: 800; padding: 4px 6px; }
QLineEdit#listingPrice { min-width: 86px; background: #1a2a39; border: 1px solid #4b6f8c; color: #f3d187; font-weight: 750; padding: 3px 5px; }
QTableWidget { background: #15161b; border: 1px solid #2b2d35; gridline-color: #272930; alternate-background-color: #1a1b21; }
QHeaderView::section { background: #202127; padding: 4px; border: 0; color: #aaa6b6; font-weight: 700; }
QCheckBox { spacing: 0; color: #bbb7c7; font-size: 11px; font-weight: 800; }
QCheckBox::indicator { width: 0; }
"""
