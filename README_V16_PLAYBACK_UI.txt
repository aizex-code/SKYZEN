SKYZEN V17 — STARTUP HOTFIX + PLAYBACK CORE
================================

What changed
------------
- Fixed the startup crash by importing Qt in app/main_window/main.py. The previous
  build called Qt.FocusPolicy.StrongFocus before Qt was defined.
- Added startup regression tests for the shortcut setup and modular UI integration.
- Selecting media no longer starts playback automatically. Use Play/Pause or Space.
- Multi-track preview merges all visible video/image layers into one FFmpeg output.
  Clips are positioned on the project timeline before compositing, so clips starting
  later than zero appear at the correct time.
- If an optional proxy is not yet available, preview uses the original file.
- The workspace layout is separated into app/ui/editor_layout.py; common styling is
  app/ui/theme.py. The workspace keeps the screenshot-inspired layout: media/tools
  on the left, preview in the center, details on the right, and timeline underneath.
- Preview cache version was bumped to prevent old incorrectly composited videos
  from being reused.

Run
---
Use run.bat on Windows. Install requirements from requirements.txt if needed.
Keep the ffmpeg folder beside the project or ensure ffmpeg and ffprobe are on PATH.

Important
---------
This build was validated with Python tests and an FFmpeg synthetic overlap test.
The Qt desktop UI could not be launched in the build environment because PySide6
is unavailable here. Please test on Windows with one clip, then two overlapping
clips, and pause/resume after seeking.
