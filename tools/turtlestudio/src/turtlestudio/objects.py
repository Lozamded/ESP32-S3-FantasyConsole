"""Definicion JSON de objetos de juego (v0: nombre + sprite asociado)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from turtlestudio.sprites import (
    normalize_palette_rel,
    palette_paths_equivalent,
    read_sprite_file,
    sprite_json_path,
    validate_sprite_id,
)

OBJECT_JSON_VERSION = 1
OBJECT_JSON_KIND = "turtlestudio.object"


def objects_dir(project_root: Path) -> Path:
    return project_root / "objects" / "Objects"


def validate_object_id(raw: str) -> str:
    """Mismo criterio que IDs de sprite (nombre de archivo .json)."""
    return validate_sprite_id(raw)


def validate_sprite_ref(project_root: Path, sprite_id: str) -> str:
    sid = validate_sprite_id(sprite_id)
    sp = sprite_json_path(project_root, sid)
    if not sp.is_file():
        raise ValueError(f"no existe el sprite {sid}.json en objects/Sprites/")
    return sid


def list_object_ids_for_scene_palette(project_root: Path, scene_palette_rel: str) -> list[str]:
    """
    IDs de objeto cuyo sprite declara la misma paleta (ruta relativa) que la escena.
    """
    if not scene_palette_rel.strip():
        return []
    sp = normalize_palette_rel(scene_palette_rel)
    out: list[str] = []
    for oid in list_object_json_stems(project_root):
        try:
            od = read_object_file(project_root, oid)
        except ValueError:
            continue
        spr = str(od.get("sprite_id", "")).strip()
        if not spr:
            continue
        try:
            sd = read_sprite_file(project_root, spr)
        except ValueError:
            continue
        opal = str(sd.get("palette", "")).strip()
        if opal and palette_paths_equivalent(opal, sp):
            out.append(oid)
    return sorted(out)


def object_payload(
    object_id: str,
    *,
    name: str,
    sprite_id: str,
) -> dict[str, object]:
    oid = validate_object_id(object_id)
    display = name.strip() or oid
    return {
        "format_version": OBJECT_JSON_VERSION,
        "kind": OBJECT_JSON_KIND,
        "id": oid,
        "name": display,
        "sprite_id": sprite_id,
    }


def object_json_path(project_root: Path, stem: str) -> Path:
    return objects_dir(project_root) / f"{stem}.json"


def read_object_file(project_root: Path, stem: str) -> dict[str, Any]:
    p = object_json_path(project_root, stem)
    if not p.is_file():
        raise ValueError(f"no existe el objeto {stem}.json")
    try:
        data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON invalido en {stem}.json") from e
    if not isinstance(data, dict):
        raise ValueError(f"{stem}.json: raiz debe ser un objeto")
    return data


def write_object_json(
    project_root: Path,
    object_id: str,
    *,
    name: str,
    sprite_id: str,
) -> Path:
    oid = validate_object_id(object_id)
    sprite_ok = validate_sprite_ref(project_root, sprite_id)
    d = objects_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{oid}.json"
    if path.exists():
        raise ValueError(f"ya existe {path.name}")
    payload = object_payload(oid, name=name, sprite_id=sprite_ok)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def save_object_json(
    project_root: Path,
    object_id: str,
    *,
    name: str,
    sprite_id: str,
) -> Path:
    oid = validate_object_id(object_id)
    sprite_ok = validate_sprite_ref(project_root, sprite_id)
    d = objects_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{oid}.json"
    payload = object_payload(oid, name=name, sprite_id=sprite_ok)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def list_object_json_stems(project_root: Path) -> list[str]:
    d = objects_dir(project_root)
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json"))
