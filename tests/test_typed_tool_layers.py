"""Regression tests for typed Text/Effects/Adjustment timeline objects."""
from pathlib import Path
import tempfile
import unittest

from app.left_toolbar.catalog import CATALOGS, TOOL_COLORS
from app.video_engine.project_snapshot import build_snapshot
from app.video_engine.ffmpeg_backend import _overlay_chain


class FakeTimeline:
    FPS = 30
    def __init__(self, root, tracks):
        self.root_dir = Path(root)
        self.tracks = tracks
    def playback_tracks(self):
        return self.tracks


class TypedToolLayerTests(unittest.TestCase):
    def test_catalogs_have_stable_unique_ids_and_colors(self):
        self.assertEqual(set(CATALOGS), {"Text", "Effects", "Filters", "Adjustments"})
        self.assertEqual(len(CATALOGS["Text"]), 1)
        self.assertEqual(len(CATALOGS["Effects"]), 4)
        self.assertEqual(len(CATALOGS["Filters"]), 4)
        self.assertEqual(len(CATALOGS["Adjustments"]), 1)
        for tool, presets in CATALOGS.items():
            ids = [item["id"] for item in presets]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertTrue(TOOL_COLORS[tool].startswith("#"))

    def test_snapshot_separates_rendered_text_from_effect_and_adjustment_layers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            names = ("main.mp4", "title.png", "effect.png", "grade.png")
            paths = {}
            for name in names:
                path = root / name
                path.write_bytes(b"test placeholder")
                paths[name] = str(path)
            tracks = [
                {"name": "V1", "base": "V", "is_main": True, "_stack_order": 10,
                 "clips": [{"path": paths["main.mp4"], "kind": "Video", "start": 0, "duration": 10}]},
                {"name": "V2", "base": "V", "track_type": "Text", "_stack_order": 0,
                 "clips": [{"path": paths["title.png"], "kind": "Image", "tool_type": "Text", "tool_preset": "basic_title", "text": "Test", "start": 1, "duration": 4}]},
                {"name": "V3", "base": "V", "track_type": "Effects", "_stack_order": -1,
                 "clips": [{"path": paths["effect.png"], "kind": "Image", "tool_type": "Effects", "effect_type": "warm_film", "intensity": 0.5, "start": 2, "duration": 3}]},
                {"name": "V4", "base": "V", "track_type": "Adjustments", "_stack_order": -2,
                 "clips": [{"path": paths["grade.png"], "kind": "Image", "tool_type": "Adjustments", "scope": "project", "contrast": 1.1, "saturation": 1.05, "start": 0, "duration": 1}]},
                {"name": "V5", "base": "V", "track_type": "Filters", "_stack_order": -3,
                 "clips": [{"path": paths["grade.png"], "kind": "Image", "tool_type": "Filters", "effect_type": "filter_mono", "intensity": 1.0, "start": 2, "duration": 3}]},
            ]
            snapshot = build_snapshot(FakeTimeline(root, tracks))
            self.assertEqual(len(snapshot["visual"]), 2)
            self.assertEqual(len(snapshot["effects"]), 2)
            self.assertTrue(any(item.get("tool_type") == "Filters" for item in snapshot["effects"]))
            self.assertEqual(len(snapshot["adjustments"]), 1)
            self.assertEqual(snapshot["duration"], 10)
            self.assertEqual(snapshot["adjustments"][0]["end"], 10)
            self.assertEqual(snapshot["visual"][-1]["tool_type"], "Text")

    def test_effect_and_project_adjustment_filters_are_in_render_graph(self):
        visual = [{
            "path": "unused.mp4", "kind": "Video", "start": 0.0, "end": 5.0,
            "duration": 5.0, "source_in": 0.0, "scale": 1.0, "position_x": 0.0,
            "position_y": 0.0, "position_z": 0.0, "rotation": 0.0, "opacity": 1.0,
            "brightness": 0.0, "contrast": 1.0, "saturation": 1.0, "gamma": 1.0,
            "hue": 0.0, "temperature": 0.0, "tint": 0.0, "highlights": 0.0,
            "shadows": 0.0, "vibrance": 0.0, "chroma_key_enabled": False,
            "crop_left": 0.0, "crop_top": 0.0, "crop_right": 0.0, "crop_bottom": 0.0,
            "stack_order": 10.0,
        }]
        effects = [{"effect_type": "warm_film", "intensity": 0.5, "start": 1.0, "end": 3.0, "stack_order": 0.0}]
        adjustments = [{"scope": "project", "brightness": 0.05, "contrast": 1.1,
                        "saturation": 1.2, "gamma": 1.0, "start": 0.0, "end": 5.0}]
        graph = ";".join(_overlay_chain(visual, 30, 5.0, effects=effects, adjustments=adjustments))
        self.assertIn("eq=brightness=0.0075:contrast=1.08:saturation=1.11", graph)
        self.assertIn("enable='gte(t,1)*lt(t,3)'", graph)
        self.assertIn("projectgrade0", graph)
        self.assertIn("eq=brightness=0.05:contrast=1.1:saturation=1.2:gamma=1", graph)
        filter_graph = ";".join(_overlay_chain(visual, 30, 5.0, effects=[{"effect_type":"filter_mono", "intensity":1.0, "start":0.0, "end":5.0, "stack_order":0.0}]))
        self.assertIn("hue=s=0", filter_graph)
        blur_graph = ";".join(_overlay_chain(visual, 30, 5.0, effects=[{"effect_type":"blur", "intensity":0.5, "start":0.0, "end":5.0, "stack_order":0.0}]))
        self.assertIn("gblur=sigma=3", blur_graph)


if __name__ == "__main__":
    unittest.main()
