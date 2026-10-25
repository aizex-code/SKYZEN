"""Regression tests for previously observed application startup crashes."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def imported_names(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
    return names


class StartupRegressionTests(unittest.TestCase):
    def test_main_window_imports_qt_used_by_shortcut_setup(self):
        path = ROOT / "app" / "main_window" / "main.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = imported_names(tree)
        self.assertIn("Qt", names, "main_window uses Qt.FocusPolicy and Qt.ShortcutContext")
        self.assertIn("QShortcut", names)
        self.assertIn("QKeySequence", names)

    def test_shortcut_setup_uses_explicit_space_play_pause(self):
        path = ROOT / "app" / "main_window" / "main.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "EditorMainWindow")
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_install_shortcuts")
        text = ast.get_source_segment(path.read_text(encoding="utf-8"), method) or ""
        self.assertIn('("Space", self.player.toggle_play)', text)
        self.assertIn("Qt.ShortcutContext.WidgetWithChildrenShortcut", text)

    def test_ui_folder_is_part_of_main_window_integration(self):
        path = ROOT / "app" / "main_window" / "main.py"
        source = path.read_text(encoding="utf-8")
        self.assertIn("from app.ui.editor_layout import build_editor_layout", source)
        self.assertIn("from app.ui.theme import STYLE", source)


if __name__ == "__main__":
    unittest.main()
