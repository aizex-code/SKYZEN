Skyzen V25 — Responsive Multitrack Preview & Inspector Repair
=============================================================

This build continues the modular V23/V24 Skyzen project and keeps the existing
timeline, media bin, player panel, FFmpeg backend, proxy service, export flow,
and concat-reference documentation.

Main repairs
------------
1. Fixed a real inspector selection failure: the selection loader referenced
   name_label/path_label without creating those widgets. Selecting a clip could
   therefore abort before populating the controls.
2. Inspector now shows a compact selected-clip information row, hides itself
   behind a "Nothing selected" state when the selection is cleared, and changes
   the visible properties according to media type.
3. Basic tab has transform controls plus per-clip volume and mute for video/audio.
   Per-clip volume is combined with track volume and is included in render
   fingerprints, so edits invalidate the correct preview.
4. Slider drags request bounded preview refreshes; obsolete full-project renders
   are cancelled so they cannot block the latest adjustment for several seconds.
5. During playback, the last valid composite keeps playing while a revised
   composite is prepared in the background. The updated composite replaces it
   at the latest playhead time when ready.
6. FFmpeg's compositor skips neutral grading and rotation filters. The preview
   cache namespace was bumped so old preview renders are not reused.
7. Trim L now removes the selected clip's left portion up to the playhead, and
   Trim R removes the right portion from the playhead onward. Source in-points
   are updated for left trims. Frame-domain trim math is isolated in
   app/timeline_trim_math.py.
8. Reduced workspace margins and improved splitter sizing. The left, preview,
   inspector, and timeline remain resizable.
9. The GUI launcher continues to use pythonw through the hidden VBS launcher.

Inspector tabs
--------------
Basic      Transform, clip volume/mute, and clearly marked future compositing,
           mask/chroma-key and clip-action sections.
Adjustment Color grading controls.
Speed      Reserved until timeline retiming and audio pitch/time handling are
           connected.
AI Tools   Reserved for your later AI integrations.

Playback and audio notes
------------------------
The project preview is rendered as one low-resolution composite MP4. All active
video layers are composited according to their stacking order; embedded audio
from unmuted video clips and dedicated audio-track clips are mixed into the same
preview file. Sources without an audio stream cannot produce sound. The source
video itself is not modified.

The first render after a project change can still take time on a modest CPU.
This build cancels obsolete work and keeps playback running while a replacement
composite is generated, but it does not replace FFmpeg with a GPU-native live
compositor.

Testing
-------
- Python compilation passed.
- 65+ automated tests cover preview command generation, audio mixing, snapshots,
  inspector workflow, filter optimization, and frame-domain trim math.
- Three timeline GUI tests are skipped in environments without PySide6.
- Synthetic FFmpeg validation produced both video and audio streams from two
  overlapping videos and mixed their audio.

Run run.bat as usual. Keep V24 as a backup until this build has been tested on
your Windows machine.
