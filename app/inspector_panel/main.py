from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QEvent, QPoint
from PySide6.QtGui import QColor, QCursor, QMouseEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import (
    QAbstractSpinBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QScrollArea, QSlider,
    QVBoxLayout, QWidget, QTabWidget, QStackedWidget, QCheckBox, QPushButton,
    QLineEdit, QPlainTextEdit, QSpinBox, QComboBox,
)
from app.animation import upsert_keyframe, remove_keyframe, normalize_keyframes, evaluate_keyframes
from app.curve_editor import CurveEditorDialog, CurveCanvas


# Slider domain is intentionally normalized to -100..100. A value of zero
# sits in the visual centre for bidirectional adjustments, like a motion editor.
ANIMATABLE_UI_KEYS = {"scale_percent", "position_x", "position_y", "position_z", "rotation", "opacity_percent", "brightness", "contrast", "saturation", "gamma", "hue", "temperature", "tint", "highlights", "shadows", "vibrance", "volume_percent", "chroma_similarity_percent", "chroma_blend_percent", "chroma_opacity_percent", "crop_left_percent", "crop_top_percent", "crop_right_percent", "crop_bottom_percent"}

BIDIRECTIONAL = {
    "scale_percent", "position_x", "position_y", "position_z", "rotation",
    "brightness", "contrast", "saturation", "gamma", "hue", "temperature",
    "tint", "highlights", "shadows", "vibrance",
}


def slider_to_value(key: str, position: int) -> float:
    p = float(position) / 10.0
    if key == "scale_percent":
        return 100.0 + p * (0.95 if p < 0 else 4.0)
    if key in ("position_x", "position_y"):
        return p * 50.0
    if key == "position_z":
        return p * 20.0
    if key == "rotation":
        return p * 3.6
    if key == "brightness":
        return p / 100.0
    if key == "contrast":
        return 1.0 + p / 100.0
    if key == "saturation":
        return 1.0 + (p / 100.0 if p < 0 else p * 0.02)
    if key == "gamma":
        return 1.0 + (p * 0.009 if p < 0 else p * 0.02)
    if key == "hue":
        return p * 1.8
    if key in ("temperature", "tint", "highlights", "shadows"):
        return p / 100.0
    if key == "vibrance":
        return p / 50.0
    if key == "opacity_percent":
        return float(max(0, min(100, p)))
    if key == "volume_percent":
        return float(max(0, min(200, p)))
    if key in ("chroma_similarity_percent", "chroma_blend_percent", "chroma_opacity_percent"):
        return float(max(0, min(100, p)))
    if key in ("crop_left_percent", "crop_top_percent", "crop_right_percent", "crop_bottom_percent"):
        return float(max(0, min(45, p)))
    return float(p)


def _value_to_slider_coarse(key: str, value: float) -> int:
    v = float(value)
    if key == "scale_percent":
        return round((v - 100.0) / (0.95 if v < 100.0 else 4.0))
    if key in ("position_x", "position_y"):
        return round(v / 50.0)
    if key == "position_z":
        return round(v / 20.0)
    if key == "rotation":
        return round(v / 3.6)
    if key == "brightness":
        return round(v * 100.0)
    if key == "contrast":
        return round((v - 1.0) * 100.0)
    if key == "saturation":
        return round((v - 1.0) * (100.0 if v < 1.0 else 50.0))
    if key == "gamma":
        return round((v - 1.0) / (0.009 if v < 1.0 else 0.02))
    if key == "hue":
        return round(v / 1.8)
    if key in ("temperature", "tint", "highlights", "shadows"):
        return round(v * 100.0)
    if key == "vibrance":
        return round(v * 50.0)
    if key == "opacity_percent":
        return round(v)
    if key == "volume_percent":
        return round(v)
    if key in ("chroma_similarity_percent", "chroma_blend_percent", "chroma_opacity_percent"):
        return round(v)
    if key in ("crop_left_percent", "crop_top_percent", "crop_right_percent", "crop_bottom_percent"):
        return round(v)
    return round(v)


def value_to_slider(key: str, value: float) -> int:
    # Ten times the old slider resolution gives fine adjustment without
    # changing the established parameter ranges.
    return int(round(_value_to_slider_coarse(key, value) * 10))


class FocusedWheelSpinBox(QDoubleSpinBox):
    """Wheel-adjust only when the numeric field itself has keyboard focus."""

    def wheelEvent(self, event):
        if self.hasFocus() and self.underMouse():
            super().wheelEvent(event)
        else:
            event.ignore()


class InspectorPanel(QFrame):
    """Selection-aware, live inspector with centred adjustment sliders."""

    def __init__(self, timeline):
        super().__init__()
        self.timeline = timeline
        self._clip = None
        self._loading = False
        self._fields = {}
        self._sliders = {}
        self._keyframe_buttons = {}
        self._slider_dragging = False
        self._picker_active = False
        self._chroma_color = "#00FF00"
        self.setObjectName("Inspector")
        self.setMinimumWidth(250)

        # Coalesce slider events into a small number of preview refreshes.
        # Model values change immediately; the expensive render notification
        # is sent at most once per 90 ms while a slider is being dragged.
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(90)
        self._preview_timer.timeout.connect(self._flush_preview_update)
        self._slider_preview_timer = QTimer(self)
        self._slider_preview_timer.setInterval(180)
        self._slider_preview_timer.timeout.connect(self._flush_preview_update)
        self._tool_refresh_timer = QTimer(self)
        self._tool_refresh_timer.setSingleShot(True)
        self._tool_refresh_timer.setInterval(220)
        self._tool_refresh_timer.timeout.connect(self._refresh_tool_asset)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        heading = QLabel("  INSPECTOR")
        heading.setFixedHeight(30)
        heading.setStyleSheet(
            "color:#00D8E8; background:#292929; border-bottom:1px solid #3A3A3A;"
            "font-weight:700; font-size:11px;"
        )
        # Keep the inspector compact: properties and tabs begin at the top.
        heading.hide()

        # The selection metadata row is deliberately compact and only visible
        # when a timeline clip is selected. These labels are also used by the
        # selection loader; keeping them in the actual widget tree prevents
        # selection callbacks from failing before controls are populated.
        # Parent it so it can never become a stray top-level window.
        self.selection_info = QFrame(self)
        self.selection_info.setStyleSheet(
            "QFrame{background:#222528;border-bottom:1px solid #343A40;}"
        )
        info_layout = QVBoxLayout(self.selection_info)
        info_layout.setContentsMargins(7, 3, 7, 3)
        info_layout.setSpacing(1)
        self.name_label = QLabel("No clip selected")
        self.name_label.setStyleSheet("color:#E8EDF2;font-weight:650;font-size:11px;")
        self.name_label.setMaximumHeight(15)
        self.path_label = QLabel("Select a timeline clip")
        self.path_label.setStyleSheet("color:#89939D;font-size:9px;")
        self.path_label.setMaximumHeight(13)
        self.path_label.setToolTip("")
        info_layout.addWidget(self.name_label)
        info_layout.addWidget(self.path_label)
        # The clip filename/type detail strip was redundant with the media
        # selection and consumed valuable inspector height. Keep the widgets
        # for selection-loader compatibility but remove them from the UI.
        self.selection_info.hide()

        self.pages = QStackedWidget()
        self.empty_page = QWidget()
        empty_layout = QVBoxLayout(self.empty_page)
        empty_layout.setContentsMargins(18, 22, 18, 18)
        empty_layout.setSpacing(8)
        empty_icon = QLabel("◇")
        empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_icon.setStyleSheet("font-size:30px;color:#00D8E8;")
        empty_layout.addWidget(empty_icon)
        empty_title = QLabel("Nothing selected")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_title.setStyleSheet("font-size:14px;font-weight:650;color:#E8E8E8;")
        empty_layout.addWidget(empty_title)
        empty_hint = QLabel("Select a clip on the timeline to see its editable properties.")
        empty_hint.setWordWrap(True)
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint.setStyleSheet("color:#9299A2;font-size:11px;")
        empty_layout.addWidget(empty_hint)
        empty_layout.addStretch(1)
        self.pages.addWidget(self.empty_page)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(False)
        self.tabs.setStyleSheet(
            "QTabWidget::pane{border:0;background:#202020;}"
            "QTabBar::tab{background:#292929;color:#B8BEC6;padding:6px 8px;"
            "border:0;border-bottom:2px solid transparent;}"
            "QTabBar::tab:selected{color:#00D8E8;border-bottom:2px solid #00D8E8;"
            "background:#24282B;}"
            "QTabBar::tab:hover{color:#FFFFFF;}"
        )

        # BASIC: transform and clip operations.
        basic_page = self._scroll_page()
        basic_layout = basic_page[1]

        self.tool_text_group, text_layout = self._make_group("TEXT CONTENT")
        text_layout.addWidget(QLabel("Text"))
        self.tool_text_edit = QPlainTextEdit()
        self.tool_text_edit.setPlaceholderText("Type your title…")
        self.tool_text_edit.setMaximumHeight(64)
        self.tool_text_edit.setStyleSheet("QPlainTextEdit{background:#202329;color:#F3F5F7;border:1px solid #3A414A;border-radius:5px;padding:5px;}")
        self.tool_text_edit.textChanged.connect(self._tool_text_changed)
        text_layout.addWidget(self.tool_text_edit)
        text_row = QHBoxLayout()
        text_row.addWidget(QLabel("Size"))
        self.tool_text_size = QSpinBox(); self.tool_text_size.setRange(12,220); self.tool_text_size.setValue(76)
        self.tool_text_size.valueChanged.connect(self._tool_text_size_changed)
        text_row.addWidget(self.tool_text_size)
        text_row.addWidget(QLabel("Color"))
        self.tool_text_color = QLineEdit("#FFFFFF"); self.tool_text_color.setMaximumWidth(92)
        self.tool_text_color.editingFinished.connect(self._tool_text_color_changed)
        text_row.addWidget(self.tool_text_color)
        text_layout.addLayout(text_row)
        basic_layout.addWidget(self.tool_text_group)
        self.tool_text_group.hide()

        self.tool_effect_group, effect_layout = self._make_group("EFFECT")
        effect_row = QHBoxLayout(); effect_row.addWidget(QLabel("Intensity"))
        self.tool_effect_intensity = QSlider(Qt.Orientation.Horizontal); self.tool_effect_intensity.setRange(0,100); self.tool_effect_intensity.setValue(50)
        self.tool_effect_intensity.valueChanged.connect(self._tool_effect_intensity_changed)
        effect_row.addWidget(self.tool_effect_intensity, 1)
        self.tool_effect_value = QLabel("50%")
        effect_row.addWidget(self.tool_effect_value)
        effect_layout.addLayout(effect_row)
        basic_layout.addWidget(self.tool_effect_group)
        self.tool_effect_group.hide()

        self.tool_adjustment_group, adjustment_layout = self._make_group("ADJUSTMENT LAYER")
        adjustment_layout.addWidget(QLabel("Scope"))
        self.tool_adjustment_scope = QComboBox()
        self.tool_adjustment_scope.addItem("Whole project", "project")
        self.tool_adjustment_scope.addItem("Visual layers below", "below")
        self.tool_adjustment_scope.currentIndexChanged.connect(self._tool_adjustment_scope_changed)
        adjustment_layout.addWidget(self.tool_adjustment_scope)
        basic_layout.addWidget(self.tool_adjustment_group)
        self.tool_adjustment_group.hide()

        transform_group, transform_layout = self._make_group("TRANSFORM")
        self.transform_group = transform_group
        definitions = (
            ("Scale", "scale_percent", 100.0, 5.0, 500.0, 0.1, "%"),
            ("Position X", "position_x", 0.0, -5000.0, 5000.0, 1.0, " px"),
            ("Position Y", "position_y", 0.0, -5000.0, 5000.0, 1.0, " px"),
            ("Position Z", "position_z", 0.0, -2000.0, 2000.0, 1.0, " px"),
            ("Rotation", "rotation", 0.0, -360.0, 360.0, 0.1, "°"),
            ("Opacity", "opacity_percent", 100.0, 0.0, 100.0, 1.0, "%"),
        )
        for definition in definitions:
            self._add_adjuster(transform_layout, *definition)
        basic_layout.addWidget(transform_group)
        crop_group, crop_layout = self._make_group("CROP")
        self.crop_group = crop_group
        crop_definitions = (
            ("Left", "crop_left_percent"),
            ("Top", "crop_top_percent"),
            ("Right", "crop_right_percent"),
            ("Bottom", "crop_bottom_percent"),
        )
        for crop_label, crop_key in crop_definitions:
            self._add_adjuster(crop_layout, crop_label, crop_key, 0.0, 0.0, 45.0, 0.1, "%")
        # Crop is handled by the dedicated interactive Crop dialog launched
        # from the timeline toolbar, not by numeric fields in the inspector.
        crop_group.hide()
        self.compositing_group = self._add_future_group(
            basic_layout, "BLEND MODE",
            "Normal compositing is active. Multiply, Screen and advanced blend modes need a dedicated alpha-correct compositor pass."
        )
        chroma_group, chroma_layout = self._make_group("CHROMA KEY")
        self.mask_group = chroma_group
        self.chroma_enabled = QCheckBox("Enable chroma key")
        self.chroma_enabled.setStyleSheet("color:#D6DCE3; spacing:6px;")
        self.chroma_enabled.setEnabled(False)
        self.chroma_enabled.toggled.connect(self._chroma_enabled_changed)
        chroma_layout.addWidget(self.chroma_enabled)

        color_row = QHBoxLayout()
        self.chroma_swatch = QLabel("  ")
        self.chroma_swatch.setFixedSize(24, 18)
        self.chroma_swatch.setStyleSheet("background:#00FF00;border:1px solid #5B626B;border-radius:3px;")
        self.chroma_color_label = QLabel("#00FF00")
        self.chroma_color_label.setStyleSheet("color:#B8BEC6;font-size:10px;")
        self.pick_chroma_button = QPushButton("Pick color")
        self.pick_chroma_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pick_chroma_button.setEnabled(False)
        self.pick_chroma_button.setToolTip("Click, then click a pixel inside the preview to key out that color.")
        self.pick_chroma_button.clicked.connect(self.start_chroma_color_pick)
        color_row.addWidget(self.chroma_swatch)
        color_row.addWidget(self.chroma_color_label, 1)
        color_row.addWidget(self.pick_chroma_button)
        chroma_layout.addLayout(color_row)
        self._add_adjuster(
            chroma_layout, "Color tolerance", "chroma_similarity_percent",
            15.0, 0.0, 100.0, 0.5, "%"
        )
        self._add_adjuster(
            chroma_layout, "Edge softness", "chroma_blend_percent",
            5.0, 0.0, 100.0, 0.5, "%"
        )
        self._add_adjuster(
            chroma_layout, "Foreground opacity", "chroma_opacity_percent",
            100.0, 0.0, 100.0, 0.5, "%"
        )
        chroma_note = QLabel("Pick a color in the preview. Tolerance removes similar colors; softness blends edges.")
        chroma_note.setWordWrap(True)
        chroma_note.setStyleSheet("color:#89919B;font-size:10px;")
        chroma_layout.addWidget(chroma_note)
        basic_layout.addWidget(chroma_group)
        self.actions_group = self._add_future_group(
            basic_layout, "CLIP ACTIONS",
            "Reverse and speed changes require timeline retiming support."
        )
        audio_group, audio_layout = self._make_group("AUDIO")
        self.audio_group = audio_group
        self._add_adjuster(
            audio_layout, "Volume", "volume_percent", 100.0, 0.0, 200.0, 1.0, "%"
        )
        self.mute_checkbox = QCheckBox("Mute this clip")
        self.mute_checkbox.setStyleSheet("color:#B8BEC6; spacing:7px;")
        self.mute_checkbox.setEnabled(False)
        self.mute_checkbox.toggled.connect(self._mute_changed)
        audio_layout.addWidget(self.mute_checkbox)
        basic_layout.addWidget(audio_group)
        basic_layout.addStretch(1)
        self.basic_scroll = basic_page[0]
        self.tabs.addTab(basic_page[0], "Basic")

        # ADJUSTMENT: grading controls live on their own scrollable page.
        grade_page = self._scroll_page()
        grade_layout = grade_page[1]
        grade_group, grade_controls = self._make_group("COLOR GRADING")
        grade_definitions = (
            ("Brightness", "brightness", 0.0, -1.0, 1.0, 0.01, ""),
            ("Contrast", "contrast", 1.0, 0.0, 2.0, 0.02, "×"),
            ("Saturation", "saturation", 1.0, 0.0, 3.0, 0.02, "×"),
            ("Gamma", "gamma", 1.0, 0.1, 3.0, 0.02, "×"),
            ("Hue", "hue", 0.0, -180.0, 180.0, 1.0, "°"),
            ("Temperature", "temperature", 0.0, -1.0, 1.0, 0.01, ""),
            ("Tint", "tint", 0.0, -1.0, 1.0, 0.01, ""),
            ("Highlights", "highlights", 0.0, -1.0, 1.0, 0.01, ""),
            ("Shadows", "shadows", 0.0, -1.0, 1.0, 0.01, ""),
            ("Vibrance", "vibrance", 0.0, -2.0, 2.0, 0.02, ""),
        )
        for definition in grade_definitions:
            self._add_adjuster(grade_controls, *definition)
        grade_layout.addWidget(grade_group)
        self._add_future_group(
            grade_layout, "HSL & CURVES",
            "Per-color HSL ranges and editable RGB curves are planned as separate grading tools."
        )
        grade_layout.addStretch(1)
        self.tabs.addTab(grade_page[0], "Adjustment")

        speed_page, speed_layout = self._scroll_page()
        speed_group, speed_controls = self._make_group("SPEED")
        speed_controls.addWidget(QLabel("Playback rate"))
        speed_row = QHBoxLayout()
        self.speed_spin = FocusedWheelSpinBox()
        self.speed_spin.setRange(0.5, 5.0)
        self.speed_spin.setSingleStep(0.1)
        self.speed_spin.setDecimals(2)
        self.speed_spin.setSuffix("×")
        self.speed_spin.setValue(1.0)
        self.speed_spin.setEnabled(False)
        self.speed_spin.valueChanged.connect(self._speed_changed)
        speed_row.addWidget(self.speed_spin, 1)
        speed_controls.addLayout(speed_row)
        speed_controls.addWidget(QLabel("Speed curve · 0.5×–5× · drag points to set velocity over the clip"))
        self.speed_curve_canvas = CurveCanvas(
            [{"x":0.0,"y":1.0},{"x":1.0,"y":1.0}], "speed", speed_group
        )
        self.speed_curve_canvas.setMinimumHeight(160)
        self.speed_curve_canvas.setMaximumHeight(190)
        self.speed_curve_canvas.setEnabled(False)
        self.speed_curve_canvas.curveChanged.connect(self._apply_speed_curve_points)
        speed_controls.addWidget(self.speed_curve_canvas)
        self.speed_curve_button = QPushButton("Open larger curve editor…")
        self.speed_curve_button.setEnabled(False)
        self.speed_curve_button.clicked.connect(self._edit_speed_curve)
        speed_controls.addWidget(self.speed_curve_button)
        speed_controls.addWidget(QLabel("Drag a point to change speed; click the line to add points. The clip duration updates automatically."))
        speed_layout.addWidget(speed_group)
        speed_layout.addStretch(1)
        self.tabs.addTab(speed_page, "Speed")

        ai_page = self._simple_page(
            "AI TOOLS",
            "Reserved for your later AI integrations. This page is intentionally separate from the core editing controls."
        )
        self.tabs.addTab(ai_page, "AI Tools")

        self.pages.addWidget(self.tabs)
        root.addWidget(self.pages, 1)
        self.pages.setCurrentWidget(self.empty_page)
        try:
            self.timeline.time_changed.connect(lambda *_: self._sync_keyframed_values())
        except Exception:
            pass

    def focus_crop_controls(self):
        """Expose crop controls directly when the timeline Crop tool is chosen."""
        try:
            self.pages.setCurrentWidget(self.tabs)
            self.tabs.setCurrentIndex(0)
            self.basic_scroll.ensureWidgetVisible(self.crop_group, 0, 8)
            self.crop_group.setStyleSheet(
                "QFrame{border:1px solid #00CFE8;border-radius:6px;}"
            )
            QTimer.singleShot(
                900,
                lambda: self.crop_group.setStyleSheet(
                    "QFrame{border:1px solid #363B43;border-radius:6px;}"
                ) if self.crop_group else None
            )
        except (AttributeError, RuntimeError):
            pass

    def _scroll_page(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 14, 8, 20)  # breathing room above/below
        layout.setSpacing(8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll, layout

    def _simple_page(self, title, message):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(10)
        heading = QLabel(title)
        heading.setStyleSheet("color:#00D8E8;font-weight:700;")
        body = QLabel(message)
        body.setWordWrap(True)
        body.setStyleSheet("color:#A0A7B0;")
        layout.addWidget(heading)
        layout.addWidget(body)
        layout.addStretch(1)
        return page

    def _add_future_group(self, layout, title, message):
        group, group_layout = self._make_group(title)
        label = QLabel(message)
        label.setWordWrap(True)
        label.setStyleSheet("color:#89919B;font-size:10px;")
        group_layout.addWidget(label)
        layout.addWidget(group)
        return group

    def _make_group(self, title):
        group = QFrame()
        group.setStyleSheet(
            "QFrame { background:#292929; border:1px solid #3A3A3A; border-radius:5px; }"
        )
        layout = QVBoxLayout(group)
        layout.setContentsMargins(9, 9, 9, 9)
        layout.setSpacing(5)
        heading = QLabel(title)
        heading.setStyleSheet("color:#00D8E8; font-weight:700;")
        layout.addWidget(heading)
        return group, layout

    def _add_adjuster(self, layout, label, key, default, minimum, maximum, step, suffix):
        row = QVBoxLayout()
        row.setSpacing(2)
        top = QHBoxLayout()
        name = QLabel(label)
        name.setMinimumWidth(70)
        name.setStyleSheet("color:#A5A5A5;")
        top.addWidget(name)
        field = FocusedWheelSpinBox()
        field.setRange(minimum, maximum)
        field.setDecimals(3)
        field.setSingleStep(step)
        field.setSuffix(suffix)
        field.setValue(default)
        field.setKeyboardTracking(False)
        field.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)
        field.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        field.setEnabled(False)
        field.setMinimumWidth(72)
        top.addWidget(field, 1)
        key_button = QPushButton("◇")
        key_button.setFixedSize(23, 24)
        key_button.setEnabled(False)
        key_button.setToolTip("Add/remove a keyframe at the playhead")
        key_button.setStyleSheet("QPushButton{color:#8A98A8;background:transparent;border:1px solid #3B434D;border-radius:4px;font-size:15px;padding:0;} QPushButton:checked{color:#00D8E8;border-color:#00D8E8;background:#123038;}")
        key_button.setCheckable(True)
        key_button.clicked.connect(lambda checked=False, k=key: self._toggle_keyframe(k))
        top.addWidget(key_button)
        self._keyframe_buttons[key] = key_button
        field.installEventFilter(self)
        key_button.installEventFilter(self)
        row.addLayout(top)

        slider = QSlider(Qt.Orientation.Horizontal)
        if key in ("crop_left_percent", "crop_top_percent", "crop_right_percent", "crop_bottom_percent"):
            slider.setRange(0, 450)
        elif key == "opacity_percent" or key in (
            "chroma_similarity_percent", "chroma_blend_percent", "chroma_opacity_percent"
        ):
            slider.setRange(0, 1000)
        elif key == "volume_percent":
            slider.setRange(0, 2000)
        else:
            slider.setRange(-1000, 1000)
        slider.setValue(value_to_slider(key, default))
        slider.setEnabled(False)
        slider.setTracking(True)
        slider.setStyleSheet(
            "QSlider { min-height:14px; }"
            "QSlider::groove:horizontal { height:3px; background:#444B52; border-radius:1px; }"
            "QSlider::sub-page:horizontal { background:#00CFE3; }"
            "QSlider::add-page:horizontal { background:#444B52; }"
            "QSlider::handle:horizontal { background:#E7F9FB; border:1px solid #00D8E8;"
            "width:9px; margin:-5px 0; border-radius:5px; }"
        )
        slider.installEventFilter(self)
        row.addWidget(slider)
        layout.addLayout(row)
        self._fields[key] = field
        self._sliders[key] = slider
        field.valueChanged.connect(lambda value, k=key: self._field_changed(k, value))
        slider.valueChanged.connect(lambda position, k=key: self._slider_changed(k, position))
        slider.sliderPressed.connect(self._begin_slider_preview)
        slider.sliderReleased.connect(self._end_slider_preview)

    def _begin_slider_preview(self):
        self._slider_dragging = True
        self._preview_timer.stop()
        self._slider_preview_timer.start()

    def _end_slider_preview(self):
        self._slider_dragging = False
        self._slider_preview_timer.stop()
        self._preview_timer.stop()
        self._flush_preview_update()

    def _slider_changed(self, key, position):
        if self._loading:
            return
        value = slider_to_value(key, position)
        field = self._fields[key]
        self._loading = True
        field.setValue(value)
        self._loading = False
        self._apply_value(key, value)

    def _field_changed(self, key, value):
        if self._loading:
            return
        slider = self._sliders[key]
        position = value_to_slider(key, value)
        self._loading = True
        slider.setValue(max(slider.minimum(), min(slider.maximum(), position)))
        self._loading = False
        self._apply_value(key, value)

    def load_selected_clip(self, path="", start=None, duration=None, kind=None):
        clip = getattr(self.timeline, "selected_clip", None)
        # Resolve from the signal payload as a fallback. This keeps the
        # inspector responsive even if another selection listener changes
        # timeline state during the same Qt signal dispatch.
        if clip is None and path:
            try:
                target_path = str(Path(path).resolve())
                for track in self.timeline.playback_tracks():
                    for candidate in track.get("clips", []):
                        if str(Path(str(candidate.get("path", ""))).resolve()) != target_path:
                            continue
                        if start is not None and abs(float(candidate.get("start", 0.0)) - float(start)) > 0.05:
                            continue
                        if duration is not None and abs(float(candidate.get("duration", 0.0)) - float(duration)) > 0.05:
                            continue
                        clip = candidate
                        self.timeline.selected_clip = candidate
                        break
                    if clip is not None:
                        break
            except (OSError, TypeError, ValueError, AttributeError):
                clip = None
        self._clip = clip
        for key, key_button in self._keyframe_buttons.items():
            key_button.setEnabled(clip is not None and key in ANIMATABLE_UI_KEYS)
        self.speed_spin.setEnabled(bool(clip and str(clip.get("kind", "")).lower() == "video"))
        self.speed_curve_button.setEnabled(bool(clip and str(clip.get("kind", "")).lower() == "video"))
        self.speed_curve_canvas.setEnabled(bool(clip and str(clip.get("kind", "")).lower() == "video"))
        self._selected_kind = str((clip or {}).get("kind", "Video")).lower()
        # Metadata strip is intentionally never shown (see __init__).
        self.selection_info.hide()
        self._preview_timer.stop()
        self._slider_preview_timer.stop()
        self._slider_dragging = False
        self.pages.setCurrentWidget(self.empty_page if clip is None else self.tabs)
        self._loading = True
        try:
            if clip is None:
                self.name_label.setText("No clip selected")
                self.path_label.setText("Select a timeline clip to edit its properties.")
            else:
                path = str(clip.get("path", ""))
                self.name_label.setText(Path(path).name or "Selected clip")
                self.path_label.setText(f"{self._selected_kind.title()} clip")
                self.path_label.setToolTip(path)
            is_audio = self._selected_kind == "audio"
            self.speed_spin.setEnabled(clip is not None and self._selected_kind == "video")
            self.speed_curve_button.setEnabled(clip is not None and self._selected_kind == "video")
            self.speed_spin.setValue(max(0.5, min(5.0, float((clip or {}).get("speed", 1.0)))))
            self._sync_speed_curve_canvas(clip)
            tool_type = str((clip or {}).get("tool_type", ""))
            if tool_type:
                self.path_label.setText(f"{tool_type} layer · {str((clip or {}).get('display_name', ''))}")
            self.tool_text_group.setVisible(tool_type == "Text")
            self.tool_effect_group.setVisible(tool_type in ("Effects", "Filters"))
            self.tool_adjustment_group.setVisible(tool_type == "Adjustments")
            self.tool_text_edit.setPlainText(str((clip or {}).get("text", "")))
            self.tool_text_size.setValue(int((clip or {}).get("font_size", 76)))
            self.tool_text_color.setText(str((clip or {}).get("text_color", "#FFFFFF")))
            intensity = max(0, min(100, int(round(float((clip or {}).get("intensity", 0.5)) * 100))))
            self.tool_effect_intensity.setValue(intensity)
            self.tool_effect_value.setText(f"{intensity}%")
            scope_index = self.tool_adjustment_scope.findData(str((clip or {}).get("scope", "project")))
            self.tool_adjustment_scope.setCurrentIndex(max(0, scope_index))
            self.transform_group.setVisible(not is_audio)
            self.crop_group.hide()
            self.compositing_group.setVisible(not is_audio)
            self.mask_group.setVisible(not is_audio)
            self.actions_group.setVisible(not is_audio)
            self.tabs.setTabVisible(1, not is_audio)
            self.tabs.setTabVisible(2, self._selected_kind in ("video", "audio"))
            self.audio_group.setVisible(self._selected_kind in ("video", "audio"))
            self.mute_checkbox.setEnabled(clip is not None and self._selected_kind in ("video", "audio"))
            self.mute_checkbox.setChecked(bool((clip or {}).get("clip_muted", False)))
            self._chroma_color = str((clip or {}).get("chroma_key_color", "#00FF00")).upper()
            self._set_chroma_color_ui(self._chroma_color)
            chroma_on = bool((clip or {}).get("chroma_key_enabled", False))
            self.chroma_enabled.setEnabled(clip is not None and self._selected_kind in ("video", "image"))
            self.pick_chroma_button.setEnabled(clip is not None and self._selected_kind in ("video", "image"))
            self.chroma_enabled.setChecked(chroma_on)
            values = {
                "scale_percent": float((clip or {}).get("scale", 1.0)) * 100.0,
                "position_x": float((clip or {}).get("position_x", 0.0)),
                "position_y": float((clip or {}).get("position_y", 0.0)),
                "position_z": float((clip or {}).get("position_z", 0.0)),
                "rotation": float((clip or {}).get("rotation", 0.0)),
                "opacity_percent": float((clip or {}).get("opacity", 1.0)) * 100.0,
                "brightness": float((clip or {}).get("brightness", 0.0)),
                "contrast": float((clip or {}).get("contrast", 1.0)),
                "saturation": float((clip or {}).get("saturation", 1.0)),
                "gamma": float((clip or {}).get("gamma", 1.0)),
                "hue": float((clip or {}).get("hue", 0.0)),
                "temperature": float((clip or {}).get("temperature", 0.0)),
                "tint": float((clip or {}).get("tint", 0.0)),
                "highlights": float((clip or {}).get("highlights", 0.0)),
                "shadows": float((clip or {}).get("shadows", 0.0)),
                "vibrance": float((clip or {}).get("vibrance", 0.0)),
                "volume_percent": float((clip or {}).get("volume", 1.0)) * 100.0,
                "chroma_similarity_percent": float((clip or {}).get("chroma_similarity", 0.15)) * 100.0,
                "chroma_blend_percent": float((clip or {}).get("chroma_blend", 0.05)) * 100.0,
                "chroma_opacity_percent": float((clip or {}).get("chroma_opacity", 1.0)) * 100.0,
                "crop_left_percent": float((clip or {}).get("crop_left", 0.0)) * 100.0,
                "crop_top_percent": float((clip or {}).get("crop_top", 0.0)) * 100.0,
                "crop_right_percent": float((clip or {}).get("crop_right", 0.0)) * 100.0,
                "crop_bottom_percent": float((clip or {}).get("crop_bottom", 0.0)) * 100.0,
            }
            for key, field in self._fields.items():
                field.setEnabled(clip is not None)
                self._sliders[key].setEnabled(clip is not None)
                self._keyframe_buttons[key].setEnabled(clip is not None and key in ANIMATABLE_UI_KEYS)
                field.setValue(values[key])
                self._sliders[key].setValue(max(
                    self._sliders[key].minimum(),
                    min(self._sliders[key].maximum(), value_to_slider(key, values[key]))
                ))
        except (TypeError, ValueError):
            pass
        finally:
            self._loading = False
        self._refresh_keyframe_buttons()

    def clear_selection(self):
        if self._picker_active:
            self._finish_chroma_color_pick()
        self._clip = None
        self._selected_kind = ""
        for key_button in self._keyframe_buttons.values():
            key_button.setEnabled(False)
        self.speed_spin.setEnabled(False)
        self.speed_curve_button.setEnabled(False)
        self.speed_curve_canvas.setEnabled(False)
        self.speed_curve_canvas.set_points([{"x":0.0,"y":1.0},{"x":1.0,"y":1.0}])
        self.selection_info.hide()
        self._preview_timer.stop()
        self._slider_preview_timer.stop()
        self._tool_refresh_timer.stop()
        self._slider_dragging = False
        self.tool_text_group.hide()
        self.tool_effect_group.hide()
        self.tool_adjustment_group.hide()
        self.pages.setCurrentWidget(self.empty_page)
        self._loading = True
        try:
            self.name_label.setText("No clip selected")
            self.path_label.setText("Select a timeline clip to edit its properties.")
            defaults = {
                "scale_percent": 100.0, "position_x": 0.0, "position_y": 0.0,
                "position_z": 0.0, "rotation": 0.0, "opacity_percent": 100.0,
                "brightness": 0.0, "contrast": 1.0, "saturation": 1.0, "gamma": 1.0,
                "hue": 0.0, "temperature": 0.0, "tint": 0.0, "highlights": 0.0,
                "shadows": 0.0, "vibrance": 0.0, "volume_percent": 100.0,
                "chroma_similarity_percent": 15.0, "chroma_blend_percent": 5.0,
                "chroma_opacity_percent": 100.0,
                "crop_left_percent": 0.0, "crop_top_percent": 0.0,
                "crop_right_percent": 0.0, "crop_bottom_percent": 0.0,
            }
            self.mute_checkbox.setEnabled(False)
            self.mute_checkbox.setChecked(False)
            self.chroma_enabled.setEnabled(False)
            self.chroma_enabled.setChecked(False)
            self.pick_chroma_button.setEnabled(False)
            self._set_chroma_color_ui("#00FF00")
            self.transform_group.setVisible(True)
            self.crop_group.hide()
            self.compositing_group.setVisible(True)
            self.mask_group.setVisible(True)
            self.actions_group.setVisible(True)
            self.audio_group.setVisible(True)
            self.tabs.setTabVisible(1, True)
            self.tabs.setTabVisible(2, True)
            for key, field in self._fields.items():
                field.setEnabled(False)
                self._sliders[key].setEnabled(False)
                field.setValue(defaults[key])
                self._sliders[key].setValue(value_to_slider(key, defaults[key]))
        finally:
            self._loading = False

    def _tool_text_changed(self):
        if self._loading or not self._clip or self._clip.get("tool_type") != "Text":
            return
        self._clip["text"] = self.tool_text_edit.toPlainText()
        first_line = self._clip["text"].splitlines()[0].strip() if self._clip["text"].splitlines() else "Text"
        self._clip["display_name"] = first_line[:48] or "Text"
        self._tool_refresh_timer.start()

    def _tool_text_size_changed(self, value):
        if self._loading or not self._clip or self._clip.get("tool_type") != "Text":
            return
        self._clip["font_size"] = int(value)
        self._tool_refresh_timer.start()

    def _tool_text_color_changed(self):
        if self._loading or not self._clip or self._clip.get("tool_type") != "Text":
            return
        color = str(self.tool_text_color.text()).strip()
        if not color.startswith("#"):
            color = "#" + color
        if len(color) not in (4, 7) or not QColor(color).isValid():
            self.tool_text_color.setText(str(self._clip.get("text_color", "#FFFFFF")))
            return
        self._clip["text_color"] = QColor(color).name().upper()
        self._tool_refresh_timer.start()

    def _refresh_tool_asset(self):
        if self._clip is None or self._clip.get("tool_type") != "Text":
            return
        try:
            self.timeline.refresh_tool_clip(self._clip)
        except Exception:
            self._preview_timer.start()

    def _tool_effect_intensity_changed(self, value):
        self.tool_effect_value.setText(f"{int(value)}%")
        if self._loading or not self._clip or self._clip.get("tool_type") not in ("Effects", "Filters"):
            return
        self._clip["intensity"] = float(value) / 100.0
        self._preview_timer.start()

    def _tool_adjustment_scope_changed(self, index):
        if self._loading or not self._clip or self._clip.get("tool_type") != "Adjustments":
            return
        scope = str(self.tool_adjustment_scope.currentData() or "project")
        self._clip["scope"] = scope
        if scope == "project":
            self._clip["start"] = 0.0
            self._clip["duration"] = max(1.0 / self.timeline.FPS, self.timeline.duration())
        self.timeline.rebuild(keep_view=True)
        self._preview_timer.start()

    def _set_chroma_color_ui(self, color_value):
        color = QColor(str(color_value))
        if not color.isValid():
            color = QColor("#00FF00")
        self._chroma_color = color.name().upper()
        self.chroma_swatch.setStyleSheet(
            f"background:{self._chroma_color};border:1px solid #5B626B;border-radius:3px;"
        )
        self.chroma_color_label.setText(self._chroma_color)

    def _chroma_enabled_changed(self, checked):
        if self._loading or self._clip is None:
            return
        self._clip["chroma_key_enabled"] = bool(checked)
        self._clip.setdefault("chroma_key_color", self._chroma_color)
        self._preview_timer.start()

    def start_chroma_color_pick(self):
        if self._clip is None:
            return
        app = QApplication.instance()
        if app is None:
            return
        self._picker_active = True
        app.installEventFilter(self)
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.CrossCursor))
        self.pick_chroma_button.setText("Click preview…")
        self.pick_chroma_button.setToolTip("Click a pixel in the preview to remove that color. Press Esc to cancel.")

    def _finish_chroma_color_pick(self, color=None):
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
            try:
                QApplication.restoreOverrideCursor()
            except Exception:
                pass
        self._picker_active = False
        self.pick_chroma_button.setText("Pick color")
        self.pick_chroma_button.setToolTip("Click, then click a pixel inside the preview to key out that color.")
        if color is None or not color.isValid() or self._clip is None:
            return
        self._set_chroma_color_ui(color.name().upper())
        self._clip["chroma_key_color"] = self._chroma_color
        self._clip["chroma_key_enabled"] = True
        self._loading = True
        self.chroma_enabled.setChecked(True)
        self._loading = False
        self._preview_timer.start()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.MouseButtonPress):
            for key, field in self._fields.items():
                if watched is field or watched is self._sliders.get(key) or watched is self._keyframe_buttons.get(key):
                    self._set_keyframe_display_property(key)
                    break
        if not self._picker_active:
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Type.KeyPress and getattr(event, "key", lambda: None)() == Qt.Key.Key_Escape:
            self._finish_chroma_color_pick()
            return True
        if event.type() == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            if event.button() != Qt.MouseButton.LeftButton:
                return False
            global_pos = event.globalPosition().toPoint()
            try:
                player = getattr(self.window(), "player", None)
                surface = getattr(player, "surface", None)
                if surface is None:
                    return False
                from PySide6.QtCore import QRect
                preview_rect = QRect(surface.mapToGlobal(QPoint(0, 0)), surface.size())
                if not preview_rect.contains(global_pos):
                    return False
                screen = QApplication.screenAt(global_pos)
                if screen is None:
                    return False
                local_x = global_pos.x() - screen.geometry().x()
                local_y = global_pos.y() - screen.geometry().y()
                pixel = screen.grabWindow(0, local_x, local_y, 1, 1).toImage()
                color = pixel.pixelColor(0, 0) if not pixel.isNull() else QColor()
                self._finish_chroma_color_pick(color)
                return True
            except Exception:
                self._finish_chroma_color_pick()
                return True
        return False

    def _mute_changed(self, checked):
        if self._loading or self._clip is None:
            return
        self._clip["clip_muted"] = bool(checked)
        if not self._slider_dragging:
            self._preview_timer.start()

    def _apply_value(self, key, value):
        if self._loading or self._clip is None:
            return
        self._set_keyframe_display_property(key)
        storage = {
            "scale_percent": ("scale", float(value) / 100.0),
            "position_x": ("position_x", float(value)),
            "position_y": ("position_y", float(value)),
            "position_z": ("position_z", float(value)),
            "rotation": ("rotation", float(value)),
            "opacity_percent": ("opacity", float(value) / 100.0),
            "brightness": ("brightness", float(value)),
            "contrast": ("contrast", float(value)),
            "saturation": ("saturation", float(value)),
            "gamma": ("gamma", float(value)),
            "hue": ("hue", float(value)),
            "temperature": ("temperature", float(value)),
            "tint": ("tint", float(value)),
            "highlights": ("highlights", float(value)),
            "shadows": ("shadows", float(value)),
            "vibrance": ("vibrance", float(value)),
            "volume_percent": ("volume", float(value) / 100.0),
            "chroma_similarity_percent": ("chroma_similarity", float(value) / 100.0),
            "chroma_blend_percent": ("chroma_blend", float(value) / 100.0),
            "chroma_opacity_percent": ("chroma_opacity", float(value) / 100.0),
            "crop_left_percent": ("crop_left", float(value) / 100.0),
            "crop_top_percent": ("crop_top", float(value) / 100.0),
            "crop_right_percent": ("crop_right", float(value) / 100.0),
            "crop_bottom_percent": ("crop_bottom", float(value) / 100.0),
        }
        name, stored_value = storage[key]
        self._clip[name] = stored_value
        keyframes = self._clip.get("keyframes", {}).get(name, [])
        if keyframes:
            local_time = max(0.0, float(self.timeline.playhead) - float(self._clip.get("start", 0.0)))
            upsert_keyframe(self._clip, name, local_time, stored_value, fps=self.timeline.FPS)
            self._refresh_keyframe_buttons()
        # Values update immediately in the model. While dragging, refresh the
        # preview on a bounded cadence instead of queuing one render per pixel.
        if not self._slider_dragging:
            self._preview_timer.start()

    def _property_storage_name(self, key):
        mapping = {
            "scale_percent":"scale", "position_x":"position_x", "position_y":"position_y",
            "position_z":"position_z", "rotation":"rotation", "opacity_percent":"opacity",
            "brightness":"brightness", "contrast":"contrast", "saturation":"saturation",
            "gamma":"gamma", "hue":"hue", "temperature":"temperature", "tint":"tint",
            "highlights":"highlights", "shadows":"shadows", "vibrance":"vibrance",
            "volume_percent":"volume", "chroma_similarity_percent":"chroma_similarity",
            "chroma_blend_percent":"chroma_blend", "chroma_opacity_percent":"chroma_opacity",
            "crop_left_percent":"crop_left", "crop_top_percent":"crop_top",
            "crop_right_percent":"crop_right", "crop_bottom_percent":"crop_bottom",
        }
        return mapping.get(key, key)

    def _sync_keyframed_values(self):
        clip = self._clip
        if not clip:
            return
        local_time = max(0.0, float(self.timeline.playhead) - float(clip.get("start", 0.0)))
        scale_fields = {"scale_percent", "opacity_percent", "volume_percent", "chroma_similarity_percent", "chroma_blend_percent", "chroma_opacity_percent", "crop_left_percent", "crop_top_percent", "crop_right_percent", "crop_bottom_percent"}
        self._loading = True
        try:
            for key, field in self._fields.items():
                prop = self._property_storage_name(key)
                points = clip.get("keyframes", {}).get(prop, [])
                if not points:
                    continue
                default = float(clip.get(prop, 0.0))
                value = evaluate_keyframes(points, local_time, default)
                ui_value = value * 100.0 if key in scale_fields else value
                field.setValue(ui_value)
                slider = self._sliders[key]
                slider.setValue(max(slider.minimum(), min(slider.maximum(), value_to_slider(key, ui_value))))
        finally:
            self._loading = False
        self._refresh_keyframe_buttons()

    def _toggle_keyframe(self, key):
        if self._loading or not self._clip:
            return
        self._set_keyframe_display_property(key)
        prop = self._property_storage_name(key)
        local_time = max(0.0, float(self.timeline.playhead) - float(self._clip.get("start", 0.0)))
        ui_value = float(self._fields[key].value()) if key in self._fields else float(self._clip.get(prop, 0.0))
        current = ui_value / 100.0 if key in ("scale_percent", "opacity_percent", "volume_percent", "chroma_similarity_percent", "chroma_blend_percent", "chroma_opacity_percent", "crop_left_percent", "crop_top_percent", "crop_right_percent", "crop_bottom_percent") else ui_value
        try:
            self.timeline._push_history()
        except (AttributeError, TypeError):
            pass
        if remove_keyframe(self._clip, prop, local_time, fps=self.timeline.FPS):
            pass
        else:
            upsert_keyframe(self._clip, prop, local_time, current, fps=self.timeline.FPS)
        self._refresh_keyframe_buttons()
        self._preview_timer.start()

    def _refresh_keyframe_buttons(self):
        clip = self._clip
        current = max(0.0, float(self.timeline.playhead) - float((clip or {}).get("start", 0.0)))
        for key, button in self._keyframe_buttons.items():
            prop = self._property_storage_name(key)
            points = normalize_keyframes((clip or {}).get("keyframes", {}).get(prop, []))
            active = any(abs(p["time"] - current) <= 0.5 / max(1, self.timeline.FPS) for p in points)
            button.setChecked(active)
            button.setText("◆" if active else "◇")

    def _set_keyframe_display_property(self, key):
        """Show only the active inspector property's keyframes on the clip."""
        prop = self._property_storage_name(key)
        if getattr(self.timeline, "_keyframe_display_property", None) == prop:
            return
        self.timeline._keyframe_display_property = prop
        refresh = getattr(self.timeline, "refresh_keyframe_overlays", None)
        if callable(refresh):
            refresh()

    def _sync_speed_curve_canvas(self, clip=None):
        clip = clip or self._clip
        if not clip or str(clip.get("kind", "")).lower() != "video":
            self.speed_curve_canvas.set_points([{"x":0.0,"y":1.0},{"x":1.0,"y":1.0}])
            return
        speed = max(0.5, min(5.0, float(clip.get("speed", 1.0))))
        points = clip.get("speed_curve") if clip.get("speed_mode") == "curve" else None
        if not points:
            points = [{"x":0.0,"y":speed},{"x":1.0,"y":speed}]
        self.speed_curve_canvas.set_points(points)

    def _apply_speed_curve_points(self, points):
        if self._loading or not self._clip or str(self._clip.get("kind", "")).lower() != "video":
            return
        from app.animation import integrate_speed_curve
        clip = self._clip
        old_duration = max(1.0 / self.timeline.FPS, float(clip.get("duration", 1.0)))
        old_speed = max(0.5, min(5.0, float(clip.get("speed", 1.0))))
        if clip.get("speed_mode") == "curve" and clip.get("speed_curve"):
            source_span = integrate_speed_curve(clip["speed_curve"], old_duration, old_speed)
        else:
            source_span = max(1.0 / self.timeline.FPS, float(clip.get("speed_source_duration", old_duration * old_speed)))
        pts = sorted([{"x":max(0.0,min(1.0,float(p.get("x",0.0)))),
                          "y":max(0.1,min(4.0,float(p.get("y",old_speed))))} for p in points],
                     key=lambda p:p["x"])
        if len(pts) < 2:
            pts = [{"x":0.0,"y":old_speed},{"x":1.0,"y":old_speed}]
        pts[0]["x"], pts[-1]["x"] = 0.0, 1.0
        mean_speed = max(0.1, integrate_speed_curve(pts, 1.0, old_speed))
        new_duration = max(1.0 / self.timeline.FPS, source_span / mean_speed)
        try:
            self.timeline._push_history()
        except (AttributeError, TypeError):
            pass
        clip["speed_source_duration"] = source_span
        clip["speed_curve"] = pts
        clip["speed_mode"] = "curve"
        clip["speed"] = max(0.5, min(5.0, source_span / new_duration))
        # Match Patch 10: the timeline clip length follows the integrated curve.
        clip["duration"] = new_duration
        self._loading = True
        try:
            self.speed_spin.setValue(clip["speed"])
        finally:
            self._loading = False
        self.timeline.rebuild(keep_view=True)
        self._preview_timer.start()

    def _speed_changed(self, value):
        if self._loading or not self._clip:
            return
        from app.animation import integrate_speed_curve
        clip = self._clip
        old_speed = max(0.5, min(5.0, float(clip.get("speed", 1.0))))
        old_duration = max(1.0 / self.timeline.FPS, float(clip.get("duration", 1.0)))
        if clip.get("speed_mode") == "curve" and clip.get("speed_curve"):
            source_span = integrate_speed_curve(clip["speed_curve"], old_duration, old_speed)
        else:
            source_span = float(clip.get("speed_source_duration", old_duration * old_speed))
        new_speed = max(0.5, min(5.0, float(value)))
        try:
            self.timeline._push_history()
        except (AttributeError, TypeError):
            pass
        clip["speed_source_duration"] = source_span
        clip["speed"] = new_speed
        clip["speed_mode"] = "constant"
        clip.pop("speed_curve", None)
        clip["duration"] = max(1.0 / self.timeline.FPS, source_span / new_speed)
        self._sync_speed_curve_canvas(clip)
        self.timeline.rebuild(keep_view=True)
        self._preview_timer.start()

    def _edit_speed_curve(self):
        if not self._clip:
            return
        from app.animation import integrate_speed_curve
        clip = self._clip
        old_duration = max(1.0 / self.timeline.FPS, float(clip.get("duration", 1.0)))
        old_speed = max(0.5, min(5.0, float(clip.get("speed", 1.0))))
        if clip.get("speed_mode") == "curve" and clip.get("speed_curve"):
            source_span = integrate_speed_curve(clip["speed_curve"], old_duration, old_speed)
            points = [dict(p) for p in clip["speed_curve"]]
        else:
            source_span = float(clip.get("speed_source_duration", old_duration * old_speed))
            points = [{"x":0.0,"y":old_speed},{"x":1.0,"y":old_speed}]
        dialog = CurveEditorDialog("Speed curve", points, "speed", self)
        if dialog.exec():
            try:
                self.timeline._push_history()
            except (AttributeError, TypeError):
                pass
            pts = sorted(dialog.points(), key=lambda p: p.get("x", 0.0))
            if len(pts) < 2:
                pts = [{"x":0.0,"y":old_speed},{"x":1.0,"y":old_speed}]
            pts[0]["x"] = 0.0
            pts[-1]["x"] = 1.0
            mean_speed = integrate_speed_curve(pts, 1.0, old_speed)
            new_duration = max(1.0 / self.timeline.FPS, source_span / max(0.1, mean_speed))
            clip["speed_source_duration"] = source_span
            clip["speed_curve"] = pts
            clip["speed_mode"] = "curve"
            clip["speed"] = max(0.5, min(5.0, source_span / new_duration))
            clip["duration"] = new_duration
            self._sync_speed_curve_canvas(clip)
            self._loading = True
            self.speed_spin.setValue(clip["speed"])
            self._loading = False
            self.timeline.rebuild(keep_view=True)
            self._preview_timer.start()

    def _flush_preview_update(self):
        if self._clip is None:
            return
        self.timeline._emit_active_clips(self.timeline.playhead)
