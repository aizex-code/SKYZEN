SKYZEN V43 — V42-BASED SYMMETRIC TIMELINE GAP + VERTICAL METER

Base
----
Built from Skyzen_V42_Polish_Trim_Meter(4).zip.

Implemented
-----------
1. Symmetric timeline workspace
   - Equal outer gaps above and below the track stack.
   - Minimum outer gap is 2 * TRACK_HEIGHT + 12 (112 px at the current 50 px row height).
   - Short stacks distribute extra free height evenly above/below.
   - The bottom drop area is visible even for a one-track project.
   - The geometry continues to use the shared row-layout model.

2. Vertical FL-Studio-inspired dB meter
   - Vertical dB scale, green/yellow/red segments, peak hold and smooth release.
   - The meter's playing-state check reads the multitrack engine state directly
     instead of relying only on the toolbar glyph.
   - Source peak envelopes are lazily decoded with FFmpeg and the current
     timeline playhead is sampled on the meter timer.
   - This is a source-envelope estimate of project output, not a hardware loopback
     meter or post-effects sample-accurate meter. The current cache is mono, so
     both narrow columns show the same level.

3. Player control arrangement
   - Meter, timecode, play/pause, preview ratio preference selector, fullscreen.
   - The ratio selector currently records a preview preference and keeps the
     native video surface in KeepAspectRatio mode; exact fixed-ratio canvas
     framing still requires a dedicated preview-container implementation.

Safety
------
These V42 files are byte-identical to the source archive:
- app/timeline_panel/alignment.py
- app/player_panel/multitrack_engine.py
- app/video_engine/controller.py
- app/video_engine/ffmpeg_backend.py

Not implemented in this build
-----------------------------
The main track is still part of the normal shared scroll stack. The requested
scroll-direction-dependent sticky main-lane behavior (center while scrolling up,
bottom while scrolling down, overlays passing behind it) is not implemented here;
implementing it safely requires a coordinated display/hit-test mapping across
all three timeline columns. It was intentionally not approximated with separate
scrollbars because that would risk reintroducing the synchronization bug.

Validation
----------
- Python compileall passed.
- Relevant targeted tests: 45 passed.
- Full suite still has two pre-existing source-contract test failures in
  test_live_playback_contract.py and test_v24_inspector_workflow.py; those files
  were not modified. The V42 baseline already contains those mismatches.
- PySide6 is not installed in this environment, so no live Windows GUI test was
  possible. Test in a separate extracted folder and keep V42 as backup.
