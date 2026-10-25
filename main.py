from __future__ import annotations

import faulthandler
import sys
import traceback
from pathlib import Path
from PySide6.QtWidgets import QApplication
from project_manager.project_win import ProjectWindow


def _install_crash_logging(log_path: Path):
    log_file = log_path.open("a", encoding="utf-8", buffering=1)
    faulthandler.enable(log_file, all_threads=True)
    def _hook(exc_type, exc_value, exc_tb):
        log_file.write("\n\n=== Skyzen uncaught Python exception ===\n")
        traceback.print_exception(exc_type, exc_value, exc_tb, file=log_file)
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    sys.excepthook = _hook
    return log_file


def main() -> int:
    editor_root = Path(__file__).resolve().parent
    _crash_log = _install_crash_logging(editor_root / "skyzen-crash.log")
    app = QApplication(sys.argv)
    app.setApplicationName("Skyzen")
    app.setApplicationDisplayName("Skyzen Editor")
    app.setOrganizationName("Skyzen")
    # Prevent Qt from exiting when the editor window closes while the project
    # window is temporarily hidden. The app should only quit when the project
    # window itself is closed.
    app.setQuitOnLastWindowClosed(False)
    window = ProjectWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
