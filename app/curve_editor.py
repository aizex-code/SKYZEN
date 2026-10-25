"""Reusable compact curve canvas for clip speed and keyframe easing."""
from __future__ import annotations

from PySide6.QtCore import Qt, QPointF, Signal
from PySide6.QtGui import QPainter, QPen, QBrush, QPainterPath
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QWidget, QSizePolicy
)


def _preset_points(name):
    # X handles are fixed at one-third/two-thirds so the displayed curve and
    # the runtime cubic interpolation use the same parameterization.
    presets = {
        "Linear": [{"x":0.0,"y":0.0},{"x":1/3,"y":1/3},{"x":2/3,"y":2/3},{"x":1.0,"y":1.0}],
        "Ease in": [{"x":0.0,"y":0.0},{"x":1/3,"y":0.0},{"x":2/3,"y":0.0},{"x":1.0,"y":1.0}],
        "Ease out": [{"x":0.0,"y":0.0},{"x":1/3,"y":1.0},{"x":2/3,"y":1.0},{"x":1.0,"y":1.0}],
        "Ease in-out": [{"x":0.0,"y":0.0},{"x":1/3,"y":0.0},{"x":2/3,"y":1.0},{"x":1.0,"y":1.0}],
        "Hold": [{"x":0.0,"y":0.0},{"x":1/3,"y":0.0},{"x":2/3,"y":0.0},{"x":1.0,"y":1.0}],
    }
    return [dict(p) for p in presets.get(name, presets["Ease in-out"])]

class CurveCanvas(QWidget):
    curveChanged = Signal(object)

    def __init__(self, points=None, mode="ease", parent=None):
        super().__init__(parent)
        self.mode = mode
        self._points = [dict(p) for p in (points or [])]
        if mode == "speed" and not self._points:
            self._points = [{"x":0.0,"y":1.0},{"x":1.0,"y":1.0}]
        if mode == "ease" and len(self._points) != 4:
            self._points = _preset_points("Ease in-out")
        self.setMinimumSize(260, 160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self._drag_point = None

    def set_points(self, points):
        self._points = [dict(p) for p in (points or [])]
        if self.mode == "ease" and len(self._points) != 4:
            self._points = _preset_points("Ease in-out")
        if self.mode == "speed":
            self._points.sort(key=lambda q: float(q.get("x", 0)))
        self.update()

    def _rect(self):
        # Reserve room for the speed-axis labels; keep the graph inside narrow Inspector panels.
        return self.rect().adjusted(38 if self.mode == "speed" else 18, 14, -12, -22)

    def _to_point(self, item):
        r = self._rect()
        y = float(item.get("y", 0.5))
        if self.mode == "speed":
            y = (y - 0.5) / 4.5
        y = max(0.0, min(1.0, y))
        return QPointF(r.left() + float(item.get("x", 0.0)) * r.width(),
                       r.bottom() - y * r.height())

    def _ease_path(self):
        ordered = self._points
        path = QPainterPath(self._to_point(ordered[0]))
        path.cubicTo(self._to_point(ordered[1]), self._to_point(ordered[2]), self._to_point(ordered[3]))
        return path

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._rect()
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setPen(QPen(Qt.GlobalColor.darkGray, 1))
        for i in range(5):
            x = r.left() + r.width() * i / 4
            y = r.top() + r.height() * i / 4
            p.drawLine(int(x), r.top(), int(x), r.bottom())
            p.drawLine(r.left(), int(y), r.right(), int(y))
        if self.mode == "speed":
            p.setPen(QPen(Qt.GlobalColor.lightGray, 1))
            p.setFont(self.font())
            for i in range(5):
                speed_label = 5.0 - (4.5 * i / 4.0)
                label_y = r.top() + r.height() * i / 4.0
                p.drawText(1, int(label_y + 4), 33, 14, Qt.AlignmentFlag.AlignRight, f"{speed_label:.2g}×")
        p.setPen(QPen(Qt.GlobalColor.cyan, 2))
        if self.mode == "ease" and len(self._points) == 4:
            p.drawPath(self._ease_path())
            p.setPen(QPen(Qt.GlobalColor.gray, 1, Qt.PenStyle.DashLine))
            p.drawLine(self._to_point(self._points[0]), self._to_point(self._points[1]))
            p.drawLine(self._to_point(self._points[2]), self._to_point(self._points[3]))
        else:
            ordered = sorted(self._points, key=lambda q: float(q.get("x", 0)))
            for a, b in zip(ordered, ordered[1:]):
                p.drawLine(self._to_point(a), self._to_point(b))
        p.setBrush(QBrush(Qt.GlobalColor.white))
        p.setPen(QPen(Qt.GlobalColor.cyan, 1.5))
        for index, item in enumerate(self._points):
            if self.mode == "ease" and index in (0, 3):
                continue
            pt = self._to_point(item)
            p.drawEllipse(pt, 5, 5)
        if self.mode == "speed" and self._points:
            first = min(self._points, key=lambda q: float(q.get("x", 0.0)))
            pt = self._to_point(first)
            p.setPen(QPen(Qt.GlobalColor.white, 1))
            label = f"Start {float(first.get('y', 1.0)):.2f}×"
            label_x = min(max(40, int(pt.x() + 9)), max(40, self.width() - 88))
            label_y = min(max(14, int(pt.y() - 8)), max(14, self.height() - 4))
            p.drawText(label_x, label_y, label)
        p.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        candidates = [(i, self._to_point(point)) for i, point in enumerate(self._points)
                      if not (self.mode == "ease" and i in (0, 3))]
        if candidates:
            i, pt = min(candidates, key=lambda pair: (pair[1].x()-pos.x())**2 + (pair[1].y()-pos.y())**2)
            if (pt.x()-pos.x())**2 + (pt.y()-pos.y())**2 < 18**2:
                self._drag_point = self._points[i]
                return
        if self.mode == "speed":
            r = self._rect()
            x = max(0.0, min(1.0, (pos.x()-r.left()) / max(1, r.width())))
            y = max(0.5, min(5.0, 0.5 + (r.bottom()-pos.y()) / max(1, r.height()) * 4.5))
            point = {"x":x,"y":y}
            self._points.append(point)
            self._points.sort(key=lambda q: q["x"])
            self._drag_point = point
            self.update()

    def mouseMoveEvent(self, event):
        if self._drag_point is None:
            return
        r = self._rect()
        pos = event.position()
        x = max(0.0, min(1.0, (pos.x()-r.left()) / max(1, r.width())))
        if self.mode == "speed":
            y = max(0.5, min(5.0, 0.5 + (r.bottom()-pos.y()) / max(1, r.height()) * 4.5))
            # Endpoints stay pinned to the start/end of the clip.
            if self._drag_point is self._points[0]:
                x = 0.0
            elif self._drag_point is self._points[-1]:
                x = 1.0
        else:
            y = max(0.0, min(1.0, (r.bottom()-pos.y()) / max(1, r.height())))
            # Keep easing handles at fixed one-third/two-thirds X positions.
            x = float(self._drag_point.get("x", x))
        self._drag_point["x"] = x
        self._drag_point["y"] = y
        if self.mode == "speed":
            self._points.sort(key=lambda q: q["x"])
        self.update()

    def mouseReleaseEvent(self, event):
        if self._drag_point is not None:
            self._drag_point = None
            self.curveChanged.emit(self.get_points())
        super().mouseReleaseEvent(event)

    def get_points(self):
        return [dict(p) for p in self._points]

    def points(self):
        return [dict(p) for p in self._points]


class CurveEditorDialog(QDialog):
    def __init__(self, title="Curve editor", points=None, mode="ease", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.setWindowTitle(title)
        self.setMinimumWidth(360)
        self.setStyleSheet("QDialog{background:#202329;color:#E6EDF3;} QLabel{color:#B8C2CC;} QPushButton,QComboBox{background:#2B3037;color:#E6EDF3;border:1px solid #414A55;border-radius:4px;padding:5px;}")
        root = QVBoxLayout(self)
        help_text = ("Drag points to shape speed over time (0.5×–5×). Click the line to add a speed point."
                     if mode == "speed" else "Drag the two handles to shape interpolation between keyframes.")
        root.addWidget(QLabel(help_text))
        self.canvas = CurveCanvas(points, mode, self)
        root.addWidget(self.canvas)
        if mode == "ease":
            self.canvas.curveChanged.connect(self._mark_custom_curve)
        controls = QHBoxLayout()
        if mode == "ease":
            controls.addWidget(QLabel("Preset"))
            self.ease_combo = QComboBox()
            self.ease_combo.addItems(["Linear", "Ease in", "Ease out", "Ease in-out", "Hold", "Custom Bezier"])
            self.ease_combo.currentTextChanged.connect(self._preset_changed)
            controls.addWidget(self.ease_combo, 1)
            self.ease_combo.setCurrentText("Custom Bezier")
        else:
            self.ease_combo = None
            reset = QPushButton("Reset to 1×")
            reset.clicked.connect(self._reset_speed)
            controls.addWidget(reset)
        root.addLayout(controls)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        apply = QPushButton("Apply")
        cancel.clicked.connect(self.reject)
        apply.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(apply)
        root.addLayout(buttons)

    def _mark_custom_curve(self, _points):
        if self.ease_combo is not None and self.ease_combo.currentText() != "Custom Bezier":
            self.ease_combo.setCurrentText("Custom Bezier")

    @staticmethod
    def points_for_ease(ease):
        if isinstance(ease, dict) and ease.get("type") == "bezier":
            return [
                {"x":0.0,"y":0.0},
                {"x":float(ease.get("x1", .33)),"y":float(ease.get("y1", .0))},
                {"x":float(ease.get("x2", .67)),"y":float(ease.get("y2", 1.0))},
                {"x":1.0,"y":1.0},
            ]
        presets = {"linear":"Linear","ease_in":"Ease in","ease_out":"Ease out",
                   "ease_in_out":"Ease in-out","hold":"Hold"}
        return _preset_points(presets.get(str(ease), "Ease in-out"))

    def _preset_changed(self, name):
        if self.mode == "ease" and name != "Custom Bezier":
            self.canvas.set_points(_preset_points(name))

    def _reset_speed(self):
        self.canvas.set_points([{"x":0.0,"y":1.0},{"x":1.0,"y":1.0}])
        self.canvas.curveChanged.emit(self.canvas.get_points())

    def points(self):
        return self.canvas.get_points()

    def easing(self):
        if not self.ease_combo:
            return "linear"
        name = self.ease_combo.currentText()
        mapping = {"Linear":"linear", "Ease in":"ease_in", "Ease out":"ease_out",
                   "Ease in-out":"ease_in_out", "Hold":"hold"}
        if name in mapping:
            return mapping[name]
        pts = self.canvas.get_points()
        return {"type":"bezier",
                "x1":max(0.0,min(1.0,float(pts[1]["x"]))),
                "y1":max(0.0,min(1.0,float(pts[1]["y"]))),
                "x2":max(0.0,min(1.0,float(pts[2]["x"]))),
                "y2":max(0.0,min(1.0,float(pts[2]["y"])))}
