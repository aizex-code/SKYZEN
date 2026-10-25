"""Frame-based keyframe and speed-curve math for Skyzen.

Keyframe times are clip-local seconds. Curves are plain JSON-serializable data,
so project save/load remains backward compatible with clips that have no keys.
"""
from __future__ import annotations

import math


def _clamp(value, low, high):
    return max(low, min(high, float(value)))


def normalize_keyframes(points):
    clean = []
    for point in points or []:
        try:
            t = max(0.0, float(point.get("time", 0.0)))
            v = float(point.get("value", 0.0))
        except (AttributeError, TypeError, ValueError):
            continue
        raw_ease = point.get("ease", "linear")
        if isinstance(raw_ease, dict) and raw_ease.get("type") == "bezier":
            try:
                ease = {
                    "type": "bezier",
                    "x1": _clamp(raw_ease.get("x1", 0.33), 0.0, 1.0),
                    "y1": _clamp(raw_ease.get("y1", 0.0), 0.0, 1.0),
                    "x2": _clamp(raw_ease.get("x2", 0.67), 0.0, 1.0),
                    "y2": _clamp(raw_ease.get("y2", 1.0), 0.0, 1.0),
                }
            except (TypeError, ValueError):
                ease = "linear"
        else:
            ease = str(raw_ease)
            if ease not in ("linear", "ease_in", "ease_out", "ease_in_out", "hold"):
                ease = "linear"
        clean.append({"time": t, "value": v, "ease": ease})
    clean.sort(key=lambda p: p["time"])
    deduped = []
    for point in clean:
        if deduped and abs(point["time"] - deduped[-1]["time"]) < 1e-7:
            deduped[-1] = point
        else:
            deduped.append(point)
    return deduped


def ease_progress(progress, ease="linear"):
    p = _clamp(progress, 0.0, 1.0)
    if ease == "hold":
        return 0.0 if p < 1.0 else 1.0
    if ease == "ease_in":
        return p * p
    if ease == "ease_out":
        return 1.0 - (1.0 - p) * (1.0 - p)
    if ease == "ease_in_out":
        return p * p * (3.0 - 2.0 * p)
    if isinstance(ease, dict) and ease.get("type") == "bezier":
        # Cubic Bezier y curve parameterized by normalized segment time.
        y1 = _clamp(ease.get("y1", 0.0), 0.0, 1.0)
        y2 = _clamp(ease.get("y2", 1.0), 0.0, 1.0)
        q = 1.0 - p
        return _clamp(3*q*q*p*y1 + 3*q*p*p*y2 + p*p*p, 0.0, 1.0)
    return p


def evaluate_keyframes(points, time_value, default=0.0):
    keys = normalize_keyframes(points)
    if not keys:
        return float(default)
    t = max(0.0, float(time_value))
    if t <= keys[0]["time"]:
        return keys[0]["value"]
    if t >= keys[-1]["time"]:
        return keys[-1]["value"]
    for left, right in zip(keys, keys[1:]):
        if left["time"] <= t <= right["time"]:
            span = right["time"] - left["time"]
            p = 1.0 if span <= 0 else (t - left["time"]) / span
            p = ease_progress(p, left["ease"])
            return left["value"] + (right["value"] - left["value"]) * p
    return float(default)


def upsert_keyframe(clip, property_name, time_value, value, ease="linear", fps=30):
    all_keys = clip.setdefault("keyframes", {})
    points = normalize_keyframes(all_keys.get(property_name, []))
    frame_time = round(max(0.0, float(time_value)) * max(1, int(fps))) / max(1, int(fps))
    points.append({"time": frame_time, "value": float(value), "ease": ease})
    all_keys[property_name] = normalize_keyframes(points)
    return all_keys[property_name]


def remove_keyframe(clip, property_name, time_value, fps=30):
    tolerance = 0.5 / max(1, int(fps))
    keys = clip.get("keyframes", {})
    points = normalize_keyframes(keys.get(property_name, []))
    kept = [p for p in points if abs(p["time"] - float(time_value)) > tolerance]
    if kept:
        keys[property_name] = kept
    else:
        keys.pop(property_name, None)
    return len(kept) != len(points)


def curve_points(curve, duration, default_speed=1.0):
    """Normalize speed curve points into local seconds and bounded speed values."""
    duration = max(1.0 / 30.0, float(duration))
    raw = curve or [{"x": 0.0, "y": default_speed}, {"x": 1.0, "y": default_speed}]
    points = []
    for point in raw:
        try:
            x = _clamp(point.get("x", 0.0), 0.0, 1.0)
            y = _clamp(point.get("y", default_speed), 0.5, 5.0)
        except (AttributeError, TypeError, ValueError):
            continue
        points.append({"time": x * duration, "value": y, "ease": "linear"})
    points = normalize_keyframes(points)
    if not points or points[0]["time"] > 0:
        points.insert(0, {"time": 0.0, "value": points[0]["value"] if points else _clamp(default_speed, .5, 5), "ease": "linear"})
    if points[-1]["time"] < duration:
        points.append({"time": duration, "value": points[-1]["value"], "ease": "linear"})
    return points


def integrate_speed_curve(curve, duration, default_speed=1.0):
    """Return source-time duration for a linearly interpolated speed curve."""
    points = curve_points(curve, duration, default_speed)
    total = 0.0
    for left, right in zip(points, points[1:]):
        total += (right["time"] - left["time"]) * (left["value"] + right["value"]) * 0.5
    return max(0.0, total)



def evaluate_speed_curve(curve, duration, time_value, default_speed=1.0):
    points = curve_points(curve, duration, default_speed)
    return evaluate_keyframes(points, max(0.0, float(time_value)), default_speed)


def integrate_speed_to(curve, duration, time_value, default_speed=1.0):
    """Integrate speed only from clip start through local time_value."""
    duration = max(1.0 / 30.0, float(duration))
    target = max(0.0, min(duration, float(time_value)))
    points = curve_points(curve, duration, default_speed)
    total = 0.0
    for left, right in zip(points, points[1:]):
        a = left["time"]
        b = min(right["time"], target)
        if b <= a:
            continue
        span = max(1e-9, right["time"] - left["time"])
        va = left["value"]
        vb = va + (right["value"] - va) * ((b-a) / span)
        total += (b-a) * (va+vb) * 0.5
        if target <= right["time"]:
            break
    return total

def speed_curve_setpts_expression(curve, duration, default_speed=1.0):
    """FFmpeg setpts expression mapping source timestamps back to timeline time.

    Each linear speed segment is inverted analytically. Expression uses source
    timestamp T (seconds) and returns output timestamp in seconds.
    """
    points = curve_points(curve, duration, default_speed)
    segments = []
    source_at = 0.0
    for left, right in zip(points, points[1:]):
        dt = right["time"] - left["time"]
        v0, v1 = left["value"], right["value"]
        source_end = source_at + dt * (v0 + v1) * 0.5
        a = (v1 - v0) / dt if dt > 1e-9 else 0.0
        if abs(a) < 1e-8:
            out = f"({left['time']:.6f}+((PTS*TB)-{source_at:.6f})/{max(.1, v0):.6f})"
        else:
            out = f"({left['time']:.6f}+(-{v0:.6f}+sqrt(max(0,{v0*v0:.6f}+2*{a:.6f}*((PTS*TB)-{source_at:.6f}))))/{a:.6f})"
        segments.append((source_end, out))
        source_at = source_end
    expr = segments[-1][1] if segments else f"T/{max(.1, default_speed):.6f}"
    for threshold, out in reversed(segments[:-1]):
        expr = f"if(lt(PTS*TB,{threshold:.6f}),{out},{expr})"
    return expr


def split_speed_curve(curve, duration, split_time, default_speed=1.0):
    """Split a normalized speed curve into two normalized curves at local time."""
    duration = max(1.0 / 30.0, float(duration))
    split_time = max(0.0, min(duration, float(split_time)))
    points = curve_points(curve, duration, default_speed)
    split_speed = evaluate_keyframes(points, split_time, default_speed)
    left_raw = [{"x": p["time"] / duration, "y": p["value"]} for p in points if p["time"] < split_time]
    right_raw = [{"x": (p["time"]-split_time) / max(1e-9, duration-split_time), "y": p["value"]} for p in points if p["time"] > split_time]
    left_raw.extend([{"x": 0.0, "y": points[0]["value"]}, {"x": 1.0, "y": split_speed}])
    right_raw.extend([{"x": 0.0, "y": split_speed}, {"x": 1.0, "y": points[-1]["value"]}])
    def clean(raw):
        raw.sort(key=lambda p: p["x"])
        result = []
        for p in raw:
            p["x"] = _clamp(p["x"], 0.0, 1.0)
            if result and abs(result[-1]["x"]-p["x"]) < 1e-6:
                result[-1] = p
            else:
                result.append(p)
        if len(result) < 2:
            result = [{"x":0.0,"y":split_speed},{"x":1.0,"y":split_speed}]
        result[0]["x"] = 0.0
        result[-1]["x"] = 1.0
        return result
    return clean(left_raw), clean(right_raw), split_speed


def trim_keyframes(clip, old_start, new_start, new_duration, fps=30):
    """Keep clip-local keyframes aligned after a left/right edge trim."""
    keys = clip.get("keyframes", {}) or {}
    shift = float(new_start) - float(old_start)
    duration = max(0.0, float(new_duration))
    frame = 1.0 / max(1, int(fps))
    cleaned = {}
    for prop, points in keys.items():
        moved = []
        for point in normalize_keyframes(points):
            t = point["time"] - shift
            if -frame * 0.5 <= t <= duration + frame * 0.5:
                moved.append({"time": max(0.0, min(duration, t)), "value": point["value"], "ease": point["ease"]})
        if moved:
            cleaned[prop] = normalize_keyframes(moved)
    if cleaned:
        clip["keyframes"] = cleaned
    else:
        clip.pop("keyframes", None)


def split_keyframes(keyframes, split_time, duration, defaults=None):
    """Return left/right keyframe maps with a sampled boundary key per property."""
    defaults = defaults or {}
    left_map, right_map = {}, {}
    split_time = max(0.0, float(split_time))
    duration = max(split_time, float(duration))
    for prop, raw in (keyframes or {}).items():
        points = normalize_keyframes(raw)
        if not points:
            continue
        boundary = evaluate_keyframes(points, split_time, defaults.get(prop, points[0]["value"]))
        left_points = [dict(p) for p in points if p["time"] < split_time]
        right_points = [dict(p) for p in points if p["time"] > split_time]
        left_points.append({"time": split_time, "value": boundary, "ease": "linear"})
        right_points.insert(0, {"time": 0.0, "value": boundary, "ease": "linear"})
        right_points = [{"time": max(0.0, p["time"]-split_time), "value": p["value"], "ease": p["ease"]} for p in right_points]
        left_points = [p for p in left_points if p["time"] <= split_time]
        right_points = [p for p in right_points if p["time"] <= duration-split_time]
        left_map[prop] = normalize_keyframes(left_points)
        right_map[prop] = normalize_keyframes(right_points)
    return left_map, right_map
