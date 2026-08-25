"""Ensamblado de cartuchos .turtlecart segun spec/turtlecart-v0.md."""

from __future__ import annotations

import json
import re
import shutil
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Assets mas grandes se escriben junto al .turtlecart en la SD (mismas rutas que el proyecto).
DEFAULT_ASSET_INLINE_MAX_BYTES = 32 * 1024
BACKGROUND_REF_KIND = "turtlestudio.background_ref"
SPRITE_REF_KIND = "turtlestudio.sprite_ref"
OBJECT_REF_KIND = "turtlestudio.object_ref"
TILESET_REF_KIND = "turtlestudio.tileset_ref"
FONT_REF_KIND = "turtlestudio.font_ref"
DEFAULT_PACKAGE_DIR_NAME = "build"
DEFAULT_CART_FILENAME = "main.turtlecart"
SD_DEPLOY_README_NAME = "COPIAR_A_SD.txt"
LUA_SCRIPT_EXPORT_WARN_BYTES = 32 * 1024

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


def save_palette_lines(path: Path, hex_lines: list[str]) -> None:
    """Escribe lineas #RRGGBB (una por color, orden = indice), mismo formato que load_palette_lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(normalize_hex_display(h) for h in hex_lines) + "\n"
    path.write_text(body, encoding="utf-8", newline="\n")


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
    bundle_file: str | None = None,
    initial_scene: str | None = None,
) -> str:
    """
    Genera el texto completo de un .turtlecart v0.
    Usa saltos de linea \\n (LF).

    embedded_files: lista de (ruta POSIX dentro del cartucho, texto UTF-8).
    Se insertan antes del bloque ---FILE:ENTRY--- (orden conservado).
    La seccion PALETTE: termina en el primer ---FILE: (spec v0).

    initial_scene: linea INITIAL_SCENE: (id de escena; por defecto intro).
    bundle_file: ruta POSIX en SD (p. ej. studio/project_bundle.json); no embeber el JSON.
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
    if bundle_file and str(bundle_file).strip():
        parts.append(f"BUNDLE_FILE:{_normalize_entry_path(bundle_file.strip())}")
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


@dataclass(frozen=True)
class CartExportPackage:
    """Archivos del cartucho: embebidos en `.turtlecart` y sidecar en la misma carpeta de salida."""

    embedded: tuple[tuple[str, str], ...]
    # str = JSON texto (objects); bytes = binario .tbg / .tsp / .tts para ESP32
    sidecar: tuple[tuple[str, str | bytes], ...]
    lua_export_notes: tuple[str, ...] = ()


def _asset_json_utf8_size(data: dict[str, Any]) -> int:
    return len(json.dumps(data, ensure_ascii=False).encode("utf-8"))


def _render_mode(data: dict[str, Any]) -> str | None:
    render = data.get("render")
    if isinstance(render, dict):
        m = render.get("mode")
        if isinstance(m, str):
            return m
    return None


def should_externalize_background(data: dict[str, Any]) -> bool:
    """Fondos indexados siempre fuera del bundle (suelen ser ~escena completa)."""
    if _render_mode(data) == "indexed_pixels":
        return True
    return _asset_json_utf8_size(data) > DEFAULT_ASSET_INLINE_MAX_BYTES


def should_externalize_sprite(data: dict[str, Any]) -> bool:
    if _render_mode(data) == "indexed_pixels":
        return True
    return _asset_json_utf8_size(data) > DEFAULT_ASSET_INLINE_MAX_BYTES


def should_externalize_tileset(data: dict[str, Any]) -> bool:
    """Tilesets con arte indexado van siempre a sidecar .tts (suelen ser varios tiles)."""
    from turtlestudio.tiles import parse_tileset_all_tiles

    if parse_tileset_all_tiles(data, fill_index=1):
        return True
    return _asset_json_utf8_size(data) > DEFAULT_ASSET_INLINE_MAX_BYTES


def should_externalize_font(data: dict[str, Any]) -> bool:
    """Fuentes con glifos indexados van a sidecar .tfn."""
    from turtlestudio.fonts import parse_font_glyphs

    if parse_font_glyphs(data, fill_index=1):
        return True
    return _asset_json_utf8_size(data) > DEFAULT_ASSET_INLINE_MAX_BYTES


def _manifest_tile_px(project_root: Path) -> int:
    from turtlestudio.project import MANIFEST_NAME
    from turtlestudio.tiles import DEFAULT_TILE_PX, parse_tile_px_from_manifest

    mp = project_root / MANIFEST_NAME
    if not mp.is_file():
        return DEFAULT_TILE_PX
    try:
        data = json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_TILE_PX
    if not isinstance(data, dict):
        return DEFAULT_TILE_PX
    return parse_tile_px_from_manifest(data)


def _asset_ref_entry(asset_id: str, sd_relpath: str, ref_kind: str) -> dict[str, Any]:
    return {
        "format_version": 1,
        "id": asset_id,
        "kind": ref_kind,
        "file": sd_relpath.replace("\\", "/"),
    }


def collect_studio_bundle_files(
    project_root: Path,
    *,
    scenes: list[dict[str, Any]],
    active_scene: str,
    transparent_index: int,
    entry_relpath: str,
) -> CartExportPackage:
    """
    Paquete para `main.turtlecart`: bundle delgado embebido + JSON pesados como sidecar.

    Rutas sidecar (p. ej. `backgrounds/cielo.json`) coinciden con el proyecto; copiar la
    carpeta de exportacion entera a la raiz de la microSD.
    """
    from turtlestudio.asset_bin import (
        background_json_to_tbg,
        font_json_to_tfn,
        sprite_json_to_tsp,
        tileset_json_to_tts,
    )
    from turtlestudio.backgrounds import read_background_file, shrink_background_json_for_export
    from turtlestudio.objects import (
        list_object_json_stems,
        object_sprite_ids_for_bundle,
        read_object_file,
    )
    from turtlestudio.sprites import read_sprite_file
    from turtlestudio.fonts import (
        list_font_json_stems,
        read_font_file,
        shrink_font_json_for_export,
    )
    from turtlestudio.tiles import (
        collect_tileset_stems_from_scenes,
        read_tileset_file,
        shrink_tileset_json_for_export,
    )

    root = project_root.expanduser().resolve()
    entry = _normalize_entry_path(entry_relpath)
    from turtlestudio.palette_policy import clamp_transparent_index

    ti = clamp_transparent_index(transparent_index)
    tile_px = _manifest_tile_px(root)

    oids_in_scenes: set[str] = set()
    bg_stems: set[str] = set()
    tile_stems: set[str] = collect_tileset_stems_from_scenes(scenes)
    for row in scenes:
        if not isinstance(row, dict):
            continue
        raw_objs = row.get("objects")
        if isinstance(raw_objs, list):
            for item in raw_objs:
                if isinstance(item, dict):
                    # "object" = referencia al catalogo (spec/scene-object-identity-v0.md);
                    # fallback a "id" para escenas legado (sin migrar via el editor todavia).
                    robj = item.get("object")
                    oid = str(robj).strip() if isinstance(robj, str) and robj.strip() else str(item.get("id", "")).strip()
                elif isinstance(item, str):
                    oid = item.strip()
                else:
                    continue
                if oid:
                    oids_in_scenes.add(oid)
        b = str(row.get("background", "")).strip()
        if b:
            bg_stems.add(b)
        for ld in row.get("background_layers") or []:
            if isinstance(ld, dict):
                lb = str(ld.get("background", "")).strip()
                if lb:
                    bg_stems.add(lb)

    # Todos los JSON en objects/Objects/ van al paquete SD (no solo los colocados en escena).
    oids: set[str] = set(list_object_json_stems(root)) | oids_in_scenes

    sidecar: list[tuple[str, str | bytes]] = []
    sids: set[str] = set()

    objects_map: dict[str, Any] = {}
    for oid in sorted(oids):
        try:
            odata = read_object_file(root, oid)
        except ValueError:
            objects_map[oid] = {"error": "missing_object_json", "id": oid}
            continue
        for sp in object_sprite_ids_for_bundle(odata):
            sids.add(sp)
        orel = f"objects/{oid}.json"
        objects_map[oid] = _asset_ref_entry(oid, orel, OBJECT_REF_KIND)
        sidecar.append(
            (orel, json.dumps(odata, ensure_ascii=False, separators=(",", ":")) + "\n")
        )

    from turtlestudio.sprites import parse_sprite_origin, sprite_pixel_dimensions

    sprites_map: dict[str, Any] = {}
    for sid in sorted(sids):
        try:
            data = read_sprite_file(root, sid)
        except ValueError:
            sprites_map[sid] = {"error": "missing_sprite_json", "id": sid}
            continue
        rel = f"sprites/{sid}.tsp"
        if should_externalize_sprite(data):
            _, pw, ph = sprite_pixel_dimensions(data)
            ox, oy = parse_sprite_origin(data, pw=pw, ph=ph)
            ref = _asset_ref_entry(sid, rel, SPRITE_REF_KIND)
            ref["origin_x"] = ox
            ref["origin_y"] = oy
            sprites_map[sid] = ref
            sidecar.append((rel, sprite_json_to_tsp(data)))
        else:
            sprites_map[sid] = data

    backgrounds_map: dict[str, Any] = {}
    for bid in sorted(bg_stems):
        try:
            data = shrink_background_json_for_export(read_background_file(root, bid))
        except ValueError:
            backgrounds_map[bid] = {"error": "missing_background_json", "id": bid}
            continue
        rel = f"backgrounds/{bid}.tbg"
        if should_externalize_background(data):
            backgrounds_map[bid] = _asset_ref_entry(bid, rel, BACKGROUND_REF_KIND)
            sidecar.append((rel, background_json_to_tbg(data)))
        else:
            backgrounds_map[bid] = data

    tilesets_map: dict[str, Any] = {}
    for tid in sorted(tile_stems):
        try:
            data = shrink_tileset_json_for_export(read_tileset_file(root, tid))
        except ValueError:
            tilesets_map[tid] = {"error": "missing_tileset_json", "id": tid}
            continue
        rel = f"tiles/{tid}.tts"
        if should_externalize_tileset(data):
            tilesets_map[tid] = _asset_ref_entry(tid, rel, TILESET_REF_KIND)
            sidecar.append((rel, tileset_json_to_tts(data)))
        else:
            tilesets_map[tid] = data

    fonts_map: dict[str, Any] = {}
    for fid in sorted(list_font_json_stems(root)):
        try:
            data = shrink_font_json_for_export(read_font_file(root, fid))
        except ValueError:
            fonts_map[fid] = {"error": "missing_font_json", "id": fid}
            continue
        rel = f"fonts/{fid}.tfn"
        if should_externalize_font(data):
            fonts_map[fid] = _asset_ref_entry(fid, rel, FONT_REF_KIND)
            sidecar.append((rel, font_json_to_tfn(data)))
        else:
            fonts_map[fid] = data

    from turtlestudio.project import MANIFEST_NAME
    from turtlestudio.project_runtime import parse_runtime_from_manifest

    manifest_data: dict[str, Any] = {}
    mp = root / MANIFEST_NAME
    if mp.is_file():
        try:
            raw_m = json.loads(mp.read_text(encoding="utf-8"))
            if isinstance(raw_m, dict):
                manifest_data = raw_m
        except (OSError, json.JSONDecodeError):
            manifest_data = {}
    target_fps, default_anim_fps = parse_runtime_from_manifest(manifest_data)

    bundle: dict[str, Any] = {
        "format_version": 1,
        "kind": "turtlestudio.cart_bundle",
        "entry": entry,
        "transparent_index": ti,
        "tile_px": tile_px,
        "target_fps": target_fps,
        "default_anim_fps": default_anim_fps,
        "active_scene": (active_scene.strip() or DEFAULT_EXPORT_INITIAL_SCENE_ID),
        "scenes": scenes,
        "objects": objects_map,
        "sprites": sprites_map,
        "backgrounds": backgrounds_map,
        "tilesets": tilesets_map,
        "fonts": fonts_map,
    }
    bundle_rel = "studio/project_bundle.json"
    bundle_text = json.dumps(bundle, separators=(",", ":"), ensure_ascii=False) + "\n"
    sidecar.append((bundle_rel, bundle_text))

    lua_notes = append_lua_scripts_sidecar(
        root,
        sidecar,
        entry_relpath=entry,
        scenes=scenes,
        object_ids=oids,
    )

    return CartExportPackage(
        embedded=(),
        sidecar=tuple(sidecar),
        lua_export_notes=tuple(lua_notes),
    )


def _read_lua_file_normalized(root: Path, rel: str) -> str | None:
    path = root / rel
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except OSError:
        return None


def append_lua_scripts_sidecar(
    project_root: Path,
    sidecar: list[tuple[str, str | bytes]],
    *,
    entry_relpath: str,
    scenes: list[dict[str, Any]],
    object_ids: set[str],
) -> list[str]:
    """
    Anade scripts/*.lua al sidecar: ENTRY, un Lua por escena (stem) y por objeto con campo script.
    Devuelve avisos (p. ej. archivo grande o referenciado pero ausente).
    """
    from turtlestudio.lua_bytecode import (
        LuaCompileError,
        compile_lua_to_bytecode,
        lua_bytecode_available,
        lua_bytecode_unavailable_reason,
    )
    from turtlestudio.objects import parse_object_script, read_object_file
    from turtlestudio.project import object_lua_relpath, scene_lua_relpath, validate_scene_script_stem

    root = project_root.expanduser().resolve()
    notes: list[str] = []
    script_seen: set[str] = set()
    bytecode_ok = lua_bytecode_available()
    warned_no_bytecode = False

    def add_script(rel: str, *, required: bool = False, compile_script: bool = True) -> None:
        nonlocal warned_no_bytecode
        rel = _normalize_entry_path(rel)
        if rel in script_seen:
            return
        body = _read_lua_file_normalized(root, rel)
        if body is None:
            if required:
                notes.append(f"  Falta {rel} (requerido para export)")
            return
        script_seen.add(rel)
        payload: str | bytes = body
        if compile_script and bytecode_ok:
            try:
                payload = compile_lua_to_bytecode(body, f"/{rel}")
            except LuaCompileError as exc:
                notes.append(f"  Error de sintaxis en {rel} (se exporta como texto): {exc}")
                payload = body
        elif compile_script and not bytecode_ok and not warned_no_bytecode:
            warned_no_bytecode = True
            notes.append(
                "  Aviso: scripts exportados como texto Lua plano (lupa no disponible: "
                f"{lua_bytecode_unavailable_reason()}); ver README seccion \"Play\" para "
                "compilar lupa contra el Lua 5.4.6 vendorizado y habilitar bytecode."
            )
        sidecar.append((rel, payload))
        nbytes = len(payload) if isinstance(payload, bytes) else len(payload.encode("utf-8"))
        if nbytes > LUA_SCRIPT_EXPORT_WARN_BYTES:
            notes.append(
                f"  Aviso: {rel} es grande ({nbytes} bytes; umbral "
                f"{LUA_SCRIPT_EXPORT_WARN_BYTES // 1024} KiB)"
            )

    entry = _normalize_entry_path(entry_relpath)
    if not entry.lower().endswith(".lua"):
        entry = f"{entry}.lua"
    # ENTRY va embebido como texto en main.turtlecart (fuera de este sidecar por completo,
    # ver merge_entry_lua_into_sidecar); esta copia en scripts/ es solo de referencia --
    # nunca la lee el firmware -- asi que se deja como texto legible a proposito.
    add_script(entry, required=False, compile_script=False)

    for row in scenes:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("id", "")).strip() or DEFAULT_EXPORT_INITIAL_SCENE_ID
        try:
            stem = validate_scene_script_stem(row.get("script"), fallback_scene_id=sid)
        except ValueError:
            notes.append(f"  Escena {sid!r}: script stem invalido (omitido)")
            continue
        add_script(scene_lua_relpath(stem), required=False)

    for oid in sorted(object_ids):
        try:
            odata = read_object_file(root, oid)
        except ValueError:
            continue
        stem = parse_object_script(odata)
        if not stem:
            continue
        add_script(object_lua_relpath(stem), required=False)

    return notes


def resolve_package_cart_path(
    user_path: Path | str,
    *,
    cart_name: str = DEFAULT_CART_FILENAME,
) -> Path:
    """
    Ruta del .turtlecart dentro del paquete SD.

    Si `user_path` es carpeta (sin extension .turtlecart), usa `<carpeta>/main.turtlecart`.
    """
    p = Path(user_path).expanduser()
    if p.suffix.lower() == ".turtlecart":
        return p
    return p / cart_name


def package_dir_from_cart_path(cart_path: Path) -> Path:
    return cart_path.parent


_UNSAFE_CLEAN_ROOTS = (
    Path("/"),
    Path.home(),
)


def export_package_dir(user_path: Path | str) -> Path:
    """Carpeta del paquete SD (padre de main.turtlecart)."""
    return package_dir_from_cart_path(resolve_package_cart_path(user_path))


def clean_export_package_dir(
    user_path: Path | str,
    *,
    project_root: Path | None = None,
) -> Path:
    """
    Borra y recrea la carpeta de exportacion (p. ej. build/) para evitar restos de exports viejos.
    """
    package_dir = export_package_dir(user_path).expanduser().resolve()
    for unsafe in _UNSAFE_CLEAN_ROOTS:
        if package_dir == unsafe.resolve():
            raise ValueError(f"No se puede limpiar una ruta del sistema: {package_dir}")
    if len(package_dir.parts) < 2:
        raise ValueError(f"Ruta de exportacion demasiado corta para limpiar: {package_dir}")
    if project_root is not None:
        proot = project_root.expanduser().resolve()
        if package_dir == proot:
            raise ValueError(
                "La carpeta de exportacion no puede ser la raiz del proyecto; usa p. ej. build/"
            )
    if package_dir.is_file():
        raise ValueError(f"La ruta de exportacion es un archivo, no una carpeta: {package_dir}")
    if package_dir.is_dir():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)
    return package_dir


def _sd_deploy_readme_text(*, cart_name: str, sidecar_rels: Sequence[str]) -> str:
    lines = [
        "Paquete TurtleCart para microSD (FantasyConsole / TurtleReader)",
        "",
        "Copia TODO el contenido de esta carpeta a la RAIZ de la microSD:",
        "",
        f"  {cart_name}",
    ]
    for rel in sorted(sidecar_rels):
        lines.append(f"  {rel.replace(chr(92), '/')}")
    lines.extend(
        [
            "",
            "No copies solo el .turtlecart: fondos/sprites/tilesets/fuentes/objetos/scripts referenciados",
            "estan en backgrounds/, sprites/, tiles/, fonts/, objects/, scripts/.",
            "",
            "Generado por TurtleStudio.",
        ]
    )
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class CartPackageWriteResult:
    package_dir: Path
    cart_path: Path
    sidecar_paths: tuple[Path, ...]
    deploy_readme_path: Path | None
    lua_path: Path | None


def format_cart_package_log(result: CartPackageWriteResult, *, initial_scene: str) -> str:
    cart_n = result.cart_path.stat().st_size
    lines = [
        "Paquete SD exportado OK:",
        f"  Carpeta: {result.package_dir}",
        f"  Cartucho: {result.cart_path.name} ({cart_n} bytes)",
        f"  INITIAL_SCENE: {initial_scene}",
        "  Cart: ENTRY Lua + BUNDLE_FILE:studio/project_bundle.json (JSON en sidecar)",
    ]
    if result.sidecar_paths:
        by_dir: dict[str, list[Path]] = {}
        for p in result.sidecar_paths:
            key = p.parent.name if p.parent != result.package_dir else "."
            by_dir.setdefault(key, []).append(p)
        lines.append(f"  Assets en carpetas ({len(result.sidecar_paths)} archivos):")
        if "scripts" in by_dir:
            lines.append(
                f"    scripts/ ({len(by_dir['scripts'])} Lua: ENTRY, escenas y objetos con \"script\")"
            )
        for folder in sorted(by_dir.keys()):
            if folder == "scripts":
                continue
            files = by_dir[folder]
            lines.append(f"    {folder}/ ({len(files)})")
            for p in sorted(files)[:8]:
                lines.append(f"      {p.name} ({p.stat().st_size} bytes)")
            if len(files) > 8:
                lines.append(f"      ... +{len(files) - 8} mas")
    if result.deploy_readme_path is not None:
        lines.append(f"  Instrucciones: {result.deploy_readme_path.name}")
    lines.append("  -> Copia la carpeta entera a la raiz de la microSD.")
    if result.lua_path is not None:
        lines.append(f"  Lua ENTRY (extra): {result.lua_path.relative_to(result.package_dir)}")
    return "\n".join(lines) + "\n"


def merge_entry_lua_into_sidecar(
    sidecar: Sequence[tuple[str, str | bytes]] | None,
    *,
    entry_relpath: str,
    entry_body: str,
) -> list[tuple[str, str | bytes]]:
    """Sustituye o anade el ENTRY embebido en el cartucho tambien como scripts/<...>.lua en SD."""
    entry = _normalize_entry_path(entry_relpath)
    if not entry.lower().endswith(".lua"):
        entry = f"{entry}.lua"
    body = entry_body.replace("\r\n", "\n").replace("\r", "\n")
    out: list[tuple[str, str | bytes]] = [
        (rel, payload) for rel, payload in (sidecar or ()) if _normalize_entry_path(rel) != entry
    ]
    out.append((entry, body))
    return out


def write_cart_package(
    output: Path | str,
    *,
    entry_relpath: str,
    main_lua_body: str,
    palette_path: Path | None = None,
    write_lua_file: bool = False,
    embedded_files: Sequence[tuple[str, str]] | None = None,
    sidecar_files: Sequence[tuple[str, str | bytes]] | None = None,
    initial_scene: str | None = None,
    write_deploy_readme: bool = True,
) -> CartPackageWriteResult:
    """Escribe paquete SD: main.turtlecart + subcarpetas backgrounds/, sprites/, objects/."""
    cart_path = resolve_package_cart_path(output)
    cart_path, _lua_skip, sidecar_written = write_turtlecart_content(
        cart_path,
        entry_relpath=entry_relpath,
        main_lua_body=main_lua_body,
        palette_path=palette_path,
        write_lua_file=False,
        embedded_files=embedded_files,
        sidecar_files=sidecar_files,
        initial_scene=initial_scene,
    )
    package_dir = package_dir_from_cart_path(cart_path)

    lua_written: Path | None = None
    if write_lua_file:
        entry = _normalize_entry_path(entry_relpath)
        lua_written = package_dir / entry
        lua_written.parent.mkdir(parents=True, exist_ok=True)
        lua_written.write_text(
            main_lua_body.replace("\r\n", "\n").replace("\r", "\n"),
            encoding="utf-8",
            newline="\n",
        )

    deploy_path: Path | None = None
    sidecar_rels = [rel for rel, _ in (sidecar_files or ())]
    if write_deploy_readme and (sidecar_rels or True):
        deploy_path = package_dir / SD_DEPLOY_README_NAME
        deploy_path.write_text(
            _sd_deploy_readme_text(cart_name=cart_path.name, sidecar_rels=sidecar_rels),
            encoding="utf-8",
            newline="\n",
        )

    return CartPackageWriteResult(
        package_dir=package_dir,
        cart_path=cart_path,
        sidecar_paths=sidecar_written,
        deploy_readme_path=deploy_path,
        lua_path=lua_written,
    )


def write_cart_sidecar_files(
    output_cart: Path,
    sidecar_files: Sequence[tuple[str, str | bytes]] | None,
) -> list[Path]:
    """Escribe sidecars junto al `.turtlecart` (JSON o binario .tbg/.tsp/.tts)."""
    written: list[Path] = []
    if not sidecar_files:
        return written
    base = output_cart.parent
    for rel, payload in sidecar_files:
        sub = _normalize_entry_path(rel)
        dest = base / sub
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, bytes):
            dest.write_bytes(payload)
        else:
            dest.write_text(
                payload.replace("\r\n", "\n").replace("\r", "\n"),
                encoding="utf-8",
                newline="\n",
            )
        written.append(dest)
    return written


def write_turtlecart_content(
    output: Path,
    *,
    entry_relpath: str,
    main_lua_body: str,
    palette_path: Path | None = None,
    write_lua_file: bool = False,
    embedded_files: Sequence[tuple[str, str]] | None = None,
    sidecar_files: Sequence[tuple[str, str | bytes]] | None = None,
    initial_scene: str | None = None,
    bundle_file: str | None = "studio/project_bundle.json",
) -> tuple[Path, Path | None, tuple[Path, ...]]:
    """
    Escribe el .turtlecart desde el cuerpo Lua en memoria.
    Si write_lua_file es True, tambien escribe el .lua junto al cartucho (mismo directorio),
    con el nombre base de entry_relpath (p. ej. global.lua); por defecto False (el ENTRY solo va embebido).
    embedded_files: archivos extra embebidos antes del Lua ENTRY (p. ej. bundle delgado).
    sidecar_files: JSON externos (p. ej. backgrounds/, sprites/) en la carpeta del cartucho.
    initial_scene: id para la linea INITIAL_SCENE: (por defecto intro).
    Devuelve (ruta_cartucho, ruta_lua_escrita o None, rutas sidecar escritas).
    """
    entry = _normalize_entry_path(entry_relpath)
    palette_lines: list[str] | None = None
    if palette_path is not None and palette_path.is_file():
        palette_lines = load_palette_lines(palette_path)

    bundle_rel: str | None = None
    if sidecar_files:
        for rel, _payload in sidecar_files:
            if _normalize_entry_path(rel) == "studio/project_bundle.json":
                bundle_rel = "studio/project_bundle.json"
                break
    if bundle_rel is None and bundle_file:
        bundle_rel = _normalize_entry_path(bundle_file)

    content = assemble_turtlecart_v0(
        entry_relpath=entry,
        main_lua_body=main_lua_body,
        palette_hex_lines=palette_lines,
        embedded_files=embedded_files,
        bundle_file=bundle_rel,
        initial_scene=initial_scene,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8", newline="\n")
    sidecar_written = tuple(write_cart_sidecar_files(output, sidecar_files))

    lua_written: Path | None = None
    if write_lua_file:
        lua_written = output.parent / entry
        lua_written.parent.mkdir(parents=True, exist_ok=True)
        lua_written.write_text(
            main_lua_body.replace("\r\n", "\n").replace("\r", "\n"),
            encoding="utf-8",
            newline="\n",
        )

    return output, lua_written, sidecar_written


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