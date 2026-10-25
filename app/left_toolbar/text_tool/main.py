"""Text preset rendering helpers. The output is a real transparent PNG clip."""
from pathlib import Path
import hashlib
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QFontMetrics, QPen


def render_text_asset(root_dir, preset, text=None, font_size=None, color=None):
    root = Path(root_dir)
    text = str(text if text is not None else preset.get("text", "Your title"))
    size = max(12, min(220, int(font_size if font_size is not None else preset.get("font_size", 72))))
    color = str(color or preset.get("color", "#FFFFFF"))
    key = hashlib.sha1(f'{preset.get("id")}\0{text}\0{size}\0{color}\0{preset.get("bold")}'.encode("utf-8")).hexdigest()[:16]
    folder = root / "cache" / "tool_assets"
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / f"text_{key}.png"
    if output.is_file() and output.stat().st_size > 100:
        return output
    image = QImage(1280, 720, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    font = QFont("Segoe UI", size)
    font.setBold(bool(preset.get("bold", False)))
    painter.setFont(font)
    lines = text.splitlines() or [""]
    metrics = QFontMetrics(font)
    line_height = max(metrics.height(), int(size * 1.15))
    total_height = line_height * len(lines)
    center_y = int(720 * float(preset.get("y", 0.5)))
    top = center_y - total_height // 2
    alignment = str(preset.get("align", "center"))
    if alignment == "left":
        rect = QRectF(92, top, 1096, total_height + 8)
        flags = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    elif alignment == "right":
        rect = QRectF(92, top, 1096, total_height + 8)
        flags = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    else:
        rect = QRectF(72, top, 1136, total_height + 8)
        flags = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
    # Subtle dark outline/shadow keeps white text readable on footage.
    painter.setPen(QPen(QColor(0, 0, 0, 190), max(2, size // 18)))
    painter.drawText(rect.translated(2, 3), flags, text)
    painter.setPen(QColor(color))
    painter.drawText(rect, flags, text)
    painter.end()
    image.save(str(output), "PNG")
    return output
