SKYZEN V27 — BASIC EDITOR RELEASE CANDIDATE
============================================

This build continues the existing Skyzen/PySide6/FFmpeg architecture. It is
optimized for a CPU-only or low-end PC by default and adds selectable preview
quality, safe chroma-key rendering, and functional crop controls.

START
-----
1. Extract this ZIP into its own folder.
2. Keep your previous V26 folder as a backup.
3. Run run.bat (launches without a terminal window).
4. Import a video, add it to the timeline, select the clip, then use Inspector.
5. Menu > Preview Quality changes the edit-preview trade-off.

PREVIEW QUALITY
---------------
Performance (default)
  640x360 composite, 640x360 proxy, ultrafast H.264. Recommended for low-end
  CPUs and the smoothest basic editing experience.

Balanced
  854x480 composite and proxies. Clearer preview with a moderate increase in
  CPU work and proxy disk space.

Clear
  1280x720 composite using original source media instead of 360p proxies.
  This is the clearest preview but can be substantially slower on older CPUs.
  Switch back to Performance while doing complex edits if needed.

These settings affect disposable preview renders only. They do not change the
project's output dimensions or the export dialog's quality settings. Profile
changes use separate cache IDs and proxy markers so stale low-resolution media
cannot be mistaken for a high-quality proxy.

CORE FEATURES IN THIS BUILD
---------------------------
- Existing modular media browser, preview/player, timeline, inspector and
  export architecture retained.
- Background proxy creation is serialized to avoid saturating low-end CPUs.
- Synchronized multitrack video composition and audio mixing through a single
  FFmpeg composite playback file.
- Inspector settings update the selected clip only.
- Scale, X/Y/Z position, rotation, opacity and basic color grading.
- Crop left/top/right/bottom, applied to preview and export render graphs.
- Chroma key with color sampling, similarity, edge blend and foreground alpha.
- Trim L / Trim R, split, delete, undo/redo and existing timeline behavior.
- Performance/Balanced/Clear preview profiles.
- Original sources remain unmodified; proxies are disposable cached copies.

CHROMA KEY FIX
--------------
FFmpeg's colorkey filter rejects similarity=0 because its minimum is 0.00001.
The previous build could therefore fail the whole preview render when the
tolerance slider was at zero. V27 clamps this parameter to the valid FFmpeg
range and validates malformed values. The preview cache profile is versioned
to avoid reusing an old failed render.

REFERENCE IMPLEMENTATION NOTES
------------------------------
OpenCut and Concat were reviewed as architecture references, not copied into
Skyzen as a wholesale source merge. OpenCut's command-oriented edit operations,
selection-aware property panels and timeline separation informed the workflow.
Concat's explicit bottom-to-top layer ordering, per-frame render planning and
single compositor contract informed the preview pipeline. Skyzen remains a
Python/PySide6 application using FFmpeg, rather than the Rust/WGPU or web stack
used by those projects.

NOT YET CLAIMED AS IMPLEMENTED
------------------------------
This is a polished basic-editing foundation, not a pixel-for-pixel clone of
every OpenCut/Concat feature. Advanced alpha-correct blend modes, full masks,
keyframes, HSL/curve grading, speed ramps, reverse, HDR/linear-light GPU
compositing, scopes and a GPU-native real-time compositor remain future engine
work. Speed and AI tabs are intentionally reserved rather than fake controls.
Export uses the selected export settings and is separate from preview quality.

VALIDATION
----------
- Python compilation: passed.
- Automated tests: 80 passed, 3 skipped (GUI tests require PySide6, which was
  unavailable in the build environment).
- FFmpeg integration regression: renders a synthetic green-screen source with
  zero requested tolerance and crop enabled; verifies successful video output.
- Full Windows GUI interaction cannot be launched from this build environment;
  the final smoke test should be performed on the target PC.


V28 UI REFINEMENT PASS
----------------------
See CHANGELOG_V28_UI_REFINEMENT.txt and editing.txt for the added Layers
view selector, Crop toolbar shortcut, Frame Peek toggle, inspector space
reduction, image-thumbnail detection improvement, and known limitations.
