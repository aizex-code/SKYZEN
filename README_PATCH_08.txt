SKYZEN V43 — PATCH 08
CAPCUT-INSPIRED TOOL LIBRARIES + OVERLAY DROP SAFETY

INSTALL
1. Keep your current Patch 07 folder unchanged as a backup.
2. Extract this complete ZIP into a new folder.
3. Launch using the included run.bat as usual.
4. Do not copy isolated Python files into the old folder.

WHAT CHANGED
- Preset cards are smaller and more like a compact editor asset library.
- The card grid adapts to panel width: normally 2 columns, and 3 columns when there is enough space.
- Thumbnail previews scale to the card instead of forcing a wide card.
- Each card keeps its + button and drag-and-drop behavior.
- Text, Effects and Adjustments dropped over Main are created as typed overlay layers; Main itself remains a normal video layer.
- Timeline row gaps use a darker background and a restrained hover highlight.
- Typed layers continue to use the shared half-height row policy.

CHECK FIRST
1. Open each tool library and inspect card sizing.
2. Click + and drag a preset to an overlay lane.
3. Drag a preset over Main and confirm it creates a separate typed overlay.
4. Confirm the gap hover effect is subtle.
5. Re-test media import, music drop, trimming, playback, undo/redo and export.

VALIDATION
- Python compileall for app/: passed.
- GUI test: pending; PySide6 is unavailable in the patching environment.
- Full automated suite: not run for this patch.

Next planned work after this visual/drop fix is confirmed: Speed settings, then keyframes and graph editing.
