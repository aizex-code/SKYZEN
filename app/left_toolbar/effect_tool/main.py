"""Effect preset metadata and renderer contract."""
from app.left_toolbar.catalog import EFFECT_PRESETS
TOOL_ID = "Effects"
TOOL_COLOR = "#F2A44A"
RENDERER_CONTRACT = "Effect clips modify visual layers beneath their timeline lane during the clip's half-open time range."

def presets():
    return tuple(dict(item) for item in EFFECT_PRESETS)
