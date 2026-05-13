"""Definicion JSON de sprites (v0: paleta propia del sprite + bloques 8x8 + indice de color)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from turtlestudio.project import DEFAULT_EXAMPLE_PALETTE_REL

SPRITE_JSON_VERSION = 1
SPRITE_JSON_KIND = "turtlestudio.sprite"
# Tamano logico en celdas de 8x8 (evita sprites enormes en disco por error).
MAX_BLOCKS_PER_AXIS = 32
DEFAULT_CELL_PX = 8
_SPRITE_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")


def sprites_dir(project_root: Path) -> Path:
    return project_root / "objects" / "Sprites"


def validate_sprite_id(sprite_id: str) -> str:
    s = sprite_id.strip()
    if not s:
        raise ValueError("ID vacio")
    if not _SPRITE_ID_RE.match(s):
        raise ValueError(
            "ID invalido (letra inicial, luego letras, digitos, _ o -; max 64 chars)"
        )
    return s


def normalize_palette_rel(raw: str) -> str:
    """Ruta relativa al proyecto, estilo POSIX (como escenas en turtlestudio.json)."""
    s = raw.strip().replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    return s


def validate_palette_file_under_project(project_root: Path, raw_rel: str) -> str:
    """Devuelve la ruta relativa normalizada; el archivo debe existir bajo project_root."""
    rel = normalize_palette_rel(raw_rel)
    if not rel:
        raise ValueError("paleta del sprite: indica una ruta (ej. palettes/palette.txt)")
    abs_p = (project_root / rel).resolve()
    root_r = project_root.resolve()
    try:
        abs_p.relative_to(root_r)
    except ValueError as e:
        raise ValueError("paleta del sprite: la ruta debe estar dentro del proyecto") from e
    if not abs_p.is_file():
        raise ValueError(f"paleta del sprite no encontrada: {rel}")
    return rel


def palette_paths_equivalent(a: str, b: str) -> bool:
    """Misma paleta en disco (para validar sprite vs escena mas adelante)."""
    return normalize_palette_rel(a) == normalize_palette_rel(b)


def solid_sprite_payload(
    sprite_id: str,
    *,
    palette_rel: str,
    blocks_w: int,
    blocks_h: int,
    palette_index: int,
    cell_px: int = DEFAULT_CELL_PX,
) -> dict[str, object]:
    """Sprite v0: rectangulo lleno; indice respecto a la paleta propia del sprite (no la de la escena)."""
    pal = normalize_palette_rel(palette_rel)
    bw = max(1, min(int(blocks_w), MAX_BLOCKS_PER_AXIS))
    bh = max(1, min(int(blocks_h), MAX_BLOCKS_PER_AXIS))
    cp = max(1, min(int(cell_px), 256))
    pi = max(0, int(palette_index))
    return {
        "format_version": SPRITE_JSON_VERSION,
        "kind": SPRITE_JSON_KIND,
        "id": sprite_id,
        "notes": "",
        "palette": pal,
        "cell_px": cp,
        "blocks_w": bw,
        "blocks_h": bh,
        "pixel_w": bw * cp,
        "pixel_h": bh * cp,
        "render": {
            "mode": "solid_palette_index",
            "palette_index": pi,
        },
        "image": None,
        "frames": [],
    }


def sprite_json_path(project_root: Path, stem: str) -> Path:
    return sprites_dir(project_root) / f"{stem}.json"


def read_sprite_file(project_root: Path, stem: str) -> dict[str, Any]:
    p = sprite_json_path(project_root, stem)
    if not p.is_file():
        raise ValueError(f"no existe el sprite {stem}.json")
    try:
        data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON invalido en {stem}.json") from e
    if not isinstance(data, dict):
        raise ValueError(f"{stem}.json: raiz debe ser un objeto")
    return data


def _preserve_sprite_extras(new: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    if not previous:
        return new
    if isinstance(previous.get("notes"), str):
        new["notes"] = previous["notes"]
    if "image" in previous:
        new["image"] = previous["image"]
    if isinstance(previous.get("frames"), list):
        new["frames"] = previous["frames"]
    return new


def write_empty_sprite_json(project_root: Path, sprite_id: str) -> Path:
    """Crea sprite por defecto 1x1 celda, indice 0, paleta de ejemplo del proyecto."""
    return write_solid_sprite_json(
        project_root,
        sprite_id,
        palette_rel=DEFAULT_EXAMPLE_PALETTE_REL,
        blocks_w=1,
        blocks_h=1,
        palette_index=0,
    )


def save_solid_sprite_json(
    project_root: Path,
    sprite_id: str,
    *,
    palette_rel: str,
    blocks_w: int,
    blocks_h: int,
    palette_index: int,
    cell_px: int | None = None,
) -> Path:
    """Crea o sobrescribe objects/Sprites/<id>.json (edicion desde GUI). Conserva notes/image/frames."""
    sid = validate_sprite_id(sprite_id)
    pal_ok = validate_palette_file_under_project(project_root, palette_rel)
    d = sprites_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{sid}.json"
    previous: dict[str, Any] | None = None
    if path.is_file():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(previous, dict):
                previous = None
        except json.JSONDecodeError:
            previous = None
    cp = DEFAULT_CELL_PX
    if cell_px is not None:
        cp = max(1, min(int(cell_px), 256))
    elif isinstance(previous, dict) and isinstance(previous.get("cell_px"), int):
        cp = max(1, min(int(previous["cell_px"]), 256))
    payload = solid_sprite_payload(
        sid,
        palette_rel=pal_ok,
        blocks_w=blocks_w,
        blocks_h=blocks_h,
        palette_index=palette_index,
        cell_px=cp,
    )
    _preserve_sprite_extras(payload, previous)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def write_solid_sprite_json(
    project_root: Path,
    sprite_id: str,
    *,
    palette_rel: str,
    blocks_w: int,
    blocks_h: int,
    palette_index: int,
    cell_px: int = DEFAULT_CELL_PX,
) -> Path:
    sid = validate_sprite_id(sprite_id)
    pal_ok = validate_palette_file_under_project(project_root, palette_rel)
    d = sprites_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{sid}.json"
    if path.exists():
        raise ValueError(f"ya existe {path.name}")
    payload = solid_sprite_payload(
        sid,
        palette_rel=pal_ok,
        blocks_w=blocks_w,
        blocks_h=blocks_h,
        palette_index=palette_index,
        cell_px=cell_px,
    )
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def list_sprite_json_stems(project_root: Path) -> list[str]:
    d = sprites_dir(project_root)
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json"))
