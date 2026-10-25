"""Compact, intentionally curated starter libraries for typed timeline assets."""
from __future__ import annotations

TOOL_ORDER = ("Media", "Audio", "Text", "Effects", "Filters", "Adjustments")
TOOL_COLORS = {
    "Media": "#00D5EE", "Audio": "#6F91FF", "Text": "#B27CFF",
    "Effects": "#F2A44A", "Filters": "#5CB8FF", "Adjustments": "#54C995",
}

TEXT_PRESETS = (
    {"id":"basic_title", "name":"Basic title", "subtitle":"Clean centered title", "text":"Your title", "font_size":76, "color":"#FFFFFF", "align":"center", "y":0.48, "bold":False},
)

EFFECT_PRESETS = (
    {"id":"blur", "name":"Blur", "subtitle":"Soft cinematic blur", "effect":"blur", "intensity":0.55},
    {"id":"shake", "name":"Shake", "subtitle":"Subtle handheld movement", "effect":"shake", "intensity":0.45},
    {"id":"glow", "name":"Glow", "subtitle":"Soft luminous highlights", "effect":"soft_glow", "intensity":0.45},
    {"id":"vignette", "name":"Vignette", "subtitle":"Darkened cinematic edges", "effect":"vignette", "intensity":0.5},
)

FILTER_PRESETS = (
    {"id":"cinematic", "name":"Cinematic", "subtitle":"Balanced cinematic contrast", "effect":"filter_cinematic", "intensity":0.65},
    {"id":"vintage", "name":"Vintage", "subtitle":"Warm faded film look", "effect":"filter_vintage", "intensity":0.65},
    {"id":"mono", "name":"Mono", "subtitle":"Classic black and white", "effect":"filter_mono", "intensity":1.0},
    {"id":"teal_orange", "name":"Teal & orange", "subtitle":"Cool shadows, warm highlights", "effect":"filter_teal_orange", "intensity":0.55},
)

ADJUSTMENT_PRESETS = (
    {"id":"adjustment", "name":"Adjustment layer", "subtitle":"Choose project-wide or local grading in Properties", "scope":"project", "brightness":0.0, "contrast":1.0, "saturation":1.0, "gamma":1.0},
)

CATALOGS = {"Text":TEXT_PRESETS, "Effects":EFFECT_PRESETS, "Filters":FILTER_PRESETS, "Adjustments":ADJUSTMENT_PRESETS}

def preset_for(tool_type: str, preset_id: str) -> dict | None:
    for preset in CATALOGS.get(tool_type, ()):
        if preset["id"] == preset_id:
            return dict(preset)
    return None
