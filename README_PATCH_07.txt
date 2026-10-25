SKYZEN V43 — PATCH 07: REAL TOOL LAYERS

INSTALL
1. Keep your Patch 05 folder as a backup.
2. Extract this ZIP to a new folder.
3. Run run.bat as usual.
4. Do not copy individual .py files into the old folder; use the complete release folder so modules stay aligned.

WHAT TO CHECK FIRST
1. Confirm Media and Audio still open and import works.
2. Click Text. Use the + on Basic title. The playhead should get a purple half-height text lane and the title should appear in the player.
3. Select the title clip. Edit its text, size and color in the inspector; wait briefly for the preview to refresh.
4. Drag a text preset card onto an existing overlay lane. It should create/place the typed clip at the drop time.
5. Click Effects, add Warm film or Vignette, and play/scrub across the effect's time range. It should affect visual layers beneath it only while the effect clip is active.
6. Click Adjustments, add Project adjustment, then adjust Contrast or Saturation in the Adjustment inspector tab. It should affect the whole composite. Add Local adjustment to affect visual layers beneath its lane.
7. Check that typed rows are about half the height of normal overlays and match their toolbar colors.
8. Finally re-test ordinary video drop, music drop below Main, trim left/right/back, playback, undo/redo and export.

IMPORTANT LIMITATIONS
- The patching environment does not have PySide6, so the actual Windows GUI has not been launched here.
- Text controls currently cover content, font size and color; font family, alignment editing, outline/shadow and animation are future upgrades.
- The first Effects library includes six FFmpeg-backed effects; this is a foundation, not a complete commercial effects catalog.
- Adjustment layers support basic grading (brightness, contrast, saturation, gamma, temperature and tint); HSL, curves and LUTs remain future work.
- The baseline project does not provide a complete save/reopen project-file workflow. Tool metadata is stored in the same in-memory clip/track dictionaries as existing clips, but persistence must be verified when a project-file system is added.

VERIFICATION
- Python compilation: passed.
- Automated suite: 126 passed, 3 skipped.
- FFmpeg project-render smoke test: passed for all six effect presets with a whole-project adjustment.
- FFmpeg single-frame preview smoke test: passed.
- GUI verification: pending user test on Windows/PySide6.
