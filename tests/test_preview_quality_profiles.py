"""Preview quality profiles stay separate from final export quality."""
from __future__ import annotations

import unittest

from app.video_engine import preview_profile
from app.video_engine.ffmpeg_backend import build_project_command
from app.video_engine.project_snapshot import build_snapshot


class FakeTimeline:
    FPS = 30
    root_dir = "."

    def playback_tracks(self):
        return [{
            "name": "V1", "base": "V", "is_main": True,
            "_stack_order": 1, "hidden": False, "muted": False, "volume": 1.0,
            "clips": [{
                "path": __file__, "kind": "Video", "start": 0.0,
                "duration": 1.0, "source_in": 0.0,
            }],
        }]


class PreviewQualityProfileTests(unittest.TestCase):
    def tearDown(self):
        preview_profile.configure_preview_profile("Performance")

    def test_performance_is_low_end_default(self):
        preview_profile.configure_preview_profile("Performance")
        self.assertEqual((preview_profile.PREVIEW_WIDTH, preview_profile.PREVIEW_HEIGHT), (640, 360))
        self.assertTrue(preview_profile.USE_PROXIES)

    def test_balanced_profile_improves_proxy_and_preview_resolution(self):
        preview_profile.configure_preview_profile("Balanced")
        self.assertEqual((preview_profile.PREVIEW_WIDTH, preview_profile.PREVIEW_HEIGHT), (854, 480))
        self.assertEqual((preview_profile.PROXY_WIDTH, preview_profile.PROXY_HEIGHT), (854, 480))
        self.assertTrue(preview_profile.USE_PROXIES)
        snapshot = build_snapshot(FakeTimeline(), use_proxies=False)
        command = build_project_command("ffmpeg", None, snapshot, "preview.mp4")
        self.assertIn("854x480", " ".join(command))

    def test_clear_profile_uses_originals_and_full_hd_preview(self):
        preview_profile.configure_preview_profile("Clear")
        self.assertEqual((preview_profile.PREVIEW_WIDTH, preview_profile.PREVIEW_HEIGHT), (1280, 720))
        self.assertFalse(preview_profile.USE_PROXIES)
        self.assertIn("clear-1280x720", preview_profile.PREVIEW_PROFILE_ID)

    def test_profile_switch_changes_render_signature(self):
        preview_profile.configure_preview_profile("Performance")
        performance = build_snapshot(FakeTimeline())["signature"]
        preview_profile.configure_preview_profile("Balanced")
        balanced = build_snapshot(FakeTimeline())["signature"]
        self.assertNotEqual(performance, balanced)


if __name__ == "__main__":
    unittest.main()
