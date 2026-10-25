import importlib.util
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "app" / "timeline_panel" / "track_layout.py"
SPEC = importlib.util.spec_from_file_location("skyzen_shared_track_layout", MODULE)
LAYOUT = importlib.util.module_from_spec(SPEC)
LAYER = LAYOUT
SPEC.loader.exec_module(LAYOUT)


class FakeTimeline:
    TRACK_HEIGHT = 50
    SECTION_HEADER_HEIGHT = 22
    EFFECT_DROP_HEIGHT = 42
    LAYER_INSERT_GAP_HEIGHT = 0

    def top_layer_drop_height(self):
        return 0

    def timeline_ui_rows(self):
        return [
            ("track", {"name": "V4"}, None),
            ("track", {"name": "V3"}, None),
            ("section", "Audio", "audio"),
            ("track", {"name": "A1"}, "audio"),
            ("track", {"name": "V1 - MAIN"}, None),
        ]


def test_track_positions_match_shared_geometry():
    timeline = FakeTimeline()
    rows, _ = LAYOUT.shared_row_geometry(timeline)
    expected = [(value, y) for kind, value, _section, y, _height, _idx, _src
                in rows if kind == "track"]
    assert LAYOUT.track_row_positions(timeline) == expected


def test_section_height_is_included_before_following_track():
    timeline = FakeTimeline()
    positions = dict((track["name"], y) for track, y in LAYOUT.track_row_positions(timeline))
    assert positions["A1"] - positions["V3"] == 50 + 22


def test_side_columns_get_identical_scroll_range():
    # Timeline viewport is 10 px shorter (horizontal scrollbar).
    heights = LAYER.side_column_heights(600, 190, [200, 200])
    assert heights == [610, 610]
    for h in heights:
        assert h - 200 == 600 - 190  # same max scroll value


def test_wheel_step_is_one_row_per_notch_and_pixels_for_trackpads():
    assert LAYER.wheel_scroll_delta(-120, 0, 50) == 50
    assert LAYER.wheel_scroll_delta(120, 0, 50) == -50
    assert LAYER.wheel_scroll_delta(0, -7, 50) == 7
    assert LAYER.wheel_scroll_delta(0, 0, 50) == 0


def test_bottom_gap_only_reserved_when_visible():
    assert LAYER.reserved_bottom_gap(4, 112) == 0
    assert LAYER.reserved_bottom_gap(5, 112) == 112


def test_stack_is_bottom_anchored_until_it_overflows():
    # 3 rows (150px) in a 300px viewport -> 150px of space above the stack.
    assert LAYER.bottom_anchor_pad(300, 150, 0) == 150
    # Stack taller than viewport -> no pad, normal scrolling.
    assert LAYER.bottom_anchor_pad(300, 400, 0) == 0
    # Reserved bottom gap is subtracted so total height equals the viewport.
    assert LAYER.bottom_anchor_pad(400, 250, 112) == 38


def test_symmetric_outer_gap_matches_above_and_below():
    assert LAYOUT.symmetric_outer_gap(700, 300, 112) == 200
    assert LAYOUT.symmetric_outer_gap(500, 300, 112) == 112
    # Overflowing stacks retain the same 112 px workspace at both ends.
    assert LAYOUT.symmetric_outer_gap(400, 650, 112) == 112


def test_main_row_is_pinned_to_viewport_bottom_while_overlays_scroll():
    # 400px viewport, 50px row, 8px gap -> pinned line is scroll + 342.
    assert LAYER.sticky_main_y(natural_y=600, scroll_y=0, viewport_h=400, track_h=50, bottom_gap=8) == 342
    assert LAYER.sticky_main_y(600, 100, 400, 50, 8) == 442       # follows the pin while scrolling
    assert LAYER.sticky_main_y(600, 300, 400, 50, 8) == 600       # joins the content flow at the end
    assert LAYER.sticky_main_y(150, 0, 400, 50, 8) == 150         # short stack: stays centred/natural
    assert LAYER.sticky_main_y(150, 400, 400, 50, 8) == 150       # scrolled away: leaves with the content
