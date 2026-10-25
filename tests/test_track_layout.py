import unittest
import importlib.util
from pathlib import Path

_module_path = Path(__file__).resolve().parents[1] / 'app' / 'timeline_panel' / 'track_layout.py'
_spec = importlib.util.spec_from_file_location('skyzen_track_layout', _module_path)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
sticky_main_lane_y = _module.sticky_main_lane_y
row_height = _module.row_height
clip_height = _module.clip_height


class Bar:
    def __init__(self, value=0):
        self._value = value

    def value(self):
        return self._value


class Viewport:
    def __init__(self, height):
        self._height = height

    def height(self):
        return self._height


class ScrollArea:
    def __init__(self, height, scroll=0):
        self._viewport = Viewport(height)
        self._bar = Bar(scroll)

    def viewport(self):
        return self._viewport

    def verticalScrollBar(self):
        return self._bar


class FakeTimeline:
    TRACK_HEIGHT = 48
    CLIP_TOP_MARGIN = 2
    MAIN_STICKY_GAP_HEIGHT = 14
    overlays_ui_visible = True

    def __init__(self, count, height=400, scroll=0):
        self.tracks_scroll = ScrollArea(height, scroll)
        self.count = count

    def _normalise_track_stack(self):
        return ([{"clips": [{"start": 0.0, "duration": 1.0}]} for _ in range(self.count)], {}, [], [])


class TrackLayoutTests(unittest.TestCase):
    def test_main_is_centered_without_overlays(self):
        timeline = FakeTimeline(0)
        self.assertEqual(sticky_main_lane_y(timeline), (400 - 48) // 2)

    def test_first_and_second_overlay_move_main_down(self):
        base = sticky_main_lane_y(FakeTimeline(0))
        first = sticky_main_lane_y(FakeTimeline(1))
        second = sticky_main_lane_y(FakeTimeline(2))
        self.assertGreater(first, base)
        self.assertGreater(second, first)

    def test_three_overlays_pin_main_near_bottom(self):
        timeline = FakeTimeline(3)
        self.assertEqual(
            sticky_main_lane_y(timeline),
            400 - 48 - 14,
        )

    def test_scroll_content_coordinates_include_scroll_offset(self):
        self.assertEqual(
            sticky_main_lane_y(FakeTimeline(3, scroll=80)),
            80 + 400 - 48 - 14,
        )

    def test_typed_tool_rows_are_compact_but_clip_fills_the_row(self):
        timeline = FakeTimeline(0)
        track = {"base": "V", "track_type": "Filters"}
        self.assertEqual(row_height(timeline, track), 25)
        self.assertEqual(clip_height(timeline, track), 21)


if __name__ == "__main__":
    unittest.main()
