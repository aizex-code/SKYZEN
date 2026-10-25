# Third-party license audit before public release

Skyzen contains a `docs/concat_reference/` tree and depends on external software such as
PySide6 and FFmpeg. The repository-level Skyzen Community Non-Commercial License does
not override licenses attached to third-party code, libraries, codecs, fonts, images,
icons, or other assets.

Before publishing a public GitHub release:

- Identify the original source and license for every file in `docs/concat_reference/`.
- Preserve upstream copyright notices and license files.
- Confirm the applicable license allows the intended redistribution and is compatible
  with Skyzen's distribution terms. If it is not, remove the material or replace it
  with a link/reference and document that decision.
- Record third-party packages and their licenses in a maintained dependency notice.
- Verify FFmpeg build/codec licensing and distribution obligations for the exact build
  shipped, if any. Skyzen currently instructs users to install FFmpeg separately.
- Check fonts, icons, example media, and screenshots for redistribution permission.

**Status:** This is a checklist, not a completed legal audit. Do not claim that all
third-party material has been cleared until each item has been reviewed.
