COLORS = {
    "window": "#202020",
    "top": "#1C1C1C",
    "panel": "#262626",
    "panel2": "#303030",
    "panel3": "#292929",
    "border": "#3A3A3A",
    "border2": "#484848",
    "text": "#EEEEEE",
    "muted": "#A0A0A0",
    "cyan": "#00D8E8",
    "cyan2": "#26E0EF",
}


STYLE = f"""
* {{
    font-family:"Segoe UI";
}}
QMainWindow,QWidget {{
    background:{COLORS["window"]};
    color:{COLORS["text"]};
}}
QFrame#TopBar {{
    background:{COLORS["top"]};
    border-bottom:1px solid {COLORS["border"]};
}}
QLabel#Brand {{
    color:{COLORS["cyan"]};
    font-size:16px;
    font-weight:800;
}}
QLabel#Saved {{
    color:{COLORS["cyan"]};
    font-size:10px;
}}
QLabel#ProjectName {{
    color:{COLORS["text"]};
    background:#242424;
    padding:5px 16px;
    font-size:12px;
    font-weight:650;
}}
QPushButton,QToolButton,QComboBox,QLineEdit {{
    background:{COLORS["panel2"]};
    color:{COLORS["text"]};
    border:1px solid {COLORS["border"]};
    border-radius:5px;
    min-height:25px;
    padding:0 8px;
}}
QPushButton:hover,QToolButton:hover,QComboBox:hover,QLineEdit:hover {{
    border-color:{COLORS["cyan"]};
}}
QPushButton:pressed,QToolButton:pressed {{
    background:#10232A;
    border-color:{COLORS["cyan"]};
}}
QPushButton#SettingsButton {{
    background:#28282A;
    color:{COLORS["text"]};
    border:1px solid {COLORS["border"]};
    padding:0 8px;
}}
QPushButton#SettingsButton:hover {{
    border-color:{COLORS["cyan"]};
    color:{COLORS["cyan"]};
}}
QPushButton#Export {{
    background:{COLORS["cyan"]};
    color:#001014;
    border-color:{COLORS["cyan"]};
    font-weight:750;
}}
QPushButton#Export:hover {{
    background:{COLORS["cyan2"]};
}}
QSplitter::handle {{
    background:#1B222C;
}}
QSplitter::handle:hover {{
    background:{COLORS["cyan"]};
}}
QScrollArea {{
    border:0;
    background:transparent;
}}
"""


