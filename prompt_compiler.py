import re
from typing import Dict, Any

def resolve_asset_placeholders(text: str, assets: Dict[str, Any], use_label_only: bool = False) -> str:
    pattern = re.compile(r"\{assets\.([a-zA-Z0-9_-]+)\}")
    def replacer(match):
        key = match.group(1)
        if key in assets:
            if use_label_only:
                return assets[key].get("label", key)
            return assets[key].get("visual_dna", assets[key].get("label", key))
        return key
    return pattern.sub(replacer, text)

def compile_beat_prompt(
    beat: Dict[str, Any],
    assets: Dict[str, Any],
    global_style: Dict[str, Any],
    aspect_ratio: str = "9:16",
    is_in_session: bool = True
) -> str:
    if aspect_ratio == "9:16":
        ratio_tag = "vertical 9:16 smartphone portrait ratio, tall vertical framing"
    else:
        ratio_tag = "horizontal 16:9 widescreen cinematic ratio, wide panoramic framing"

    action_mode = beat.get("action_mode", "new_camera_angle")
    art_style = global_style.get("art_style", "").strip()

    if is_in_session and action_mode == "in_place_action":
        delta = beat.get("session_delta_prompt") or beat.get("prompt_action", "")
        resolved = resolve_asset_placeholders(delta, assets, use_label_only=True)
        return f"{resolved}. Maintain exact same visual continuity, character clothes, and setting. {ratio_tag}"

    raw = beat.get("prompt_action", "")
    resolved_action = resolve_asset_placeholders(raw, assets, use_label_only=False)
    camera = beat.get("camera_type", "Cinematic shot")
    return f"{art_style}. {camera}: {resolved_action}. {ratio_tag}".strip()