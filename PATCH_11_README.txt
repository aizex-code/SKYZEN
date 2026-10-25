SKYZEN V43 — PATCH 11
=====================

Start from this extracted folder; do not merge it over your Patch 10 folder.
Keep Patch 10 as a rollback copy.

PATCH 11 CHANGES
----------------
- Restores the full timeline toolbar and adds Keyframe Curve beside the existing edit actions.
- Keeps a draggable speed graph visible under the Playback Rate field.
- Supports custom Bezier easing between selected keyframe pairs.
- Enables keyframes for scale, X/Y/Z position, rotation, opacity, and supported color grading.
- Improves layer visibility glyph, left tool strip sizing, and media thumbnail height.

HOW TO TEST
-----------
1. Launch main.py using the same Python environment that already runs Skyzen.
2. Check Undo, Redo, Crop, Frame Peek, Split, Delete, Trim Left, Trim Right, and Zoom.
3. Select a video, open Speed, drag one of the speed graph points, then preview and export.
4. Add two keyframes to Brightness or Scale at different times.
5. Put the playhead between the keys, select Keyframe Curve, and change the easing.
6. Scrub, play, save/reopen, trim, split, and export.
7. Verify the layer visibility icon toggles hide/show correctly.

VALIDATION
----------
143 tests passed, 3 skipped. Python compilation and a real FFmpeg animated transform/opacity/grading smoke render passed.

LIMITATION
----------
The patch environment does not have PySide6, so the live Windows GUI has not been launched here. Verify the UI on your PC before replacing the previous working folder. Speed-curve audio still follows average speed.
