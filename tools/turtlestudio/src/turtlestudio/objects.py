"""Definicion JSON de objetos de juego (v0: nombre + sprite asociado + animaciones)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, TypedDict

from turtlestudio.project import validate_lua_script_stem
from turtlestudio.sprites import (
    normalize_palette_rel,
    palette_paths_equivalent,
    parse_sprite_origin,
    read_sprite_file,
    sprite_json_path,
    sprite_pixel_dimensions,
    validate_sprite_id,
)

OBJECT_JSON_VERSION = 1
OBJECT_JSON_KIND = "turtlestudio.object"
MAX_OBJECT_ANIMATIONS = 32
_OBJECT_ANIM_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,31}$")
OBJECT_COLLISION_MODE_AABB = "aabb"
OBJECT_COLLISION_MODE_TRIANGLE = "triangle"
OBJECT_COLLISION_MODE_HEXAGON = "hexagon"
OBJECT_COLLISION_MODES = (
    OBJECT_COLLISION_MODE_AABB,
    OBJECT_COLLISION_MODE_TRIANGLE,
    OBJECT_COLLISION_MODE_HEXAGON,
)
MAX_COLLISION_SPAN_PX = 256
ObjectCollision = dict[str, Any]


class ObjectCollisionAabb(TypedDict):
    """Compat: collision.mode == aabb."""

    mode: str
    x0: int
    y0: int
    x1: int
    y1: int


def objects_dir(project_root: Path) -> Path:
    return project_root / "objects" / "Objects"


def validate_object_id(raw: str) -> str:
    """Mismo criterio que IDs de sprite (nombre de archivo .json)."""
    return validate_sprite_id(raw)


def validate_animation_name(raw: str) -> str:
    s = raw.strip()
    if not s:
        raise ValueError("nombre de animacion vacio")
    if not _OBJECT_ANIM_NAME_RE.match(s):
        raise ValueError(
            "nombre de animacion invalido (letra inicial, luego letras, digitos, _ o -; max 32)"
        )
    return s


def validate_sprite_ref(project_root: Path, sprite_id: str) -> str:
    sid = validate_sprite_id(sprite_id)
    sp = sprite_json_path(project_root, sid)
    if not sp.is_file():
        raise ValueError(f"no existe el sprite {sid}.json en objects/Sprites/")
    return sid


def parse_object_animations(data: dict[str, Any]) -> list[dict[str, str]]:
    """Lista {name, sprite_id} desde JSON (sin validar disco)."""
    raw = data.get("animations")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            name = validate_animation_name(str(item.get("name", "")))
        except ValueError:
            continue
        sid = str(item.get("sprite_id", "")).strip()
        if not sid:
            continue
        out.append({"name": name, "sprite_id": sid})
    return out


def normalize_object_animations(
    project_root: Path,
    animations: list[dict[str, str]] | None,
) -> list[dict[str, str]]:
    """Valida nombres unicos, sprites existentes y limite de entradas."""
    if not animations:
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in animations:
        if not isinstance(item, dict):
            continue
        name = validate_animation_name(str(item.get("name", "")))
        if name in seen:
            raise ValueError(f"animacion duplicada: {name!r}")
        seen.add(name)
        sid = validate_sprite_ref(
            project_root, str(item.get("sprite_id", "")).strip()
        )
        out.append({"name": name, "sprite_id": sid})
        if len(out) > MAX_OBJECT_ANIMATIONS:
            raise ValueError(
                f"demasiadas animaciones (max {MAX_OBJECT_ANIMATIONS})"
            )
    return out


def parse_object_script(data: dict[str, Any]) -> str | None:
    """Stem scripts/<stem>.lua en el JSON del objeto; None si no hay script."""
    raw = data.get("script")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return validate_lua_script_stem(raw.strip())
    except ValueError:
        return None


def normalize_object_script(raw: Any) -> str | None:
    """Valida stem de script de objeto; None = sin script asociado."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    return validate_lua_script_stem(raw.strip())


def object_sprite_ids_for_bundle(od: dict[str, Any]) -> list[str]:
    """Sprites referenciados por un objeto (default + animaciones)."""
    ids: list[str] = []
    base = str(od.get("sprite_id", "")).strip()
    if base:
        ids.append(base)
    for anim in parse_object_animations(od):
        sid = anim["sprite_id"]
        if sid and sid not in ids:
            ids.append(sid)
    return ids


def _clamp_collision_coord(v: int) -> int:
    return max(-MAX_COLLISION_SPAN_PX, min(MAX_COLLISION_SPAN_PX, int(v)))


def _sprite_local_aabb(sprite_data: dict[str, Any]) -> tuple[int, int, int, int]:
    """Esquina inferior izquierda y superior derecha del bbox del sprite (ancla en 0,0)."""
    _, pw, ph = sprite_pixel_dimensions(sprite_data)
    ox, oy = parse_sprite_origin(sprite_data, pw=pw, ph=ph)
    return (-int(ox), -int(oy), int(pw - 1 - ox), int(ph - 1 - oy))


def _parse_collision_points(raw: object) -> list[list[int]] | None:
    if not isinstance(raw, list):
        return None
    pts: list[list[int]] = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            return None
        try:
            pts.append(
                [
                    _clamp_collision_coord(item[0]),
                    _clamp_collision_coord(item[1]),
                ]
            )
        except (TypeError, ValueError):
            return None
    return pts


def _validate_point_span(points: list[list[int]]) -> None:
    if not points:
        raise ValueError("collision: faltan puntos")
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    if max(xs) - min(xs) > MAX_COLLISION_SPAN_PX:
        raise ValueError(
            f"collision: anchura > {MAX_COLLISION_SPAN_PX} px"
        )
    if max(ys) - min(ys) > MAX_COLLISION_SPAN_PX:
        raise ValueError(
            f"collision: altura > {MAX_COLLISION_SPAN_PX} px"
        )


def collision_to_json(collision: ObjectCollision) -> dict[str, object]:
    mode = str(collision["mode"])
    if mode == OBJECT_COLLISION_MODE_AABB:
        return {
            "mode": mode,
            "x0": int(collision["x0"]),
            "y0": int(collision["y0"]),
            "x1": int(collision["x1"]),
            "y1": int(collision["y1"]),
        }
    return {
        "mode": mode,
        "points": [[int(p[0]), int(p[1])] for p in collision["points"]],
    }


def default_collision_from_sprite(
    sprite_data: dict[str, Any],
    mode: str = OBJECT_COLLISION_MODE_AABB,
) -> ObjectCollision:
    """Forma por defecto inscrita en el bbox del sprite (ancla = origen)."""
    x0, y0, x1, y1 = _sprite_local_aabb(sprite_data)
    m = str(mode).strip()
    if m == OBJECT_COLLISION_MODE_TRIANGLE:
        return {
            "mode": OBJECT_COLLISION_MODE_TRIANGLE,
            "points": [
                [x0, y0],
                [x1, y0],
                [(x0 + x1) // 2, y1],
            ],
        }
    if m == OBJECT_COLLISION_MODE_HEXAGON:
        w = x1 - x0
        h = y1 - y0
        cy = y0 + h // 2
        return {
            "mode": OBJECT_COLLISION_MODE_HEXAGON,
            "points": [
                [x0 + w // 4, y0],
                [x1 - w // 4, y0],
                [x1, cy],
                [x1 - w // 4, y1],
                [x0 + w // 4, y1],
                [x0, cy],
            ],
        }
    return {
        "mode": OBJECT_COLLISION_MODE_AABB,
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1,
    }


def parse_object_collision(data: dict[str, Any]) -> ObjectCollision | None:
    raw = data.get("collision")
    if not isinstance(raw, dict):
        return None
    mode = str(raw.get("mode", OBJECT_COLLISION_MODE_AABB)).strip()
    if mode == OBJECT_COLLISION_MODE_AABB:
        try:
            return {
                "mode": mode,
                "x0": int(raw.get("x0", 0)),
                "y0": int(raw.get("y0", 0)),
                "x1": int(raw.get("x1", 0)),
                "y1": int(raw.get("y1", 0)),
            }
        except (TypeError, ValueError):
            return None
    if mode in (OBJECT_COLLISION_MODE_TRIANGLE, OBJECT_COLLISION_MODE_HEXAGON):
        pts = _parse_collision_points(raw.get("points"))
        if pts is None:
            return None
        return {"mode": mode, "points": pts}
    return None


def normalize_object_collision(
    collision: dict[str, Any] | ObjectCollisionAabb | None,
) -> ObjectCollision | None:
    if collision is None:
        return None
    if not isinstance(collision, dict):
        raise ValueError("collision: debe ser un objeto")
    mode = str(collision.get("mode", OBJECT_COLLISION_MODE_AABB)).strip()
    if mode not in OBJECT_COLLISION_MODES:
        raise ValueError(
            f"collision.mode no soportado: {mode!r} "
            f"(usa {', '.join(OBJECT_COLLISION_MODES)})"
        )
    if mode == OBJECT_COLLISION_MODE_AABB:
        try:
            x0 = _clamp_collision_coord(collision.get("x0", 0))
            y0 = _clamp_collision_coord(collision.get("y0", 0))
            x1 = _clamp_collision_coord(collision.get("x1", 0))
            y1 = _clamp_collision_coord(collision.get("y1", 0))
        except (TypeError, ValueError) as e:
            raise ValueError("collision: x0,y0,x1,y1 deben ser enteros") from e
        if x1 < x0:
            raise ValueError("collision: x1 debe ser >= x0")
        if y1 < y0:
            raise ValueError("collision: y1 debe ser >= y0")
        if (x1 - x0) > MAX_COLLISION_SPAN_PX or (y1 - y0) > MAX_COLLISION_SPAN_PX:
            raise ValueError(
                f"collision: caja demasiado grande (max {MAX_COLLISION_SPAN_PX} px por eje)"
            )
        return {
            "mode": OBJECT_COLLISION_MODE_AABB,
            "x0": x0,
            "y0": y0,
            "x1": x1,
            "y1": y1,
        }
    raw_pts = collision.get("points")
    if not isinstance(raw_pts, list):
        raise ValueError("collision: points debe ser una lista de [x,y]")
    pts: list[list[int]] = []
    for item in raw_pts:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            raise ValueError("collision: cada punto es [x, y]")
        try:
            pts.append(
                [
                    _clamp_collision_coord(item[0]),
                    _clamp_collision_coord(item[1]),
                ]
            )
        except (TypeError, ValueError) as e:
            raise ValueError("collision: coordenadas de punto invalidas") from e
    need = 3 if mode == OBJECT_COLLISION_MODE_TRIANGLE else 6
    if len(pts) != need:
        raise ValueError(f"collision {mode}: se requieren {need} puntos")
    _validate_point_span(pts)
    return {"mode": mode, "points": pts}


def default_collision_for_sprite_ref(
    project_root: Path,
    sprite_id: str,
    mode: str = OBJECT_COLLISION_MODE_AABB,
) -> ObjectCollision:
    sd = read_sprite_file(project_root, sprite_id)
    return default_collision_from_sprite(sd, mode=mode)


def list_object_ids_for_scene_palette(project_root: Path, scene_palette_rel: str) -> list[str]:
    """
    IDs de objeto cuyo sprite (por defecto o en alguna animacion) declara la misma
    paleta (ruta relativa) que la escena.
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
        sprite_ids = object_sprite_ids_for_bundle(od)
        if not sprite_ids:
            continue
        matched = False
        for spr in sprite_ids:
            try:
                sd = read_sprite_file(project_root, spr)
            except ValueError:
                continue
            opal = str(sd.get("palette", "")).strip()
            if opal and palette_paths_equivalent(opal, sp):
                matched = True
                break
        if matched:
            out.append(oid)
    return sorted(out)


def object_payload(
    object_id: str,
    *,
    name: str,
    sprite_id: str,
    animations: list[dict[str, str]] | None = None,
    collision: ObjectCollision | None = None,
    script: str | None = None,
    solid: bool = False,
) -> dict[str, object]:
    oid = validate_object_id(object_id)
    display = name.strip() or oid
    payload: dict[str, object] = {
        "format_version": OBJECT_JSON_VERSION,
        "kind": OBJECT_JSON_KIND,
        "id": oid,
        "name": display,
        "sprite_id": sprite_id,
    }
    if script:
        payload["script"] = script
    anims = animations or []
    if anims:
        payload["animations"] = [
            {"name": a["name"], "sprite_id": a["sprite_id"]} for a in anims
        ]
    if collision is not None:
        payload["collision"] = collision_to_json(collision)
    if solid:
        payload["solid"] = True
    return payload


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
    animations: list[dict[str, str]] | None = None,
    collision: ObjectCollision | None = None,
    script: str | None = None,
    solid: bool = False,
) -> Path:
    oid = validate_object_id(object_id)
    sprite_ok = validate_sprite_ref(project_root, sprite_id)
    anims_ok = normalize_object_animations(project_root, animations)
    coll_ok = normalize_object_collision(collision)
    script_ok = normalize_object_script(script)
    d = objects_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{oid}.json"
    if path.exists():
        raise ValueError(f"ya existe {path.name}")
    payload = object_payload(
        oid,
        name=name,
        sprite_id=sprite_ok,
        animations=anims_ok,
        collision=coll_ok,
        script=script_ok,
        solid=solid,
    )
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
    animations: list[dict[str, str]] | None = None,
    collision: ObjectCollision | None = None,
    script: str | None = None,
    solid: bool = False,
) -> Path:
    oid = validate_object_id(object_id)
    sprite_ok = validate_sprite_ref(project_root, sprite_id)
    anims_ok = normalize_object_animations(project_root, animations)
    coll_ok = normalize_object_collision(collision)
    script_ok = normalize_object_script(script)
    d = objects_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{oid}.json"
    payload = object_payload(
        oid,
        name=name,
        sprite_id=sprite_ok,
        animations=anims_ok,
        collision=coll_ok,
        script=script_ok,
        solid=solid,
    )
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
