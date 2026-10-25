"""Compatibility adapter for Skyzen's synchronized project-preview controller.

Project playback is rendered as one low-resolution composite by FFmpeg in a
background QThread, then played through one QMediaPlayer. This gives all visual
layers and the mixed audio one media clock. Paused scrubbing renders a single
frame. The old per-clip QVideoSink engine is not attached to this path.
"""
try:
    from PySide6.QtMultimedia import QMediaPlayer  # noqa: F401
    QT_MULTITRACK_AVAILABLE = True
except Exception:
    QT_MULTITRACK_AVAILABLE = False

from app.video_engine.controller import ProjectPreviewController


class MultitrackPlaybackEngine(ProjectPreviewController):
    """Backward-compatible name used by the existing PlayerPanel API."""

    pass
