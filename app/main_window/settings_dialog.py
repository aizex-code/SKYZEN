"""Compact user preferences for Skyzen's editing responsiveness and preview."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QLabel, QSlider, QVBoxLayout, QWidget,
)


class EditorSettingsDialog(QDialog):
    def __init__(self, parent, values: dict):
        super().__init__(parent)
        self.setWindowTitle("Skyzen Settings")
        self.setMinimumWidth(390)
        self.setModal(True)
        self.setStyleSheet("QDialog{background:#202020;} QLabel{color:#EEEEEE;} QComboBox,QCheckBox{min-height:26px;}")
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        heading = QLabel("Editing & Performance")
        heading.setStyleSheet("font-size:15px;font-weight:700;color:#00D8E8;")
        root.addWidget(heading)
        hint = QLabel("These preferences are saved and reused the next time Skyzen opens.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#A0A0A0;font-size:10px;")
        root.addWidget(hint)

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(14)
        root.addLayout(form)

        self.quality = QComboBox()
        self.quality.addItems(["Performance", "Balanced", "Clear"])
        self.quality.setCurrentText(str(values.get("quality", "Performance")))
        self.quality.setToolTip("Performance is recommended for older CPUs and integrated graphics.")
        form.addRow("Preview quality", self.quality)

        self.proxies = QCheckBox("Create fast preview proxies for imported videos")
        self.proxies.setChecked(bool(values.get("proxies", True)))
        self.proxies.setToolTip("Uses smaller disposable editing copies; original files are preserved.")
        form.addRow("Media", self.proxies)

        self.zoom = self._slider(40, 350, int(values.get("zoom_step", 150)), "Slower", "Faster")
        form.addRow("Timeline zoom wheel", self.zoom)
        self.pan = self._slider(2, 14, int(values.get("pan_speed", 7)), "Slower", "Faster")
        form.addRow("Horizontal pan speed", self.pan)
        self.layer_scroll = self._slider(1, 3, int(values.get("layer_scroll", 1)), "1×", "3×")
        form.addRow("Layer scroll speed", self.layer_scroll)

        note = QLabel("Tip: Ctrl + mouse wheel zooms the timeline. Shift + wheel pans horizontally.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#8B96A3;font-size:10px;")
        root.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _slider(minimum: int, maximum: int, value: int, left: str, right: str) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(max(minimum, min(maximum, value)))
        labels = QFormLayout()
        left_label = QLabel(left)
        right_label = QLabel(right)
        left_label.setStyleSheet("color:#8B96A3;font-size:9px;")
        right_label.setStyleSheet("color:#8B96A3;font-size:9px;")
        labels.addRow(left_label, right_label)
        layout.addWidget(slider)
        layout.addLayout(labels)
        # Expose the actual slider as a property for a compact, stable caller API.
        wrap.slider = slider
        return wrap

    def values(self) -> dict:
        return {
            "quality": self.quality.currentText(),
            "proxies": self.proxies.isChecked(),
            "zoom_step": self.zoom.slider.value(),
            "pan_speed": self.pan.slider.value(),
            "layer_scroll": self.layer_scroll.slider.value(),
        }
