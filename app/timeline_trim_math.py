"""Pure frame-domain trim calculations shared by the timeline and tests.

No Qt dependency: all edit math stays deterministic and frame-accurate.
"""
from __future__ import annotations


def pointer_delta_frames(
    start_x: float,
    current_x: float,
    pixels_per_frame: float,
) -> int:
    """Convert a stable pointer-coordinate delta to whole timeline frames.

    Callers should supply coordinates from the same stable space (for example,
    global screen coordinates), not widget-local coordinates when the widget
    can move or resize during the drag.
    """
    scale = max(0.001, float(pixels_per_frame))
    return int(round((float(current_x) - float(start_x)) / scale))


def left_trim_frames(
    start_frame: int,
    end_frame: int,
    playhead_frame: int,
    source_in_frame: int,
    source_duration_frames: int | None = None,
    speed: float = 1.0,
) -> tuple[int, int, int] | None:
    """Return (new timeline start, new source in, new duration), or None."""
    start = int(start_frame)
    end = int(end_frame)
    target = int(playhead_frame)
    source_in = max(0, int(source_in_frame))
    if target <= start or target >= end:
        return None
    original_duration = end - start
    speed = max(0.1, min(8.0, float(speed)))
    source_out = source_in + int(round(original_duration * speed))
    if source_duration_frames is not None:
        source_out = min(source_out, max(0, int(source_duration_frames)))
    new_source_in = source_in + int(round((target - start) * speed))
    if new_source_in >= source_out:
        return None
    return target, new_source_in, end - target


def right_trim_frames(
    start_frame: int,
    end_frame: int,
    playhead_frame: int,
) -> int | None:
    """Return the retained duration in frames, or None for an invalid trim."""
    start = int(start_frame)
    end = int(end_frame)
    target = int(playhead_frame)
    if target <= start or target >= end:
        return None
    return target - start


def drag_trim(
    mode: str,
    orig_start: int,
    orig_duration: int,
    source_in: int,
    source_length: int | None,
    delta: int,
    prev_end: int | None = None,
    next_start: int | None = None,
    min_frames: int = 1,
    speed: float = 1.0,
) -> tuple[int, int, int]:
    """Frame-accurate edge drag. Returns (start, duration, source_in).

    ``source_length`` is the real media length in frames for video/audio, and
    ``None`` for still images, which have no intrinsic length and can be
    stretched freely.  Every result is derived from the values at drag start
    plus ``delta`` so repeated mouse moves never accumulate rounding error.

    * trim_left : right edge fixed; the left edge may move right (shorten) or
      left (lengthen) until the source in-point reaches 0, the previous clip
      ends, or the timeline start (frame 0) is reached.
    * trim_right: left edge fixed; the right edge may move left (shorten) or
      right (lengthen) until the media's last frame, the next clip, or never
      for images.
    """
    start = int(orig_start)
    duration = max(int(min_frames), int(orig_duration))
    end = start + duration
    s_in = max(0, int(source_in))
    delta = int(delta)
    min_frames = max(1, int(min_frames))
    bounded = source_length is not None
    speed = max(0.1, min(8.0, float(speed)))

    if mode == "trim_left":
        lowest = 0
        if prev_end is not None:
            lowest = max(lowest, int(prev_end))
        if bounded:
            lowest = max(lowest, start - int(s_in / speed))  # cannot go before source frame 0
        new_start = max(lowest, min(end - min_frames, start + delta))
        if bounded:
            new_in = s_in + int(round((new_start - start) * speed))
        else:
            new_in = s_in
        return new_start, end - new_start, max(0, new_in)

    if mode == "trim_right":
        highest = None
        if bounded:
            highest = start + max(min_frames, int((int(source_length) - s_in) / speed))
        if next_start is not None:
            cap = max(start + min_frames, int(next_start))
            highest = cap if highest is None else min(highest, cap)
        new_end = max(start + min_frames, end + delta)
        if highest is not None:
            new_end = min(new_end, highest)
        return start, new_end - start, s_in

    raise ValueError(f"unknown trim mode: {mode}")

def resolve_source_length_frames(
    source_length_frames: int | None,
    source_in_frames: int,
    visible_duration_frames: int,
) -> int:
    """Resolve a safe source-length bound for an existing trimmed clip.

    Some legacy project clips do not contain ``source_duration``. Falling back
    to the *timeline duration alone* is incorrect after a left trim because
    ``source_in`` has advanced while the visible duration has decreased. That
    combination can make a subsequent right trim collapse to one frame.

    When source metadata is absent or stale, preserve at least the source range
    currently visible (source-in + visible duration). A valid, longer source
    length is retained so the right edge can still be extended to the real end.
    """
    source_in = max(0, int(source_in_frames))
    visible_duration = max(1, int(visible_duration_frames))
    minimum_source_end = source_in + visible_duration
    if source_length_frames is None:
        return minimum_source_end
    return max(minimum_source_end, max(1, int(source_length_frames)))

