from pathlib import Path
import importlib.util

_MODULE = Path(__file__).resolve().parents[1] / "app" / "timeline_insert_math.py"
_SPEC = importlib.util.spec_from_file_location("skyzen_timeline_insert_math", _MODULE)
_MATH = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MATH)

ripple_insert_plan = _MATH.ripple_insert_plan
overlap_insert_boundary = _MATH.overlap_insert_boundary
contiguous_frame_starts = _MATH.contiguous_frame_starts


def test_insert_in_gap_closes_gap_to_right_clip():
    # New clip is frames 30..60; the next clip moves to frame 60 so there is
    # no blank frame gap after the inserted clip.
    assert ripple_insert_plan([(90, 180)], 30, 30) == (-30, 90)


def test_insert_in_gap_preserves_spacing_after_first_right_clip():
    # Both right-side clips move by the same delta, preserving their relative gap.
    assert ripple_insert_plan([(90, 180), (210, 270)], 30, 30) == (-30, 90)


def test_insufficient_gap_shifts_right_clip_by_inserted_duration():
    # New clip is frames 30..60, existing clip starts at 45.
    assert ripple_insert_plan([(45, 135), (150, 240)], 30, 30) == (15, 45)


def test_clip_spanning_insertion_is_shifted_clear_of_new_clip():
    # Existing clip begins before the insertion point, so shift enough that its
    # new start is at the inserted clip's end.
    assert ripple_insert_plan([(10, 100), (110, 200)], 40, 30) == (60, 10)


def test_empty_track_does_not_ripple():
    assert ripple_insert_plan([], 0, 75) == (0, None)


def test_overlap_drop_left_half_inserts_before_clip():
    assert overlap_insert_boundary(120, 240, 8, 100) == 120


def test_overlap_drop_right_half_inserts_after_clip():
    assert overlap_insert_boundary(120, 240, 75, 100) == 240


def test_overlap_drop_boundary_is_frame_exact():
    # Exactly at the midpoint is treated as after, so the result is deterministic.
    assert overlap_insert_boundary(120, 241, 50, 100) == 241


def test_main_lane_reflow_is_contiguous_from_zero():
    durations = [300, 127, 91, 240]
    starts = contiguous_frame_starts(durations)
    assert starts == [0, 300, 427, 518]
    assert all(starts[i] + durations[i] == starts[i + 1] for i in range(len(durations) - 1))


def test_main_lane_reflow_handles_short_or_invalid_durations_safely():
    assert contiguous_frame_starts([10, 0, -3, 5]) == [0, 10, 11, 12]
