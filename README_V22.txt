SKYZEN V22 QUICK NOTES
======================

Use the existing Windows setup:
  python -m pip install -r requirements.txt
  run.bat

New in V22:
- Centre-zero sliders and numeric spinboxes for transform controls.
- Scale has 100% at centre; left zooms out, right zooms in.
- Position and rotation are symmetric around zero.
- Expanded grading: gamma, hue, temperature, tint, highlights, shadows, vibrance.
- Paused preview keeps the previous good image visible while a new frame renders.
- Frame cache invalidation includes edit signatures to prevent stale frames.
- Project preview prefetch waits 700 ms after edits settle.

Validation:
- 49 unittest regression tests passed.
- All Python files compiled.
- FFmpeg still-frame render smoke test passed with extended grading.
- GUI not launched in this build environment because PySide6 is unavailable;
  verify interaction and performance on Windows.
