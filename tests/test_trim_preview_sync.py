"""Regression tests for frame-stable trimming and preview refresh contracts."""
from __future__ import annotations

import ast
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_trim_path = ROOT / "app" / "timeline_trim_math.py"
_trim_spec = importlib.util.spec_from_file_location("skyzen_trim_math_sync", _trim_path)
_trim_math = importlib.util.module_from_spec(_trim_spec)
_trim_spec.loader.exec_module(_trim_math)

from app.video_engine.ffmpeg_backend import _input_args, build_project_command
from app.video_engine.project_snapshot import build_snapshot


class TrimGestureFrameStabilityTests(unittest.TestCase):
    def test_repeated_mouse_moves_use_mouse_down_source_in_not_mutated_value(self):
        # Simulate several mouseMove events during one left-edge drag. Each
        # result must be derived from the original source_in=30, not the value
        # written by the previous event.
        original_start = 60
        original_duration = 240
        original_source_in = 30
        source_length = 300
        results = [
            _trim_math.drag_trim(
                "trim_left", original_start, original_duration,
                original_source_in, source_length, delta,
            )
            for delta in (5, 10, 15, 20)
        ]
        self.assertEqual(results[-1], (80, 220, 50))
        self.assertEqual([item[2] for item in results], [35, 40, 45, 50])

    def test_trim_back_restores_source_frames_without_changing_fixed_edge(self):
        start, duration, source_in = _trim_math.drag_trim(
            "trim_left", 60, 240, 30, 300, 20
        )
        self.assertEqual((start, duration, source_in), (80, 220, 50))
        # A separate drag back left is based on the newly committed clip state.
        restored = _trim_math.drag_trim(
            "trim_left", start, duration, source_in, 300, -20
        )
        self.assertEqual(restored, (60, 240, 30))
        self.assertEqual(restored[0] + restored[1], 300)

    def test_right_edge_can_shorten_then_restore_to_source_end(self):
        shortened = _trim_math.drag_trim(
            "trim_right", 60, 240, 30, 300, -60
        )
        self.assertEqual(shortened, (60, 180, 30))
        restored = _trim_math.drag_trim(
            "trim_right", shortened[0], shortened[1], shortened[2], 300, 60
        )
        self.assertEqual(restored, (60, 240, 30))
        self.assertEqual(restored[0] + restored[1], 300)

    def test_source_range_never_exceeds_known_media_length(self):
        result = _trim_math.drag_trim(
            "trim_right", 60, 100, 150, 200, 500
        )
        self.assertEqual(result, (60, 50, 150))
        self.assertLessEqual(result[2] + result[1], 200)


class TrimPreviewSynchronizationTests(unittest.TestCase):
    def test_trim_release_publishes_updated_active_stack(self):
        source = (ROOT / "app" / "timeline_panel" / "core.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        clip_widget = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ClipWidget"
        )
        release = next(
            node for node in clip_widget.body
            if isinstance(node, ast.FunctionDef) and node.name == "mouseReleaseEvent"
        )
        trim_branch = next(
            node for node in ast.walk(release)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and "trim_left" in ast.unparse(node.test)
            and "trim_right" in ast.unparse(node.test)
        )
        calls = [
            ast.unparse(node.func)
            for node in ast.walk(trim_branch)
            if isinstance(node, ast.Call)
        ]
        self.assertTrue(any("_emit_active_clips" in call for call in calls))

    def test_trimmed_source_in_and_duration_are_used_by_preview_input(self):
        clip = {
            "path": "fixture.mp4", "kind": "Video", "start": 2.0,
            "duration": 2.0, "end": 4.0, "source_in": 1.5,
            "volume": 0.0, "muted": False,
        }
        args = _input_args(clip, 30)
        self.assertIn("-ss", args)
        self.assertEqual(args[args.index("-ss") + 1], "1.5")
        self.assertIn("-t", args)
        self.assertEqual(args[args.index("-t") + 1], "2")

    def test_trim_values_change_project_preview_signature(self):
        class Timeline:
            FPS = 30
            root_dir = Path.cwd()

            def __init__(self, path):
                self.tracks = [{
                    "name": "V1", "base": "V", "is_main": True,
                    "clips": [{
                        "path": str(path), "kind": "Video", "start": 0.0,
                        "duration": 4.0, "source_in": 0.0, "source_duration": 10.0,
                        "volume": 0.0,
                    }],
                }]

            def playback_tracks(self):
                return self.tracks

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.mp4"
            path.write_bytes(b"test fixture placeholder")
            timeline = Timeline(path)
            before = build_snapshot(timeline)
            timeline.tracks[0]["clips"][0].update({
                "start": 1.0, "duration": 3.0, "source_in": 1.0,
            })
            after = build_snapshot(timeline)
            self.assertNotEqual(before["signature"], after["signature"])
            self.assertEqual(after["visual"][0]["start"], 1.0)
            self.assertEqual(after["visual"][0]["duration"], 3.0)
            self.assertEqual(after["visual"][0]["source_in"], 1.0)


if __name__ == "__main__":
    unittest.main()
