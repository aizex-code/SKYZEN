# Repository release checklist

Use this checklist before creating a public GitHub release.

- [ ] Confirm the app starts on a clean Windows account with Python 3.10+.
- [ ] Run `setup.bat`, then test `run.bat`, `silent.vbs`, and `run_debug.bat`.
- [ ] Verify project creation, save, reopen, rename, Trash Bin, restore, and permanent delete.
- [ ] Test media import, preview playback, timeline edits, and export with test media.
- [ ] Run `python -m unittest discover -s tests -t .`.
- [ ] Confirm `.venv`, caches, crash logs, local projects, media, and exports are not committed.
- [ ] Install FFmpeg/FFprobe separately and document the exact version used for release testing.
- [ ] Complete the third-party audit in `THIRD_PARTY_AUDIT.md`; preserve upstream licenses and notices.
- [ ] Review all files under `docs/concat_reference/` and their AGPL-3.0-or-later notices before adapting or redistributing derived work.
- [ ] Confirm `LICENSE.md`, `PRIVACY.md`, `SECURITY.md`, and `CONTRIBUTING.md` are present.
- [ ] Inspect the final GitHub diff for credentials, personal paths, private media, or other user data.
- [ ] Describe known limitations honestly in the release notes.

A checked checklist records that a task was completed; it is not a legal certification or a guarantee of bug-free behavior.
