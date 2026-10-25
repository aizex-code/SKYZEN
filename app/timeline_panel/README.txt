SKYZEN TIMELINE PANEL — BASIC EDITING SCOPE
===========================================

Responsibilities
----------------
The timeline owns editable tracks, clip positions, source in-points, duration,
selection, playhead, trimming, splitting, deleting, drag/drop, and undo/redo.
It does not create video decoders. The existing public signals and methods are
kept compatible with PlayerPanel.

Playback handoff
----------------
On edits or playhead changes, TimelinePanel publishes the active stack. The
compatibility adapter in app/player_panel/multitrack_engine.py asks
app/video_engine/controller.py to refresh the project snapshot. FFmpeg renders
a still frame while paused or a single composite preview file for playback.

Included
--------
- Main video lane and additional video overlay lanes.
- Separate audio lanes.
- Timeline thumbnails and audio waveforms where available.
- Clip drag/arrange, trim handles, split, delete, duplicate/copy/cut, and undo/redo.
- Track lock/hide/mute and layer deletion.
- Synchronized vertical scrolling for track labels and track content.
- Toolbar actions and zoom.

Not implemented in this basic stage
-----------------------------------
Effects, transitions, text, keyframes, color grading, reverse/freeze, and GPU
AI tools. Export currently supports codec/resolution presets via app/export.

Validation
----------
The FFmpeg command builder has been exercised against generated sample media.
Qt GUI, QMediaPlayer display, and Windows drag/drop still need a local smoke
test because PySide6 is unavailable in the source-validation environment.
