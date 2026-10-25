SKYZEN V17 — STARTUP FIX + STABLE COMPOSITE PLAYBACK
====================================================

STARTUP FIX
-----------
The v16 crash log showed:
  NameError: name 'Qt' is not defined
in app/main_window/main.py while installing timeline shortcuts.

V17 imports Qt from PySide6.QtCore. A regression test now verifies that the
shortcut installer imports the Qt symbols it uses, so this exact crash is
caught before packaging.

PLAYBACK DESIGN
---------------
- Selecting media or timeline clips does not start playback.
- Play/Pause button and Space are explicit playback commands.
- Project playback builds a low-resolution composite in a background worker,
  then plays one MP4 through one Qt media player. Visible video/image layers
  and the chosen audio tracks therefore share one playback clock.
- Paused scrubbing renders a single frame in the background.
- The separate UI modules remain in app/ui/editor_layout.py and app/ui/theme.py.

WINDOWS SETUP
-------------
1. Install Python 3.10 or newer.
2. Run: python -m pip install -r requirements.txt
3. Ensure FFmpeg and FFprobe are on PATH or in the project's ffmpeg folder.
4. Run run.bat.

VERIFICATION
------------
- 31 automated tests passed.
- Python compilation passed.
- FFmpeg integration smoke test rendered overlapping video layers plus a
  dedicated audio track into a valid MP4 with video and audio streams.
- The Qt GUI itself could not be launched in the build environment because
  PySide6 is not installed there. Please verify the actual Windows launch and
  playback before replacing your previous project folder.
