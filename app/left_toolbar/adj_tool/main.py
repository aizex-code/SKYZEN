"""Adjustment-layer metadata and scope contract."""
from app.left_toolbar.catalog import ADJUSTMENT_PRESETS
TOOL_ID = "Adjustments"
TOOL_COLOR = "#54C995"
SCOPES = ("below", "project")

def presets():
    return tuple(dict(item) for item in ADJUSTMENT_PRESETS)
