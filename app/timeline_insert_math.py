"""Pure frame-domain planning for ripple insertion on a timeline track."""

from __future__ import annotations


def ripple_insert_plan(ranges, insert_frame: int, duration_frames: int):
    """Return ``(shift_frames, first_affected_start)`` for ripple insertion.

    The earliest clip at or to the right of the insertion point is the ripple
    anchor. If it is in a gap, it moves to the inserted clip's end so the new
    clip and its right neighbour are frame-adjacent. All later clips move by
    the same delta, preserving their relative spacing. If a clip straddles the
    insertion point, the delta is enlarged to clear the inserted clip fully.
    ``first_affected_start`` is ``None`` when no clips need to move.
    """
    insert_frame = max(0, int(insert_frame))
    duration_frames = max(1, int(duration_frames))
    affected = [
        (int(start), int(end))
        for start, end in ranges
        if int(start) >= insert_frame or int(end) > insert_frame
    ]
    if not affected:
        return 0, None
    first_start = min(start for start, _end in affected)
    if first_start < insert_frame:
        shift = max(duration_frames, insert_frame + duration_frames - first_start)
    else:
        # Negative shift is intentional: it closes the pre-existing gap after
        # the insertion so the next clip sits exactly against the new clip.
        shift = insert_frame + duration_frames - first_start
    return shift, first_start


def contiguous_frame_starts(duration_frames):
    """Return exact frame starts for clips packed consecutively from frame 0."""
    starts = []
    cursor = 0
    for duration in duration_frames:
        starts.append(cursor)
        cursor += max(1, int(duration))
    return starts


def overlap_insert_boundary(start_frame: int, end_frame: int, pointer_offset: float, clip_width: float) -> int:
    """Choose an exact insertion boundary for a pointer dropped over a clip.

    The left half inserts before the clip; the right half inserts after it.
    Geometry is supplied in pixels, while the returned location is a frame.
    """
    start_frame = max(0, int(start_frame))
    end_frame = max(start_frame + 1, int(end_frame))
    clip_width = max(1.0, float(clip_width))
    pointer_offset = max(0.0, min(float(pointer_offset), clip_width))
    return start_frame if pointer_offset < clip_width * 0.5 else end_frame
