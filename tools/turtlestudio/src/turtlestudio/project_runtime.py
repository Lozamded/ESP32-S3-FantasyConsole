"""Ajustes de tiempo de proyecto (FPS consola y animacion por defecto)."""

from __future__ import annotations

from typing import Any

DEFAULT_TARGET_FPS = 30
DEFAULT_ANIM_FPS = 8
MIN_TARGET_FPS = 15
MAX_TARGET_FPS = 60
MIN_ANIM_FPS = 1
MAX_ANIM_FPS = 30


def clamp_target_fps(raw: Any) -> int:
    try:
        v = int(raw)
    except (TypeError, ValueError):
        v = DEFAULT_TARGET_FPS
    return max(MIN_TARGET_FPS, min(MAX_TARGET_FPS, v))


def clamp_default_anim_fps(raw: Any) -> int:
    try:
        v = int(raw)
    except (TypeError, ValueError):
        v = DEFAULT_ANIM_FPS
    return max(MIN_ANIM_FPS, min(MAX_ANIM_FPS, v))


def parse_runtime_from_manifest(data: dict[str, Any]) -> tuple[int, int]:
    """(target_fps, default_anim_fps)."""
    target = clamp_target_fps(data.get("target_fps", DEFAULT_TARGET_FPS))
    anim = clamp_default_anim_fps(data.get("default_anim_fps", DEFAULT_ANIM_FPS))
    return target, anim
