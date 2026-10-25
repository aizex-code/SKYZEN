"""FFmpeg command construction and execution for Skyzen preview rendering.

This module has no Qt dependency, which makes command generation easy to test.
"""
from __future__ import annotations

import math
import re
import shutil
import subprocess
from pathlib import Path


def find_binary(root_dir, name: str) -> str | None:
    root = Path(root_dir or ".").resolve()
    candidates = []
    for base in (root, *root.parents):
        candidates.extend((base / "ffmpeg" / name, base / name, base / "bin" / name))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    if name.lower().endswith(".exe"):
        return shutil.which(name[:-4])
    return None


def _fmt(value: float) -> str:
    return f"{float(value):.6f}".rstrip("0").rstrip(".") or "0"


def _probe_has_audio(
    ffprobe: str | None, path: str, cache: dict, ffmpeg: str | None = None
) -> bool:
    """Detect an audio stream once per source, with a fallback if ffprobe is absent."""
    key = str(Path(path).resolve())
    if key in cache:
        return cache[key]
    found = False
    try:
        if ffprobe:
            result = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", "a:0",
                 "-show_entries", "stream=index", "-of", "csv=p=0", path],
                capture_output=True, text=True, timeout=8, check=False,
            )
            found = bool(result.stdout.strip()) and result.returncode == 0
        elif ffmpeg:
            # FFmpeg reports stream types while opening input even without an
            # output target. Its expected non-zero exit is ignored; only the
            # input stream description is inspected.
            result = subprocess.run(
                [ffmpeg, "-hide_banner", "-i", path],
                capture_output=True, text=True, timeout=8, check=False,
            )
            found = "Audio:" in (result.stderr or "")
    except (OSError, subprocess.SubprocessError):
        found = False
    cache[key] = found
    return found


def _clip_speed(clip: dict) -> float:
    speed = max(0.5, min(5.0, float(clip.get("speed", 1.0))))
    if str(clip.get("speed_mode", "constant")) == "curve" and clip.get("speed_curve"):
        try:
            from app.animation import integrate_speed_curve
            return max(0.1, integrate_speed_curve(clip["speed_curve"], clip.get("duration", 1.0), speed) / max(1e-6, float(clip.get("duration", 1.0))))
        except Exception:
            pass
    return speed


def _clip_source_duration(clip: dict) -> float:
    duration = max(0.0, float(clip.get("duration", 0.0)))
    if str(clip.get("kind", "Video")).lower() == "image":
        return duration
    if str(clip.get("speed_mode", "constant")) == "curve" and clip.get("speed_curve"):
        try:
            from app.animation import integrate_speed_curve
            return integrate_speed_curve(clip["speed_curve"], duration, float(clip.get("speed", 1.0)))
        except Exception:
            pass
    return duration * max(0.5, min(5.0, float(clip.get("speed", 1.0))))


def _atempo_chain(speed: float) -> str:
    speed = max(0.5, min(5.0, float(speed)))
    pieces = []
    while speed > 2.0:
        pieces.append("atempo=2.0")
        speed /= 2.0
    while speed < 0.5:
        pieces.append("atempo=0.5")
        speed /= 0.5
    pieces.append(f"atempo={_fmt(speed)}")
    return ",".join(pieces)


def _input_args(clip: dict, fps: int) -> list[str]:
    kind = str(clip.get("kind", "Video")).lower()
    path = str(clip["path"])
    duration = _clip_source_duration(clip)
    if kind == "image":
        return ["-loop", "1", "-framerate", str(fps), "-t", _fmt(duration), "-i", path]
    args = []
    source_in = max(0.0, float(clip.get("source_in", 0.0)))
    if source_in > 0:
        args += ["-ss", _fmt(source_in)]
    args += ["-t", _fmt(duration), "-i", path]
    return args


def _keyframe_expression(points, default, clip_start, time_offset=0.0):
    """Build a safe FFmpeg expression for clip-local numeric keyframes."""
    from app.animation import normalize_keyframes
    keys = normalize_keyframes(points)
    if not keys:
        return _fmt(default)
    local_t = f"(t-{_fmt(clip_start)}+{_fmt(time_offset)})"
    def fmt(v): return _fmt(v)
    expr = fmt(keys[-1]["value"])
    for left, right in reversed(list(zip(keys, keys[1:]))):
        span = max(1e-6, right["time"] - left["time"])
        p = f"clip(({local_t}-{fmt(left['time'])})/{fmt(span)},0,1)"
        if left["ease"] == "hold":
            interp = fmt(left["value"])
        elif left["ease"] == "ease_in":
            interp = f"({fmt(left['value'])}+({fmt(right['value'])}-{fmt(left['value'])})*({p})^2)"
        elif left["ease"] == "ease_out":
            interp = f"({fmt(left['value'])}+({fmt(right['value'])}-{fmt(left['value'])})*(1-(1-({p}))^2))"
        elif left["ease"] == "ease_in_out":
            interp = f"({fmt(left['value'])}+({fmt(right['value'])}-{fmt(left['value'])})*({p})^2*(3-2*({p})))"
        elif isinstance(left["ease"], dict) and left["ease"].get("type") == "bezier":
            y1 = max(0.0, min(1.0, float(left["ease"].get("y1", 0.0))))
            y2 = max(0.0, min(1.0, float(left["ease"].get("y2", 1.0))))
            # Same cubic y(t) easing used by the interactive preview evaluator.
            q = f"(1-({p}))"
            eased = f"(3*({q})^2*({p})*{fmt(y1)}+3*({q})*({p})^2*{fmt(y2)}+({p})^3)"
            interp = f"({fmt(left['value'])}+({fmt(right['value'])}-{fmt(left['value'])})*({eased}))"
        else:
            interp = f"({fmt(left['value'])}+({fmt(right['value'])}-{fmt(left['value'])})*({p}))"
        expr = f"if(lt({local_t},{fmt(right['time'])}),{interp},{expr})"
    expr = f"if(lt({local_t},{fmt(keys[0]['time'])}),{fmt(keys[0]['value'])},{expr})"
    return expr


def _overlay_chain(
    visual_clips: list[dict], fps: int, duration: float, frame_only=False,
    width: int = 1280, height: int = 720,
    effects: list[dict] | None = None,
    adjustments: list[dict] | None = None,
):
    """Build a compositing chain with one shared output canvas."""
    effects = list(effects or [])
    adjustments = list(adjustments or [])
    filters = [
        f"color=c=black:s={int(width)}x{int(height)}:r={fps}:d={_fmt(max(duration, 1.0 / fps))},format=rgba[canvas0]"
    ]
    current = "canvas0"
    for index, clip in enumerate(visual_clips):
        input_index = index
        start = float(clip["start"])
        end = float(clip["end"])
        base_scale = max(0.05, min(8.0, float(clip.get("scale", 1.0))))
        # Skyzen currently has a 2D compositor (no camera object). Give Z a
        # predictable visual effect by treating positive Z as nearer and
        # negative Z as farther; X/Y remain project-space pixels.
        z = max(-900.0, min(4000.0, float(clip.get("position_z", 0.0))))
        depth_scale = max(0.1, min(5.0, 1000.0 / max(100.0, 1000.0 - z)))
        scale = max(0.05, min(8.0, base_scale * depth_scale))
        opacity = max(0.0, min(1.0, float(clip.get("opacity", 1.0))))
        keyframes = clip.get("keyframes", {}) or {}
        keyframe_offset = float(clip.get("_keyframe_time_offset", 0.0))
        scale_keys = keyframes.get("scale", [])
        z_keys = keyframes.get("position_z", [])
        opacity_keys = keyframes.get("opacity", [])
        rotation_keys = keyframes.get("rotation", [])
        x_keys = keyframes.get("position_x", [])
        y_keys = keyframes.get("position_y", [])
        animated_scale = bool(scale_keys or z_keys)
        scale_expr = None
        if animated_scale:
            base_expr = _keyframe_expression(scale_keys, base_scale, start, keyframe_offset)
            if z_keys:
                z_expr = _keyframe_expression(z_keys, z, start, keyframe_offset)
                depth_expr = f"clip(1000/max(100,1000-clip(({z_expr}),-900,4000)),0.1,5)"
            else:
                depth_expr = _fmt(depth_scale)
            scale_expr = f"clip(({base_expr})*({depth_expr}),0.05,8)"
        opacity_expr = _keyframe_expression(opacity_keys, opacity, start, keyframe_offset) if opacity_keys else None
        rotation_expr = _keyframe_expression(rotation_keys, float(clip.get("rotation", 0.0)), start, keyframe_offset) if rotation_keys else None
        x_expr = _keyframe_expression(x_keys, float(clip.get("position_x", 0.0)), start, keyframe_offset) if x_keys else None
        y_expr = _keyframe_expression(y_keys, float(clip.get("position_y", 0.0)), start, keyframe_offset) if y_keys else None
        brightness = max(-1.0, min(1.0, float(clip.get("brightness", 0.0))))
        contrast = max(0.0, min(2.0, float(clip.get("contrast", 1.0))))
        saturation = max(0.0, min(3.0, float(clip.get("saturation", 1.0))))
        gamma = max(0.1, min(3.0, float(clip.get("gamma", 1.0))))
        hue = max(-180.0, min(180.0, float(clip.get("hue", 0.0))))
        temperature = max(-1.0, min(1.0, float(clip.get("temperature", 0.0))))
        tint = max(-1.0, min(1.0, float(clip.get("tint", 0.0))))
        highlights = max(-1.0, min(1.0, float(clip.get("highlights", 0.0))))
        shadows = max(-1.0, min(1.0, float(clip.get("shadows", 0.0))))
        vibrance = max(-2.0, min(2.0, float(clip.get("vibrance", 0.0))))
        rotation = math.radians(float(clip.get("rotation", 0.0)))
        # Timeline transforms are authored in the 1280x720 project coordinate
        # space. Scale offsets with the output resolution so the 640x360 preview
        # and full-size export place the same object at the same relative point.
        x = float(clip.get("position_x", 0.0)) * (float(width) / 1280.0)
        y = float(clip.get("position_y", 0.0)) * (float(height) / 720.0)
        # Build a lean filter graph. Neutral grading/rotation controls do not
        # add FFmpeg filters, which noticeably reduces CPU cost on older PCs.
        if str(clip.get("speed_mode", "constant")) == "curve" and clip.get("speed_curve"):
            from app.animation import speed_curve_setpts_expression
            speed_expr = speed_curve_setpts_expression(clip.get("speed_curve"), float(clip.get("duration", 1.0)), float(clip.get("speed", 1.0)))
            pts_filter = f"settb=AVTB,setpts='({speed_expr})/TB+{_fmt(start)}/TB'"
        else:
            speed = max(0.5, min(5.0, float(clip.get("speed", 1.0))))
            if abs(speed - 1.0) < 1e-9:
                pts_filter = f"setpts=PTS-STARTPTS+{_fmt(start)}/TB"
            else:
                pts_filter = f"settb=AVTB,setpts=(PTS-STARTPTS)/{_fmt(speed)}+{_fmt(start)}/TB"
        chain = [
            f"[{input_index}:v:0]{pts_filter}",
            f"scale={int(width)}:{int(height)}:force_original_aspect_ratio=decrease",
        ]
        crop_left = max(0.0, min(0.45, float(clip.get("crop_left", 0.0))))
        crop_top = max(0.0, min(0.45, float(clip.get("crop_top", 0.0))))
        crop_right = max(0.0, min(0.45, float(clip.get("crop_right", 0.0))))
        crop_bottom = max(0.0, min(0.45, float(clip.get("crop_bottom", 0.0))))
        if any(value > 1e-9 for value in (crop_left, crop_top, crop_right, crop_bottom)):
            crop_width = _fmt(max(0.10, 1.0 - crop_left - crop_right))
            crop_height = _fmt(max(0.10, 1.0 - crop_top - crop_bottom))
            chain.append(
                f"crop=w='max(2,iw*{crop_width})':h='max(2,ih*{crop_height})':"
                f"x='iw*{_fmt(crop_left)}':y='ih*{_fmt(crop_top)}'"
            )
        grade_props = ("brightness", "contrast", "saturation", "gamma", "hue", "temperature", "tint", "highlights", "shadows", "vibrance")
        animated_grade = any(keyframes.get(prop) for prop in grade_props)
        if animated_grade:
            offset = clip.get("_keyframe_time_offset", 0.0)
            values = {
                "brightness": brightness, "contrast": contrast, "saturation": saturation,
                "gamma": gamma, "hue": hue, "temperature": temperature, "tint": tint,
                "highlights": highlights, "shadows": shadows, "vibrance": vibrance,
            }
            expr = {prop: _keyframe_expression(keyframes.get(prop, []), value, start, offset) for prop, value in values.items()}
            b_expr = f"clip(({expr['brightness']})+0.015*({expr['temperature']})+0.005*({expr['tint']})+0.02*({expr['highlights']})+0.01*({expr['shadows']}),-1,1)"
            c_expr = f"clip(({expr['contrast']})+0.02*({expr['temperature']})+0.08*({expr['highlights']})-0.06*({expr['shadows']}),0,2)"
            s_expr = f"clip(({expr['saturation']})+0.15*({expr['vibrance']}),0,3)"
            chain.append(f"eq=brightness='{b_expr}':contrast='{c_expr}':saturation='{s_expr}':gamma='{expr['gamma']}':eval=frame")
            if keyframes.get("hue") or keyframes.get("temperature") or keyframes.get("tint"):
                h_expr = f"({expr['hue']}+8*({expr['temperature']})+5*({expr['tint']}))"
                chain.append(f"hue=h='{h_expr}'")
        elif abs(brightness) > 1e-9 or abs(contrast - 1.0) > 1e-9 or abs(saturation - 1.0) > 1e-9 or abs(gamma - 1.0) > 1e-9:
            chain.append(f"eq=brightness={_fmt(brightness)}:contrast={_fmt(contrast)}:saturation={_fmt(saturation)}:gamma={_fmt(gamma)}")
        if not animated_grade and abs(hue) > 1e-9:
            chain.append(f"hue=h={_fmt(hue)}")
        if not animated_grade and any(abs(value) > 1e-9 for value in (temperature, tint, highlights, shadows)):
            chain.append(
                f"colorbalance=rs={_fmt(temperature * 0.35 + tint * 0.2 + shadows * 0.2)}:"
                f"gs={_fmt(-tint * 0.35 + shadows * 0.15)}:"
                f"bs={_fmt(-temperature * 0.35 + tint * 0.2 + shadows * 0.1)}:"
                f"rm={_fmt(temperature * 0.25 + tint * 0.15)}:"
                f"gm={_fmt(-tint * 0.3)}:"
                f"bm={_fmt(-temperature * 0.25 + tint * 0.15)}:"
                f"rh={_fmt(temperature * 0.35 + tint * 0.2 + highlights * 0.25)}:"
                f"gh={_fmt(-tint * 0.35 + highlights * 0.1)}:"
                f"bh={_fmt(-temperature * 0.35 + tint * 0.2 - highlights * 0.15)}"
            )
        if not animated_grade and abs(vibrance) > 1e-9:
            chain.append(f"vibrance=intensity={_fmt(vibrance)}")
        # Effect and local-adjustment layers are timeline objects, not fake
        # media overlays. Apply their supported filters to visual layers below
        # their lane, gated by the exact half-open project-time interval.
        for effect in effects:
            if float(clip.get("stack_order", 0.0)) <= float(effect.get("stack_order", 0.0)):
                continue
            if frame_only or (float(effect.get("start", 0.0)) < float(clip.get("end", 0.0)) and float(effect.get("end", 0.0)) > float(clip.get("start", 0.0))):
                intensity = max(0.0, min(1.0, float(effect.get("intensity", 0.5))))
                estart, eend = float(effect.get("start", 0.0)), float(effect.get("end", duration))
                enable = "" if frame_only else f":enable='gte(t,{_fmt(estart)})*lt(t,{_fmt(eend)})'"
                effect_name = str(effect.get("effect_type", ""))
                if effect_name == "warm_film":
                    chain.append(f"eq=brightness={_fmt(0.015*intensity)}:contrast={_fmt(1+0.16*intensity)}:saturation={_fmt(1+0.22*intensity)}{enable}")
                elif effect_name == "cool_night":
                    chain.append(f"eq=brightness={_fmt(-0.02*intensity)}:contrast={_fmt(1+0.14*intensity)}:saturation={_fmt(1-0.18*intensity)}{enable}")
                elif effect_name in ("blur", "soft_glow"):
                    sigma = (0.5 + 5.0 * intensity) if effect_name == "blur" else (0.25 + 1.25 * intensity)
                    chain.append(f"gblur=sigma={_fmt(sigma)}:steps=1{enable}")
                elif effect_name == "shake":
                    # Small animated rotation creates a lightweight handheld shake without changing output dimensions.
                    angle = 0.004 + 0.018 * intensity
                    chain.append(f"rotate='{_fmt(angle)}*sin(2*PI*9*t)':c=black@0:ow=iw:oh=ih{enable}")
                elif effect_name == "vignette":
                    chain.append(f"vignette=angle={_fmt(0.35+0.6*intensity)}{enable}")
                elif effect_name == "filter_cinematic":
                    chain.append(f"eq=contrast={_fmt(1+0.18*intensity)}:saturation={_fmt(1+0.08*intensity)}:gamma={_fmt(1-0.025*intensity)}{enable}")
                elif effect_name == "filter_vintage":
                    chain.append(f"colorbalance=rs={_fmt(0.10*intensity)}:gs={_fmt(0.015*intensity)}:bs={_fmt(-0.10*intensity)}{enable}")
                    chain.append(f"eq=saturation={_fmt(1-0.30*intensity)}:contrast={_fmt(1-0.08*intensity)}:brightness={_fmt(0.015*intensity)}{enable}")
                elif effect_name == "filter_mono":
                    chain.append(f"hue=s={_fmt(1-intensity)}{enable}")
                elif effect_name == "filter_teal_orange":
                    chain.append(f"colorbalance=rs={_fmt(0.18*intensity)}:gs={_fmt(-0.025*intensity)}:bs={_fmt(-0.16*intensity)}:rm={_fmt(0.10*intensity)}:bm={_fmt(-0.08*intensity)}{enable}")

        for adjustment in adjustments:
            if str(adjustment.get("scope", "below")) == "project":
                continue
            if float(clip.get("stack_order", 0.0)) <= float(adjustment.get("stack_order", 0.0)):
                continue
            astart, aend = float(adjustment.get("start", 0.0)), float(adjustment.get("end", duration))
            if not frame_only and not (astart < float(clip.get("end", 0.0)) and aend > float(clip.get("start", 0.0))):
                continue
            enable = "" if frame_only else f":enable='gte(t,{_fmt(astart)})*lt(t,{_fmt(aend)})'"
            ab = max(-1.0, min(1.0, float(adjustment.get("brightness", 0.0))))
            ac = max(0.0, min(2.0, float(adjustment.get("contrast", 1.0))))
            ass = max(0.0, min(3.0, float(adjustment.get("saturation", 1.0))))
            ag = max(0.1, min(3.0, float(adjustment.get("gamma", 1.0))))
            adjustment_keys = adjustment.get("keyframes", {}) or {}
            grade_props = ("brightness", "contrast", "saturation", "gamma", "hue", "temperature", "tint", "highlights", "shadows", "vibrance")
            animated = any(adjustment_keys.get(prop) for prop in grade_props)
            temp = max(-1.0, min(1.0, float(adjustment.get("temperature", 0.0))))
            tint_v = max(-1.0, min(1.0, float(adjustment.get("tint", 0.0))))
            hi = max(-1.0, min(1.0, float(adjustment.get("highlights", 0.0))))
            sh = max(-1.0, min(1.0, float(adjustment.get("shadows", 0.0))))
            vib = max(-2.0, min(2.0, float(adjustment.get("vibrance", 0.0))))
            hue_v = max(-180.0, min(180.0, float(adjustment.get("hue", 0.0))))
            if animated:
                offset = adjustment.get("_keyframe_time_offset", 0.0)
                vals = {"brightness":ab,"contrast":ac,"saturation":ass,"gamma":ag,"hue":hue_v,"temperature":temp,"tint":tint_v,"highlights":hi,"shadows":sh,"vibrance":vib}
                ex = {prop:_keyframe_expression(adjustment_keys.get(prop, []), value, astart, offset) for prop,value in vals.items()}
                be = f"clip(({ex['brightness']})+0.015*({ex['temperature']})+0.005*({ex['tint']})+0.02*({ex['highlights']})+0.01*({ex['shadows']}),-1,1)"
                ce = f"clip(({ex['contrast']})+0.02*({ex['temperature']})+0.08*({ex['highlights']})-0.06*({ex['shadows']}),0,2)"
                se = f"clip(({ex['saturation']})+0.15*({ex['vibrance']}),0,3)"
                chain.append(f"eq=brightness='{be}':contrast='{ce}':saturation='{se}':gamma='{ex['gamma']}':eval=frame{enable}")
                if adjustment_keys.get("hue") or adjustment_keys.get("temperature") or adjustment_keys.get("tint"):
                    chain.append(f"hue=h='({ex['hue']}+8*({ex['temperature']})+5*({ex['tint']}))'{enable}")
            elif abs(ab) > 1e-9 or abs(ac-1.0) > 1e-9 or abs(ass-1.0) > 1e-9 or abs(ag-1.0) > 1e-9:
                chain.append(f"eq=brightness={_fmt(ab)}:contrast={_fmt(ac)}:saturation={_fmt(ass)}:gamma={_fmt(ag)}{enable}")
            if not animated and any(abs(v) > 1e-9 for v in (temp,tint_v,hi,sh)):
                chain.append(f"colorbalance=rs={_fmt(temp*0.35+tint_v*0.2+sh*0.2)}:gs={_fmt(-tint_v*0.35+sh*0.15)}:bs={_fmt(-temp*0.35+tint_v*0.2+sh*0.1)}:rh={_fmt(temp*0.35+tint_v*0.2+hi*0.25)}:gh={_fmt(-tint_v*0.35+hi*0.1)}:bh={_fmt(-temp*0.35+tint_v*0.2-hi*0.15)}{enable}")
            if not animated and abs(vib) > 1e-9:
                chain.append(f"vibrance=intensity={_fmt(vib)}{enable}")
            if not animated and abs(hue_v) > 1e-9:
                chain.append(f"hue=h={_fmt(hue_v)}{enable}")

        chain.append("format=rgba")
        if bool(clip.get("chroma_key_enabled", False)):
            key_color = str(clip.get("chroma_key_color", "#00FF00")).strip().lstrip("#")
            if not re.fullmatch(r"[0-9A-Fa-f]{6}", key_color):
                key_color = "00FF00"
            # FFmpeg's colorkey filter rejects similarity=0 (valid range starts
            # at 1e-5). The UI intentionally allows a user to request the
            # tightest possible key, so clamp at FFmpeg's documented minimum
            # instead of letting the entire preview render fail.
            try:
                similarity = float(clip.get("chroma_similarity", 0.15))
            except (TypeError, ValueError):
                similarity = 0.15
            similarity = max(1e-5, min(1.0, similarity))
            try:
                blend = float(clip.get("chroma_blend", 0.05))
            except (TypeError, ValueError):
                blend = 0.05
            blend = max(0.0, min(1.0, blend))
            try:
                foreground_opacity = float(clip.get("chroma_opacity", 1.0))
            except (TypeError, ValueError):
                foreground_opacity = 1.0
            foreground_opacity = max(0.0, min(1.0, foreground_opacity))
            chain.append(
                f"colorkey=0x{key_color}:similarity={_fmt(similarity)}:blend={_fmt(blend)}"
            )
            if abs(foreground_opacity - 1.0) > 1e-9:
                # This multiplies the alpha of the remaining foreground while
                # preserving fully transparent keyed pixels.
                chain.append(f"colorchannelmixer=aa={_fmt(foreground_opacity)}")
        chain.append(
            f"pad={int(width)}:{int(height)}:(ow-iw)/2:(oh-ih)/2:color=black@0"
        )
        if animated_scale:
            chain.append(f"scale=w='max(2,iw*({scale_expr}))':h='max(2,ih*({scale_expr}))':eval=frame")
        elif abs(scale - 1.0) > 1e-9:
            chain.append(f"scale=w='max(2,iw*{_fmt(scale)})':h='max(2,ih*{_fmt(scale)})'")
        if rotation_expr is not None:
            chain.append(f"rotate='(({rotation_expr})*PI/180)':ow=rotw(iw):oh=roth(ih):c=black@0")
        elif abs(rotation) > 1e-9:
            chain.append(f"rotate={_fmt(rotation)}:ow=rotw(iw):oh=roth(ih):c=black@0")
        if opacity_expr is not None:
            if frame_only:
                # One-frame preview already resolves keyframes to the sampled value.
                chain.append(f"colorchannelmixer=aa={_fmt(opacity)}")
            else:
                # geq exposes the per-frame timestamp T and can animate alpha.
                alpha_expr = re.sub(r"\bt\b", "T", opacity_expr)
                chain.append(
                    f"format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                    f"a='alpha(X,Y)*clip(({alpha_expr}),0,1)'"
                )
        elif abs(opacity - 1.0) > 1e-9:
            chain.append(f"colorchannelmixer=aa={_fmt(opacity)}")
        chain[-1] += f"[layer{index}]"
        filters.append(",".join(chain))
        next_label = f"canvas{index + 1}"
        if frame_only:
            enable = ""
        else:
            # Half-open intervals prevent adjacent clips overlapping for one frame.
            enable = f":enable='gte(t,{_fmt(start)})*lt(t,{_fmt(end)})'"
        x_value = f"(({x_expr})*{_fmt(float(width)/1280.0)})" if x_expr is not None else _fmt(x)
        y_value = f"(({y_expr})*{_fmt(float(height)/720.0)})" if y_expr is not None else _fmt(y)
        overlay_eval = ":eval=frame" if (x_expr is not None or y_expr is not None) else ""
        filters.append(
            f"[{current}][layer{index}]overlay="
            f"x='(W-w)/2+({x_value})':y='(H-h)/2+({y_value})':"
            f"eof_action=pass:repeatlast=0:shortest=0{overlay_eval}{enable}[{next_label}]"
        )
        current = next_label

    # Whole-project grading is applied after all visual layers have been
    # composited, so it affects the complete image rather than one clip.
    for index, adjustment in enumerate(adjustments):
        if str(adjustment.get("scope", "below")) != "project":
            continue
        start = float(adjustment.get("start", 0.0)); end = float(adjustment.get("end", duration))
        enable = "" if frame_only else f":enable='gte(t,{_fmt(start)})*lt(t,{_fmt(end)})'"
        brightness = max(-1.0, min(1.0, float(adjustment.get("brightness", 0.0))))
        contrast = max(0.0, min(2.0, float(adjustment.get("contrast", 1.0))))
        saturation = max(0.0, min(3.0, float(adjustment.get("saturation", 1.0))))
        gamma = max(0.1, min(3.0, float(adjustment.get("gamma", 1.0))))
        project_keys = adjustment.get("keyframes", {}) or {}
        grade_props = ("brightness", "contrast", "saturation", "gamma", "hue", "temperature", "tint", "highlights", "shadows", "vibrance")
        animated_project_grade = any(project_keys.get(prop) for prop in grade_props)
        temp = max(-1.0, min(1.0, float(adjustment.get("temperature", 0.0))))
        tint_v = max(-1.0, min(1.0, float(adjustment.get("tint", 0.0))))
        hi = max(-1.0, min(1.0, float(adjustment.get("highlights", 0.0))))
        sh = max(-1.0, min(1.0, float(adjustment.get("shadows", 0.0))))
        vib = max(-2.0, min(2.0, float(adjustment.get("vibrance", 0.0))))
        hue_v = max(-180.0, min(180.0, float(adjustment.get("hue", 0.0))))
        if animated_project_grade or abs(brightness) > 1e-9 or abs(contrast-1.0) > 1e-9 or abs(saturation-1.0) > 1e-9 or abs(gamma-1.0) > 1e-9:
            next_label = f"projectgrade{index}"
            if animated_project_grade:
                offset = adjustment.get("_keyframe_time_offset", 0.0)
                vals = {"brightness":brightness,"contrast":contrast,"saturation":saturation,"gamma":gamma,"hue":hue_v,"temperature":temp,"tint":tint_v,"highlights":hi,"shadows":sh,"vibrance":vib}
                ex = {prop:_keyframe_expression(project_keys.get(prop, []), value, start, offset) for prop,value in vals.items()}
                be = f"clip(({ex['brightness']})+0.015*({ex['temperature']})+0.005*({ex['tint']})+0.02*({ex['highlights']})+0.01*({ex['shadows']}),-1,1)"
                ce = f"clip(({ex['contrast']})+0.02*({ex['temperature']})+0.08*({ex['highlights']})-0.06*({ex['shadows']}),0,2)"
                se = f"clip(({ex['saturation']})+0.15*({ex['vibrance']}),0,3)"
                filters.append(f"[{current}]eq=brightness='{be}':contrast='{ce}':saturation='{se}':gamma='{ex['gamma']}':eval=frame{enable}[{next_label}]")
            else:
                filters.append(f"[{current}]eq=brightness={_fmt(brightness)}:contrast={_fmt(contrast)}:saturation={_fmt(saturation)}:gamma={_fmt(gamma)}{enable}[{next_label}]")
            current = next_label
        if animated_project_grade and (project_keys.get("hue") or project_keys.get("temperature") or project_keys.get("tint")):
            offset = adjustment.get("_keyframe_time_offset", 0.0)
            he = _keyframe_expression(project_keys.get("hue", []), hue_v, start, offset)
            te = _keyframe_expression(project_keys.get("temperature", []), temp, start, offset)
            tie = _keyframe_expression(project_keys.get("tint", []), tint_v, start, offset)
            next_label = f"projecthue{index}"
            filters.append(f"[{current}]hue=h='({he}+8*({te})+5*({tie}))'{enable}[{next_label}]")
            current = next_label
        elif not animated_project_grade:
            if abs(temp) > 1e-9 or abs(tint_v) > 1e-9 or abs(hi) > 1e-9 or abs(sh) > 1e-9:
                next_label = f"projectbalance{index}"
                filters.append(f"[{current}]colorbalance=rs={_fmt(temp*0.35+tint_v*0.2+sh*0.2)}:gs={_fmt(-tint_v*0.35+sh*0.15)}:bs={_fmt(-temp*0.35+tint_v*0.2+sh*0.1)}:rh={_fmt(temp*0.35+tint_v*0.2+hi*0.25)}:gh={_fmt(-tint_v*0.35+hi*0.1)}:bh={_fmt(-temp*0.35+tint_v*0.2-hi*0.15)}{enable}[{next_label}]")
                current = next_label
            if abs(vib) > 1e-9:
                next_label = f"projectvibrance{index}"
                filters.append(f"[{current}]vibrance=intensity={_fmt(vib)}{enable}[{next_label}]")
                current = next_label
            if abs(hue_v) > 1e-9:
                next_label = f"projecthue{index}"
                filters.append(f"[{current}]hue=h={_fmt(hue_v)}{enable}[{next_label}]")
                current = next_label
    filters.append(f"[{current}]fps={fps},format=yuv420p[vout]")
    return filters


def _apply_keyframes_at_time(item: dict, local_time: float) -> None:
    """Resolve every keyframed property for one-frame scrub previews."""
    from app.animation import evaluate_keyframes
    keys = item.get("keyframes", {}) or {}
    for prop, points in keys.items():
        if points:
            default = item.get(prop, 0.0)
            try:
                item[prop] = evaluate_keyframes(points, local_time, default)
            except (TypeError, ValueError):
                continue


def build_frame_command(ffmpeg: str, snapshot: dict, seconds: float, output: str) -> list[str]:
    fps = int(snapshot["fps"])
    active = []
    t = max(0.0, float(seconds))
    for clip in snapshot["visual"]:
        if clip["start"] <= t < clip["end"]:
            item = dict(clip)
            local_time = max(0.0, t - float(clip["start"]))
            item["duration"] = max(1.0 / fps, min(clip["end"] - t, 1.0))
            item["_keyframe_time_offset"] = local_time
            _apply_keyframes_at_time(item, local_time)
            if str(clip.get("speed_mode", "constant")) == "curve" and clip.get("speed_curve"):
                from app.animation import integrate_speed_to, evaluate_speed_curve
                item["source_in"] = max(0.0, clip["source_in"] + integrate_speed_to(clip["speed_curve"], clip["duration"], local_time, clip.get("speed", 1.0)))
                item["speed"] = evaluate_speed_curve(clip["speed_curve"], clip["duration"], local_time, clip.get("speed", 1.0))
                item["speed_mode"] = "constant"
                item.pop("speed_curve", None)
            else:
                item["source_in"] = max(0.0, clip["source_in"] + local_time * float(clip.get("speed", 1.0)))
            item["start"] = 0.0
            item["end"] = 1.0 / fps
            active.append(item)

    active_effects = []
    for source in snapshot.get("effects", []):
        if source["start"] <= t < source["end"]:
            item = dict(source); item["_keyframe_time_offset"] = max(0.0, t-float(source["start"])); _apply_keyframes_at_time(item, item["_keyframe_time_offset"]); item["start"] = 0.0; item["end"] = 1.0 / fps; active_effects.append(item)
    active_adjustments = []
    for source in snapshot.get("adjustments", []):
        if source["start"] <= t < source["end"]:
            item = dict(source); item["_keyframe_time_offset"] = max(0.0, t-float(source["start"])); _apply_keyframes_at_time(item, item["_keyframe_time_offset"]); item["start"] = 0.0; item["end"] = 1.0 / fps; active_adjustments.append(item)
    args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-filter_complex_threads", "1"]
    for clip in active:
        kind = str(clip.get("kind", "Video")).lower()
        if kind == "image":
            args += ["-loop", "1", "-framerate", str(fps), "-i", clip["path"]]
        else:
            local = max(0.0, float(clip.get("source_in", 0.0)))
            if local > 0:
                args += ["-ss", _fmt(local)]
            args += ["-i", clip["path"]]
    # Scrub previews are deliberately low-resolution; the original source and
    # final export settings are untouched.
    from .preview_profile import PREVIEW_WIDTH, PREVIEW_HEIGHT
    filters = _overlay_chain(
        active, fps, 1.0, width=PREVIEW_WIDTH, height=PREVIEW_HEIGHT,
        frame_only=True, effects=active_effects, adjustments=active_adjustments,
    )
    graph = ";".join(filters)
    args += ["-filter_complex", graph, "-map", "[vout]", "-frames:v", "1",
             "-update", "1", "-compression_level", "1", output]
    return args


def build_project_command(
    ffmpeg: str,
    ffprobe: str | None,
    snapshot: dict,
    output: str,
    *,
    width: int | None = None,
    height: int | None = None,
    codec_options: dict | None = None,
) -> list[str]:
    """Render a single composite preview MP4 for the entire editable project."""
    from .preview_profile import (
        PREVIEW_WIDTH, PREVIEW_HEIGHT, PREVIEW_CRF, PREVIEW_THREADS,
        PREVIEW_PRESET, PREVIEW_AUDIO_BITRATE,
    )
    fps = int(snapshot["fps"])
    duration = max(1.0 / fps, float(snapshot["duration"]))
    visual = snapshot["visual"]
    # Preview renders are temporary and optimized for responsiveness, not fidelity.
    # Explicit width/height or codec_options are used by final export callers.
    is_preview = codec_options is None and width is None and height is None
    width = int(width or PREVIEW_WIDTH)
    height = int(height or PREVIEW_HEIGHT)
    args = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-filter_complex_threads", str(PREVIEW_THREADS if is_preview else 1),
    ]

    codec_options = dict(codec_options or {})
    # Preview defaults prioritize fast generation; export profiles can override
    # these codec arguments without changing the timeline or compositor.
    for clip in visual:
        args += _input_args(clip, fps)

    # Probe and append independent audio inputs. Embedded video audio shares
    # the visual input index; dedicated audio tracks get their own input.
    video_input_count = len(visual)
    audio_sources = []
    probe_cache = {}
    for index, clip in enumerate(visual):
        # Every unmuted video layer contributes its own soundtrack. This is
        # important for overlays: previously the backend filtered by is_main,
        # so every overlay's sound was silently discarded even when unmuted.
        # Layer mute/volume values come from the render snapshot.
        volume_keys = (clip.get("keyframes", {}) or {}).get("volume", [])
        has_volume_keys = len(volume_keys) >= 1
        if (
            (clip.get("volume", 0.0) > 0.0 or has_volume_keys)
            and not clip.get("muted", False)
            and str(clip.get("kind", "Video")).lower() == "video"
        ):
            if _probe_has_audio(ffprobe, clip["path"], probe_cache, ffmpeg):
                audio_sources.append({
                    "input": index, "start": clip["start"], "duration": clip["duration"],
                    "source_in": clip["source_in"], "volume": clip["volume"], "path": clip["path"],
                    "speed": _clip_speed(clip), "embedded": True,
                    "volume_keyframes": volume_keys, "track_volume": clip.get("track_volume", 1.0),
                    "clip_volume": clip.get("clip_volume", 1.0),
                })

    for clip in snapshot["audio"]:
        volume_keys = (clip.get("keyframes", {}) or {}).get("volume", [])
        has_volume_keys = len(volume_keys) >= 1
        if clip.get("volume", 0.0) <= 0.0 and not has_volume_keys:
            continue
        if clip.get("muted", False):
            continue
        args += _input_args(clip, fps)
        audio_sources.append({
            "input": video_input_count, "start": clip["start"], "duration": clip["duration"],
            "source_in": clip["source_in"], "volume": clip["volume"], "path": clip["path"],
            "speed": _clip_speed(clip), "embedded": False,
            "volume_keyframes": volume_keys, "track_volume": clip.get("track_volume", 1.0),
            "clip_volume": clip.get("clip_volume", 1.0),
        })
        video_input_count += 1

    filters = _overlay_chain(
        visual, fps, duration, width=width, height=height,
        effects=snapshot.get("effects", []), adjustments=snapshot.get("adjustments", []),
    )
    audio_labels = []
    for n, source in enumerate(audio_sources):
        delay = max(0, int(round(float(source["start"]) * 1000.0)))
        # Inputs were trimmed before input, so source timestamps start at zero.
        volume_keys = source.get("volume_keyframes") or []
        if volume_keys:
            # Audio timestamps are reset above, so keyframe time is clip-local.
            # Keep track volume separate from clip automation and let FFmpeg
            # evaluate the expression per audio frame for smooth volume ramps.
            volume_expr = _keyframe_expression(
                volume_keys, source.get("clip_volume", 1.0), 0.0
            )
            track_gain = max(0.0, min(2.0, float(source.get("track_volume", 1.0))))
            volume_filter = f"volume='({volume_expr})*{_fmt(track_gain)}':eval=frame"
        else:
            volume_filter = f"volume={_fmt(source['volume'])}"
        filters.append(
            f"[{source['input']}:a:0]asetpts=PTS-STARTPTS,{_atempo_chain(source.get('speed', 1.0))},"
            f"adelay={delay}:all=1,{volume_filter},"
            f"atrim=duration={_fmt(duration)},asetpts=PTS-STARTPTS[aud{n}]"
        )
        audio_labels.append(f"[aud{n}]")

    if audio_labels:
        filters.append(
            "".join(audio_labels)
            + f"amix=inputs={len(audio_labels)}:duration=longest:dropout_transition=0:normalize=0,"
            + f"alimiter=limit=0.95,atrim=duration={_fmt(duration)},asetpts=PTS-STARTPTS[aout]"
        )

    args += ["-filter_complex", ";".join(filters), "-map", "[vout]"]
    if audio_labels:
        args += ["-map", "[aout]"]
        args += list(codec_options.get(
            "audio_args",
            ["-c:a", "aac", "-b:a", PREVIEW_AUDIO_BITRATE if is_preview else "160k"],
        ))
    else:
        args += ["-an"]
    if is_preview:
        default_video_args = [
            "-c:v", "libx264", "-preset", PREVIEW_PRESET, "-crf", str(PREVIEW_CRF),
            "-tune", "zerolatency", "-threads", str(PREVIEW_THREADS),
            "-bf", "0", "-g", str(max(1, fps * 2)),
            "-pix_fmt", "yuv420p",
        ]
    else:
        default_video_args = [
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        ]
    args += ["-t", _fmt(duration), "-r", str(fps)]
    args += list(codec_options.get("video_args", default_video_args))
    if codec_options.get("metadata", True):
        args += ["-metadata", "comment=Skyzen preview cache"]
    args += [output]
    return args


def run_command(command: list[str], timeout: float | None = None) -> tuple[bool, str]:
    """Run FFmpeg without blocking the GUI (call only from a worker thread)."""
    try:
        result = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=timeout, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return False, "FFmpeg preview render timed out."
    except OSError as exc:
        return False, f"Could not start FFmpeg: {exc}"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Unknown FFmpeg error").strip()
        return False, detail[-5000:]
    return True, ""
