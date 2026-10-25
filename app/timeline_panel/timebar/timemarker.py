from __future__ import annotations


def set_preview_marker(timeline, seconds: float):
    if not timeline._concat_preview_axis:
        return
    target = timeline.snap_to_frame(max(0.0, float(seconds)), timeline.FPS)
    timeline.preview_time = target
    timeline._emit_active_clips(target, push_to_player=True)
    timeline._move_marker()


def apply(TimelinePanel):
    TimelinePanel.set_preview_marker = set_preview_marker
