from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InspectorPreviewUIRegressionTests(unittest.TestCase):
    def test_selection_signal_emission_matches_four_argument_signature(self):
        source = (ROOT / "app/timeline_panel/core.py").read_text(encoding="utf-8")
        self.assertIn("clip_selected = Signal(str, float, float, str)", source)
        start = source.index("self.clip_selected.emit(")
        end = source.index("\n            )", start)
        emission = source[start:end]
        for expected in (
            'str(clip.get("path", ""))',
            'float(clip.get("start", 0.0))',
            'float(clip.get("duration", 0.0))',
            'str(clip.get("kind", "Video"))',
        ):
            self.assertIn(expected, emission)

    def test_inspector_can_resolve_clip_from_signal_payload(self):
        source = (ROOT / "app/inspector_panel/main.py").read_text(encoding="utf-8")
        self.assertIn("def load_selected_clip(self, path=\"\", start=None, duration=None, kind=None):", source)
        self.assertIn("self.timeline.selected_clip = candidate", source)

    def test_player_has_no_visible_processing_strip(self):
        source = (ROOT / "app/player_panel/main.py").read_text(encoding="utf-8")
        self.assertIn("self.processing_bar = _HiddenProcessingIndicator()", source)
        self.assertNotIn("root.addWidget(self.processing_bar)", source)

    def test_play_does_not_swap_to_loading_message(self):
        source = (ROOT / "app/video_engine/controller.py").read_text(encoding="utf-8")
        body = source[source.index("    def play(self):"):source.index("    def _activate_project_preview")]
        self.assertNotIn("Preparing smooth timeline playback", body)
        self.assertNotIn("setCurrentWidget(self.panel.message)", body)

    def test_inspector_update_does_not_silently_swallow_errors(self):
        source = (ROOT / "app/inspector_panel/main.py").read_text(encoding="utf-8")
        start = source.index("    def _apply_value")
        end = source.find("\n    def ", start + 5)
        body = source[start:end if end >= 0 else len(source)]
        self.assertIn("self._preview_timer.start()", body)
        self.assertNotIn("except Exception", body)


if __name__ == "__main__":
    unittest.main()
