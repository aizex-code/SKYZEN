SKYZEN V18 — STABLE MULTITRACK
==============================

This build is based on the supplied v17 Skyzen project and the supplied Concat
source archive, using the screenshot as the workspace reference.

Changes:
- Removed the unused per-clip live-decoder engine from the active project
  controller. One controller now owns the composite QMediaPlayer playback path.
- Pause preserves a valid composite frame and avoids scheduling an unnecessary
  still-render job that could conflict with an immediate Play.
- FFmpeg preview transforms now scale position offsets from 1280x720 project
  coordinates to the actual preview/export resolution.
- Reworked the shared palette toward the screenshot's neutral charcoal panels
  and cyan accent; retained left/player/inspector/timeline resizable structure.
- Isolated the proxy-cache test in its own temporary directory, so tests do not
  mutate a shared system temp cache.
- Added regression coverage for playback ownership, Pause behavior, fullscreen
  play-state preservation, transform scaling, and proxy cache identity.
- Added docs/CONCAT_ARCHITECTURE_NOTES.md describing the source files reviewed
  and how their timeline/compositor principles map into Skyzen.

Verification:
- 36 automated tests passed.
- Python compileall passed.
- FFmpeg integration smoke test rendered a 640x360 composite with both video
  and audio streams, plus a paused still frame.
- Qt GUI launch/playback cannot be verified in this environment because
  PySide6 is not installed. Do not treat source-level/FFmpeg tests as proof of
  a successful Windows GUI run.
