from app.animation import (
    evaluate_keyframes, integrate_speed_curve, normalize_keyframes,
    upsert_keyframe, remove_keyframe, speed_curve_setpts_expression,
)


def test_linear_keyframe_interpolation():
    keys = [{"time": 0, "value": 0}, {"time": 2, "value": 10}]
    assert evaluate_keyframes(keys, 1, 0) == 5


def test_ease_in_interpolation():
    keys = [{"time": 0, "value": 0, "ease": "ease_in"}, {"time": 2, "value": 10}]
    assert evaluate_keyframes(keys, 1, 0) == 2.5


def test_duplicate_keyframes_are_deduplicated():
    keys = normalize_keyframes([{"time": 1, "value": 2}, {"time": 1, "value": 4}])
    assert len(keys) == 1 and keys[0]["value"] == 4


def test_keyframe_upsert_and_remove():
    clip = {}
    upsert_keyframe(clip, "brightness", 0.51, 0.2, fps=30)
    upsert_keyframe(clip, "brightness", 0.50, 0.7, fps=30)
    assert len(clip["keyframes"]["brightness"]) == 1
    assert clip["keyframes"]["brightness"][0]["value"] == 0.7
    assert remove_keyframe(clip, "brightness", 0.5, fps=30)
    assert "brightness" not in clip["keyframes"]


def test_constant_speed_curve_integral():
    assert abs(integrate_speed_curve([{"x": 0, "y": 2}, {"x": 1, "y": 2}], 10, 1) - 20) < 1e-6


def test_variable_speed_curve_integral():
    # Average of 0.5x and 1.5x over ten seconds is 1x.
    curve = [{"x": 0, "y": 0.5}, {"x": 1, "y": 1.5}]
    assert abs(integrate_speed_curve(curve, 10, 1) - 10) < 1e-6


def test_speed_curve_generates_ffmpeg_expression():
    expr = speed_curve_setpts_expression([{"x": 0, "y": 1}, {"x": 1, "y": 2}], 5, 1)
    assert "sqrt" in expr and "PTS*TB" in expr


def test_split_speed_curve_preserves_boundary_speed():
    from app.animation import split_speed_curve, evaluate_speed_curve
    curve = [{"x": 0, "y": 0.5}, {"x": 0.5, "y": 2.0}, {"x": 1, "y": 1.0}]
    left, right, boundary = split_speed_curve(curve, 8.0, 3.0, 1.0)
    assert left[0]["x"] == 0.0 and left[-1]["x"] == 1.0
    assert right[0]["x"] == 0.0 and right[-1]["x"] == 1.0
    assert abs(left[-1]["y"] - boundary) < 1e-6
    assert abs(right[0]["y"] - boundary) < 1e-6


def test_trim_keyframes_shifts_and_clamps_local_times():
    from app.animation import trim_keyframes
    clip = {"keyframes": {"brightness": [
        {"time": 0, "value": 0}, {"time": 1, "value": 0.5}, {"time": 3, "value": 1}
    ]}}
    trim_keyframes(clip, old_start=0, new_start=1, new_duration=2, fps=30)
    assert [p["time"] for p in clip["keyframes"]["brightness"]] == [0.0, 2.0]


def test_speed_input_duration_preserves_source_span():
    from app.video_engine.ffmpeg_backend import _input_args
    args = _input_args({"kind":"Video", "path":"sample.mp4", "duration":3.0, "speed":2.0}, 30)
    assert args[args.index("-t") + 1] == "6"


def test_speed_curve_filter_uses_high_resolution_timebase():
    from app.video_engine.ffmpeg_backend import _overlay_chain
    clip = {"start":0.0, "duration":2.0, "end":2.0, "kind":"Video", "path":"x", "speed":1.0,
            "speed_mode":"curve", "speed_curve":[{"x":0,"y":0.5},{"x":1,"y":2.0}],
            "scale":1.0, "opacity":1.0, "position_x":0.0, "position_y":0.0}
    graph = ";".join(_overlay_chain([clip], 30, 2.0))
    assert "settb=AVTB,setpts=" in graph
    assert "sqrt" in graph


def test_grade_keyframes_are_exported_as_frame_evaluated_expression():
    from app.video_engine.ffmpeg_backend import _overlay_chain
    clip = {"start":0.0, "duration":2.0, "end":2.0, "kind":"Video", "path":"x", "speed":1.0,
            "scale":1.0, "opacity":1.0, "position_x":0.0, "position_y":0.0,
            "keyframes":{"brightness":[{"time":0,"value":0.0},{"time":1,"value":0.3}]}}
    graph = ";".join(_overlay_chain([clip], 30, 2.0))
    assert "eval=frame" in graph and "clip(" in graph


def test_speed_aware_left_trim_advances_source_in_by_rate():
    from app.timeline_trim_math import drag_trim
    start, duration, source_in = drag_trim("trim_left", 30, 90, 0, 300, 10, speed=2.0)
    assert (start, duration, source_in) == (40, 80, 20)


def test_speed_aware_right_trim_respects_source_length():
    from app.timeline_trim_math import drag_trim
    start, duration, source_in = drag_trim("trim_right", 0, 30, 40, 100, 100, speed=2.0)
    assert start == 0 and source_in == 40
    assert duration == 30


def test_custom_bezier_keyframe_easing_is_evaluated():
    from app.animation import evaluate_keyframes
    keys = [
        {"time": 0, "value": 0, "ease": {
            "type": "bezier", "x1": 1/3, "y1": 0.0, "x2": 2/3, "y2": 1.0
        }},
        {"time": 1, "value": 1},
    ]
    assert abs(evaluate_keyframes(keys, 0.5, 0) - 0.5) < 1e-6


def test_transform_keyframes_are_exported_as_frame_expressions():
    from app.video_engine.ffmpeg_backend import _overlay_chain
    clip = {
        "start": 0.0, "end": 2.0, "duration": 2.0, "kind": "Video",
        "path": "sample.mp4", "speed": 1.0, "scale": 1.0, "opacity": 1.0,
        "position_x": 0.0, "position_y": 0.0, "position_z": 0.0, "rotation": 0.0,
        "keyframes": {
            "scale": [{"time": 0, "value": 0.8}, {"time": 1, "value": 1.2}],
            "opacity": [{"time": 0, "value": 0.2}, {"time": 1, "value": 1.0}],
            "rotation": [{"time": 0, "value": 0}, {"time": 1, "value": 15}],
            "position_x": [{"time": 0, "value": -20}, {"time": 1, "value": 20}],
        },
    }
    graph = ";".join(_overlay_chain([clip], 30, 2.0))
    assert "eval=frame" in graph
    assert "geq=" in graph
    assert "rotate='" in graph
    assert "overlay=" in graph and "eval=frame" in graph
