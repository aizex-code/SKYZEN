import importlib.util
from pathlib import Path

_p = Path(__file__).resolve().parents[1] / "app" / "timeline_trim_math.py"
_s = importlib.util.spec_from_file_location("trim_math", _p)
M = importlib.util.module_from_spec(_s)
_s.loader.exec_module(M)
drag = M.drag_trim
pointer_delta_frames = M.pointer_delta_frames
resolve_source_length_frames = M.resolve_source_length_frames

# 10 s video @30fps: clip placed at 100, currently shows source 60..240.
V = dict(orig_start=100, orig_duration=180, source_in=60, source_length=300)


def test_right_trim_shortens_and_lengthens_to_source_end():
    assert drag("trim_right", delta=-50, **V) == (100, 130, 60)
    # source has 300-60 = 240 frames available
    assert drag("trim_right", delta=500, **V) == (100, 240, 60)


def test_left_trim_can_reveal_hidden_head_until_source_start():
    assert drag("trim_left", delta=20, **V) == (120, 160, 80)
    # dragging far left stops where source_in hits 0 (60 frames earlier)
    assert drag("trim_left", delta=-500, **V) == (40, 240, 0)


def test_left_trim_never_passes_previous_clip_or_zero():
    assert drag("trim_left", delta=-500, prev_end=90, **V) == (90, 190, 50)
    A = dict(orig_start=30, orig_duration=100, source_in=100, source_length=500)
    assert drag("trim_left", delta=-500, **A)[0] == 0


def test_right_trim_stops_at_next_clip():
    assert drag("trim_right", delta=500, next_start=330, **V) == (100, 230, 60)


def test_minimum_length_is_one_frame():
    assert drag("trim_right", delta=-9999, **V)[1] == 1
    assert drag("trim_left", delta=9999, **V)[1] == 1


def test_images_have_no_length_limit():
    I = dict(orig_start=0, orig_duration=150, source_in=0, source_length=None)
    assert drag("trim_right", delta=5000, **I) == (0, 5150, 0)
    assert drag("trim_right", delta=5000, next_start=400, **I) == (0, 400, 0)
    start, dur, s_in = drag("trim_left", delta=-5000, **dict(I, orig_start=200))
    assert (start, dur, s_in) == (0, 350, 0)


def test_pointer_delta_uses_stable_coordinate_delta():
    # A 15 px pointer movement at 3 px/frame must always mean five frames.
    # This remains true even if the clip widget moves underneath the pointer.
    assert pointer_delta_frames(100.0, 115.0, 3.0) == 5
    assert pointer_delta_frames(115.0, 100.0, 3.0) == -5


def test_pointer_delta_rounds_to_nearest_frame_and_guards_zero_scale():
    assert pointer_delta_frames(10.0, 14.4, 2.0) == 2
    assert pointer_delta_frames(10.0, 10.0, 0.0) == 0


def test_missing_source_duration_preserves_visible_source_range_after_left_trim():
    # A legacy clip has no source_duration field. It starts as 300 frames.
    # Trimming 180 frames from the left leaves source-in=180 and duration=120.
    # The right trim must not mistake 120 (timeline duration) for total source
    # length and clamp the clip to one frame.
    source_in_after_left_trim = 180
    visible_duration_after_left_trim = 120
    resolved = resolve_source_length_frames(
        None, source_in_after_left_trim, visible_duration_after_left_trim
    )
    assert resolved == 300
    assert drag(
        "trim_right",
        orig_start=180,
        orig_duration=120,
        source_in=source_in_after_left_trim,
        source_length=resolved,
        delta=-60,
    ) == (180, 60, 180)


def test_stale_source_duration_cannot_truncate_current_visible_range():
    # Even if stored source metadata is stale and shorter than the source range
    # currently shown, a subsequent right trim should shorten normally rather
    # than collapse the clip to the minimum frame.
    resolved = resolve_source_length_frames(100, 180, 120)
    assert resolved == 300
    assert drag(
        "trim_right",
        orig_start=180,
        orig_duration=120,
        source_in=180,
        source_length=resolved,
        delta=-60,
    ) == (180, 60, 180)
