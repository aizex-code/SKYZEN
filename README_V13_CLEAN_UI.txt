Skyzen v13 — Clean Basic UI
===========================

This version deliberately keeps the scope small: media import, a clean player,
a compact timeline, clip selection, trim/split/delete, and synchronized layer
controls. No new effects, transitions, animation, or color tools were added.

Timeline cleanup
----------------
- Empty saved overlay/audio tracks are hidden from the visible timeline; their
  project data is preserved. A track appears when it contains a clip.
- Decorative OVERLAYS/AUDIO section bars and insertion-gap rows are removed.
- Up to four occupied overlay tracks are arranged directly above the pinned
  Main lane. Main is centered when there are no occupied overlays, moves down
  with one or two overlays, and stays near the bottom with three or more.
- For larger stacks, tracks scroll normally while Main remains pinned; the
  layer controls and timeline share the same vertical scroll coordinator.
- The empty top drop area is removed and the gap beneath Main is reduced.

Player cleanup
--------------
- Removed the non-functional Ratio and Fit buttons.
- Kept only the time display, Play/Pause, and Fullscreen controls.
- The live composite shows a subtle "No clip at playhead" message when no
  visual clip is active, rather than an unexplained empty black canvas.

Run
---
Run run.bat on Windows with the dependencies in requirements.txt installed.
The build environment used for this archive does not have PySide6, so the
actual Windows GUI layout and media playback still need to be checked locally.

Validation
----------
All Python files compile with compileall. All 16 automated tests pass.
