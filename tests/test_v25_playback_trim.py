from pathlib import Path
import unittest

try:
    from app.timeline_panel.core import TimelinePanel
except ImportError:
    TimelinePanel = None

from app.video_engine.ffmpeg_backend import _overlay_chain
from app.timeline_trim_math import left_trim_frames, right_trim_frames


class SignalStub:
    def __init__(self):
        self.values = []

    def emit(self, value):
        self.values.append(value)


class FakeTimeline:
    FPS = 30

    def __init__(self, start=2.0, duration=5.0, source_in=1.0, playhead=3.5):
        self.playhead = playhead
        self.selected_clip = {
            "path": "fixture.mp4",
            "kind": "Video",
            "start": start,
            "duration": duration,
            "source_in": source_in,
            "source_duration": 20.0,
        }
        self.track = {"name": "V1", "base": "V", "clips": [self.selected_clip], "locked": False}
        self.tracks = [self.track]
        self.history_count = 0
        self.rebuild_count = 0
        self.time_changed = SignalStub()
        self.emit_count = 0

    def _find_selected_track(self):
        return self.track

    def clip_start_frame(self, clip):
        return round(float(clip["start"]) * self.FPS)

    def clip_end_frame(self, clip):
        return self.clip_start_frame(clip) + round(float(clip["duration"]) * self.FPS)

    def frame_from_seconds(self, seconds):
        return round(float(seconds) * self.FPS)

    def _push_history(self):
        self.history_count += 1

    def rebuild(self, keep_view=False):
        self.rebuild_count += 1

    def _emit_active_clips(self, seconds):
        self.emit_count += 1


class PlayheadTrimTests(unittest.TestCase):
    @unittest.skipIf(TimelinePanel is None, "PySide6 is required for timeline-core tests")
    def test_left_trim_moves_start_and_source_in_to_playhead(self):
        timeline = FakeTimeline(playhead=3.5)
        TimelinePanel.trim_selected_left(timeline)
        clip = timeline.selected_clip
        self.assertAlmostEqual(clip["start"], 3.5)
        self.assertAlmostEqual(clip["source_in"], 2.5)
        self.assertAlmostEqual(clip["duration"], 3.5)
        self.assertEqual(timeline.history_count, 1)
        self.assertEqual(timeline.rebuild_count, 1)

    @unittest.skipIf(TimelinePanel is None, "PySide6 is required for timeline-core tests")
    def test_right_trim_ends_clip_at_playhead(self):
        timeline = FakeTimeline(playhead=4.25)
        TimelinePanel.trim_selected_right(timeline)
        clip = timeline.selected_clip
        self.assertAlmostEqual(clip["start"], 2.0)
        self.assertAlmostEqual(clip["duration"], 2.25)
        self.assertEqual(timeline.history_count, 1)

    @unittest.skipIf(TimelinePanel is None, "PySide6 is required for timeline-core tests")
    def test_trim_is_noop_when_playhead_outside_clip(self):
        timeline = FakeTimeline(playhead=1.0)
        original = dict(timeline.selected_clip)
        TimelinePanel.trim_selected_left(timeline)
        self.assertEqual(timeline.selected_clip, original)
        self.assertEqual(timeline.history_count, 0)

    def test_neutral_clips_skip_expensive_grade_and_rotation_filters(self):
        graph = " ".join(_overlay_chain([{
            "path": "fixture.mp4", "start": 0.0, "end": 2.0,
            "scale": 1.0, "position_x": 0.0, "position_y": 0.0,
            "position_z": 0.0, "opacity": 1.0, "brightness": 0.0,
            "contrast": 1.0, "saturation": 1.0, "gamma": 1.0,
            "hue": 0.0, "temperature": 0.0, "tint": 0.0,
            "highlights": 0.0, "shadows": 0.0, "vibrance": 0.0,
            "rotation": 0.0,
        }], 30, 2.0, width=640, height=360))
        self.assertNotIn("eq=", graph)
        self.assertNotIn("hue=h=", graph)
        self.assertNotIn("colorbalance=", graph)
        self.assertNotIn("vibrance=", graph)
        self.assertNotIn("rotate=", graph)


if __name__ == "__main__":
    unittest.main()
