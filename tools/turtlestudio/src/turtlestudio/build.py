"""Ensamblado de cartuchos .turtlecart segun spec/turtlecart-v0.md."""

from __future__ import annotations

import json
import re
import warnings
from collections.abc import Sequence
from pathlib import Path
from typing import Any

_CART_VERSION = "0"
_END_MARKER = "---END---"


def _normalize_entry_path(name: str) -> str:
    s = name.strip().replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    if not s or ".." in s.split("/"):
        raise ValueError(f"ENTRY invalido: {name!r}")
    return s


_PALETTE_LINE = re.compile(
    r"^#?(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})$",
)

# Mismo criterio que ids de escena en turtlestudio.json (ver project.py).
_INITIAL_SCENE_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
# Coincide con la primera escena por defecto en TurtleStudio (id reservado `main` = main.turtlecart).
DEFAULT_EXPORT_INITIAL_SCENE_ID = "intro"


def normalize_export_initial_scene(raw: str | None) -> str:
    """Id de escena inicial para cartucho; vacio -> intro."""
    s = (raw or "").strip()
    if not s:
        return DEFAULT_EXPORT_INITIAL_SCENE_ID
    if not _INITIAL_SCENE_ID_RE.match(s):
        raise ValueError(
            f"Escena inicial invalida {s!r}: letra inicial, luego letras, digitos, _ o - (max 64 chars)."
        )
    return s


def load_palette_lines(path: Path) -> list[str]:
    """Lee lineas #RRGGBB o #RGB (con o sin #). Ignora vacias y lineas tipo comentario."""
    text = path.read_text(encoding="utf-8")
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#") and not _PALETTE_LINE.fullmatch(line):
            continue
        cand = line if line.startswith("#") else f"#{line}"
        if not _PALETTE_LINE.fullmatch(cand):
            warnings.warn(f"Paleta: linea ignorada: {raw!r}")
            continue
        out.append(cand)
    return out


# Paleta por defecto del firmware (Genesis-like), misma orden que turtle_gpu.cpp
DEFAULT_CONSOLE_PALETTE_HEX: tuple[str, ...] = (
    "#000000",
    "#242424",
    "#494949",
    "#6D6D6D",
    "#9292B6",
    "#B6B6DB",
    "#DBDBFF",
    "#FFFFFF",
    "#240049",
    "#49246D",
    "#6D0092",
    "#00006D",
    "#0024B6",
    "#246DDB",
    "#6DB6FF",
    "#004924",
    "#009249",
    "#49DB6D",
    "#6DFFB6",
    "#492400",
    "#924924",
    "#DB6D49",
    "#DB926D",
    "#FFB692",
    "#FFDBB6",
    "#6D0000",
    "#B62424",
    "#FF4949",
    "#FF9200",
    "#FFDB24",
    "#FFDBDB",
    "#B69200",
)


def hex_line_to_rgb01(line: str) -> tuple[float, float, float]:
    """Convierte #RRGGBB o #RGB a RGB en 0..1."""
    s = line.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        raise ValueError(f"Color hex invalido: {line!r}")
    r = int(s[0:2], 16) / 255.0
    g = int(s[2:4], 16) / 255.0
    b = int(s[4:6], 16) / 255.0
    return (r, g, b)


def normalize_hex_display(line: str) -> str:
    """Devuelve #RRGGBB en mayusculas para etiquetas."""
    s = line.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    return "#" + s.upper()


def load_palette_rgb01_for_preview(palette_path: Path | None) -> tuple[list[tuple[float, float, float]], list[str]]:
    """
    Carga colores para vista previa del estudio.
    Si no hay archivo o esta vacio, usa DEFAULT_CONSOLE_PALETTE_HEX.
    Devuelve (lista RGB 0..1, lista hex normalizada para UI).
    """
    if palette_path is None or not palette_path.is_file():
        hexes = list(DEFAULT_CONSOLE_PALETTE_HEX)
    else:
        lines = load_palette_lines(palette_path)
        hexes = [normalize_hex_display(h) for h in lines] if lines else list(DEFAULT_CONSOLE_PALETTE_HEX)
    rgbs = [hex_line_to_rgb01(h) for h in hexes]
    return rgbs, hexes


def assemble_turtlecart_v0(
    *,
    entry_relpath: str,
    main_lua_body: str,
    palette_hex_lines: list[str] | None = None,
    embedded_files: Sequence[tuple[str, str]] | None = None,
    initial_scene: str | None = None,
) -> str:
    """
    Genera el texto completo de un .turtlecart v0.
    Usa saltos de linea \\n (LF).

    embedded_files: lista de (ruta POSIX dentro del cartucho, texto UTF-8).
    Se insertan antes del bloque ---FILE:ENTRY--- (orden conservado).
    La seccion PALETTE: termina en el primer ---FILE: (spec v0).

    initial_scene: linea INITIAL_SCENE: (id de escena; por defecto intro).
    """
    entry = _normalize_entry_path(entry_relpath)
    scene_id = normalize_export_initial_scene(initial_scene)
    body = main_lua_body.replace("\r\n", "\n").replace("\r", "\n")
    if _END_MARKER in body:
        warnings.warn(
            f"El Lua contiene '{_END_MARKER}'; el firmware podria cortar el archivo. "
            "Evita esa secuencia literal en el script."
        )

    parts: list[str] = [
        "TURTLECART:" + _CART_VERSION,
        f"ENTRY:{entry}",
        f"INITIAL_SCENE:{scene_id}",
    ]
    if palette_hex_lines:
        parts.append("PALETTE:")
        parts.extend(palette_hex_lines)
    if embedded_files:
        for rel, raw_body in embedded_files:
            sub = _normalize_entry_path(rel)
            text = raw_body.replace("\r\n", "\n").replace("\r", "\n")
            if _END_MARKER in text:
                warnings.warn(
                    f"Archivo embebido {sub!r} contiene '{_END_MARKER}'; "
                    "el firmware podria truncarlo."
                )
            parts.append(f"---FILE:{sub}---")
            parts.append(text.rstrip("\n"))
            parts.append(_END_MARKER)
    parts.append(f"---FILE:{entry}---")
    parts.append(body.rstrip("\n"))
    parts.append(_END_MARKER)
    return "\n".join(parts) + "\n"


def collect_studio_bundle_files(
    project_root: Path,
    *,
    scenes: list[dict[str, Any]],
    active_scene: str,
    transparent_index: int,
    entry_relpath: str,
) -> list[tuple[str, str]]:
    """
    Datos del proyecto para el cartucho inicial `main.turtlecart`.

    Solo embebe `studio/project_bundle.json` (escenas, objetos, sprites, fondos).
    El Lua de arranque va en el bloque ENTRY (p. ej. contenido de `scripts/global.lua`);
    los Lua de escena **no** se duplican aqui: pueden distribuirse en otros archivos / cartuchos.
    """
    from turtlestudio.objects import read_object_file
    from turtlestudio.sprites import read_sprite_file

    root = project_root.expanduser().resolve()
    entry = _normalize_entry_path(entry_relpath)
    ti = max(0, min(31, int(transparent_index)))

    oids: set[str] = set()
    bg_stems: set[str] = set()
    for row in scenes:
        if not isinstance(row, dict):
            continue
        raw_objs = row.get("objects")
        if isinstance(raw_objs, list):
            for item in raw_objs:
                if isinstance(item, dict):
                    oid = str(item.get("id", "")).strip()
                elif isinstance(item, str):
                    oid = item.strip()
                else:
                    continue
                if oid:
                    oids.add(oid)
        b = str(row.get("background", "")).strip()
        if b:
            bg_stems.add(b)

    from turtlestudio.backgrounds import read_background_file

    objects_map: dict[str, Any] = {}
    for oid in sorted(oids):
        try:
            objects_map[oid] = read_object_file(root, oid)
        except ValueError:
            objects_map[oid] = {"error": "missing_object_json", "id": oid}

    sids: set[str] = set()
    for od in objects_map.values():
        if isinstance(od, dict) and "error" not in od:
            sp = str(od.get("sprite_id", "")).strip()
            if sp:
                sids.add(sp)

    sprites_map: dict[str, Any] = {}
    for sid in sorted(sids):
        try:
            sprites_map[sid] = read_sprite_file(root, sid)
        except ValueError:
            sprites_map[sid] = {"error": "missing_sprite_json", "id": sid}

    backgrounds_map: dict[str, Any] = {}
    for bid in sorted(bg_stems):
        try:
            backgrounds_map[bid] = read_background_file(root, bid)
        except ValueError:
            backgrounds_map[bid] = {"error": "missing_background_json", "id": bid}

    bundle: dict[str, Any] = {
        "format_version": 1,
        "kind": "turtlestudio.cart_bundle",
        "entry": entry,
        "transparent_index": ti,
        "active_scene": (active_scene.strip() or DEFAULT_EXPORT_INITIAL_SCENE_ID),
        "scenes": scenes,
        "objects": objects_map,
        "sprites": sprites_map,
        "backgrounds": backgrounds_map,
    }
    text = json.dumps(bundle, indent=2, ensure_ascii=False) + "\n"
    return [("studio/project_bundle.json", text)]


def write_turtlecart_content(
    output: Path,
    *,
    entry_relpath: str,
    main_lua_body: str,
    palette_path: Path | None = None,
    write_lua_file: bool = False,
    embedded_files: Sequence[tuple[str, str]] | None = None,
    initial_scene: str | None = None,
) -> tuple[Path, Path | None]:
    """
    Escribe el .turtlecart desde el cuerpo Lua en memoria.
    Si write_lua_file es True, tambien escribe el .lua junto al cartucho (mismo directorio),
    con el nombre base de entry_relpath (p. ej. global.lua); por defecto False (el ENTRY solo va embebido).
    embedded_files: archivos extra embebidos antes del Lua ENTRY (p. ej. datos TurtleStudio).
    initial_scene: id para la linea INITIAL_SCENE: (por defecto intro).
    Devuelve (ruta_cartucho, ruta_lua_escrita o None).
    """
    entry = _normalize_entry_path(entry_relpath)
    palette_lines: list[str] | None = None
    if palette_path is not None and palette_path.is_file():
        palette_lines = load_palette_lines(palette_path)

    content = assemble_turtlecart_v0(
        entry_relpath=entry,
        main_lua_body=main_lua_body,
        palette_hex_lines=palette_lines,
        embedded_files=embedded_files,
        initial_scene=initial_scene,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8", newline="\n")

    lua_written: Path | None = None
    if write_lua_file:
        lua_name = Path(entry).name
        if not lua_name.lower().endswith(".lua"):
            lua_name = lua_name + ".lua" if lua_name else "main.lua"
        lua_written = output.parent / lua_name
        lua_written.write_text(
            main_lua_body.replace("\r\n", "\n").replace("\r", "\n"),
            encoding="utf-8",
            newline="\n",
        )

    return output, lua_written


def write_turtlecart(
    output: Path,
    *,
    entry_relpath: str,
    lua_path: Path,
    palette_path: Path | None = None,
) -> None:
    lua_body = lua_path.read_text(encoding="utf-8")
    write_turtlecart_content(
        output,
        entry_relpath=entry_relpath,
        main_lua_body=lua_body,
        palette_path=palette_path,
        write_lua_file=True,
    )