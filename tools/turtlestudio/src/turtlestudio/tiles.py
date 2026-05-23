"""Tilesets del proyecto: `tiles/<id>.json` + `tile_px` en manifest."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from turtlestudio.sprites import (
    SPRITE_IMAGE_FORMAT_ROWS,
    _parse_palette_rows_from_image_dict,
    normalize_palette_rel,
    solid_fill_indices,
    trim_palette_rows,
    validate_palette_file_under_project,
    validate_sprite_id,
)

DEFAULT_TILE_PX = 16
MIN_TILE_PX = 4
MAX_TILE_PX = 128
TILE_PX_STEP = 4
TILESET_JSON_VERSION = 1
TILESET_JSON_KIND = "turtlestudio.tileset"
MAX_TILES_PER_TILESET = 256


def normalize_tile_px(raw: object) -> int:
    """Tamano de tile cuadrado en px; multiplo de 4 entre MIN y MAX."""
    try:
        n = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = DEFAULT_TILE_PX
    if n <= MIN_TILE_PX:
        return MIN_TILE_PX
    n = min(MAX_TILE_PX, n)
    snapped = int(round(n / float(TILE_PX_STEP))) * TILE_PX_STEP
    return max(MIN_TILE_PX, snapped)


def parse_tile_px_from_manifest(data: dict[str, Any]) -> int:
    """Lee `tiles.tile_px` del manifest; por defecto DEFAULT_TILE_PX."""
    tiles = data.get("tiles")
    if isinstance(tiles, dict):
        return normalize_tile_px(tiles.get("tile_px", DEFAULT_TILE_PX))
    if "tile_px" in data:
        return normalize_tile_px(data.get("tile_px"))
    return DEFAULT_TILE_PX


def tiles_section_to_json(tile_px: int) -> dict[str, int]:
    return {"tile_px": normalize_tile_px(tile_px)}


def tiles_dir(project_root: Path) -> Path:
    return project_root / "tiles"


def validate_tileset_id(raw: str) -> str:
    return validate_sprite_id(raw)


def tileset_json_path(project_root: Path, stem: str) -> Path:
    tid = validate_tileset_id(stem)
    return tiles_dir(project_root) / f"{tid}.json"


def list_tileset_json_stems(project_root: Path) -> list[str]:
    d = tiles_dir(project_root)
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json") if p.is_file())


def read_tileset_file(project_root: Path, stem: str) -> dict[str, Any]:
    p = tileset_json_path(project_root, stem)
    if not p.is_file():
        raise ValueError(f"no existe el tileset {stem}.json en tiles/")
    try:
        data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON invalido en tiles/{stem}.json") from e
    if not isinstance(data, dict):
        raise ValueError(f"tiles/{stem}.json: raiz debe ser un objeto")
    if data.get("kind") != TILESET_JSON_KIND:
        raise ValueError(
            f"tiles/{stem}.json: kind esperado {TILESET_JSON_KIND!r}"
        )
    return data


def tileset_file_pixel_dimensions(data: dict[str, Any]) -> int:
    """Lado del tile en px declarado en el tileset (cuadrado)."""
    try:
        px = int(data.get("tile_px", DEFAULT_TILE_PX))
    except (TypeError, ValueError):
        px = DEFAULT_TILE_PX
    return normalize_tile_px(px)


def _pack_tile_image(rows: list[list[int]], *, pw: int, ph: int, fill_index: int) -> dict[str, Any]:
    norm = trim_palette_rows(rows, pw, ph, fill_index=fill_index)
    return {"format": SPRITE_IMAGE_FORMAT_ROWS, "rows": norm}


def parse_tileset_all_tiles(
    data: dict[str, Any],
    *,
    fill_index: int = 0,
) -> list[list[list[int]]]:
    """Lista de matrices [tile][y][x]; fila 0 arriba."""
    px = tileset_file_pixel_dimensions(data)
    raw = data.get("tiles")
    if not isinstance(raw, list) or not raw:
        return []
    out: list[list[list[int]]] = []
    for entry in raw:
        parsed: list[list[int]] | None = None
        if isinstance(entry, dict):
            im = entry.get("image")
            if isinstance(im, dict):
                parsed = _parse_palette_rows_from_image_dict(im, pw=px, ph=px)
            elif entry.get("format") == SPRITE_IMAGE_FORMAT_ROWS:
                parsed = _parse_palette_rows_from_image_dict(entry, pw=px, ph=px)
        if parsed is None:
            parsed = solid_fill_indices(px, px, fill_index)
        out.append(parsed)
    return out


def serialize_tileset_tiles(
    tiles_rows: list[list[list[int]]],
    *,
    pw: int,
    ph: int,
    fill_index: int = 0,
) -> list[dict[str, Any]]:
    fi = max(0, int(fill_index))
    return [
        {"image": _pack_tile_image(rows, pw=pw, ph=ph, fill_index=fi)}
        for rows in tiles_rows
    ]


def tileset_payload(
    tileset_id: str,
    *,
    palette_rel: str,
    tile_px: int,
    tiles_rows: list[list[list[int]]],
    fill_index: int = 0,
) -> dict[str, object]:
    tid = validate_tileset_id(tileset_id)
    pal = normalize_palette_rel(palette_rel)
    px = normalize_tile_px(tile_px)
    return {
        "format_version": TILESET_JSON_VERSION,
        "kind": TILESET_JSON_KIND,
        "id": tid,
        "notes": "",
        "palette": pal,
        "tile_px": px,
        "tiles": serialize_tileset_tiles(
            tiles_rows, pw=px, ph=px, fill_index=fill_index
        ),
    }


def save_tileset_json(
    project_root: Path,
    tileset_id: str,
    *,
    palette_rel: str,
    tile_px: int,
    tiles_rows: list[list[list[int]]],
    fill_index: int = 0,
) -> Path:
    tid = validate_tileset_id(tileset_id)
    pal_ok = validate_palette_file_under_project(project_root, palette_rel)
    px = normalize_tile_px(tile_px)
    d = tiles_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{tid}.json"
    previous: dict[str, Any] | None = None
    if path.is_file():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(previous, dict):
                previous = None
        except json.JSONDecodeError:
            previous = None
    if isinstance(previous, dict):
        px = tileset_file_pixel_dimensions({**previous, "tile_px": px})
    payload = tileset_payload(
        tid,
        palette_rel=pal_ok,
        tile_px=px,
        tiles_rows=tiles_rows,
        fill_index=fill_index,
    )
    if isinstance(previous, dict) and isinstance(previous.get("notes"), str):
        payload["notes"] = previous["notes"]
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def write_tileset_json(
    project_root: Path,
    tileset_id: str,
    *,
    palette_rel: str,
    tile_px: int,
    initial_tiles: int = 1,
    fill_index: int = 0,
) -> Path:
    tid = validate_tileset_id(tileset_id)
    pal_ok = validate_palette_file_under_project(project_root, palette_rel)
    px = normalize_tile_px(tile_px)
    d = tiles_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{tid}.json"
    if path.exists():
        raise ValueError(f"ya existe tiles/{path.name}")
    n = max(1, min(MAX_TILES_PER_TILESET, int(initial_tiles)))
    fi = max(0, int(fill_index))
    tiles_rows = [solid_fill_indices(px, px, fi) for _ in range(n)]
    payload = tileset_payload(
        tid,
        palette_rel=pal_ok,
        tile_px=px,
        tiles_rows=tiles_rows,
        fill_index=fi,
    )
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def collect_tileset_stems_from_scenes(scenes: list[Any]) -> set[str]:
    """Stems de tileset referenciados en capas de tile de las escenas."""
    stems: set[str] = set()
    if not isinstance(scenes, list):
        return stems
    for row in scenes:
        if not isinstance(row, dict):
            continue
        raw = row.get("tile_layers")
        if not isinstance(raw, list):
            continue
        for ly in raw:
            if not isinstance(ly, dict):
                continue
            ts = str(ly.get("tileset", ly.get("tileset_id", ""))).strip()
            if ts:
                stems.add(ts)
    return stems


def shrink_tileset_json_for_export(data: dict[str, Any]) -> dict[str, Any]:
    """JSON minimo para sidecar / comparacion en pruebas."""
    tid = str(data.get("id", "")).strip()
    return {
        "format_version": int(data.get("format_version", TILESET_JSON_VERSION)),
        "kind": TILESET_JSON_KIND,
        "id": tid,
        "palette": str(data.get("palette", "")).strip(),
        "tile_px": tileset_file_pixel_dimensions(data),
        "tiles": data.get("tiles") if isinstance(data.get("tiles"), list) else [],
    }


def empty_tile_rows(tile_px: int, *, fill_index: int = 1) -> list[list[int]]:
    px = normalize_tile_px(tile_px)
    fi = max(0, int(fill_index))
    return solid_fill_indices(px, px, fi)
