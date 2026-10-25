"""Regression tests for overlay soundtracks, proxy import, and layer scrolling."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from app.video_engine.ffmpeg_backend import build_project_command
from app.video_engine.project_snapshot import build_snapshot
from app.media.proxy_paths import PROXY_PROFILE_ID, proxy_marker_value, proxy_path_for, source_identity


class FakeTimeline:
    FPS = 30
    root_dir = Path(".")

    def __init__(self, tracks):
        self.tracks = tracks

    def playback_tracks(self):
        return self.tracks


def track(name, stack, start, *, main=False, muted=False, volume=1.0):
    return {
        "name": name, "base": "V", "is_main": main, "_stack_order": stack,
        "hidden": False, "muted": muted, "volume": volume,
        "clips": [{
            "path": __file__, "kind": "Video", "start": start, "duration": 2.0,
            "source_in": 0.0, "scale": 1.0, "opacity": 1.0,
            "clip_muted": False,
        }],
    }


class AudioAndImportRegressionTests(unittest.TestCase):
    def test_unmuted_overlay_video_audio_is_mixed_with_main_audio(self):
        main = track("V1", 2, 0.0, main=True)
        overlay = track("V2", 0, 0.5, volume=0.65)
        snapshot = build_snapshot(FakeTimeline([overlay, main]))
        with patch("app.video_engine.ffmpeg_backend._probe_has_audio", return_value=True):
            command = build_project_command("ffmpeg", "ffprobe", snapshot, "preview.mp4")
        joined = " ".join(command)
        self.assertIn("amix=inputs=2", joined)
        self.assertIn("[0:a:0]", joined)
        self.assertIn("[1:a:0]", joined)
        self.assertIn("volume=0.65", joined)

    def test_muted_overlay_is_excluded_from_audio_mix(self):
        main = track("V1", 2, 0.0, main=True)
        overlay = track("V2", 0, 0.5, muted=True)
        snapshot = build_snapshot(FakeTimeline([overlay, main]))
        with patch("app.video_engine.ffmpeg_backend._probe_has_audio", return_value=True):
            command = build_project_command("ffmpeg", "ffprobe", snapshot, "preview.mp4")
        joined = " ".join(command)
        self.assertNotIn("amix=inputs=2", joined)
        self.assertIn("amix=inputs=1", joined)

    def test_chroma_key_settings_are_part_of_snapshot_and_filter_graph(self):
        main = track("V1", 2, 0.0, main=True)
        clip = main["clips"][0]
        clip.update({
            "chroma_key_enabled": True,
            "chroma_key_color": "#12ABEF",
            "chroma_similarity": 0.23,
            "chroma_blend": 0.08,
            "chroma_opacity": 0.72,
        })
        timeline = FakeTimeline([main])
        snapshot = build_snapshot(timeline)
        self.assertTrue(snapshot["visual"][0]["chroma_key_enabled"])
        self.assertEqual(snapshot["visual"][0]["chroma_key_color"], "#12ABEF")
        before = snapshot["signature"]
        clip["chroma_similarity"] = 0.31
        after = build_snapshot(timeline)["signature"]
        self.assertNotEqual(before, after)
        clip["chroma_similarity"] = 0.23
        with patch("app.video_engine.ffmpeg_backend._probe_has_audio", return_value=False):
            command = build_project_command("ffmpeg", "ffprobe", build_snapshot(timeline), "preview.mp4")
        joined = " ".join(command)
        self.assertIn("colorkey=0x12ABEF:similarity=0.23:blend=0.08", joined)
        self.assertIn("colorchannelmixer=aa=0.72", joined)

    def test_per_clip_volume_is_applied_on_top_of_track_volume(self):
        main = track("V1", 2, 0.0, main=True, volume=0.8)
        main["clips"][0]["volume"] = 0.5
        snapshot = build_snapshot(FakeTimeline([main]))
        self.assertAlmostEqual(snapshot["visual"][0]["volume"], 0.4)
        before = snapshot["signature"]
        main["clips"][0]["volume"] = 0.25
        after = build_snapshot(FakeTimeline([main]))
        self.assertNotEqual(before, after["signature"])
        self.assertAlmostEqual(after["visual"][0]["volume"], 0.2)

    def test_per_clip_mute_removes_its_embedded_audio(self):
        main = track("V1", 2, 0.0, main=True)
        main["clips"][0]["clip_muted"] = True
        snapshot = build_snapshot(FakeTimeline([main]))
        self.assertEqual(snapshot["visual"][0]["volume"], 0.0)
        with patch("app.video_engine.ffmpeg_backend._probe_has_audio", return_value=True):
            command = build_project_command("ffmpeg", "ffprobe", snapshot, "preview.mp4")
        joined = " ".join(command)
        self.assertNotIn("[0:a:0]", joined)

    def test_video_layer_volume_and_mute_are_part_of_snapshot_signature(self):
        main = track("V1", 2, 0.0, main=True)
        overlay = track("V2", 0, 0.5, volume=0.5)
        timeline = FakeTimeline([overlay, main])
        before = build_snapshot(timeline)["signature"]
        overlay["volume"] = 0.25
        after_volume = build_snapshot(timeline)["signature"]
        self.assertNotEqual(before, after_volume)
        overlay["muted"] = True
        after_mute = build_snapshot(timeline)["signature"]
        self.assertNotEqual(after_volume, after_mute)

    def test_proxy_marker_is_versioned_for_active_preview_profile(self):
        self.assertTrue(PROXY_PROFILE_ID.startswith("proxy-performance-640x360-"))
        self.assertIn(PROXY_PROFILE_ID, proxy_marker_value(__file__))

    def test_proxy_path_rejects_old_profile_marker(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(prefix="skyzen-proxy-profile-") as folder:
            source = Path(folder) / "source.mp4"
            source.write_bytes(b"source")
            cache = Path(folder) / "cache"
            cache.mkdir()
            proxy = cache / f"{source_identity(source)}.mp4"
            marker = proxy.with_suffix(".ok")
            proxy.write_bytes(b"old-proxy")
            marker.write_text(source_identity(source), encoding="utf-8")
            with patch("app.media.proxy_paths.proxy_cache_dir", return_value=cache):
                self.assertEqual(proxy_path_for(source), source.resolve())
                marker.write_text(proxy_marker_value(source), encoding="utf-8")
                self.assertEqual(proxy_path_for(source), proxy.resolve())


    def test_layer_controls_forward_wheel_events_to_shared_timeline_scroll(self):
        source = (Path(__file__).resolve().parents[1] / "app/timeline_panel/left_layers_panel/layers.py").read_text(encoding="utf-8")
        self.assertIn("self.installEventFilter(self)", source)
        self.assertIn("QEvent.Type.Wheel", source)
        self.assertIn("self.timeline._scroll_timeline_wheel(event)", source)

    def test_bottom_layer_creation_workspace_has_two_rows_of_space(self):
        source = (Path(__file__).resolve().parents[1] / "app/timeline_panel/core.py").read_text(encoding="utf-8")
        self.assertIn("NEW_LAYER_GAP_HEIGHT = 2 * TRACK_HEIGHT + 12", source)

    def test_proxy_import_is_enabled_for_existing_install_migration(self):
        source = (Path(__file__).resolve().parents[1] / "app/main_window/main.py").read_text(encoding="utf-8")
        self.assertIn('self.settings.setValue("media/create_proxies", True)', source)
        self.assertIn('self.settings.value("media/create_proxies", True, type=bool)', source)

    def test_inspector_exposes_transform_and_color_grading_fields(self):
        source = (Path(__file__).resolve().parents[1] / "app/inspector_panel/main.py").read_text(encoding="utf-8")
        for key in ("scale_percent", "position_x", "position_y", "position_z",
                    "rotation", "opacity_percent", "brightness", "contrast", "saturation"):
            self.assertIn(f'"{key}"', source)
        self.assertIn("COLOR GRADING", source)

    def test_project_composite_is_prefetched_after_edit_debounce(self):
        source = (Path(__file__).resolve().parents[1] / "app/video_engine/controller.py").read_text(encoding="utf-8")
        self.assertIn("self._project_prefetch_timer.setInterval(450)", source)
        self.assertIn("self._frame_debounce.setInterval(110)", source)
        self.assertIn("self._project_prefetch_timer.timeout.connect(self._start_project_render)", source)
        self.assertIn("self._project_prefetch_timer.stop()", source)


if __name__ == "__main__":
    unittest.main()
