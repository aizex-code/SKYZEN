"""Pure geometry regressions for audio lanes below the sticky Main lane."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "app" / "timeline_panel" / "track_layout.py"
SPEC = importlib.util.spec_from_file_location("skyzen_audio_track_layout", MODULE_PATH)
LAYOUT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAYOUT)


class _Bar:
    def __init__(self, value=0):
        self._value = value

    def value(self):
        return self._value


class _Viewport:
    def __init__(self, height):
        self._height = height

    def height(self):
        return self._height


class _Scroll:
    def __init__(self, height=400, value=0):
        self._bar = _Bar(value)
        self._viewport = _Viewport(height)

    def verticalScrollBar(self):
        return self._bar

    def viewport(self):
        return self._viewport


class _Timeline:
    TRACK_HEIGHT = 48
    MAIN_TRACK_HEIGHT = 66
    CLIP_TOP_MARGIN = 5
    LAYER_INSERT_GAP_HEIGHT = 3
    SECTION_HEADER_HEIGHT = 18
    EFFECT_DROP_HEIGHT = 20
    MAIN_STICKY_GAP_HEIGHT = 8
    audio_ui_visible = True
    overlays_ui_visible = True

    def __init__(self, audio=True, scroll=0):
        self.main = {"name": "V1", "base": "V", "is_main": True, "clips": [{"start": 0, "duration": 4}]}
        self.overlay = {"name": "V2", "base": "V", "is_main": False, "clips": [{"start": 0, "duration": 2}], "_stack_order": 0}
        self.audio = {"name": "A1", "base": "A", "clips": [{"start": 0, "duration": 5}], "_stack_order": 0}
        self._audio_enabled = audio
        self.tracks_scroll = _Scroll(400, scroll)

    def top_layer_drop_height(self):
        return 0

    def _normalise_track_stack(self):
        return [self.overlay], self.main, [], ([self.audio] if self._audio_enabled else [])

    def timeline_ui_rows(self):
        rows = [("gap", None, "overlay"), ("track", self.overlay, "overlay"), ("gap", None, "overlay"), ("track", self.main, "main")]
        if self._audio_enabled:
            rows.extend([("gap", None, "audio"), ("track", self.audio, "audio"), ("gap", None, "audio")])
        return rows


class AudioLayerLayoutTests(unittest.TestCase):
    def test_main_pins_to_top_of_audio_section_and_audio_scrolls_behind(self):
        timeline = _Timeline(audio=True, scroll=120)
        natural_main, displayed_main = LAYOUT.main_row_display_y(timeline)
        natural_audio, displayed_audio = LAYOUT.first_audio_row_display_y(timeline)
        self.assertEqual(displayed_main, 120 + timeline.top_layer_drop_height())
        self.assertEqual(displayed_audio, natural_audio)
        self.assertLess(displayed_audio, displayed_main + timeline.MAIN_TRACK_HEIGHT)

    def test_main_reserves_space_for_first_audio_lane(self):
        timeline = _Timeline(audio=True, scroll=0)
        rows, _ = LAYOUT.shared_row_geometry(timeline, displayed=True)
        main_row = next(row for row in rows if row[0] == "track" and row[1] is timeline.main)
        expected_bottom = (
            timeline.tracks_scroll.verticalScrollBar().value()
            + timeline.tracks_scroll.viewport().height()
            - timeline.MAIN_TRACK_HEIGHT
            - timeline.MAIN_STICKY_GAP_HEIGHT
            - timeline.TRACK_HEIGHT
            - timeline.LAYER_INSERT_GAP_HEIGHT
        )
        # When Main's natural position is above the sticky boundary, it remains
        # in natural flow; when below it, the reserved-space boundary is used.
        self.assertLessEqual(main_row[3], expected_bottom)

    def test_audio_follows_main_when_main_is_pinned_below_many_overlays(self):
        timeline = _Timeline(audio=True, scroll=0)
        overlays = [
            {"name": f"V{i + 2}", "base": "V", "is_main": False,
             "clips": [{"start": 0, "duration": 2}], "_stack_order": i}
            for i in range(10)
        ]
        timeline._normalise_track_stack = lambda: (overlays, timeline.main, [], [timeline.audio])
        timeline.timeline_ui_rows = lambda: (
            [("gap", None, "overlay"), *sum(([ ("track", track, "overlay"), ("gap", None, "overlay") ] for track in overlays), []),
             ("track", timeline.main, "main"), ("gap", None, "audio"),
             ("track", timeline.audio, "audio"), ("gap", None, "audio")]
        )

        natural_main, displayed_main = LAYOUT.main_row_display_y(timeline)
        natural_audio, displayed_audio = LAYOUT.first_audio_row_display_y(timeline)
        self.assertGreater(natural_main, displayed_main, "Main should be clamped at the overlay-section bottom")
        # Once scrolling reaches the audio section, Main takes the top edge and
        # audio rows return to natural-flow coordinates behind it.
        timeline.tracks_scroll.verticalScrollBar()._value = 600
        natural_main, displayed_main = LAYOUT.main_row_display_y(timeline)
        natural_audio, displayed_audio = LAYOUT.first_audio_row_display_y(timeline)
        self.assertEqual(displayed_main, 600 + timeline.top_layer_drop_height())
        self.assertEqual(displayed_audio, natural_audio)

    def test_outer_drop_workspace_does_not_create_gap_between_overlay_and_main(self):
        timeline = _Timeline(audio=False, scroll=0)
        timeline.top_layer_drop_height = lambda: 112
        timeline.tracks_scroll = _Scroll(height=240, value=0)

        rows, _ = LAYOUT.shared_row_geometry(timeline)
        overlay_row = next(row for row in rows if row[0] == "track" and row[1] is timeline.overlay)
        main_row = next(row for row in rows if row[0] == "track" and row[1] is timeline.main)
        natural, displayed = LAYOUT.main_row_display_y(timeline)

        # Main stays immediately after the overlay's 3px insertion gap. The
        # decorative 112px outer workspace must not trigger sticky pinning.
        self.assertEqual(main_row[3], overlay_row[3] + overlay_row[4] + timeline.LAYER_INSERT_GAP_HEIGHT)
        self.assertEqual(displayed, natural)

    def test_tall_overlay_stack_still_bottom_pins_main(self):
        timeline = _Timeline(audio=False, scroll=0)
        timeline.top_layer_drop_height = lambda: 112
        timeline.tracks_scroll = _Scroll(height=240, value=0)
        overlays = [
            {"name": f"V{i + 2}", "base": "V", "is_main": False,
             "clips": [{"start": 0, "duration": 2}], "_stack_order": i}
            for i in range(8)
        ]
        timeline._normalise_track_stack = lambda: (overlays, timeline.main, [], [])
        timeline.timeline_ui_rows = lambda: (
            [(kind, value, section) for track in overlays
             for kind, value, section in [("gap", None, "overlay"), ("track", track, "overlay")]]
            + [("gap", None, "overlay"), ("track", timeline.main, "main")]
        )
        natural, displayed = LAYOUT.main_row_display_y(timeline)
        expected_bottom = timeline.tracks_scroll.verticalScrollBar().value() + timeline.tracks_scroll.viewport().height() - timeline.MAIN_TRACK_HEIGHT - timeline.MAIN_STICKY_GAP_HEIGHT
        self.assertGreater(natural, expected_bottom)
        self.assertEqual(displayed, expected_bottom)

    def test_main_clamps_bottom_for_overlays_and_top_for_audio(self):
        timeline = _Timeline(audio=True, scroll=0)
        # With the Main row naturally below the visible viewport, it pins to
        # the bottom edge while overlays scroll behind it.
        natural = 600
        self.assertEqual(LAYOUT._displayed_main_y(timeline, natural),
                         400 - timeline.MAIN_TRACK_HEIGHT - timeline.MAIN_STICKY_GAP_HEIGHT)

        # At an intermediate scroll position, Main stays in its natural place
        # instead of being pulled away and creating a gap above/below it.
        timeline.tracks_scroll.verticalScrollBar()._value = 300
        self.assertEqual(LAYOUT._displayed_main_y(timeline, natural), natural)

        # Once the viewport passes Main, it pins to the top edge and audio
        # continues moving naturally behind the pinned Main row.
        timeline.tracks_scroll.verticalScrollBar()._value = 650
        self.assertEqual(LAYOUT._displayed_main_y(timeline, natural), 650)

    def test_main_pin_edges_recompute_when_timeline_viewport_resizes(self):
        timeline = _Timeline(audio=False, scroll=0)
        timeline.tracks_scroll = _Scroll(height=500, value=0)
        self.assertEqual(LAYOUT._displayed_main_y(timeline, 700),
                         500 - timeline.MAIN_TRACK_HEIGHT - timeline.MAIN_STICKY_GAP_HEIGHT)
        timeline.tracks_scroll = _Scroll(height=300, value=0)
        self.assertEqual(LAYOUT._displayed_main_y(timeline, 700),
                         300 - timeline.MAIN_TRACK_HEIGHT - timeline.MAIN_STICKY_GAP_HEIGHT)

    def test_no_audio_keeps_existing_main_sticky_reservation(self):
        timeline = _Timeline(audio=False, scroll=80)
        self.assertEqual(LAYOUT._reserved_audio_space(timeline), 0)
        self.assertIsNone(LAYOUT.first_audio_row_display_y(timeline))

    def test_displayed_geometry_moves_only_first_audio_lane(self):
        timeline = _Timeline(audio=True, scroll=180)
        rows, _ = LAYOUT.shared_row_geometry(timeline, displayed=True)
        audio_rows = [row for row in rows if row[0] == "track" and row[1].get("base") == "A"]
        self.assertEqual(len(audio_rows), 1)
        expected = LAYOUT.first_audio_row_display_y(timeline)[1]
        self.assertEqual(audio_rows[0][3], expected)


    def test_audio_rows_never_get_independent_sticky_offset(self):
        timeline = _Timeline(audio=True, scroll=250)
        timeline.top_layer_drop_height = lambda: 112
        natural_audio, displayed_audio = LAYOUT.first_audio_row_display_y(timeline)
        self.assertEqual(displayed_audio, natural_audio)
        rows, _ = LAYOUT.shared_row_geometry(timeline, displayed=True)
        audio_row = next(row for row in rows if row[0] == "track" and row[1] is timeline.audio)
        self.assertEqual(audio_row[3], natural_audio)

    def test_main_top_pin_uses_viewport_edge_not_drop_workspace(self):
        timeline = _Timeline(audio=True, scroll=650)
        timeline.top_layer_drop_height = lambda: 112
        natural_main, displayed_main = LAYOUT.main_row_display_y(timeline)
        self.assertLess(natural_main, 650)
        self.assertEqual(displayed_main, 650)
        natural_audio, displayed_audio = LAYOUT.first_audio_row_display_y(timeline)
        self.assertEqual(displayed_audio, natural_audio)

if __name__ == "__main__":
    unittest.main()
