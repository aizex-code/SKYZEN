import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QColorDialog, QComboBox, QDialogButtonBox
)

SETTINGS_FILE = Path(__file__).resolve().parent / "settings.json"

DEFAULT_SETTINGS = {
    "theme": "Dark",
    "background": "#101116",
    "panel": "#171922",
    "text": "#F3F5F7",
    "muted": "#969CAB",
    "accent": "#8B5CF6",
    "hover": "#A78BFA",
    "border": "#2B2E3A",
    "trash_retention_days": 30,
}


def load_settings():
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            result = DEFAULT_SETTINGS.copy()
            result.update(data)
            return result
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    SETTINGS_FILE.write_text(
        json.dumps(settings, indent=2),
        encoding="utf-8"
    )


class ColorButton(QPushButton):
    def __init__(self, label, color, callback, parent=None):
        super().__init__(label, parent)
        self.color = color
        self.callback = callback
        self.setMinimumHeight(38)
        self.update_style()
        self.clicked.connect(self.pick)

    def update_style(self):
        self.setStyleSheet(
            f"""
            QPushButton {{
                text-align: left;
                padding-left: 12px;
                border: 1px solid #383C48;
                border-radius: 8px;
                background: #191C24;
            }}
            QPushButton:hover {{
                border: 1px solid {self.color};
            }}
            """
        )

    def pick(self):
        color = QColorDialog.getColor(QColor(self.color), self)
        if color.isValid():
            self.color = color.name()
            self.update_style()
            self.callback(self.color)


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings.copy()
        self.setWindowTitle("Skyzen Settings")
        self.resize(500, 500)
        self.build()

    def build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = QLabel("Settings")
        title.setStyleSheet("font-size: 25px; font-weight: 700;")
        layout.addWidget(title)

        subtitle = QLabel("Theme control")
        subtitle.setStyleSheet("color: #969CAB;")
        layout.addWidget(subtitle)

        row = QHBoxLayout()
        row.addWidget(QLabel("Theme"))
        self.theme = QComboBox()
        self.theme.addItems(["Dark", "Custom"])
        self.theme.setCurrentText(self.settings.get("theme", "Dark"))
        self.theme.currentTextChanged.connect(self.theme_changed)
        row.addWidget(self.theme, 1)
        layout.addLayout(row)

        self.colors = {}

        for key, label in [
            ("background", "UI Background"),
            ("panel", "Panels / Cards"),
            ("accent", "Main Accent"),
            ("hover", "Hover Border"),
            ("border", "Normal Border"),
        ]:
            button = ColorButton(
                f"  {label}   {self.settings[key]}",
                self.settings[key],
                lambda color, k=key, b=None: self.set_color(k, color),
            )
            # Keep the button reference so its label can be updated.
            self.colors[key] = button
            button.callback = lambda color, k=key, b=button: self.set_color(k, color, b)
            layout.addWidget(button)

        layout.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def set_color(self, key, color, button=None):
        self.settings[key] = color
        if button:
            label = {
                "background": "UI Background",
                "panel": "Panels / Cards",
                "accent": "Main Accent",
                "hover": "Hover Border",
                "border": "Normal Border",
            }[key]
            button.setText(f"  {label}   {color}")

    def theme_changed(self, theme):
        if theme == "Dark":
            for key, value in DEFAULT_SETTINGS.items():
                self.settings[key] = value
            for key, button in self.colors.items():
                button.color = self.settings[key]
                button.update_style()

    def get_settings(self):
        return self.settings.copy()
