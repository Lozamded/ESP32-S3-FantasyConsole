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

# Indice reservado para chroma key (convencion FantasyConsole / scene-v0.md).
DEFAULT_TRANSPARENT_INDEX = 31

# Rutas relativas al crear un proyecto (POSIX en el JSON; se crean con Path).
STANDARD_SUBDIRS: tuple[str, ...] = (
    "scenes",
    "palettes",
    "objects/Sprites",
    "objects/Fonts",
    "scripts",
    "backgrounds",
    "audio/json",
    "audio/effects",
    "audio/music",
)

DEFAULT_ENTRY = "scripts/main.lua"
# Paleta de ejemplo (misma que el firmware por defecto); una linea #RRGGBB por color.
DEFAULT_EXAMPLE_PALETTE_REL = "palettes/palette.txt"

_SCENE_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")

_STARTER_MAIN_LUA = """-- Punto de entrada del proyecto (ENTRY al exportar cartucho)
print("Hola desde TurtleStudio")
cls(1)
flip()
"""


def manifest_path(project_root: Path) -> Path:
    return project_root / MANIFEST_NAME


def is_project_dir(project_root: Path) -> bool:
    return manifest_path(project_root).is_file()


@dataclass(frozen=True)
class SceneEntry:
    id: str
    palette: str
    background_index: int


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


def _posix_relpath(s: str) -> str:
    return s.replace("\\", "/")


def _clamp_transparent_index(raw: Any) -> int:
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TRANSPARENT_INDEX
    return max(0, min(31, v))


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
    return max(0, min(n - 1, v))


def _parse_scenes_from_manifest(
    data: dict[str, Any],
    *,
    default_palette: str | None,
    project_root: Path,
) -> tuple[tuple[SceneEntry, ...], str, int]:
    """
    Devuelve (scenes, active_scene, transparent_index).
    Si falta `scenes` en el JSON, sintetiza una escena `main` con la paleta por defecto del proyecto.
    """
    ti = _clamp_transparent_index(data.get("transparent_index", DEFAULT_TRANSPARENT_INDEX))
    raw_scenes = data.get("scenes")
    pal_fallback = default_palette or DEFAULT_EXAMPLE_PALETTE_REL

    if not isinstance(raw_scenes, list) or len(raw_scenes) == 0:
        fb = _posix_relpath(pal_fallback)
        pal_path = (project_root / fb).resolve()
        scenes_list = [
            SceneEntry(
                id="main",
                palette=fb,
                background_index=_scene_background_index(1, pal_path=pal_path),
            )
        ]
    else:
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
            parsed.append(SceneEntry(id=sid, palette=pal, background_index=bg))
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

    return ProjectInfo(
        root=root,
        format_version=ver,
        name=name.strip(),
        entry=entry,
        default_palette=pal,
        scenes=scenes,
        active_scene=active_scene,
        transparent_index=transparent_index,
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
        payload: dict[str, Any] = {
            "format_version": SCENE_JSON_VERSION,
            "kind": SCENE_JSON_KIND,
            "id": sid,
            "palette": pal,
            "bg_color_index": int(row.get("bg_color_index", 1)),
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
    return {
        "format_version": FORMAT_VERSION,
        "name": display_name,
        "entry": DEFAULT_ENTRY,
        "default_palette": DEFAULT_EXAMPLE_PALETTE_REL,
        "scenes": [
            {
                "id": "main",
                "palette": DEFAULT_EXAMPLE_PALETTE_REL,
                "background_index": 1,
            },
        ],
        "active_scene": "main",
        "transparent_index": DEFAULT_TRANSPARENT_INDEX,
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
    Crea la carpeta del proyecto, subcarpetas estandar, `turtlestudio.json` y `scripts/main.lua`
    de arranque si no existia.

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

    main_rel = Path(DEFAULT_ENTRY)
    main_path = root / main_rel
    if not main_path.is_file():
        main_path.parent.mkdir(parents=True, exist_ok=True)
        main_path.write_text(_STARTER_MAIN_LUA, encoding="utf-8", newline="\n")

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
        try:
            bg = int(
                item.get(
                    "background_index",
                    item.get("bg_color_index", 1),
                )
            )
        except (TypeError, ValueError):
            bg = 1
        bg = max(0, min(n - 1, bg))
        out.append({"id": sid, "palette": pal, "background_index": bg})
    if active_scene.strip() not in seen:
        raise ValueError(f"active_scene {active_scene!r} no coincide con ninguna escena.")
    return out


def save_project(
    project_root: Path,
    *,
    main_lua_body: str,
    palette_file: Path | None = None,
    scenes: list[dict[str, Any]] | None = None,
    active_scene: str | None = None,
    transparent_index: int | None = None,
) -> tuple[Path, bool, bool]:
    """
    Guarda el Lua de `entry`, actualiza default_palette segun `palette_file`,
    y escribe `scenes`, `active_scene`, `transparent_index` en el manifest.

    Devuelve (ruta_script, manifest_paleta_cambio, manifest_escenas_cambio).
    """
    root = project_root.expanduser().resolve()
    data = _read_manifest_for_save(root)
    entry = data["entry"]
    entry_path = (root / entry).resolve()
    try:
        entry_path.relative_to(root)
    except ValueError as e:
        raise ValueError(f"ENTRY invalido (sale del proyecto): {entry}") from e

    body = main_lua_body.replace("\r\n", "\n").replace("\r", "\n")
    entry_path.parent.mkdir(parents=True, exist_ok=True)
    entry_path.write_text(body, encoding="utf-8", newline="\n")

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

    norm_scenes: list[dict[str, str]] | None = None
    ti_final = _clamp_transparent_index(data.get("transparent_index"))
    scene_meta_changed = False
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

    if pal_changed or scene_meta_changed:
        write_manifest(root, data)

    if norm_scenes is not None:
        _write_mirror_scene_json_files(root, norm_scenes)

    return entry_path, pal_changed, scene_meta_changed
