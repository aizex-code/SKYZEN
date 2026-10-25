"""Shared vertical geometry policy for every Skyzen timeline column.

The timeline canvas, layer labels, edit gutter, and hit-testing all consume
this same row model. Keep geometry here rather than duplicating row arithmetic.
"""
from __future__ import annotations


def sticky_main_y(
    natural_y: int, scroll_y: int, viewport_h: int, track_h: int, bottom_gap: int,
    reserved_after: int = 0,
) -> int:
    """Where the Main row is drawn (content coordinates), CapCut style.

    Main normally sits at its natural place in the stack. When the stack is
    taller than the view, Main is held at the bottom of the viewport while
    overlays scroll *behind* it; scrolled to the end it joins the content flow
    again so the bottom gap is visible below it.
    """
    pinned = int(scroll_y) + max(
        0, int(viewport_h) - int(track_h) - int(bottom_gap) - max(0, int(reserved_after))
    )
    return min(int(natural_y), pinned)


def row_height(timeline, track) -> int:
    """Typed tool lanes are compact; Main remains tall and media overlays standard."""
    if isinstance(track, dict) and track.get("is_main", False):
        return int(getattr(timeline, "MAIN_TRACK_HEIGHT", timeline.TRACK_HEIGHT))
    if isinstance(track, dict) and track.get("track_type") in ("Text", "Effects", "Filters", "Adjustments"):
        return max(25, int(timeline.TRACK_HEIGHT * 0.5) + 1)
    return int(timeline.TRACK_HEIGHT)


def clip_height(timeline, track) -> int:
    return max(8, row_height(timeline, track) - 2 * int(timeline.CLIP_TOP_MARGIN))


def _displayed_main_y(timeline, natural_y: int) -> int:
    """Return Main's sticky Y in the shared scroll-content coordinate space.

    The V1-MAIN lane is the boundary between two independently editable
    regions. While the viewport is over overlays, Main clamps to the bottom;
    while the viewport is over audio, it clamps to the top. Between those
    regions it remains at its natural Y, which lets a user center Main with
    equal workspace above and below. The clamp is recalculated from the actual
    scroll viewport on every layout/scroll update, so resizing the timeline does
    not leave a stale pin coordinate.

    ``natural_y`` and the returned value are both content coordinates. Do not
    subtract the decorative top drop workspace from only one side of the
    comparison: doing so shifts the sticky threshold and creates a visible gap.
    """
    try:
        scroll_y = int(timeline.tracks_scroll.verticalScrollBar().value())
        viewport_h = int(timeline.tracks_scroll.viewport().height())
        main_height = int(getattr(timeline, "MAIN_TRACK_HEIGHT", timeline.TRACK_HEIGHT))
        bottom_gap = max(0, int(getattr(timeline, "MAIN_STICKY_GAP_HEIGHT", 0)))

        # Pin against the *viewport* edges, not the top drop-workspace inside
        # the scrollable content. Including top_layer_drop_height here leaves
        # an empty band above Main when audio is scrolled into view.
        top_edge = scroll_y
        bottom_edge = scroll_y + max(0, viewport_h - main_height - bottom_gap)
        # Tiny/resized viewports can make the edges cross. Keep a valid row
        # position by prioritizing the top edge rather than oscillating.
        if bottom_edge < top_edge:
            return top_edge
        return max(top_edge, min(int(natural_y), bottom_edge))
    except Exception:
        return int(natural_y)


def _reserved_audio_space(timeline) -> int:
    """Audio lanes do not reserve space or get independently pinned."""
    return 0


def first_audio_row_display_y(timeline):
    """Return the first audio row's natural content Y for compatibility.

    Only V1-MAIN is sticky. Audio lanes always remain in their normal row
    positions and scroll behind Main when Main reaches the viewport's top edge.
    This prevents the old independent audio pin from creating a gap or pushing
    audio rows away from the contiguous overlay → Main → audio stack.
    """
    rows, _end = shared_row_geometry(timeline)
    for kind, value, _section, y, _height, _track_index, _source_index in rows:
        if kind == "track" and isinstance(value, dict) and value.get("base") == "A":
            return int(y), int(y)
    return None


def main_row_display_y(timeline):
    """(natural_y, displayed_y) for the Main row, or None when there is none."""
    rows, _end = shared_row_geometry(timeline)
    for kind, value, _sec, y, _h, _ti, _si in rows:
        if kind == "track" and isinstance(value, dict) and value.get("is_main"):
            return y, _displayed_main_y(timeline, y)
    return None


def shared_row_geometry(timeline, displayed=False):
    """Return canonical row records and the final stack Y coordinate.

    With ``displayed=True`` the Main row uses its sticky on-screen Y (used by
    hit-testing); layout/rebuild always uses the natural stack positions.

    Each row is (kind, value, section, y, height, track_index, source_index).
    Every row type contributes its exact height once; explicit gap rows are
    represented by timeline_ui_rows(), just as in OpenCut's row stack.
    """
    source_rows = timeline.timeline_ui_rows()
    result = []
    y = int(timeline.top_layer_drop_height())
    track_index = 0

    for source_index, (kind, value, section) in enumerate(source_rows):
        if kind == "track":
            height = row_height(timeline, value)
            row_track_index = track_index
            track_index += 1
        elif kind == "section":
            height = int(timeline.SECTION_HEADER_HEIGHT)
            row_track_index = track_index
        elif kind == "effect_drop":
            height = int(timeline.EFFECT_DROP_HEIGHT)
            row_track_index = track_index
        elif kind == "gap":
            height = int(timeline.LAYER_INSERT_GAP_HEIGHT)
            row_track_index = max(0, track_index - 1)
        else:
            continue

        row_y = y
        if (
            displayed and kind == "track"
            and isinstance(value, dict) and value.get("is_main")
        ):
            row_y = _displayed_main_y(timeline, y)
        result.append(
            (kind, value, section, row_y, height, row_track_index, source_index)
        )
        y += height

    return result, y


def track_row_positions(timeline):
    """Return (track, y) pairs derived from the canonical row geometry."""
    rows, _end_y = shared_row_geometry(timeline, displayed=True)
    return [(value, y) for kind, value, _section, y, _height, _index, _source
            in rows if kind == "track"]


def sticky_main_lane_y(timeline) -> int:
    """Legacy compatibility helper for older sticky-main callers."""
    try:
        viewport_h = int(timeline.tracks_scroll.viewport().height())
        scroll_y = int(timeline.tracks_scroll.verticalScrollBar().value())
    except Exception:
        viewport_h = 0
        scroll_y = 0

    try:
        overlays, _main, _effects, _audios = timeline._normalise_track_stack()
        visible_count = (
            sum(1 for track in overlays if track.get("clips"))
            if timeline.overlays_ui_visible else 0
        )
    except Exception:
        visible_count = 0

    track_height = int(timeline.TRACK_HEIGHT)
    gap_height = int(timeline.MAIN_STICKY_GAP_HEIGHT)
    centered_y = max(0, (viewport_h - track_height) // 2)
    bottom_y = max(0, viewport_h - track_height - gap_height)

    audio_only = (
        not bool(getattr(timeline, "overlays_ui_visible", True))
        and bool(getattr(timeline, "audio_ui_visible", True))
    )
    if audio_only:
        lane_y = 0
    elif visible_count <= 0:
        lane_y = centered_y
    elif visible_count == 1:
        lane_y = min(bottom_y, centered_y + track_height)
    elif visible_count == 2:
        lane_y = min(bottom_y, centered_y + 2 * track_height)
    else:
        lane_y = bottom_y

    return scroll_y + lane_y


# ---------------------------------------------------------------------------
# Pure helpers shared by the scroll coordinator (no Qt dependency, unit-tested)
# ---------------------------------------------------------------------------

def side_column_heights(master_height: int, master_viewport: int, side_viewports):
    """Content heights that give every side column the same scroll range.

    Qt's range is ``content_height - viewport_height``. The timeline canvas has
    an always-visible horizontal scrollbar, so its viewport is shorter than the
    label/gutter viewports. Adding the viewport difference to the side content
    makes ``max`` identical in all columns, so no column clamps early.
    """
    master_height = max(1, int(master_height))
    master_viewport = max(0, int(master_viewport))
    return [
        max(1, master_height + max(0, int(vh)) - master_viewport)
        for vh in side_viewports
    ]


def wheel_scroll_delta(angle_y: int, pixel_y: int, row_height: int) -> int:
    """Vertical scroll amount (px) for one wheel event; positive = scroll down.

    Mouse wheels move one track row per 120-unit notch. Trackpads that report
    pixel deltas scroll by exactly those pixels, so they feel smooth.
    """
    if pixel_y:
        return -int(pixel_y)
    if angle_y:
        return -int(round(angle_y / 120.0 * max(1, int(row_height))))
    return 0


def reserved_bottom_gap(track_row_count: int, gap_height: int, min_tracks: int = 5) -> int:
    """Bottom 'add layer' working area; only reserved while it is visible."""
    return int(gap_height) if int(track_row_count) >= int(min_tracks) else 0


def bottom_anchor_pad(viewport_h: int, rows_h: int, bottom_gap: int, min_pad: int = 0) -> int:
    """Empty space above the layer stack so it sits at the bottom (CapCut style).

    When the stack is shorter than the viewport the spare height goes above the
    top layer; once the stack is taller than the viewport the pad is just
    ``min_pad`` and the timeline scrolls normally.
    """
    return max(int(min_pad), int(viewport_h) - int(rows_h) - int(bottom_gap))


def symmetric_outer_gap(viewport_height: int, rows_height: int, base_gap: int) -> int:
    """Compute an equal top/bottom gap around a track stack.

    If the stack is short, the two gaps expand evenly to use the viewport. If
    the stack overflows, each gap remains at ``base_gap`` and scrolling handles
    the excess content. This helper is pure so geometry can be regression-tested
    without creating Qt widgets.
    """
    viewport_height = max(0, int(viewport_height))
    rows_height = max(0, int(rows_height))
    base_gap = max(0, int(base_gap))
    return max(base_gap, (viewport_height - rows_height) // 2)
