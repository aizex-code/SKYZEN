SKYZEN V23 — INSPECTOR PREVIEW FIXES
====================================

- Removed the visible animated cyan progress strip beneath the player.
- Play no longer replaces the preview with the full-panel "Preparing smooth
  timeline playback" message. The last good frame remains visible while the
  project composite is prepared.
- Failed project renders keep the last frame visible; diagnostics are retained
  in the controller log and message tooltip.
- Inspector edits no longer silently swallow errors from the timeline preview
  update call.
- Added regression tests for selection signal wiring and preview UI behavior.

The four-argument `clip_selected` emission in V22 was already aligned with its
declared Qt signal; this build preserves it and adds a regression test.
