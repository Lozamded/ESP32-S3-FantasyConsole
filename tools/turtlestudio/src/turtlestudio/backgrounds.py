"""Definicion JSON de fondos bajo `backgrounds/` (v0: solido o indexed_pixels + paleta)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from turtlestudio.project import SCENE_PIXEL_H, SCENE_PIXEL_W
from turtlestudio.sprites import (
    DEFAULT_CELL_PX,
    normalize_palette_rel,
    palette_paths_equivalent,
    parse_palette_rows_image,
    serialize_sprite_frames,
    trim_palette_rows,
    validate_palette_file_under_project,
    validate_sprite_id,
)

BACKGROUND_JSON_VERSION = 1
BACKGROUND_JSON_KIND = "turtlestudio.background"
BACKGROUND_RENDER_SOLID = "solid_palette_index"
BACKGROUND_RENDER_INDEXED = "indexed_pixels"
DEFAULT_BACKGROUND_PIXEL_W = SCENE_PIXEL_W
DEFAULT_BACKGROUND_PIXEL_H = SCENE_PIXEL_H
# Fondos mas grandes que la vista (p. ej. capas de parallax); la escena sigue siendo 264×198.
BACKGROUND_PARALLAX_FACTOR = 2
MAX_BACKGROUND_PIXEL_W = SCENE_PIXEL_W * BACKGROUND_PARALLAX_FACTOR
MAX_BACKGROUND_PIXEL_H = SCENE_PIXEL_H * BACKGROUND_PARALLAX_FACTOR


def backgrounds_dir(project_root: Path) -> Path:
    return project_root / "backgrounds"


def list_palette_relpaths(project_root: Path) -> list[str]:
    """Archivos `palettes/*.txt` relativos al proyecto (POSIX)."""
    d = project_root / "palettes"
    if not d.is_dir():
        return []
    return sorted(
        p.relative_to(project_root).as_posix()
        for p in d.glob("*.txt")
        if p.is_file()
    )


def validate_background_id(raw: str) -> str:
    return validate_sprite_id(raw)


def background_json_path(project_root: Path, stem: str) -> Path:
    bid = validate_background_id(stem)
    return backgrounds_dir(project_root) / f"{bid}.json"


def list_background_json_stems(project_root: Path) -> list[str]:
    d = backgrounds_dir(project_root)
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def list_background_stems_for_palette(project_root: Path, scene_palette_rel: str) -> list[str]:
    """Stems en `backgrounds/` cuyo JSON declara la misma paleta (ruta relativa) que `scene_palette_rel`."""
    if not str(scene_palette_rel).strip():
        return []
    sp = normalize_palette_rel(scene_palette_rel)
    out: list[str] = []
    for stem in list_background_json_stems(project_root):
        try:
            data = read_background_file(project_root, stem)
        except ValueError:
            continue
        opal = str(data.get("palette", "")).strip()
        if opal and palette_paths_equivalent(opal, sp):
            out.append(stem)
    return sorted(out)


def read_background_file(project_root: Path, stem: str) -> dict[str, Any]:
    p = background_json_path(project_root, stem)
    if not p.is_file():
        raise ValueError(f"no existe el fondo {stem}.json en backgrounds/")
    try:
        data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON invalido en backgrounds/{stem}.json") from e
    if not isinstance(data, dict):
        raise ValueError(f"backgrounds/{stem}.json: raiz debe ser un objeto")
    if data.get("kind") != BACKGROUND_JSON_KIND:
        raise ValueError(
            f"backgrounds/{stem}.json: kind esperado {BACKGROUND_JSON_KIND!r}"
        )
    return data


def background_pixel_dimensions(data: dict[str, Any]) -> tuple[int, int]:
    """Devuelve (pixel_w, pixel_h) acotados al tamano de escena."""
    try:
        pw = int(data.get("pixel_w", DEFAULT_BACKGROUND_PIXEL_W))
    except (TypeError, ValueError):
        pw = DEFAULT_BACKGROUND_PIXEL_W
    try:
        ph = int(data.get("pixel_h", DEFAULT_BACKGROUND_PIXEL_H))
    except (TypeError, ValueError):
        ph = DEFAULT_BACKGROUND_PIXEL_H
    pw = max(1, min(MAX_BACKGROUND_PIXEL_W, pw))
    ph = max(1, min(MAX_BACKGROUND_PIXEL_H, ph))
    return pw, ph


def background_is_indexed_pixels(data: dict[str, Any]) -> bool:
    render = data.get("render")
    return isinstance(render, dict) and render.get("mode") == BACKGROUND_RENDER_INDEXED


def parse_background_palette_rows(data: dict[str, Any]) -> list[list[int]] | None:
    """Matriz de indices (fila 0 arriba), o None si no es indexed_pixels."""
    if not background_is_indexed_pixels(data):
        return None
    from turtlestudio.sprites import parse_palette_rows_for_dimensions

    pw, ph = background_pixel_dimensions(data)
    return parse_palette_rows_for_dimensions(data, pw=pw, ph=ph)


def parse_background_solid_palette_index(data: dict[str, Any]) -> int:
    render = data.get("render")
    if not isinstance(render, dict):
        return 0
    if render.get("mode") != "solid_palette_index":
        return 0
    try:
        return int(render.get("palette_index", 0))
    except (TypeError, ValueError):
        return 0


def background_scene_preview_data(
    project_root: Path,
    stem: str,
    *,
    scene_palette_rel: str,
) -> tuple[int, int, dict[str, Any]] | None:
    """(pixel_w, pixel_h, data) si el fondo aplica a la paleta de la escena."""
    s = parse_scene_background_stem(
        project_root,
        stem,
        scene_palette_rel=scene_palette_rel,
    )
    if not s:
        return None
    try:
        data = read_background_file(project_root, s)
    except ValueError:
        return None
    pw, ph = background_pixel_dimensions(data)
    return pw, ph, data


def background_solid_preview_info(
    project_root: Path,
    stem: str,
    *,
    scene_palette_rel: str,
) -> tuple[int, int, int] | None:
    """(pixel_w, pixel_h, palette_index) si el fondo es solido y la paleta coincide."""
    got = background_scene_preview_data(
        project_root, stem, scene_palette_rel=scene_palette_rel
    )
    if got is None:
        return None
    pw, ph, data = got
    if background_is_indexed_pixels(data):
        return None
    return pw, ph, parse_background_solid_palette_index(data)


def indexed_background_payload(
    background_id: str,
    *,
    palette_rel: str,
    rows: list[list[int]],
    pixel_w: int | None = None,
    pixel_h: int | None = None,
    fill_index: int = 0,
) -> dict[str, object]:
    bid = validate_background_id(background_id)
    pal = normalize_palette_rel(palette_rel)
    pw = DEFAULT_BACKGROUND_PIXEL_W if pixel_w is None else max(1, min(MAX_BACKGROUND_PIXEL_W, int(pixel_w)))
    ph = DEFAULT_BACKGROUND_PIXEL_H if pixel_h is None else max(1, min(MAX_BACKGROUND_PIXEL_H, int(pixel_h)))
    from turtlestudio.palette_policy import clamp_pixel_storage_index

    fi = clamp_pixel_storage_index(fill_index)
    norm = trim_palette_rows(rows, pw, ph, fill_index=fi)
    image0, _, _ = serialize_sprite_frames([norm], pw=pw, ph=ph, fill_index=fi)
    return {
        "format_version": BACKGROUND_JSON_VERSION,
        "kind": BACKGROUND_JSON_KIND,
        "id": bid,
        "notes": "",
        "palette": pal,
        "pixel_w": pw,
        "pixel_h": ph,
        "cell_px": DEFAULT_CELL_PX,
        "render": {"mode": BACKGROUND_RENDER_INDEXED},
        "image": image0,
    }


def solid_background_payload(
    background_id: str,
    *,
    palette_rel: str,
    palette_index: int,
    pixel_w: int | None = None,
    pixel_h: int | None = None,
) -> dict[str, object]:
    bid = validate_background_id(background_id)
    pal = normalize_palette_rel(palette_rel)
    pi = max(0, int(palette_index))
    pw = DEFAULT_BACKGROUND_PIXEL_W if pixel_w is None else max(1, min(MAX_BACKGROUND_PIXEL_W, int(pixel_w)))
    ph = DEFAULT_BACKGROUND_PIXEL_H if pixel_h is None else max(1, min(MAX_BACKGROUND_PIXEL_H, int(pixel_h)))
    return {
        "format_version": BACKGROUND_JSON_VERSION,
        "kind": BACKGROUND_JSON_KIND,
        "id": bid,
        "notes": "",
        "palette": pal,
        "pixel_w": pw,
        "pixel_h": ph,
        "cell_px": DEFAULT_CELL_PX,
        "render": {
            "mode": "solid_palette_index",
            "palette_index": pi,
        },
    }


def save_background_json(
    project_root: Path,
    background_id: str,
    *,
    palette_rel: str,
    pixel_w: int,
    pixel_h: int,
    palette_index: int = 0,
    rows: list[list[int]] | None = None,
) -> Path:
    """Crea o sobrescribe `backgrounds/<id>.json` (solido o indexed_pixels)."""
    if rows is not None:
        return save_indexed_background_json(
            project_root,
            background_id,
            palette_rel=palette_rel,
            rows=rows,
            pixel_w=pixel_w,
            pixel_h=pixel_h,
            fill_index=palette_index,
        )
    return save_solid_background_json(
        project_root,
        background_id,
        palette_rel=palette_rel,
        palette_index=palette_index,
        pixel_w=pixel_w,
        pixel_h=pixel_h,
    )


def save_indexed_background_json(
    project_root: Path,
    background_id: str,
    *,
    palette_rel: str,
    rows: list[list[int]],
    pixel_w: int | None = None,
    pixel_h: int | None = None,
    fill_index: int = 0,
) -> Path:
    bid = validate_background_id(background_id)
    pal_ok = validate_palette_file_under_project(project_root, palette_rel)
    d = backgrounds_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{bid}.json"
    previous: dict[str, Any] | None = None
    if path.is_file():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(previous, dict):
                previous = None
        except json.JSONDecodeError:
            previous = None
    pw_i = pixel_w
    ph_i = pixel_h
    if pw_i is None and isinstance(previous, dict):
        pw_i, ph_i = background_pixel_dimensions(previous)
    payload = indexed_background_payload(
        bid,
        palette_rel=pal_ok,
        rows=rows,
        pixel_w=pw_i,
        pixel_h=ph_i,
        fill_index=fill_index,
    )
    if isinstance(previous, dict) and isinstance(previous.get("notes"), str):
        payload["notes"] = previous["notes"]
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def save_solid_background_json(
    project_root: Path,
    background_id: str,
    *,
    palette_rel: str,
    palette_index: int,
    pixel_w: int | None = None,
    pixel_h: int | None = None,
) -> Path:
    """Crea o sobrescribe `backgrounds/<id>.json` (relleno solido v0)."""
    bid = validate_background_id(background_id)
    from turtlestudio.palette_policy import clamp_paint_palette_index
    from turtlestudio.project import _palette_n_colors

    pal_ok = validate_palette_file_under_project(project_root, palette_rel)
    n_colors = _palette_n_colors((project_root / pal_ok).resolve())
    palette_index = clamp_paint_palette_index(palette_index, palette_len=n_colors)
    d = backgrounds_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{bid}.json"
    previous: dict[str, Any] | None = None
    if path.is_file():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(previous, dict):
                previous = None
        except json.JSONDecodeError:
            previous = None
    pw_i = pixel_w
    ph_i = pixel_h
    if pw_i is None and isinstance(previous, dict):
        pw_i, ph_i = background_pixel_dimensions(previous)
    payload = solid_background_payload(
        bid,
        palette_rel=pal_ok,
        palette_index=palette_index,
        pixel_w=pw_i,
        pixel_h=ph_i,
    )
    if isinstance(previous, dict) and isinstance(previous.get("notes"), str):
        payload["notes"] = previous["notes"]
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def write_solid_background_json(
    project_root: Path,
    background_id: str,
    *,
    palette_rel: str,
    palette_index: int,
    pixel_w: int | None = None,
    pixel_h: int | None = None,
) -> Path:
    bid = validate_background_id(background_id)
    from turtlestudio.palette_policy import clamp_paint_palette_index
    from turtlestudio.project import _palette_n_colors

    pal_ok = validate_palette_file_under_project(project_root, palette_rel)
    n_colors = _palette_n_colors((project_root / pal_ok).resolve())
    palette_index = clamp_paint_palette_index(palette_index, palette_len=n_colors)
    d = backgrounds_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{bid}.json"
    if path.exists():
        raise ValueError(f"ya existe backgrounds/{path.name}")
    payload = solid_background_payload(
        bid,
        palette_rel=pal_ok,
        palette_index=palette_index,
        pixel_w=pixel_w,
        pixel_h=pixel_h,
    )
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def parse_scene_background_stem(
    project_root: Path,
    raw: Any,
    *,
    scene_palette_rel: str,
) -> str:
    """Stem valido y coherente con la paleta de la escena, o cadena vacia."""
    if not isinstance(raw, str) or not raw.strip():
        return ""
    try:
        stem = validate_background_id(raw.strip())
    except ValueError:
        return ""
    sp = normalize_palette_rel(scene_palette_rel)
    if not sp:
        return ""
    try:
        data = read_background_file(project_root, stem)
    except ValueError:
        return ""
    opal = str(data.get("palette", "")).strip()
    if not opal or not palette_paths_equivalent(opal, sp):
        return ""
    return stem


def scene_background_solid_palette_index(
    project_root: Path,
    stem: str,
    *,
    scene_palette_rel: str,
) -> int | None:
    """
    Si el fondo es relleno solido por indice y la paleta coincide con la escena,
    devuelve el indice en la paleta compartida; si no aplica, None.
    """
    info = background_solid_preview_info(
        project_root, stem, scene_palette_rel=scene_palette_rel
    )
    if info is None:
        return None
    return info[2]


def validate_scene_background_for_save(
    project_root: Path,
    raw_stem: Any,
    *,
    scene_palette_rel: str,
) -> str:
    """Para guardar manifest: stem normalizado o vacio si no es valido."""
    if not isinstance(raw_stem, str) or not raw_stem.strip():
        return ""
    return parse_scene_background_stem(
        project_root,
        raw_stem.strip(),
        scene_palette_rel=scene_palette_rel,
    )
