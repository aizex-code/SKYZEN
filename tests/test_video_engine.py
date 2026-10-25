"""Pure-Python regression tests for FFmpeg preview command generation."""
from __future__ import annotations

import unittest
import tempfile
from unittest.mock import patch
from pathlib import Path

from app.video_engine.ffmpeg_backend import build_frame_command, build_project_command
from app.video_engine.project_snapshot import build_snapshot, project_fingerprint
from app.media.proxy_paths import proxy_cache_dir, source_identity, proxy_marker_value
from app.export.codec_profiles import export_options


class FakeTimeline:
    FPS = 30
    root_dir = Path(".")

    def __init__(self, tracks):
        self.tracks = tracks

    def playback_tracks(self):
        return self.tracks


class VideoEngineTests(unittest.TestCase):
    def setUp(self):
        self.main = {
            "name": "V1", "base": "V", "is_main": True,
            "_stack_order": 2, "hidden": False, "muted": False, "volume": 1.0,
            "clips": [{
                "path": __file__, "kind": "Video", "start": 0.0, "duration": 3.0,
                "source_in": 0.0, "scale": 1.0, "opacity": 1.0,
            }],
        }
        self.overlay = {
            "name": "V2", "base": "V", "is_main": False,
            "_stack_order": 0, "hidden": False, "muted": True, "volume": 1.0,
            "clips": [{
                "path": __file__, "kind": "Video", "start": 0.5, "duration": 1.0,
                "source_in": 0.0, "scale": 0.5, "opacity": 0.9,
            }],
        }

    def test_snapshot_keeps_main_below_overlay(self):
        snapshot = build_snapshot(FakeTimeline([self.overlay, self.main]))
        self.assertEqual(len(snapshot["visual"]), 2)
        self.assertTrue(snapshot["visual"][0]["is_main"])
        self.assertFalse(snapshot["visual"][1]["is_main"])
        self.assertEqual(snapshot["duration"], 3.0)

    def test_optional_import_proxy_is_reused_by_preview_snapshot_only(self):
        with tempfile.TemporaryDirectory(prefix="skyzen-proxy-test-") as folder:
            source = Path(folder) / "source.mp4"
            source.write_bytes(b"source-placeholder")
            cache_dir = Path(folder) / "proxy_cache"
            cache_dir.mkdir()
            with patch("app.media.proxy_paths.proxy_cache_dir", return_value=cache_dir):
                proxy = cache_dir / f"{source_identity(source)}.mp4"
                marker = proxy.with_suffix(".ok")
                try:
                    proxy.write_bytes(b"proxy-placeholder")
                    marker.write_text(proxy_marker_value(source), encoding="utf-8")
                    timeline = FakeTimeline([{
                        "name": "V1", "base": "V", "is_main": True,
                        "_stack_order": 1, "hidden": False, "muted": False, "volume": 1.0,
                        "clips": [{
                            "path": str(source), "kind": "Video", "start": 0.0,
                            "duration": 1.0, "source_in": 0.0,
                        }],
                    }])
                    original_snapshot = build_snapshot(timeline)
                    preview_snapshot = build_snapshot(timeline, use_proxies=True)
                    self.assertEqual(Path(original_snapshot["visual"][0]["path"]), source.resolve())
                    self.assertEqual(Path(preview_snapshot["visual"][0]["path"]), proxy.resolve())
                    self.assertEqual(preview_snapshot["visual"][0]["original_path"], str(source.resolve()))
                finally:
                    proxy.unlink(missing_ok=True)
                    marker.unlink(missing_ok=True)

    def test_proxy_file_stamp_participates_in_preview_signature(self):
        with tempfile.TemporaryDirectory(prefix="skyzen-proxy-signature-") as folder:
            source = Path(folder) / "source.mp4"
            source.write_bytes(b"source-placeholder")
            cache_dir = Path(folder) / "proxy_cache"
            cache_dir.mkdir()
            with patch("app.media.proxy_paths.proxy_cache_dir", return_value=cache_dir):
                proxy = cache_dir / f"{source_identity(source)}.mp4"
                marker = proxy.with_suffix(".ok")
                proxy.write_bytes(b"proxy-version-one")
                marker.write_text(proxy_marker_value(source), encoding="utf-8")
                timeline = FakeTimeline([{
                    "name": "V1", "base": "V", "is_main": True,
                    "_stack_order": 1, "hidden": False, "muted": False, "volume": 1.0,
                    "clips": [{
                        "path": str(source), "kind": "Video", "start": 0.0,
                        "duration": 1.0, "source_in": 0.0,
                    }],
                }])
                before = build_snapshot(timeline, use_proxies=True)["signature"]
                proxy.write_bytes(b"proxy-version-two-is-different")
                after = build_snapshot(timeline, use_proxies=True)["signature"]
                self.assertNotEqual(before, after)

    def test_fingerprint_changes_when_clip_is_trimmed(self):
        timeline = FakeTimeline([self.main, self.overlay])
        before = project_fingerprint(timeline)
        self.main["clips"][0]["duration"] = 2.5
        after = project_fingerprint(timeline)
        self.assertNotEqual(before, after)

    def test_project_command_uses_single_composite_output(self):
        snapshot = build_snapshot(FakeTimeline([self.main, self.overlay]))
        command = build_project_command("ffmpeg", None, snapshot, "preview.mp4")
        joined = " ".join(command)
        self.assertIn("overlay=", joined)
        self.assertIn("libx264", joined)
        self.assertIn("-map [vout]", joined)
        self.assertIn("640x360", joined)

    def test_preview_profile_uses_fast_low_resolution_encoding(self):
        snapshot = build_snapshot(FakeTimeline([self.main, self.overlay]))
        command = build_project_command("ffmpeg", None, snapshot, "preview.mp4")
        joined = " ".join(command)
        self.assertIn("640x360", joined)
        self.assertIn("-preset ultrafast", joined)
        self.assertIn("-crf 27", joined)
        self.assertIn("-threads 2", joined)
        self.assertNotIn("+faststart", joined)

    def test_transform_offsets_scale_with_preview_resolution(self):
        snapshot = build_snapshot(FakeTimeline([self.main, self.overlay]))
        command = build_project_command("ffmpeg", None, snapshot, "preview.mp4")
        joined = " ".join(command)
        # The overlay's project-space x=0 in this fixture is still 0, while
        # a non-zero offset is asserted in a dedicated changed copy below.
        moved = dict(self.overlay["clips"][0])
        moved["position_x"] = 200
        self.overlay["clips"] = [moved]
        moved_snapshot = build_snapshot(FakeTimeline([self.main, self.overlay]))
        preview = " ".join(build_project_command("ffmpeg", None, moved_snapshot, "preview.mp4"))
        full = " ".join(build_project_command("ffmpeg", None, moved_snapshot, "export.mp4", width=1280, height=720, codec_options={}))
        self.assertIn("(100)", preview)
        self.assertIn("(200)", full)

    def test_color_grading_is_part_of_render_signature_and_filter_graph(self):
        timeline = FakeTimeline([self.main])
        before = build_snapshot(timeline)
        self.main["clips"][0]["brightness"] = 0.2
        self.main["clips"][0]["contrast"] = 1.2
        self.main["clips"][0]["saturation"] = 1.4
        after = build_snapshot(timeline)
        self.assertNotEqual(before["signature"], after["signature"])
        command = build_project_command("ffmpeg", None, after, "preview.mp4")
        joined = " ".join(command)
        self.assertIn("brightness=0.2", joined)
        self.assertIn("contrast=1.2", joined)
        self.assertIn("saturation=1.4", joined)

    def test_extended_color_controls_change_signature_and_filter_graph(self):
        timeline = FakeTimeline([self.main])
        before = build_snapshot(timeline)
        clip = self.main["clips"][0]
        clip.update({
            "gamma": 1.25, "hue": 18.0, "temperature": 0.25, "tint": -0.1,
            "highlights": 0.2, "shadows": -0.15, "vibrance": 0.6,
        })
        after = build_snapshot(timeline)
        self.assertNotEqual(before["signature"], after["signature"])
        joined = " ".join(build_project_command("ffmpeg", None, after, "preview.mp4"))
        self.assertIn("gamma=1.25", joined)
        self.assertIn("hue=h=18", joined)
        self.assertIn("colorbalance=", joined)
        self.assertIn("vibrance=intensity=0.6", joined)

    def test_z_position_changes_depth_scale_in_filter_graph(self):
        timeline = FakeTimeline([self.main])
        self.main["clips"][0]["position_z"] = 250
        snapshot = build_snapshot(timeline)
        command = build_project_command("ffmpeg", None, snapshot, "preview.mp4")
        joined = " ".join(command)
        # Positive Z is nearer in Skyzen's current 2D depth approximation.
        self.assertIn("scale=w='max(2,iw*1.333333)'", joined)

    def test_frame_preview_uses_compact_resolution(self):
        snapshot = build_snapshot(FakeTimeline([self.main]))
        command = build_frame_command("ffmpeg", snapshot, 0.5, "frame.png")
        joined = " ".join(command)
        self.assertIn("640x360", joined)

    def test_frame_command_renders_one_still(self):
        snapshot = build_snapshot(FakeTimeline([self.main, self.overlay]))
        command = build_frame_command("ffmpeg", snapshot, 0.75, "frame.png")
        joined = " ".join(command)
        self.assertIn("-frames:v 1", joined)
        self.assertIn("overlay=", joined)

    def test_render_worker_imports_subprocess_for_background_process(self):
        # RenderWorker launches FFmpeg from its QThread. If subprocess isn't
        # imported, the thread exits before emitting succeeded/failed and the
        # player remains black with no diagnostic.
        import ast
        worker_source = Path(__file__).resolve().parents[1] / "app" / "video_engine" / "render_worker.py"
        tree = ast.parse(worker_source.read_text(encoding="utf-8"))
        imported = any(
            isinstance(node, ast.Import)
            and any(alias.name == "subprocess" for alias in node.names)
            for node in ast.walk(tree)
        )
        self.assertTrue(imported, "render_worker.py must import subprocess")

    def test_crop_controls_change_signature_and_filter_graph(self):
        timeline = FakeTimeline([self.main])
        before = build_snapshot(timeline)
        self.main["clips"][0].update({
            "crop_left": 0.1, "crop_top": 0.05,
            "crop_right": 0.15, "crop_bottom": 0.0,
        })
        after = build_snapshot(timeline)
        self.assertNotEqual(before["signature"], after["signature"])
        graph = " ".join(build_project_command("ffmpeg", None, after, "preview.mp4"))
        self.assertIn("crop=w='max(2,iw*0.75)'", graph)
        self.assertIn("x='iw*0.1':y='ih*0.05'", graph)

    def test_crop_values_are_clamped_to_safe_ranges(self):
        timeline = FakeTimeline([self.main])
        self.main["clips"][0].update({
            "crop_left": 9.0, "crop_top": -2.0,
            "crop_right": 0.0, "crop_bottom": 0.0,
        })
        snapshot = build_snapshot(timeline)
        self.assertEqual(snapshot["visual"][0]["crop_left"], 0.45)
        self.assertEqual(snapshot["visual"][0]["crop_top"], 0.0)

    def test_export_profiles_override_preview_codec(self):
        snapshot = build_snapshot(FakeTimeline([self.main]))
        options = export_options("H.264 (MP4)", 20)
        command = build_project_command(
            "ffmpeg", None, snapshot, "export.mp4",
            width=1920, height=1080, codec_options=options,
        )
        joined = " ".join(command)
        self.assertIn("1920x1080", joined)
        self.assertIn("-crf 20", joined)
        self.assertNotIn("ultrafast", joined)


if __name__ == "__main__":
    unittest.main()
