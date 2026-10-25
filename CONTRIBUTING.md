# Contributing to Skyzen

Thank you for helping make Skyzen better. Contributions can include code, tests,
bug reports, accessibility feedback, documentation, translations, and reproducible
performance reports.

## Before you start

1. Read `LICENSE.md`. Contributions and redistributed versions must respect the
   Skyzen Community Non-Commercial License.
2. Search existing issues before opening a duplicate.
3. For larger changes, open an issue first so the direction can be discussed.
4. Do not submit private media, credentials, personal data, or assets you do not
   have permission to redistribute.

## Development setup

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Install FFmpeg and FFprobe separately and verify both are available on `PATH`.

## Pull request checklist

- Keep changes focused and avoid unrelated UI rewrites.
- Preserve the modular separation between project manager, panels, timeline, player,
  inspector, export, and video-engine code.
- Add or update regression tests for behavior changes when practical.
- Run `python -m unittest discover -s tests -t .`.
- Test on Windows with representative video, audio, and image files when the change
  affects playback, import, timeline behavior, or export.
- Describe what changed, why it changed, what you tested, and known limitations.
- Never include `.venv`, caches, local project media, user project folders, crash logs,
  or generated export files in a pull request.

## Reporting bugs

Include the Skyzen version/commit, Windows and Python versions, steps to reproduce,
expected behavior, actual behavior, and a sanitized traceback if available. Do not
share personal paths or media unless you have intentionally redacted them.

## Contributor recognition

Contributors are credited based on documented contributions. BRONVEIL and S7XIAN are
listed in the project README as community/creative supporters at the project's request;
specific code authorship should be attributed only where it is documented.
