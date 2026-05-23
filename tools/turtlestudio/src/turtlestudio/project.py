"""Proyecto TurtleStudio: carpeta en disco + manifest JSON (`turtlestudio.json`)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MANIFEST_NAME = "turtlestudio.json"
FORMAT_VERSION = 1
# Archivo por escena bajo scenes/ (espejo legible; la fuente de verdad al abrir es el manifest).
SCENE_JSON_VERSION = 1
SCENE_JSON_KIND = "turtlestudio.scene"

from turtlestudio.palette_policy import (
    DEFAULT_TRANSPARENT_INDEX,
    PALETTE_SIZE,
    clamp_paint_palette_index,
    clamp_transparent_index,
)

# Rutas relativas al crear un proyecto (POSIX en el JSON; se crean con Path).
STANDARD_SUBDIRS: tuple[str, ...] = (
    "scenes",
    "palettes",
    "objects/Sprites",
    "objects/Objects",
    "objects/Fonts",
    "scripts",
    "backgrounds",
    "tiles",
    "audio/json",
    "audio/effects",
    "audio/music",
)

DEFAULT_ENTRY = "scripts/global.lua"
# Paleta de ejemplo (misma que el firmware por defecto); una linea #RRGGBB por color.
DEFAULT_EXAMPLE_PALETTE_REL = "palettes/palette.txt"

_SCENE_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")

# Reservado: el cartucho de arranque se llama convencionalmente main.turtlecart (no usar como id de escena).
RESERVED_SCENE_IDS: frozenset[str] = frozenset({"main"})
DEFAULT_INITIAL_SCENE_ID = "intro"

_STARTER_GLOBAL_LUA = """-- ENTRY por defecto: scripts/global.lua (arranque del cartucho)
print("Hola desde TurtleStudio (global)")
cls(1)
flip()
"""

_STARTER_SCENE_INTRO_LUA = f"""-- Script de la primera escena (scripts/{DEFAULT_INITIAL_SCENE_ID}.lua)
-- Titulo, logo, menu, etc. El ENTRY del cartucho es scripts/global.lua (solo en proyecto TurtleStudio).
"""


def manifest_path(project_root: Path) -> Path:
    return project_root / MANIFEST_NAME


def is_project_dir(project_root: Path) -> bool:
    return manifest_path(project_root).is_file()


# Tamano logico escena / vista previa canvas (spec/scene-v0.md)
SCENE_PIXEL_W = 264
SCENE_PIXEL_H = 198

BACKGROUND_LAYER_COUNT = 4


@dataclass(frozen=True)
class BackgroundLayer:
    """Capa de fondo a pantalla completa (misma area que la escena). Indices en la paleta de la escena."""

    enabled: bool
    color_index: int
    opacity: int  # 0..255 para mezcla en vista previa del estudio


_DEFAULT_SCENE_BACKGROUND_LAYERS: tuple[BackgroundLayer, ...] = (
    BackgroundLayer(True, 1, 255),
    BackgroundLayer(False, 1, 255),
    BackgroundLayer(False, 1, 255),
    BackgroundLayer(False, 1, 255),
)


@dataclass(frozen=True)
class SceneObjectPlacement:
    """Instancia en escena; x,y en espacio escena (origen abajo-izquierda, Y hacia arriba)."""

    id: str
    x: int
    y: int


def _clamp_scene_xy(x: int, y: int) -> tuple[int, int]:
    return (
        max(0, min(SCENE_PIXEL_W - 1, x)),
        max(0, min(SCENE_PIXEL_H - 1, y)),
    )


def _parse_one_scene_object(raw: Any) -> SceneObjectPlacement | None:
    from turtlestudio.objects import validate_object_id

    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        oid = validate_object_id(s)
        return SceneObjectPlacement(id=oid, x=0, y=0)
    if isinstance(raw, dict):
        rid = raw.get("id")
        if not isinstance(rid, str) or not rid.strip():
            return None
        oid = validate_object_id(rid.strip())
        try:
            xi = int(raw.get("x", 0))
            yi = int(raw.get("y", 0))
        except (TypeError, ValueError):
            xi, yi = 0, 0
        xi, yi = _clamp_scene_xy(xi, yi)
        return SceneObjectPlacement(id=oid, x=xi, y=yi)
    return None


def parse_scene_objects_raw(raw: Any) -> tuple[SceneObjectPlacement, ...]:
    if not isinstance(raw, list):
        return ()
    out: list[SceneObjectPlacement] = []
    for item in raw:
        p = _parse_one_scene_object(item)
        if p is not None:
            out.append(p)
    return tuple(out)


def normalize_scene_objects_for_save(
    root: Path,
    scene_palette_rel: str,
    raw_objs: list[Any],
) -> list[dict[str, Any]]:
    from turtlestudio.objects import list_object_ids_for_scene_palette
    from turtlestudio.sprites import normalize_palette_rel as normpal

    placements = parse_scene_objects_raw(raw_objs)
    allowed = set(list_object_ids_for_scene_palette(root, scene_palette_rel))
    sp = normpal(scene_palette_rel)
    out: list[dict[str, Any]] = []
    for p in placements:
        if p.id not in allowed:
            raise ValueError(
                f"Objeto {p.id!r}: no existe o su sprite no usa la paleta de esta escena ({sp})."
            )
        out.append({"id": p.id, "x": p.x, "y": p.y})
    return out


@dataclass(frozen=True)
class SceneEntry:
    id: str
    palette: str
    background_index: int
    objects: tuple[SceneObjectPlacement, ...] = ()
    # Stem del Lua de escena: scripts/<script>.lua (por defecto = id de escena).
    script: str = DEFAULT_INITIAL_SCENE_ID
    background_layers: tuple[BackgroundLayer, ...] = _DEFAULT_SCENE_BACKGROUND_LAYERS
    # Stem opcional: backgrounds/<stem>.json (misma paleta que la escena).
    background: str = ""
    # Hasta 4 capas de tilemap (rejilla segun `tiles.tile_px` del manifest).
    tile_layers: tuple[Any, ...] = ()


@dataclass(frozen=True)
class ProjectInfo:
    root: Path
    format_version: int
    name: str
    entry: str
    default_palette: str | None
    scenes: tuple[SceneEntry, ...]
    active_scene: str
    transparent_index: int
    tile_px: int
    target_fps: int
    default_anim_fps: int


def _posix_relpath(s: str) -> str:
    return s.replace("\\", "/")


def assert_scene_id_allowed(sid: str) -> str:
    """Ids reservados (p. ej. main = nombre del cartucho principal main.turtlecart)."""
    s = sid.strip()
    if not s:
        raise ValueError("id de escena vacio.")
    if s in RESERVED_SCENE_IDS:
        raise ValueError(
            f"id de escena {s!r} reservado (el cartucho de arranque se exporta como main.turtlecart). "
            f"Usa p. ej. {DEFAULT_INITIAL_SCENE_ID!r} para la primera escena."
        )
    return s


def validate_scene_script_stem(raw: Any, *, fallback_scene_id: str) -> str:
    """Stem del archivo scripts/<stem>.lua; mismas reglas que id de escena."""
    if isinstance(raw, str) and raw.strip():
        stem = raw.strip()
        if not _SCENE_ID_RE.match(stem):
            raise ValueError(
                f"script invalido {stem!r}: letra inicial, luego letras, digitos, _ o - (max 64 chars)."
            )
        return stem
    sid = fallback_scene_id.strip()
    if not _SCENE_ID_RE.match(sid):
        raise ValueError(f"id de escena invalido para script por defecto: {sid!r}")
    return sid


def scene_lua_relpath(stem: str) -> str:
    s = validate_scene_script_stem(stem, fallback_scene_id=stem)
    return f"scripts/{s}.lua"


def ordered_lua_relpaths_for_project(entry: str, scenes: list[dict[str, Any]]) -> tuple[str, ...]:
    """Orden estable: ENTRY primero, luego un Lua por escena (sin duplicar rutas)."""
    ent = _posix_relpath(entry.strip())
    seen: set[str] = {ent}
    out: list[str] = [ent]
    for row in scenes:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("id", "")).strip() or DEFAULT_INITIAL_SCENE_ID
        stem = validate_scene_script_stem(row.get("script"), fallback_scene_id=sid)
        rel = scene_lua_relpath(stem)
        if rel not in seen:
            seen.add(rel)
            out.append(rel)
    return tuple(out)


def _safe_lua_write_relpath(root: Path, rel: str) -> Path:
    rel = _posix_relpath(rel.strip())
    if not rel or ".." in rel.split("/"):
        raise ValueError(f"Ruta Lua invalida: {rel!r}")
    abs_p = (root / rel).resolve()
    abs_p.relative_to(root.resolve())
    return abs_p


def _clamp_transparent_index(raw: Any) -> int:
    return clamp_transparent_index(raw)


def _palette_n_colors(pal_path: Path) -> int:
    """Numero de colores validos en un archivo de paleta (lineas hex)."""
    from turtlestudio.build import DEFAULT_CONSOLE_PALETTE_HEX, load_palette_lines

    if not pal_path.is_file():
        return len(DEFAULT_CONSOLE_PALETTE_HEX)
    lines = load_palette_lines(pal_path)
    if not lines:
        return len(DEFAULT_CONSOLE_PALETTE_HEX)
    return len(lines)


def _scene_background_index(raw: Any, *, pal_path: Path) -> int:
    """Indice de color de fondo de escena (0..N-1 segun paleta). Por defecto 1 (alinea con cls(1) del starter)."""
    try:
        v = int(raw)
    except (TypeError, ValueError):
        v = 1
    n = max(1, _palette_n_colors(pal_path))
    return clamp_paint_palette_index(v, palette_len=n)


def clamp_palette_color_index(idx: int, *, n_colors: int) -> int:
    n = max(1, min(PALETTE_SIZE, int(n_colors)))
    try:
        v = int(idx)
    except (TypeError, ValueError):
        v = 0
    return clamp_paint_palette_index(v, palette_len=n)


def default_background_layers(fallback_flat_index: int) -> tuple[BackgroundLayer, ...]:
    ci = clamp_palette_color_index(fallback_flat_index, n_colors=32)
    return (
        BackgroundLayer(True, ci, 255),
        *(BackgroundLayer(False, 1, 255) for _ in range(BACKGROUND_LAYER_COUNT - 1)),
    )


def parse_background_layers(
    raw: Any,
    *,
    legacy_flat_index: int,
    n_colors: int,
) -> tuple[BackgroundLayer, ...]:
    """Cuatro capas de fondo a pantalla completa; si falta el array, se deriva de legacy_flat_index."""
    fb = clamp_palette_color_index(legacy_flat_index, n_colors=n_colors)
    if not isinstance(raw, list):
        return default_background_layers(fb)
    out: list[BackgroundLayer] = []
    for i in range(BACKGROUND_LAYER_COUNT):
        if i < len(raw) and isinstance(raw[i], dict):
            d = raw[i]
            if "enabled" in d:
                en = bool(d.get("enabled"))
            else:
                en = i == 0
            try:
                ci = int(d.get("color_index", fb if i == 0 else 1))
            except (TypeError, ValueError):
                ci = fb if i == 0 else 1
            ci = clamp_palette_color_index(ci, n_colors=n_colors)
            try:
                op = int(d.get("opacity", 255))
            except (TypeError, ValueError):
                op = 255
            op = max(0, min(255, op))
            out.append(BackgroundLayer(en, ci, op))
        else:
            out.append(BackgroundLayer(True, fb, 255) if i == 0 else BackgroundLayer(False, 1, 255))
    return tuple(out)


def firmware_background_index_from_layers(
    layers: tuple[BackgroundLayer, ...],
    *,
    fallback: int,
) -> int:
    """Indice unico para cls() en firmware hasta que soporte mezcla por capas."""
    fb = clamp_paint_palette_index(fallback, palette_len=PALETTE_SIZE)
    for ly in reversed(layers):
        if ly.enabled and ly.opacity > 0:
            return clamp_paint_palette_index(ly.color_index, palette_len=PALETTE_SIZE)
    return fb


def background_layers_to_json_list(layers: tuple[BackgroundLayer, ...]) -> list[dict[str, Any]]:
    return [
        {"enabled": ly.enabled, "color_index": ly.color_index, "opacity": ly.opacity} for ly in layers
    ]


def _parse_scenes_from_manifest(
    data: dict[str, Any],
    *,
    default_palette: str | None,
    project_root: Path,
) -> tuple[tuple[SceneEntry, ...], str, int]:
    """
    Devuelve (scenes, active_scene, transparent_index).
    Si falta `scenes` en el JSON, sintetiza una escena `intro` con la paleta por defecto del proyecto.
    """
    ti = _clamp_transparent_index(data.get("transparent_index", DEFAULT_TRANSPARENT_INDEX))
    from turtlestudio.scene_tiles import default_tile_layers, parse_tile_layers
    from turtlestudio.tiles import parse_tile_px_from_manifest

    tile_px = parse_tile_px_from_manifest(data)
    raw_scenes = data.get("scenes")
    pal_fallback = default_palette or DEFAULT_EXAMPLE_PALETTE_REL

    if not isinstance(raw_scenes, list) or len(raw_scenes) == 0:
        fb = _posix_relpath(pal_fallback)
        pal_path = (project_root / fb).resolve()
        bg = _scene_background_index(1, pal_path=pal_path)
        n_pal = _palette_n_colors(pal_path)
        layers = parse_background_layers(None, legacy_flat_index=bg, n_colors=n_pal)
        bg_fw = firmware_background_index_from_layers(layers, fallback=bg)
        scenes_list = [
            SceneEntry(
                id=DEFAULT_INITIAL_SCENE_ID,
                palette=fb,
                background_index=bg_fw,
                objects=parse_scene_objects_raw([]),
                script=DEFAULT_INITIAL_SCENE_ID,
                background_layers=layers,
                background="",
                tile_layers=default_tile_layers(tile_px),
            )
        ]
    else:
        from turtlestudio.backgrounds import parse_scene_background_stem

        parsed: list[SceneEntry] = []
        for item in raw_scenes:
            if not isinstance(item, dict):
                raise ValueError("Cada entrada de 'scenes' debe ser un objeto {id, palette, background_index?}.")
            sid = item.get("id")
            pal = item.get("palette")
            if not isinstance(sid, str) or not sid.strip():
                raise ValueError("Cada escena necesita 'id' (string no vacio).")
            if not isinstance(pal, str) or not pal.strip():
                raise ValueError(f"Escena {sid!r}: 'palette' debe ser ruta relativa no vacia.")
            sid = sid.strip()
            pal = _posix_relpath(pal.strip())
            if not _SCENE_ID_RE.match(sid):
                raise ValueError(
                    f"id de escena invalido {sid!r}: usa letras, numeros, _ y - (max 64 chars)."
                )
            assert_scene_id_allowed(sid)
            pal_path = (project_root / pal).resolve()
            try:
                pal_path.relative_to(project_root.resolve())
            except ValueError as e:
                raise ValueError(f"Escena {sid!r}: paleta sale del proyecto: {pal}") from e
            if not pal_path.is_file():
                raise ValueError(f"Escena {sid!r}: no existe la paleta {pal_path}")
            bg = _scene_background_index(
                item.get("background_index", item.get("bg_color_index", 1)),
                pal_path=pal_path,
            )
            n_pal = _palette_n_colors(pal_path)
            layers = parse_background_layers(
                item.get("background_layers"),
                legacy_flat_index=bg,
                n_colors=n_pal,
            )
            bg_fw = firmware_background_index_from_layers(layers, fallback=bg)
            raw_objs = item.get("objects", [])
            if not isinstance(raw_objs, list):
                raw_objs = []
            o_placements = parse_scene_objects_raw(raw_objs)
            stem = validate_scene_script_stem(item.get("script"), fallback_scene_id=sid)

            bg_asset = parse_scene_background_stem(
                project_root,
                item.get("background", item.get("background_id", "")),
                scene_palette_rel=pal,
            )
            tile_ly = parse_tile_layers(item.get("tile_layers"), tile_px=tile_px)
            parsed.append(
                SceneEntry(
                    id=sid,
                    palette=pal,
                    background_index=bg_fw,
                    objects=o_placements,
                    script=stem,
                    background_layers=layers,
                    background=bg_asset,
                    tile_layers=tile_ly,
                )
            )
        scenes_list = parsed

    ids = [s.id for s in scenes_list]
    if len(set(ids)) != len(ids):
        raise ValueError("Los ids de escena deben ser unicos.")

    active = data.get("active_scene", scenes_list[0].id)
    if not isinstance(active, str) or not active.strip():
        active = scenes_list[0].id
    active = active.strip()
    if active not in ids:
        active = scenes_list[0].id

    return (tuple(scenes_list), active, ti)


def load_project(project_root: Path) -> ProjectInfo:
    """
    Lee `turtlestudio.json` y valida campos minimos.
    No comprueba que existan todos los assets; si falta `entry` en disco, lanza ValueError.
    """
    root = project_root.expanduser().resolve()
    mp = manifest_path(root)
    if not mp.is_file():
        raise ValueError(f"No es un proyecto TurtleStudio (falta {MANIFEST_NAME}): {root}")
    try:
        data: dict[str, Any] = json.loads(mp.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON invalido en {mp}: {e}") from e

    ver = data.get("format_version")
    if not isinstance(ver, int) or ver < 1:
        raise ValueError(f"format_version no soportado: {ver!r}")

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Campo 'name' obligatorio (string no vacio).")

    entry = data.get("entry", DEFAULT_ENTRY)
    if not isinstance(entry, str) or not entry.strip():
        raise ValueError("Campo 'entry' debe ser una ruta relativa no vacia.")
    entry = _posix_relpath(entry.strip())

    pal = data.get("default_palette")
    if pal is not None and (not isinstance(pal, str) or not pal.strip()):
        raise ValueError("default_palette debe ser string no vacio o null.")
    if isinstance(pal, str):
        pal = _posix_relpath(pal.strip()) or None

    entry_path = (root / entry).resolve()
    try:
        entry_path.relative_to(root)
    except ValueError as e:
        raise ValueError(f"ENTRY sale del proyecto: {entry}") from e
    if not entry_path.is_file():
        raise ValueError(f"No existe el script de entrada: {entry_path}")

    if pal is not None:
        pal_path = (root / pal).resolve()
        try:
            pal_path.relative_to(root)
        except ValueError as e:
            raise ValueError(f"default_palette sale del proyecto: {pal}") from e
        if not pal_path.is_file():
            raise ValueError(f"No existe la paleta por defecto: {pal_path}")

    scenes, active_scene, transparent_index = _parse_scenes_from_manifest(
        data, default_palette=pal, project_root=root
    )

    from turtlestudio.project_runtime import parse_runtime_from_manifest
    from turtlestudio.tiles import parse_tile_px_from_manifest

    tile_px = parse_tile_px_from_manifest(data)
    target_fps, default_anim_fps = parse_runtime_from_manifest(data)

    return ProjectInfo(
        root=root,
        format_version=ver,
        name=name.strip(),
        entry=entry,
        default_palette=pal,
        scenes=scenes,
        active_scene=active_scene,
        transparent_index=transparent_index,
        tile_px=tile_px,
        target_fps=target_fps,
        default_anim_fps=default_anim_fps,
    )


def _mkdir_layout(root: Path) -> None:
    for rel in STANDARD_SUBDIRS:
        (root / rel).mkdir(parents=True, exist_ok=True)


def _write_mirror_scene_json_files(
    root: Path,
    scenes: list[dict[str, Any]],
) -> None:
    """
    Escribe `scenes/<id>.json` por cada escena (espejo del manifest para Git/IDE).
    Elimina en `scenes/` solo JSON con kind=turtlestudio.scene cuyo id ya no esta en la lista.
    """
    sd = (root / "scenes").resolve()
    sd.mkdir(parents=True, exist_ok=True)
    valid_ids = {str(s["id"]) for s in scenes}
    for row in scenes:
        sid = str(row["id"])
        pal = _posix_relpath(str(row["palette"]))
        path = sd / f"{sid}.json"
        stem = str(row.get("script") or sid).strip() or sid
        payload: dict[str, Any] = {
            "format_version": SCENE_JSON_VERSION,
            "kind": SCENE_JSON_KIND,
            "id": sid,
            "palette": pal,
            "script": stem,
            "bg_color_index": int(row.get("background_index", row.get("bg_color_index", 1))),
            "background_layers": list(row["background_layers"])
            if isinstance(row.get("background_layers"), list)
            else background_layers_to_json_list(_DEFAULT_SCENE_BACKGROUND_LAYERS),
            "background": str(row.get("background", "") or ""),
            "objects": list(row["objects"]) if isinstance(row.get("objects"), list) else [],
            "tile_layers": list(row["tile_layers"])
            if isinstance(row.get("tile_layers"), list)
            else [],
        }
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    for p in sd.glob("*.json"):
        if p.stem in valid_ids:
            continue
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if obj.get("kind") == SCENE_JSON_KIND:
            try:
                p.unlink()
            except OSError:
                pass


def _default_manifest_dict(display_name: str) -> dict[str, Any]:
    from turtlestudio.tiles import DEFAULT_TILE_PX, tiles_section_to_json

    return {
        "format_version": FORMAT_VERSION,
        "name": display_name,
        "entry": DEFAULT_ENTRY,
        "default_palette": DEFAULT_EXAMPLE_PALETTE_REL,
        "tiles": tiles_section_to_json(DEFAULT_TILE_PX),
        "scenes": [
            {
                "id": DEFAULT_INITIAL_SCENE_ID,
                "palette": DEFAULT_EXAMPLE_PALETTE_REL,
                "background_index": 1,
                "background_layers": background_layers_to_json_list(_DEFAULT_SCENE_BACKGROUND_LAYERS),
                "background": "",
                "script": DEFAULT_INITIAL_SCENE_ID,
                "objects": [],
                "tile_layers": [],
            },
        ],
        "active_scene": DEFAULT_INITIAL_SCENE_ID,
        "transparent_index": DEFAULT_TRANSPARENT_INDEX,
        "target_fps": 30,
        "default_anim_fps": 8,
    }


def _ensure_example_palette(root: Path) -> None:
    """Crea `palettes/palette.txt` con la paleta generica del firmware si aun no existe."""
    from turtlestudio.build import DEFAULT_CONSOLE_PALETTE_HEX

    pal_path = root / DEFAULT_EXAMPLE_PALETTE_REL
    if pal_path.is_file():
        return
    pal_path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(h.upper() for h in DEFAULT_CONSOLE_PALETTE_HEX) + "\n"
    pal_path.write_text(text, encoding="utf-8", newline="\n")


def create_project(
    project_root: Path,
    *,
    display_name: str | None = None,
    force: bool = False,
) -> Path:
    """
    Crea la carpeta del proyecto, subcarpetas estandar, `turtlestudio.json`,
    `scripts/global.lua` (ENTRY; se embebe en main.turtlecart al exportar) y
    `scripts/<primera escena>.lua` (por defecto intro) si no existian.

    Si ya existe el manifest y `force` es False, lanza ValueError.
    Devuelve la ruta al manifest escrito.
    """
    root = project_root.expanduser().resolve()
    mp = manifest_path(root)

    if mp.is_file() and not force:
        raise ValueError(
            f"Ya existe {MANIFEST_NAME} en {root}. Usa force=True para actualizar manifest y carpetas."
        )

    root.mkdir(parents=True, exist_ok=True)
    _mkdir_layout(root)
    _ensure_example_palette(root)

    name = (display_name or root.name or "untitled").strip() or "untitled"
    data = _default_manifest_dict(name)
    mp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    global_rel = Path(DEFAULT_ENTRY)
    global_path = root / global_rel
    if not global_path.is_file():
        global_path.parent.mkdir(parents=True, exist_ok=True)
        global_path.write_text(_STARTER_GLOBAL_LUA, encoding="utf-8", newline="\n")

    intro_rel = Path("scripts") / f"{DEFAULT_INITIAL_SCENE_ID}.lua"
    intro_path = root / intro_rel
    if not intro_path.is_file():
        intro_path.parent.mkdir(parents=True, exist_ok=True)
        intro_path.write_text(_STARTER_SCENE_INTRO_LUA, encoding="utf-8", newline="\n")

    _write_mirror_scene_json_files(root, list(data["scenes"]))

    return mp


def write_manifest(project_root: Path, data: dict[str, Any]) -> None:
    """Sobrescribe el manifest (el caller debe mantener format_version coherente)."""
    root = project_root.expanduser().resolve()
    mp = manifest_path(root)
    if "format_version" not in data:
        data = {**data, "format_version": FORMAT_VERSION}
    mp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _read_manifest_for_save(project_root: Path) -> dict[str, Any]:
    root = project_root.expanduser().resolve()
    mp = manifest_path(root)
    if not mp.is_file():
        raise ValueError(f"No hay manifest en {root}")
    try:
        data: dict[str, Any] = json.loads(mp.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON invalido en {mp}: {e}") from e
    entry = data.get("entry", DEFAULT_ENTRY)
    if not isinstance(entry, str) or not entry.strip():
        entry = DEFAULT_ENTRY
    data["entry"] = _posix_relpath(entry.strip())
    return data


def _normalize_scenes_for_save(
    root: Path,
    scenes: list[dict[str, Any]],
    active_scene: str,
) -> list[dict[str, Any]]:
    if not scenes:
        raise ValueError("Debe existir al menos una escena.")
    from turtlestudio.backgrounds import validate_scene_background_for_save
    from turtlestudio.scene_tiles import validate_tile_layers_for_save
    from turtlestudio.tiles import DEFAULT_TILE_PX, parse_tile_px_from_manifest

    mp = manifest_path(root)
    tile_px = DEFAULT_TILE_PX
    if mp.is_file():
        try:
            mdata = json.loads(mp.read_text(encoding="utf-8"))
            if isinstance(mdata, dict):
                tile_px = parse_tile_px_from_manifest(mdata)
        except (OSError, json.JSONDecodeError):
            tile_px = DEFAULT_TILE_PX

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in scenes:
        sid = (item.get("id") or "").strip()
        pal = (item.get("palette") or "").strip()
        if not sid or not pal:
            raise ValueError("Cada escena necesita id y palette (ruta relativa al proyecto).")
        if not _SCENE_ID_RE.match(sid):
            raise ValueError(
                f"id de escena invalido {sid!r}: usa letras, numeros, _ y - (max 64 chars)."
            )
        assert_scene_id_allowed(sid)
        pal = _posix_relpath(pal)
        if sid in seen:
            raise ValueError(f"Id de escena duplicado: {sid}")
        seen.add(sid)
        pal_path = (root / pal).resolve()
        try:
            pal_path.relative_to(root.resolve())
        except ValueError as e:
            raise ValueError(f"Escena {sid!r}: paleta fuera del proyecto: {pal}") from e
        if not pal_path.is_file():
            raise ValueError(f"Escena {sid!r}: no existe el archivo de paleta: {pal_path}")
        n = max(1, _palette_n_colors(pal_path))
        bg = _scene_background_index(
            item.get("background_index", item.get("bg_color_index", 1)),
            pal_path=pal_path,
        )
        layers = parse_background_layers(
            item.get("background_layers"),
            legacy_flat_index=bg,
            n_colors=n,
        )
        bg_fw = firmware_background_index_from_layers(layers, fallback=bg)
        raw_objs = item.get("objects", [])
        if not isinstance(raw_objs, list):
            raw_objs = []
        try:
            objs_ok = normalize_scene_objects_for_save(root, pal, raw_objs)
        except ValueError as e:
            raise ValueError(f"Escena {sid!r}: {e}") from e
        stem = validate_scene_script_stem(item.get("script"), fallback_scene_id=sid)
        bg_saved = validate_scene_background_for_save(
            root,
            item.get("background", item.get("background_id", "")),
            scene_palette_rel=pal,
        )
        tile_saved = validate_tile_layers_for_save(
            root,
            item.get("tile_layers"),
            scene_palette_rel=pal,
            tile_px=tile_px,
        )
        out.append(
            {
                "id": sid,
                "palette": pal,
                "background_index": bg_fw,
                "background_layers": background_layers_to_json_list(layers),
                "background": bg_saved,
                "script": stem,
                "objects": objs_ok,
                "tile_layers": tile_saved,
            }
        )
    if active_scene.strip() not in seen:
        raise ValueError(f"active_scene {active_scene!r} no coincide con ninguna escena.")
    return out


def save_project(
    project_root: Path,
    *,
    lua_files: dict[str, str],
    palette_file: Path | None = None,
    scenes: list[dict[str, Any]] | None = None,
    active_scene: str | None = None,
    transparent_index: int | None = None,
    tile_px: int | None = None,
    target_fps: int | None = None,
    default_anim_fps: int | None = None,
) -> tuple[Path, bool, bool, bool]:
    """
    Guarda uno o mas .lua bajo el proyecto (claves = rutas relativas POSIX),
    actualiza default_palette segun `palette_file`,
    y escribe `scenes`, `active_scene`, `transparent_index` en el manifest.

    `lua_files` debe incluir al menos el script manifest `entry`.

    Devuelve (ruta_script_entry, manifest_paleta_cambio, manifest_escenas_cambio, tiles_cambio).
    """
    from turtlestudio.project_runtime import (
        clamp_default_anim_fps,
        clamp_target_fps,
        parse_runtime_from_manifest,
    )
    from turtlestudio.tiles import (
        normalize_tile_px,
        parse_tile_px_from_manifest,
        tiles_section_to_json,
    )

    root = project_root.expanduser().resolve()
    data = _read_manifest_for_save(root)
    entry = data["entry"]
    entry_key = _posix_relpath(entry.strip())
    if entry_key not in lua_files:
        raise ValueError(
            f"lua_files debe incluir la clave del ENTRY del manifest ({entry_key!r})."
        )
    entry_path = _safe_lua_write_relpath(root, entry_key)

    for rel_raw, text in lua_files.items():
        rel = _posix_relpath(str(rel_raw).strip())
        if not rel:
            continue
        path = _safe_lua_write_relpath(root, rel)
        body = str(text).replace("\r\n", "\n").replace("\r", "\n")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8", newline="\n")

    pal_changed = False
    old_pal = data.get("default_palette")
    if palette_file is None or not palette_file.is_file():
        if old_pal is not None:
            data["default_palette"] = None
            pal_changed = True
    else:
        pal_res = palette_file.expanduser().resolve()
        try:
            rel = pal_res.relative_to(root)
            rel_s = _posix_relpath(str(rel))
            if old_pal != rel_s:
                data["default_palette"] = rel_s
                pal_changed = True
        except ValueError:
            pass

    norm_scenes: list[dict[str, Any]] | None = None
    ti_final = _clamp_transparent_index(data.get("transparent_index"))
    scene_meta_changed = False
    tiles_changed = False
    if tile_px is not None:
        new_px = normalize_tile_px(tile_px)
        if parse_tile_px_from_manifest(data) != new_px:
            data["tiles"] = tiles_section_to_json(new_px)
            tiles_changed = True
    if scenes is not None and active_scene is not None:
        ti_final = _clamp_transparent_index(
            transparent_index if transparent_index is not None else data.get("transparent_index")
        )
        norm_scenes = _normalize_scenes_for_save(root, scenes, active_scene.strip())
        old_scenes = json.dumps(data.get("scenes"), sort_keys=True)
        new_scenes = json.dumps(norm_scenes, sort_keys=True)
        old_active = data.get("active_scene")
        old_ti = _clamp_transparent_index(data.get("transparent_index"))
        if old_scenes != new_scenes or old_active != active_scene.strip() or old_ti != ti_final:
            scene_meta_changed = True
        data["scenes"] = norm_scenes
        data["active_scene"] = active_scene.strip()
        data["transparent_index"] = ti_final

    runtime_changed = False
    if target_fps is not None:
        new_tf = clamp_target_fps(target_fps)
        if parse_runtime_from_manifest(data)[0] != new_tf:
            data["target_fps"] = new_tf
            runtime_changed = True
    if default_anim_fps is not None:
        new_af = clamp_default_anim_fps(default_anim_fps)
        if parse_runtime_from_manifest(data)[1] != new_af:
            data["default_anim_fps"] = new_af
            runtime_changed = True

    if pal_changed or scene_meta_changed or tiles_changed or runtime_changed:
        write_manifest(root, data)

    if norm_scenes is not None:
        _write_mirror_scene_json_files(root, norm_scenes)

    return entry_path, pal_changed, scene_meta_changed, tiles_changed
