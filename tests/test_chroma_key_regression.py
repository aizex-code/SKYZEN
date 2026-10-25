"""Regression coverage for the FFmpeg chroma-key parameter boundary."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.video_engine.ffmpeg_backend import build_project_command
from app.video_engine.project_snapshot import build_snapshot
from app.video_engine.preview_profile import PREVIEW_PROFILE_ID


class FakeTimeline:
    FPS = 30

    def __init__(self, media_path: str, chroma: dict):
        self.root_dir = Path(media_path).parent
        self._tracks = [{
            "name": "V1", "base": "V", "is_main": True,
            "_stack_order": 1, "hidden": False, "muted": False, "volume": 1.0,
            "clips": [{
                "path": media_path, "kind": "Video", "start": 0.0,
                "duration": 1.0, "source_in": 0.0, "scale": 1.0,
                "opacity": 1.0, **chroma,
            }],
        }]

    def playback_tracks(self):
        return self._tracks


class ChromaKeyRegressionTests(unittest.TestCase):
    def test_preview_cache_profile_invalidates_pre_fix_chroma_cache(self):
        self.assertIn("chroma-safe", PREVIEW_PROFILE_ID)

    def test_zero_tolerance_is_clamped_to_ffmpeg_minimum(self):
        # Use this test module as a placeholder source: command generation
        # does not decode it, and therefore does not require a media fixture.
        timeline = FakeTimeline(str(Path(__file__).resolve()), {
            "chroma_key_enabled": True,
            "chroma_key_color": "#E58A5F",
            "chroma_similarity": 0.0,
            "chroma_blend": 0.015,
            "chroma_opacity": 1.0,
        })
        snapshot = build_snapshot(timeline)
        command = build_project_command("ffmpeg", None, snapshot, "preview.mp4")
        graph = " ".join(command)
        self.assertIn("colorkey=0xE58A5F:similarity=0.00001:blend=0.015", graph)
        self.assertNotIn("similarity=0:blend", graph)

    def test_out_of_range_tolerance_is_clamped(self):
        timeline = FakeTimeline(str(Path(__file__).resolve()), {
            "chroma_key_enabled": True,
            "chroma_key_color": "#00FF00",
            "chroma_similarity": 9.0,
            "chroma_blend": -1.0,
            "chroma_opacity": 4.0,
        })
        graph = " ".join(build_project_command(
            "ffmpeg", None, build_snapshot(timeline), "preview.mp4"
        ))
        self.assertIn("similarity=1:blend=0", graph)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "FFmpeg/ffprobe are required for the integration test")
    def test_zero_tolerance_chroma_key_renders_without_filter_error(self):
        with tempfile.TemporaryDirectory(prefix="skyzen-chroma-regression-") as td:
            source = Path(td) / "greenscreen.mp4"
            output = Path(td) / "keyed-preview.mp4"
            subprocess.run([
                shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i",
                "color=c=green:s=320x180:r=30:d=1",
                "-vf", "drawbox=x=100:y=40:w=120:h=100:color=red:t=fill",
                "-an", "-c:v", "libx264", "-preset", "ultrafast", str(source),
            ], check=True, capture_output=True, text=True, timeout=30)
            timeline = FakeTimeline(str(source), {
                "chroma_key_enabled": True,
                "chroma_key_color": "#008000",
                "chroma_similarity": 0.0,
                "chroma_blend": 0.0,
                "chroma_opacity": 1.0,
                "crop_left": 0.05,
                "crop_top": 0.05,
                "crop_right": 0.05,
                "crop_bottom": 0.05,
            })
            command = build_project_command(
                shutil.which("ffmpeg"), shutil.which("ffprobe"),
                build_snapshot(timeline), str(output),
            )
            rendered = subprocess.run(
                command, capture_output=True, text=True, timeout=60
            )
            self.assertEqual(rendered.returncode, 0, rendered.stderr[-2000:])
            self.assertTrue(output.is_file() and output.stat().st_size > 0)
            probe = subprocess.run([
                shutil.which("ffprobe"), "-v", "error", "-show_entries",
                "stream=codec_type", "-of", "csv=p=0", str(output),
            ], check=True, capture_output=True, text=True, timeout=15)
            self.assertIn("video", probe.stdout)


if __name__ == "__main__":
    unittest.main()
