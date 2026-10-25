"""Convert the editable timeline model into a stable, immutable render snapshot."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import preview_profile


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)





def project_fingerprint(timeline) -> str:
    """Cheap in-memory edit fingerprint; avoids stat/probe work on every playhead tick."""
    try:
        tracks = timeline.playback_tracks()
    except Exception:
        tracks = list(getattr(timeline, "tracks", []))
    rows = []
    for index, track in enumerate(tracks):
        rows.append({
            "name": str(track.get("name", "")),
            "base": str(track.get("base", "V")),
            "track_type": str(track.get("track_type", "")),
            "is_main": bool(track.get("is_main", False)),
            "stack": _safe_float(track.get("_stack_order", index), index),
            "hidden": bool(track.get("hidden", False)),
            "muted": bool(track.get("muted", False)),
            "volume": _safe_float(track.get("volume", 1.0), 1.0),
            "clips": [
                {
                    "path": str(clip.get("path", "")),
                    "kind": str(clip.get("kind", "Video")),
                    "tool_type": str(clip.get("tool_type", "")),
                    "tool_preset": str(clip.get("tool_preset", "")),
                    "text": str(clip.get("text", "")),
                    "effect_type": str(clip.get("effect_type", "")),
                    "scope": str(clip.get("scope", "")),
                    "intensity": _safe_float(clip.get("intensity", 1.0), 1.0),
                    "speed": _safe_float(clip.get("speed", 1.0), 1.0),
                    "speed_source_duration": _safe_float(clip.get("speed_source_duration", 0.0)),
                    "speed_mode": str(clip.get("speed_mode", "constant")),
                    "speed_curve": clip.get("speed_curve", []),
                    "keyframes": clip.get("keyframes", {}),
                    "start": _safe_float(clip.get("start", 0.0)),
                    "duration": _safe_float(clip.get("duration", 0.0)),
                    "source_in": _safe_float(clip.get("source_in", 0.0)),
                    "scale": _safe_float(clip.get("scale", 1.0), 1.0),
                    "x": _safe_float(clip.get("position_x", 0.0)),
                    "y": _safe_float(clip.get("position_y", 0.0)),
                    "z": _safe_float(clip.get("position_z", 0.0)),
                    "rotation": _safe_float(clip.get("rotation", 0.0)),
                    "opacity": _safe_float(clip.get("opacity", 1.0), 1.0),
                    "brightness": _safe_float(clip.get("brightness", 0.0)),
                    "contrast": _safe_float(clip.get("contrast", 1.0), 1.0),
                    "saturation": _safe_float(clip.get("saturation", 1.0), 1.0),
                    "gamma": _safe_float(clip.get("gamma", 1.0), 1.0),
                    "hue": _safe_float(clip.get("hue", 0.0)),
                    "temperature": _safe_float(clip.get("temperature", 0.0)),
                    "tint": _safe_float(clip.get("tint", 0.0)),
                    "highlights": _safe_float(clip.get("highlights", 0.0)),
                    "shadows": _safe_float(clip.get("shadows", 0.0)),
                    "vibrance": _safe_float(clip.get("vibrance", 0.0)),
                    "muted": bool(clip.get("clip_muted", False)),
                    "volume": _safe_float(clip.get("volume", 1.0), 1.0),
                    "chroma_key_enabled": bool(clip.get("chroma_key_enabled", False)),
                    "chroma_key_color": str(clip.get("chroma_key_color", "#00FF00")),
                    "chroma_similarity": _safe_float(clip.get("chroma_similarity", 0.15), 0.15),
                    "chroma_blend": _safe_float(clip.get("chroma_blend", 0.05), 0.05),
                    "chroma_opacity": _safe_float(clip.get("chroma_opacity", 1.0), 1.0),
                    "crop_left": _safe_float(clip.get("crop_left", 0.0)),
                    "crop_top": _safe_float(clip.get("crop_top", 0.0)),
                    "crop_right": _safe_float(clip.get("crop_right", 0.0)),
                    "crop_bottom": _safe_float(clip.get("crop_bottom", 0.0)),
                }
                for clip in track.get("clips", [])
            ],
        })
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def build_snapshot(timeline, *, use_proxies: bool = False) -> dict:
    """Return immutable render data; optional proxies affect preview only, never export."""
    tracks = []
    try:
        tracks = timeline.playback_tracks()
    except Exception:
        tracks = list(getattr(timeline, "tracks", []))

    clips = []
    for track_index, track in enumerate(tracks):
        if track.get("hidden", False):
            continue
        base = str(track.get("base", "V"))
        stack_order = _safe_float(track.get("_stack_order", track_index), track_index)
        for clip in track.get("clips", []):
            path = Path(str(clip.get("path", ""))).expanduser()
            if not path.is_file():
                continue
            start = max(0.0, _safe_float(clip.get("start", 0.0)))
            duration = max(0.0, _safe_float(clip.get("duration", 0.0)))
            if duration <= 0.0:
                continue
            original_path = str(path.resolve())
            try:
                stat = path.stat()
                source_stamp = [stat.st_size, stat.st_mtime_ns]
            except OSError:
                source_stamp = [0, 0]

            render_path = path
            if use_proxies and str(clip.get("kind", "Video")).lower() == "video":
                try:
                    from app.media.proxy_paths import proxy_path_for
                    candidate = Path(proxy_path_for(path, getattr(timeline, "root_dir", None)))
                    # A configured proxy path is not proof that proxy generation
                    # has completed. Missing/incomplete proxies caused playback
                    # to fail intermittently; always fall back to the real source.
                    if candidate.is_file() and candidate.stat().st_size > 0:
                        render_path = candidate
                except Exception:
                    render_path = path

            # Cache identity must include the actual decoder input as well as
            # the original. Otherwise a regenerated proxy can silently reuse an
            # old composite whose filename/signature still matches.
            try:
                render_stat = render_path.stat()
                render_stamp = [render_stat.st_size, render_stat.st_mtime_ns]
            except OSError:
                render_stamp = [0, 0]

            muted = bool(track.get("muted", False) or clip.get("clip_muted", False))
            track_volume = max(0.0, min(2.0, _safe_float(track.get("volume", 1.0), 1.0)))
            clip_volume = max(0.0, min(2.0, _safe_float(clip.get("volume", 1.0), 1.0)))
            volume = 0.0 if muted else max(0.0, min(2.0, track_volume * clip_volume))
            kind = str(clip.get("kind", "Video"))
            clips.append({
                "path": str(render_path.resolve()),
                "original_path": original_path,
                "source_stamp": source_stamp,
                "render_stamp": render_stamp,
                "kind": kind,
                "base": base,
                "tool_type": str(clip.get("tool_type", track.get("track_type", ""))),
                "tool_preset": str(clip.get("tool_preset", "")),
                "display_name": str(clip.get("display_name", "")),
                "text": str(clip.get("text", "")),
                "effect_type": str(clip.get("effect_type", "")),
                "intensity": max(0.0, min(1.0, _safe_float(clip.get("intensity", 1.0), 1.0))),
                "speed": max(0.5, min(5.0, _safe_float(clip.get("speed", 1.0), 1.0))),
                "speed_mode": str(clip.get("speed_mode", "constant")),
                "speed_curve": list(clip.get("speed_curve", []) or []),
                "keyframes": dict(clip.get("keyframes", {}) or {}),
                "track_volume": track_volume,
                "clip_volume": clip_volume,
                "muted": muted,
                "scope": str(clip.get("scope", "below")),
                "is_main": bool(track.get("is_main", False)),
                "track_name": str(track.get("name", "")),
                "track_index": track_index,
                "stack_order": stack_order,
                "start": start,
                "duration": duration,
                "end": start + duration,
                "source_in": max(0.0, _safe_float(clip.get("source_in", 0.0))),
                "scale": max(0.05, min(8.0, _safe_float(clip.get("scale", 1.0), 1.0))),
                "position_x": _safe_float(clip.get("position_x", 0.0)),
                "position_y": _safe_float(clip.get("position_y", 0.0)),
                "position_z": _safe_float(clip.get("position_z", 0.0)),
                "rotation": _safe_float(clip.get("rotation", 0.0)),
                "opacity": max(0.0, min(1.0, _safe_float(clip.get("opacity", 1.0), 1.0))),
                "brightness": max(-1.0, min(1.0, _safe_float(clip.get("brightness", 0.0)))),
                "contrast": max(0.0, min(2.0, _safe_float(clip.get("contrast", 1.0), 1.0))),
                "saturation": max(0.0, min(3.0, _safe_float(clip.get("saturation", 1.0), 1.0))),
                "gamma": max(0.1, min(3.0, _safe_float(clip.get("gamma", 1.0), 1.0))),
                "hue": max(-180.0, min(180.0, _safe_float(clip.get("hue", 0.0)))),
                "temperature": max(-1.0, min(1.0, _safe_float(clip.get("temperature", 0.0)))),
                "tint": max(-1.0, min(1.0, _safe_float(clip.get("tint", 0.0)))),
                "highlights": max(-1.0, min(1.0, _safe_float(clip.get("highlights", 0.0)))),
                "shadows": max(-1.0, min(1.0, _safe_float(clip.get("shadows", 0.0)))),
                "vibrance": max(-2.0, min(2.0, _safe_float(clip.get("vibrance", 0.0)))),
                "chroma_key_enabled": bool(clip.get("chroma_key_enabled", False)),
                "chroma_key_color": str(clip.get("chroma_key_color", "#00FF00")).upper(),
                "chroma_similarity": max(0.0, min(1.0, _safe_float(clip.get("chroma_similarity", 0.15), 0.15))),
                "chroma_blend": max(0.0, min(1.0, _safe_float(clip.get("chroma_blend", 0.05), 0.05))),
                "chroma_opacity": max(0.0, min(1.0, _safe_float(clip.get("chroma_opacity", 1.0), 1.0))),
                "crop_left": max(0.0, min(0.45, _safe_float(clip.get("crop_left", 0.0)))),
                "crop_top": max(0.0, min(0.45, _safe_float(clip.get("crop_top", 0.0)))),
                "crop_right": max(0.0, min(0.45, _safe_float(clip.get("crop_right", 0.0)))),
                "crop_bottom": max(0.0, min(0.45, _safe_float(clip.get("crop_bottom", 0.0)))),
                "volume": volume,
                "muted": muted,
            })

    # FFmpeg overlay chain must composite bottom-to-top. The timeline model
    # defines lower stack_order as visually higher, so descending order starts
    # with the main/base lane and ends with the uppermost overlay.
    visual = [c for c in clips if c["base"] == "V" and c["kind"].lower() in ("video", "image") and c.get("tool_type") not in ("Effects", "Filters", "Adjustments")]
    visual.sort(key=lambda c: (-c["stack_order"], c["start"], c["track_index"]))
    effects = [c for c in clips if c.get("tool_type") in ("Effects", "Filters")]
    adjustments = [c for c in clips if c.get("tool_type") == "Adjustments"]
    # Only dedicated audio-track clips are separate inputs. Embedded audio
    # from video clips is mixed from the corresponding video input in the
    # backend, preventing every video soundtrack from being opened twice.
    audio = [c for c in clips if c["base"] == "A"]
    audio.sort(key=lambda c: (c["start"], c["track_index"]))

    fps = max(1, int(getattr(timeline, "FPS", 30)))
    duration = max((c["end"] for c in clips if not (c.get("tool_type") == "Adjustments" and c.get("scope") == "project")), default=0.0)
    duration = max(0.0, round(duration * fps) / fps)
    for adjustment in adjustments:
        if adjustment.get("scope") == "project":
            adjustment["start"] = 0.0
            adjustment["duration"] = duration
            adjustment["end"] = duration

    identity = {
        "fps": fps,
        "preview_profile": preview_profile.PREVIEW_PROFILE_ID,
        "size": [1280, 720],
        "duration": round(duration, 6),
        "clips": [
            {
                k: c[k] for k in (
                    "path", "original_path", "source_stamp", "render_stamp", "kind", "base", "is_main",
                    "track_name", "stack_order", "start", "duration", "speed", "speed_mode", "speed_curve", "keyframes",
                    "source_in", "scale", "position_x", "position_y",
                    "position_z", "rotation", "opacity", "brightness", "contrast",
                    "saturation", "gamma", "hue", "temperature", "tint", "highlights", "shadows", "vibrance",
                    "chroma_key_enabled", "chroma_key_color", "chroma_similarity", "chroma_blend", "chroma_opacity",
                    "crop_left", "crop_top", "crop_right", "crop_bottom",
                    "volume", "muted",
                )
            }
            for c in clips
        ],
    }
    signature = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    return {
        "fps": fps,
        "width": 1280,
        "height": 720,
        "duration": duration,
        "clips": clips,
        "visual": visual,
        "effects": effects,
        "adjustments": adjustments,
        "audio": audio,
        "signature": signature,
    }


def active_visual_at(snapshot: dict, seconds: float) -> list[dict]:
    """Visual clips active at a project timestamp, already ordered bottom-to-top."""
    frame = round(max(0.0, seconds) * int(snapshot["fps"]))
    t = frame / int(snapshot["fps"])
    return [
        clip for clip in snapshot["visual"]
        if clip["start"] <= t < clip["end"]
    ]
