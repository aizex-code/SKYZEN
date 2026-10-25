"""Generate small valid transparent source files for non-media timeline objects."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage


def transparent_tool_asset(root_dir, tool_type, preset_id):
    folder = Path(root_dir) / "cache" / "tool_assets"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{str(tool_type).lower()}_{preset_id}.png"
    if not path.is_file() or path.stat().st_size < 60:
        image = QImage(1280, 720, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        image.save(str(path), "PNG")
    return path
