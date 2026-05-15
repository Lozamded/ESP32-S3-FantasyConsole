"""Definicion JSON de fondos bajo `backgrounds/` (v0: paleta + relleno solido por indice)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from turtlestudio.sprites import (
    normalize_palette_rel,
    palette_paths_equivalent,
    validate_palette_file_under_project,
    validate_sprite_id,
)

BACKGROUND_JSON_VERSION = 1
BACKGROUND_JSON_KIND = "turtlestudio.background"


def backgrounds_dir(project_root: Path) -> Path:
    return project_root / "backgrounds"


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


def solid_background_payload(
    background_id: str,
    *,
    palette_rel: str,
    palette_index: int,
) -> dict[str, object]:
    bid = validate_background_id(background_id)
    pal = normalize_palette_rel(palette_rel)
    pi = max(0, int(palette_index))
    return {
        "format_version": BACKGROUND_JSON_VERSION,
        "kind": BACKGROUND_JSON_KIND,
        "id": bid,
        "notes": "",
        "palette": pal,
        "render": {
            "mode": "solid_palette_index",
            "palette_index": pi,
        },
    }


def save_solid_background_json(
    project_root: Path,
    background_id: str,
    *,
    palette_rel: str,
    palette_index: int,
) -> Path:
    """Crea o sobrescribe `backgrounds/<id>.json` (relleno solido v0)."""
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
    payload = solid_background_payload(
        bid,
        palette_rel=pal_ok,
        palette_index=palette_index,
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
) -> Path:
    bid = validate_background_id(background_id)
    pal_ok = validate_palette_file_under_project(project_root, palette_rel)
    d = backgrounds_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{bid}.json"
    if path.exists():
        raise ValueError(f"ya existe backgrounds/{path.name}")
    payload = solid_background_payload(
        bid,
        palette_rel=pal_ok,
        palette_index=palette_index,
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
    render = data.get("render")
    if not isinstance(render, dict):
        return None
    if render.get("mode") != "solid_palette_index":
        return None
    try:
        return int(render.get("palette_index", 0))
    except (TypeError, ValueError):
        return None


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
