"""Collision por indice de tile en tilesets (solid / none / shape + oneway)."""

from __future__ import annotations

from typing import Any, TypedDict

from turtlestudio.objects import (
    OBJECT_COLLISION_MODE_AABB,
    collision_to_json,
    normalize_object_collision,
)
from turtlestudio.project import DEFAULT_TRANSPARENT_INDEX

TILE_COLLISION_SOLID = "solid"
TILE_COLLISION_NONE = "none"
TILE_COLLISION_SHAPE = "shape"

TILE_COLLISION_KINDS = (
    TILE_COLLISION_SOLID,
    TILE_COLLISION_NONE,
    TILE_COLLISION_SHAPE,
)

TILE_ONEWAY_UP = "up"
TILE_ONEWAY_DOWN = "down"
TILE_ONEWAY_LEFT = "left"
TILE_ONEWAY_RIGHT = "right"

TILE_ONEWAY_DIRECTIONS = (
    TILE_ONEWAY_UP,
    TILE_ONEWAY_DOWN,
    TILE_ONEWAY_LEFT,
    TILE_ONEWAY_RIGHT,
)

TILE_ONEWAY_DIR_DEFAULT = TILE_ONEWAY_UP

TileCollisionMeta = dict[str, Any]


class TileCollisionMetaTyped(TypedDict, total=False):
    kind: str
    shape: dict[str, Any]
    oneway: bool
    oneway_direction: str


def normalize_oneway_direction(raw: object) -> str:
    s = str(raw or TILE_ONEWAY_DIR_DEFAULT).strip().lower()
    aliases = {
        "arriba": TILE_ONEWAY_UP,
        "abajo": TILE_ONEWAY_DOWN,
        "izquierda": TILE_ONEWAY_LEFT,
        "derecha": TILE_ONEWAY_RIGHT,
        "u": TILE_ONEWAY_UP,
        "d": TILE_ONEWAY_DOWN,
        "l": TILE_ONEWAY_LEFT,
        "r": TILE_ONEWAY_RIGHT,
    }
    if s in aliases:
        return aliases[s]
    if s in TILE_ONEWAY_DIRECTIONS:
        return s
    return TILE_ONEWAY_DIR_DEFAULT


def _parse_oneway_bool(raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return raw != 0
    if isinstance(raw, str):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return False


def default_tile_collision_meta(*, kind: str = TILE_COLLISION_SOLID) -> TileCollisionMeta:
    k = str(kind).strip()
    if k not in TILE_COLLISION_KINDS:
        k = TILE_COLLISION_SOLID
    base: TileCollisionMeta = {
        "kind": k,
        "oneway": False,
        "oneway_direction": TILE_ONEWAY_DIR_DEFAULT,
    }
    if k == TILE_COLLISION_SHAPE:
        base["shape"] = {
            "mode": OBJECT_COLLISION_MODE_AABB,
            "x0": 0,
            "y0": 0,
            "x1": 0,
            "y1": 0,
        }
    return base


def aabb_from_tile_pixels(
    rows: list[list[int]],
    *,
    tile_px: int,
    transparent_index: int = DEFAULT_TRANSPARENT_INDEX,
) -> dict[str, int]:
    """Caja en espacio tile: origen (0,0) = esquina inferior izquierda, Y hacia arriba."""
    px = max(1, int(tile_px))
    min_x = px
    max_x = -1
    min_row = px
    max_row = -1
    for py, row in enumerate(rows):
        if not isinstance(row, list):
            continue
        for lx, ci in enumerate(row):
            if lx >= px:
                break
            if int(ci) == int(transparent_index):
                continue
            min_x = min(min_x, lx)
            max_x = max(max_x, lx)
            min_row = min(min_row, py)
            max_row = max(max_row, py)
    if max_x < 0:
        return {"x0": 0, "y0": 0, "x1": 0, "y1": 0}
    y0 = px - 1 - max_row
    y1 = px - 1 - min_row
    return {"x0": min_x, "y0": y0, "x1": max_x, "y1": y1}


def default_shape_from_tile_pixels(
    rows: list[list[int]],
    *,
    tile_px: int,
    transparent_index: int = DEFAULT_TRANSPARENT_INDEX,
) -> dict[str, Any]:
    box = aabb_from_tile_pixels(
        rows, tile_px=tile_px, transparent_index=transparent_index
    )
    return {
        "mode": OBJECT_COLLISION_MODE_AABB,
        "x0": box["x0"],
        "y0": box["y0"],
        "x1": box["x1"],
        "y1": box["y1"],
    }


def _read_oneway_from_entry(entry: dict[str, Any]) -> tuple[bool, str]:
    oneway = _parse_oneway_bool(entry.get("oneway"))
    direction = normalize_oneway_direction(entry.get("oneway_direction"))
    raw_coll = entry.get("collision")
    if isinstance(raw_coll, dict):
        if "oneway" in raw_coll:
            oneway = _parse_oneway_bool(raw_coll.get("oneway"))
        if "oneway_direction" in raw_coll:
            direction = normalize_oneway_direction(raw_coll.get("oneway_direction"))
        elif "oneway_dir" in raw_coll:
            direction = normalize_oneway_direction(raw_coll.get("oneway_dir"))
    return oneway, direction


def _apply_oneway_to_meta(meta: TileCollisionMeta, oneway: bool, direction: str) -> None:
    meta["oneway"] = bool(oneway)
    meta["oneway_direction"] = normalize_oneway_direction(direction)


def parse_tile_collision_from_entry(entry: object) -> TileCollisionMeta:
    """Lee collision de un elemento de tiles[] en JSON."""
    if not isinstance(entry, dict):
        return default_tile_collision_meta()
    raw = entry.get("collision")
    if raw is None:
        meta = default_tile_collision_meta(kind=TILE_COLLISION_SOLID)
    elif isinstance(raw, str):
        s = raw.strip().lower()
        if s in (TILE_COLLISION_SOLID, "full"):
            meta = default_tile_collision_meta(kind=TILE_COLLISION_SOLID)
        elif s in (TILE_COLLISION_NONE, "pass", "passthrough"):
            meta = default_tile_collision_meta(kind=TILE_COLLISION_NONE)
        else:
            meta = default_tile_collision_meta()
    elif isinstance(raw, dict):
        try:
            shape = normalize_object_collision(raw)
        except ValueError:
            meta = default_tile_collision_meta(kind=TILE_COLLISION_SHAPE)
        else:
            if shape is None:
                meta = default_tile_collision_meta(kind=TILE_COLLISION_SHAPE)
            else:
                meta = default_tile_collision_meta(kind=TILE_COLLISION_SHAPE)
                meta["shape"] = shape
    else:
        meta = default_tile_collision_meta()
    oneway, direction = _read_oneway_from_entry(entry)
    _apply_oneway_to_meta(meta, oneway, direction)
    if str(meta.get("kind")) == TILE_COLLISION_NONE:
        meta["oneway"] = False
    return meta


def collision_meta_to_json_field(meta: TileCollisionMeta) -> object | None:
    """None = omitir campo collision (solid por defecto en firmware futuro)."""
    kind = str(meta.get("kind", TILE_COLLISION_SOLID)).strip()
    if kind == TILE_COLLISION_NONE:
        return TILE_COLLISION_NONE
    if kind == TILE_COLLISION_SHAPE:
        shape = meta.get("shape")
        if isinstance(shape, dict):
            try:
                norm = normalize_object_collision(shape)
            except ValueError:
                return TILE_COLLISION_SOLID
            if norm is not None:
                return collision_to_json(norm)
        return TILE_COLLISION_SOLID
    return None


def apply_oneway_to_collision_entry(
    entry: dict[str, Any],
    meta: TileCollisionMeta,
) -> None:
    """Anade oneway / oneway_direction al dict de tile ya con collision."""
    kind = str(meta.get("kind", TILE_COLLISION_SOLID)).strip()
    if kind == TILE_COLLISION_NONE:
        entry.pop("oneway", None)
        entry.pop("oneway_direction", None)
        coll = entry.get("collision")
        if isinstance(coll, dict):
            coll.pop("oneway", None)
            coll.pop("oneway_direction", None)
            coll.pop("oneway_dir", None)
        return
    if not bool(meta.get("oneway")):
        entry.pop("oneway", None)
        entry.pop("oneway_direction", None)
        coll = entry.get("collision")
        if isinstance(coll, dict):
            coll.pop("oneway", None)
            coll.pop("oneway_direction", None)
            coll.pop("oneway_dir", None)
        return
    direction = normalize_oneway_direction(meta.get("oneway_direction"))
    coll = entry.get("collision")
    if isinstance(coll, dict):
        coll["oneway"] = True
        coll["oneway_direction"] = direction
        entry.pop("oneway", None)
        entry.pop("oneway_direction", None)
    else:
        entry["oneway"] = True
        entry["oneway_direction"] = direction


def parse_tileset_collision_meta(data: dict[str, Any]) -> list[TileCollisionMeta]:
    """Un meta por tile, alineado con tiles[] del JSON."""
    raw = data.get("tiles")
    if not isinstance(raw, list):
        return []
    return [parse_tile_collision_from_entry(e) for e in raw]


def _copy_meta_fields(src: TileCollisionMeta, *, kind: str) -> TileCollisionMeta:
    out = default_tile_collision_meta(kind=kind)
    if str(src.get("kind")) == TILE_COLLISION_SHAPE:
        shape = src.get("shape")
        if isinstance(shape, dict):
            try:
                norm = normalize_object_collision(shape)
            except ValueError:
                norm = None
            if norm is not None:
                out = default_tile_collision_meta(kind=TILE_COLLISION_SHAPE)
                out["shape"] = norm
    oneway = bool(src.get("oneway")) and kind != TILE_COLLISION_NONE
    _apply_oneway_to_meta(out, oneway, str(src.get("oneway_direction", TILE_ONEWAY_DIR_DEFAULT)))
    return out


def normalize_tile_collision_meta_list(
    meta: list[TileCollisionMeta] | None,
    tile_count: int,
) -> list[TileCollisionMeta]:
    n = max(0, int(tile_count))
    out: list[TileCollisionMeta] = []
    src = meta if isinstance(meta, list) else []
    for i in range(n):
        if i < len(src) and isinstance(src[i], dict):
            kind = str(src[i].get("kind", TILE_COLLISION_SOLID)).strip()
            if kind not in TILE_COLLISION_KINDS:
                kind = TILE_COLLISION_SOLID
            out.append(_copy_meta_fields(src[i], kind=kind))
        else:
            out.append(default_tile_collision_meta())
    return out
