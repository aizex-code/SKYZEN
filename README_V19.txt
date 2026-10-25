SKYZEN V19 — AUDIO LAYER + SCROLL FIX
=====================================

This build starts from the supplied v18 project and keeps the existing
CapCut-inspired layout and one-player composite playback architecture.

KEY FIXES
---------
- Root cause of silent overlay audio fixed: embedded audio from every unmuted
  video layer is now included in the composite mix, not only the main track.
- Track mute and Volume… controls are honored by the project render snapshot.
- Audio mix uses a limiter to reduce clipping when several layer soundtracks
  overlap.
- Layer controls forward wheel events to the shared scroll coordinator.
- Tall timelines have a larger bottom drop zone for creating a new layer.
- Fast 640×360 video proxies are enabled by default, created in the background
  on import/current timeline media, and preserve audio.
- A debounced composite pre-render starts after edits settle to reduce waiting
  after pressing Play.
- Old proxy and preview caches are invalidated by versioned profile markers.

RUN
---
1. Extract this archive into a new folder.
2. Install dependencies: python -m pip install -r requirements.txt
3. Ensure ffmpeg and ffprobe are on PATH or in the project's ffmpeg folder.
4. Run run.bat.

VERIFY
------
41 automated tests passed, Python compilation passed, and a real FFmpeg
integration smoke test produced a valid H.264/AAC composite with overlapping
video layers and non-silent audio.

The Qt GUI could not be launched in the build environment because PySide6 is
not installed there. Verify the Windows UI, layer scrolling, audio, and Play /
Pause behavior before replacing your previous folder. Keep v18 as a backup.
