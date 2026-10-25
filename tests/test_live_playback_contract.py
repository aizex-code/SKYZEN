"""Source-level guards for playback and scroll ownership contracts."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LivePlaybackContractTests(unittest.TestCase):
    def test_play_uses_synchronized_project_composite(self):
        tree = ast.parse((ROOT / "app/video_engine/controller.py").read_text(encoding="utf-8"))
        controller = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ProjectPreviewController"
        )
        play = next(
            node for node in controller.body
            if isinstance(node, ast.FunctionDef) and node.name == "play"
        )
        calls = [
            node.func.attr
            for node in ast.walk(play)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        self.assertIn("_start_project_render", calls)
        self.assertNotIn("start", calls)

    def test_active_controller_uses_only_the_project_composite_player(self):
        source = (ROOT / "app/video_engine/controller.py").read_text(encoding="utf-8")
        self.assertIn("self._live_engine = None", source)
        self.assertIn("Play one synchronized FFmpeg composite", source)
        self.assertNotIn("LiveMultitrackEngine(panel, self)", source)

    def test_any_scroll_column_can_drive_synchronization(self):
        source = (ROOT / "app/timeline_panel/alignment.py").read_text(encoding="utf-8")
        # Only the tracks canvas owns a vertical scrollbar; label/gutter columns
        # are offset to -scroll_value, so they can never drift or clamp.
        self.assertIn("class SyncedColumn", source)
        self.assertIn("self._content.move(0, -self._offset)", source)
        self.assertIn("bar.valueChanged.connect(self._apply_offset)", source)
        self.assertNotIn("if source_bar is master:", source)


if __name__ == "__main__":
    unittest.main()
