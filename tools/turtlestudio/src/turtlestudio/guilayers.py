"""Capas GUI apilables (spec/gui-layer-v0.md).

Los archivos viven en `guilayers/<stem>.json` bajo la raiz del proyecto (un archivo por
capa). Al exportar, el `build.py` recoge todos los archivos y los junta en el array
`"guilayers"` a nivel top-level del bundle. El firmware los parsea en cada
`turtle_scene_begin_runtime` (turtle_gui_layer.cpp).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Alineado con la constante del firmware (kSceneW/kSceneH en turtle_scene.cpp).
SCENE_PIXEL_W = 164
SCENE_PIXEL_H = 124

MAX_GUI_LAYERS = 8
MAX_GUI_LAYER_RECTS = 16
MAX_GUI_LAYER_LABELS = 16
GUI_LAYER_TEXT_MAX_CHARS = 63  # el buffer del firmware es 64 (63 + nul)

_STEM_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,31}$")


def is_valid_gui_layer_id(s: str) -> bool:
    return bool(_STEM_RE.match(s))


@dataclass(frozen=True)
class GuiRect:
    x: int = 0
    y: int = 0
    w: int = 1
    h: int = 1
    color_index: int = 0


@dataclass(frozen=True)
class GuiTextLabel:
    id: str
    font: str
    text: str = ""
    x: int = 0
    y: int = 0
    color_index: int = -1  # -1 = sin tinte, 0..30 = tinte plano


@dataclass(frozen=True)
class GuiLayer:
    id: str
    x: int = 0
    y: int = 0
    w: int = SCENE_PIXEL_W
    h: int = SCENE_PIXEL_H
    bg_color_index: int = 0
    transparent_bg: bool = False
    pauses_scene: bool = False
    captures_input: bool = False
    z: int = 0
    rects: tuple[GuiRect, ...] = field(default_factory=tuple)
    text_labels: tuple[GuiTextLabel, ...] = field(default_factory=tuple)


def _clamp_int(v: object, lo: int, hi: int, default: int) -> int:
    try:
        n = int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = default
    return max(lo, min(hi, n))


def _clamp_color_index(v: object) -> int:
    return _clamp_int(v, 0, 31, default=0)


def _clamp_tint(v: object) -> int:
    """`color_index` de etiquetas: -1 (sin tinte) o 0..30. `31` (transparente) no tiene
    sentido para tinte de glifo — se colapsa a 30."""
    try:
        n = int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return -1
    if n < 0:
        return -1
    if n > 30:
        return 30
    return n


def parse_gui_rect(raw: Any) -> GuiRect:
    if not isinstance(raw, dict):
        return GuiRect()
    return GuiRect(
        x=_clamp_int(raw.get("x", 0), 0, SCENE_PIXEL_W, default=0),
        y=_clamp_int(raw.get("y", 0), 0, SCENE_PIXEL_H, default=0),
        w=_clamp_int(raw.get("w", 1), 1, SCENE_PIXEL_W, default=1),
        h=_clamp_int(raw.get("h", 1), 1, SCENE_PIXEL_H, default=1),
        color_index=_clamp_color_index(raw.get("color_index", 0)),
    )


def parse_gui_text_label(raw: Any) -> GuiTextLabel | None:
    if not isinstance(raw, dict):
        return None
    ident = str(raw.get("id", "") or "").strip()
    font = str(raw.get("font", "") or "").strip()
    if not ident or not font:
        return None
    if not is_valid_gui_layer_id(ident):
        return None
    text = str(raw.get("text", "") or "")
    if len(text) > GUI_LAYER_TEXT_MAX_CHARS:
        text = text[:GUI_LAYER_TEXT_MAX_CHARS]
    return GuiTextLabel(
        id=ident,
        font=font,
        text=text,
        x=_clamp_int(raw.get("x", 0), 0, SCENE_PIXEL_W, default=0),
        y=_clamp_int(raw.get("y", 0), 0, SCENE_PIXEL_H, default=0),
        color_index=_clamp_tint(raw.get("color_index", -1)),
    )


def parse_gui_layer(raw: Any) -> GuiLayer | None:
    if not isinstance(raw, dict):
        return None
    ident = str(raw.get("id", "") or "").strip()
    if not is_valid_gui_layer_id(ident):
        return None
    x = _clamp_int(raw.get("x", 0), 0, SCENE_PIXEL_W - 1, default=0)
    y = _clamp_int(raw.get("y", 0), 0, SCENE_PIXEL_H - 1, default=0)
    w = _clamp_int(raw.get("w", SCENE_PIXEL_W), 1, SCENE_PIXEL_W, default=SCENE_PIXEL_W)
    h = _clamp_int(raw.get("h", SCENE_PIXEL_H), 1, SCENE_PIXEL_H, default=SCENE_PIXEL_H)
    # Clampeo por rect completo dentro del framebuffer.
    if x + w > SCENE_PIXEL_W:
        w = SCENE_PIXEL_W - x
    if y + h > SCENE_PIXEL_H:
        h = SCENE_PIXEL_H - y
    rects_raw = raw.get("rects", []) or []
    labels_raw = raw.get("text_labels", []) or []
    rects: list[GuiRect] = []
    if isinstance(rects_raw, list):
        for r in rects_raw[:MAX_GUI_LAYER_RECTS]:
            rects.append(parse_gui_rect(r))
    labels: list[GuiTextLabel] = []
    if isinstance(labels_raw, list):
        for lbl in labels_raw:
            if len(labels) >= MAX_GUI_LAYER_LABELS:
                break
            parsed = parse_gui_text_label(lbl)
            if parsed is not None:
                labels.append(parsed)
    return GuiLayer(
        id=ident,
        x=x,
        y=y,
        w=w,
        h=h,
        bg_color_index=_clamp_color_index(raw.get("bg_color_index", 0)),
        transparent_bg=bool(raw.get("transparent_bg", False)),
        pauses_scene=bool(raw.get("pauses_scene", False)),
        captures_input=bool(raw.get("captures_input", False)),
        z=_clamp_int(raw.get("z", 0), -1000, 1000, default=0),
        rects=tuple(rects),
        text_labels=tuple(labels),
    )


def gui_rect_to_json(r: GuiRect) -> dict[str, Any]:
    return {
        "x": int(r.x),
        "y": int(r.y),
        "w": int(r.w),
        "h": int(r.h),
        "color_index": int(r.color_index),
    }


def gui_text_label_to_json(lbl: GuiTextLabel) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": lbl.id,
        "font": lbl.font,
        "text": lbl.text,
        "x": int(lbl.x),
        "y": int(lbl.y),
    }
    if lbl.color_index >= 0:
        out["color_index"] = int(lbl.color_index)
    return out


def gui_layer_to_json(ly: GuiLayer) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": ly.id,
        "x": int(ly.x),
        "y": int(ly.y),
        "w": int(ly.w),
        "h": int(ly.h),
        "bg_color_index": int(ly.bg_color_index),
        "transparent_bg": bool(ly.transparent_bg),
        "pauses_scene": bool(ly.pauses_scene),
        "captures_input": bool(ly.captures_input),
        "z": int(ly.z),
    }
    if ly.rects:
        out["rects"] = [gui_rect_to_json(r) for r in ly.rects]
    if ly.text_labels:
        out["text_labels"] = [gui_text_label_to_json(lbl) for lbl in ly.text_labels]
    return out


def list_gui_layer_stems(project_root: Path) -> list[str]:
    """Devuelve los stems de los archivos `guilayers/*.json`, en orden alfabetico."""
    d = project_root / "guilayers"
    if not d.is_dir():
        return []
    stems: list[str] = []
    for p in sorted(d.iterdir()):
        if p.suffix.lower() != ".json":
            continue
        stem = p.stem
        if is_valid_gui_layer_id(stem):
            stems.append(stem)
    return stems


def read_gui_layer_file(project_root: Path, stem: str) -> GuiLayer:
    """Lee `guilayers/<stem>.json`. Si falta el campo `id`, se usa el stem del archivo."""
    p = project_root / "guilayers" / f"{stem}.json"
    if not p.is_file():
        raise ValueError(f"guilayer {stem!r} no existe en {p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"guilayer {stem!r} JSON invalido: {e}") from e
    if isinstance(raw, dict) and "id" not in raw:
        raw = {**raw, "id": stem}
    ly = parse_gui_layer(raw)
    if ly is None:
        raise ValueError(f"guilayer {stem!r} contenido invalido")
    return ly


def write_gui_layer_file(project_root: Path, ly: GuiLayer) -> Path:
    d = project_root / "guilayers"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{ly.id}.json"
    p.write_text(
        json.dumps(gui_layer_to_json(ly), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return p
