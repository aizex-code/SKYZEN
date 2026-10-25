# Skyzen project history

This file summarizes the development trail present in this repository. The detailed
historical patch notes are retained as context; they should not be read as proof that
every intermediate build was stable or released publicly.

## Development phases

1. **Initial editor foundation** — modular Python/PySide6 UI, media import, player
   preview, inspector, and a multitrack timeline.
2. **Timeline refinement** — iterative work on clip placement, trimming, track
   geometry, overlay spacing, scroll coordination, snapping, and drag/drop behavior.
3. **Playback and audio work** — composite preview rendering, synchronization,
   audio mixing, caching, proxy generation, and playback stability regressions.
4. **Inspector and creative tools** — transform controls, crop workflows, color
   adjustments, chroma-key work, and export UI refinement.
5. **Project manager integration** — the project library became the startup screen,
   adding project creation, reopening, renaming, Trash Bin handling, and saved project
   state.
6. **Community preparation** — documentation, contribution guidance, privacy notes,
   a non-commercial license, and a folder-level Skyzen footprint were added for
   collaborative development.

## How to trace changes

Review the repository commit history once published to GitHub. Existing files named
`CHANGELOG_*`, `PATCH_*`, `README_*`, and `SKYZEN_VERIFIED_FIX_HISTORY_*` record
historical intentions and fixes from development. New changes should be committed in
small, descriptive commits, for example:

- `docs: add community license and contribution guide`
- `fix: restore project state after reopening`
- `test: cover trash restore collision handling`

Do not rewrite history to make unverified claims. Add a dated entry to this document
when a meaningful milestone is completed and tested.
