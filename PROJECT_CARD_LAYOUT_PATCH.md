# Project card layout patch

- Reduced project tiles to a compact 184 × 142 px card.
- Kept project names visible beneath each preview, with tooltips for long names.
- Added stable serial numbers to make the project grid easier to scan.
- Arranged projects left-to-right, then top-to-bottom, in a responsive grid.
- Added **Duplicate Project** to the project actions menu. The duplicate copies the saved project folder/state, chooses a unique `(Copy)` name, and refreshes its metadata.
- Existing project opening, renaming, Trash Bin, and settings actions remain in place.

Verification: `project_manager/project_win.py` passes Python bytecode compilation. GUI interactions still require testing on Windows with PySide6 installed.
