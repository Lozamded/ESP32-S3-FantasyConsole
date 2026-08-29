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
MAX_GUI_LAYER_PROGRESS_BARS = 4
MAX_GUI_LAYER_PIP_BARS = 4
MAX_GUI_LAYER_SPRITES = 4
MAX_GUI_BAR_RANGES = 3
MAX_PIP_COUNT = 32
GUI_LAYER_TEXT_MAX_CHARS = 63  # el buffer del firmware es 64 (63 + nul)

BAR_DIRECTIONS = ("left_to_right", "right_to_left", "top_to_bottom", "bottom_to_top")
FILL_MODES = ("color", "sprite")
PIP_DIRECTIONS = ("horizontal", "vertical")

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
class GuiBarRange:
    """Banda de valor que reemplaza color y/o sprite del bar cuando la fraccion actual cae
    dentro de [min_pct, max_pct). Ver spec/gui-layer-v0.md "Bandas de valor"."""

    min_pct: int = 0
    max_pct: int = 100
    alt_color_index: int = -1  # -1 = no override, 0..30 = color de paleta
    alt_sprite_id: str = ""    # "" = no override, else stem del sprite


@dataclass(frozen=True)
class GuiProgressBar:
    id: str
    x: int = 0
    y: int = 0
    w: int = 1
    h: int = 1
    direction: str = "left_to_right"
    fill_mode: str = "color"
    fill_color_index: int = 11
    fill_sprite_id: str = ""
    bg_color_index: int = 3
    border_color_index: int = -1  # -1 = sin marco, 0..30 = color de marco 1 px
    value_num: int = 0
    value_den: int = 1
    ranges: tuple[GuiBarRange, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class GuiPipBar:
    id: str
    x: int = 0
    y: int = 0
    sprite_full_id: str = ""
    direction: str = "horizontal"
    gap_px: int = 0
    value: int = 0
    max_value: int = 1
    ranges: tuple[GuiBarRange, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class GuiSpriteIcon:
    """spec/gui-layer-v0.md "Iconos sprite": un blit 1:1 de un sprite del bundle en (x, y)
    coord relativa a la capa. Paleta compartida con la escena; index 31 = transparente."""

    id: str
    sprite_id: str
    x: int = 0
    y: int = 0
    frame_index: int = 0
    flip_h: bool = False
    flip_v: bool = False


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
    progress_bars: tuple[GuiProgressBar, ...] = field(default_factory=tuple)
    pip_bars: tuple[GuiPipBar, ...] = field(default_factory=tuple)
    sprites: tuple[GuiSpriteIcon, ...] = field(default_factory=tuple)


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


def _clamp_pct(v: object, default: int) -> int:
    return _clamp_int(v, 0, 100, default=default)


def _clamp_sprite_stem(v: object) -> str:
    s = str(v or "").strip()
    if not s:
        return ""
    return s if is_valid_gui_layer_id(s) else ""


def parse_gui_bar_range(raw: Any) -> GuiBarRange | None:
    if not isinstance(raw, dict):
        return None
    min_pct = _clamp_pct(raw.get("min_pct", 0), default=0)
    max_pct = _clamp_pct(raw.get("max_pct", 100), default=100)
    if min_pct >= max_pct:
        return None  # rango degenerado
    alt_color_raw = raw.get("alt_color_index", -1)
    try:
        alt_color = int(alt_color_raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        alt_color = -1
    if alt_color < 0 or alt_color > 30:
        alt_color = -1
    return GuiBarRange(
        min_pct=min_pct,
        max_pct=max_pct,
        alt_color_index=alt_color,
        alt_sprite_id=_clamp_sprite_stem(raw.get("alt_sprite_id", "")),
    )


def _parse_ranges_list(raw: Any) -> tuple[GuiBarRange, ...]:
    if not isinstance(raw, list):
        return ()
    out: list[GuiBarRange] = []
    for r in raw:
        if len(out) >= MAX_GUI_BAR_RANGES:
            break
        parsed = parse_gui_bar_range(r)
        if parsed is not None:
            out.append(parsed)
    return tuple(out)


def parse_gui_progress_bar(raw: Any) -> GuiProgressBar | None:
    if not isinstance(raw, dict):
        return None
    ident = str(raw.get("id", "") or "").strip()
    if not is_valid_gui_layer_id(ident):
        return None
    direction = str(raw.get("direction", "left_to_right") or "left_to_right")
    if direction not in BAR_DIRECTIONS:
        direction = "left_to_right"
    fill_mode = str(raw.get("fill_mode", "color") or "color")
    if fill_mode not in FILL_MODES:
        fill_mode = "color"
    value_den = _clamp_int(raw.get("value_den", 1), 1, 32767, default=1)
    return GuiProgressBar(
        id=ident,
        x=_clamp_int(raw.get("x", 0), 0, SCENE_PIXEL_W, default=0),
        y=_clamp_int(raw.get("y", 0), 0, SCENE_PIXEL_H, default=0),
        w=_clamp_int(raw.get("w", 1), 1, SCENE_PIXEL_W, default=1),
        h=_clamp_int(raw.get("h", 1), 1, SCENE_PIXEL_H, default=1),
        direction=direction,
        fill_mode=fill_mode,
        fill_color_index=_clamp_color_index(raw.get("fill_color_index", 11)),
        fill_sprite_id=_clamp_sprite_stem(raw.get("fill_sprite_id", "")),
        bg_color_index=_clamp_color_index(raw.get("bg_color_index", 3)),
        border_color_index=_clamp_tint(raw.get("border_color_index", -1)),
        value_num=_clamp_int(raw.get("value_num", 0), -32768, 32767, default=0),
        value_den=value_den,
        ranges=_parse_ranges_list(raw.get("ranges", [])),
    )


def parse_gui_pip_bar(raw: Any) -> GuiPipBar | None:
    if not isinstance(raw, dict):
        return None
    ident = str(raw.get("id", "") or "").strip()
    if not is_valid_gui_layer_id(ident):
        return None
    sprite_full = _clamp_sprite_stem(raw.get("sprite_full_id", ""))
    if not sprite_full:
        return None
    direction = str(raw.get("direction", "horizontal") or "horizontal")
    if direction not in PIP_DIRECTIONS:
        direction = "horizontal"
    max_value = _clamp_int(raw.get("max_value", 1), 1, MAX_PIP_COUNT, default=1)
    value = _clamp_int(raw.get("value", 0), 0, max_value, default=0)
    return GuiPipBar(
        id=ident,
        x=_clamp_int(raw.get("x", 0), 0, SCENE_PIXEL_W, default=0),
        y=_clamp_int(raw.get("y", 0), 0, SCENE_PIXEL_H, default=0),
        sprite_full_id=sprite_full,
        direction=direction,
        gap_px=_clamp_int(raw.get("gap_px", 0), 0, 32, default=0),
        value=value,
        max_value=max_value,
        ranges=_parse_ranges_list(raw.get("ranges", [])),
    )


def parse_gui_sprite_icon(raw: Any) -> GuiSpriteIcon | None:
    if not isinstance(raw, dict):
        return None
    ident = str(raw.get("id", "") or "").strip()
    if not is_valid_gui_layer_id(ident):
        return None
    sprite_id = _clamp_sprite_stem(raw.get("sprite_id", ""))
    if not sprite_id:
        return None
    return GuiSpriteIcon(
        id=ident,
        sprite_id=sprite_id,
        x=_clamp_int(raw.get("x", 0), 0, SCENE_PIXEL_W, default=0),
        y=_clamp_int(raw.get("y", 0), 0, SCENE_PIXEL_H, default=0),
        frame_index=_clamp_int(raw.get("frame_index", 0), 0, 255, default=0),
        flip_h=bool(raw.get("flip_h", False)),
        flip_v=bool(raw.get("flip_v", False)),
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
    progress: list[GuiProgressBar] = []
    for bar_raw in (raw.get("progress_bars", []) or []):
        if len(progress) >= MAX_GUI_LAYER_PROGRESS_BARS:
            break
        parsed_bar = parse_gui_progress_bar(bar_raw)
        if parsed_bar is not None:
            progress.append(parsed_bar)
    pips: list[GuiPipBar] = []
    for pip_raw in (raw.get("pip_bars", []) or []):
        if len(pips) >= MAX_GUI_LAYER_PIP_BARS:
            break
        parsed_pip = parse_gui_pip_bar(pip_raw)
        if parsed_pip is not None:
            pips.append(parsed_pip)
    sprites: list[GuiSpriteIcon] = []
    for sp_raw in (raw.get("sprites", []) or []):
        if len(sprites) >= MAX_GUI_LAYER_SPRITES:
            break
        parsed_sp = parse_gui_sprite_icon(sp_raw)
        if parsed_sp is not None:
            sprites.append(parsed_sp)
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
        progress_bars=tuple(progress),
        pip_bars=tuple(pips),
        sprites=tuple(sprites),
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


def gui_bar_range_to_json(r: GuiBarRange) -> dict[str, Any]:
    out: dict[str, Any] = {
        "min_pct": int(r.min_pct),
        "max_pct": int(r.max_pct),
    }
    if r.alt_color_index >= 0:
        out["alt_color_index"] = int(r.alt_color_index)
    if r.alt_sprite_id:
        out["alt_sprite_id"] = r.alt_sprite_id
    return out


def gui_progress_bar_to_json(bar: GuiProgressBar) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": bar.id,
        "x": int(bar.x),
        "y": int(bar.y),
        "w": int(bar.w),
        "h": int(bar.h),
        "direction": bar.direction,
        "fill_mode": bar.fill_mode,
        "fill_color_index": int(bar.fill_color_index),
        "bg_color_index": int(bar.bg_color_index),
        "border_color_index": int(bar.border_color_index),
        "value_num": int(bar.value_num),
        "value_den": int(bar.value_den),
    }
    if bar.fill_sprite_id:
        out["fill_sprite_id"] = bar.fill_sprite_id
    if bar.ranges:
        out["ranges"] = [gui_bar_range_to_json(r) for r in bar.ranges]
    return out


def gui_pip_bar_to_json(bar: GuiPipBar) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": bar.id,
        "x": int(bar.x),
        "y": int(bar.y),
        "sprite_full_id": bar.sprite_full_id,
        "direction": bar.direction,
        "gap_px": int(bar.gap_px),
        "value": int(bar.value),
        "max_value": int(bar.max_value),
    }
    if bar.ranges:
        out["ranges"] = [gui_bar_range_to_json(r) for r in bar.ranges]
    return out


def gui_sprite_icon_to_json(icon: GuiSpriteIcon) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": icon.id,
        "sprite_id": icon.sprite_id,
        "x": int(icon.x),
        "y": int(icon.y),
    }
    if icon.frame_index:
        out["frame_index"] = int(icon.frame_index)
    if icon.flip_h:
        out["flip_h"] = True
    if icon.flip_v:
        out["flip_v"] = True
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
    if ly.progress_bars:
        out["progress_bars"] = [gui_progress_bar_to_json(b) for b in ly.progress_bars]
    if ly.pip_bars:
        out["pip_bars"] = [gui_pip_bar_to_json(b) for b in ly.pip_bars]
    if ly.sprites:
        out["sprites"] = [gui_sprite_icon_to_json(sp) for sp in ly.sprites]
    return out


def collect_gui_layer_sprite_ids(layer: GuiLayer) -> set[str]:
    """Devuelve todos los stems de sprites referenciados por esta capa (fill_sprite_id de
    progress bars con fill_mode="sprite", sprite_full_id de pip bars, sprite_id de iconos
    sprite, y alt_sprite_id de rangos de progress/pip). El exportador usa esto para asegurarse
    de meter estos sprites en el bundle aunque no esten referenciados por ningun objeto de
    escena.
    """
    out: set[str] = set()
    for bar in layer.progress_bars:
        if bar.fill_sprite_id and bar.fill_mode == "sprite":
            out.add(bar.fill_sprite_id)
        for r in bar.ranges:
            if r.alt_sprite_id:
                out.add(r.alt_sprite_id)
    for pb in layer.pip_bars:
        if pb.sprite_full_id:
            out.add(pb.sprite_full_id)
        for r in pb.ranges:
            if r.alt_sprite_id:
                out.add(r.alt_sprite_id)
    for icon in layer.sprites:
        if icon.sprite_id:
            out.add(icon.sprite_id)
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
