from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InspectorWorkflowV24Tests(unittest.TestCase):
    def test_inspector_has_separate_scrollable_workflow_tabs(self):
        source = (ROOT / "app/inspector_panel/main.py").read_text(encoding="utf-8")
        for label in ('"Basic"', '"Adjustment"', '"Speed"', '"AI Tools"'):
            self.assertIn(label, source)
        self.assertIn("setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)", source)

    def test_properties_are_hidden_until_clip_is_selected(self):
        source = (ROOT / "app/inspector_panel/main.py").read_text(encoding="utf-8")
        self.assertIn("self.pages.setCurrentWidget(self.empty_page if clip is None else self.tabs)", source)
        self.assertIn("self.pages.setCurrentWidget(self.empty_page)", source)

    def test_selection_labels_exist_before_property_loading(self):
        source = (ROOT / "app/inspector_panel/main.py").read_text(encoding="utf-8")
        self.assertIn("self.name_label = QLabel", source)
        self.assertIn("self.path_label = QLabel", source)
        # The strip must never become a stray top-level window: it is parented
        # and always hidden.
        self.assertIn("self.selection_info = QFrame(self)", source)
        self.assertNotIn("self.selection_info.setVisible(clip is not None)", source)

    def test_mouse_wheel_only_adjusts_a_focused_numeric_field(self):
        source = (ROOT / "app/inspector_panel/main.py").read_text(encoding="utf-8")
        self.assertIn("class FocusedWheelSpinBox", source)
        self.assertIn("if self.hasFocus() and self.underMouse()", source)
        self.assertIn("event.ignore()", source)
        self.assertIn("field.setDecimals(3)", source)
        self.assertIn("slider.setRange(-1000, 1000)", source)

    def test_chroma_key_has_preview_eyedropper_and_active_controls(self):
        source = (ROOT / "app/inspector_panel/main.py").read_text(encoding="utf-8")
        backend = (ROOT / "app/video_engine/ffmpeg_backend.py").read_text(encoding="utf-8")
        snapshot = (ROOT / "app/video_engine/project_snapshot.py").read_text(encoding="utf-8")
        self.assertIn("start_chroma_color_pick", source)
        self.assertIn("screen.grabWindow(0", source)
        self.assertIn("colorkey=0x{key_color}", backend)
        self.assertIn('"chroma_key_enabled"', snapshot)
        self.assertIn('"chroma_similarity"', snapshot)

    def test_selected_clip_audio_volume_and_mute_are_wired(self):
        inspector = (ROOT / "app/inspector_panel/main.py").read_text(encoding="utf-8")
        snapshot = (ROOT / "app/video_engine/project_snapshot.py").read_text(encoding="utf-8")
        self.assertIn('"volume_percent": ("volume", float(value) / 100.0)', inspector)
        self.assertIn('self._clip["clip_muted"] = bool(checked)', inspector)
        self.assertIn('clip.get("volume", 1.0)', snapshot)

    def test_slider_edits_are_debounced(self):
        source = (ROOT / "app/inspector_panel/main.py").read_text(encoding="utf-8")
        self.assertIn("self._preview_timer.setInterval(90)", source)
        self.assertIn("self._preview_timer.start()", source)
        self.assertIn("self._flush_preview_update", source)

    def test_launcher_uses_hidden_pythonw(self):
        source = (ROOT / "run.bat").read_text(encoding="utf-8")
        self.assertIn("launch_silent.vbs", source)
        vbs = (ROOT / "launch_silent.vbs").read_text(encoding="utf-8")
        self.assertIn('shell.Run "pythonw.exe', vbs)

    def test_speed_controls_are_connected_to_timeline_retiming(self):
        source = (ROOT / "app/inspector_panel/main.py").read_text(encoding="utf-8")
        self.assertIn("self.speed_spin", source)
        self.assertIn("_edit_speed_curve", source)
        self.assertIn("start_chroma_color_pick", source)
        self.assertIn("Color tolerance", source)


if __name__ == "__main__":
    unittest.main()
