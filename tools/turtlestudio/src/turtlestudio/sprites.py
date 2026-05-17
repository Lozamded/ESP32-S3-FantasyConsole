"""Definicion JSON de sprites (v0: paleta propia del sprite + bloques cell_px × cell_px)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from turtlestudio.palette_policy import (
    PALETTE_SIZE,
    clamp_paint_palette_index,
    clamp_pixel_storage_index,
)
from turtlestudio.project import DEFAULT_EXAMPLE_PALETTE_REL

SPRITE_JSON_VERSION = 1
SPRITE_JSON_KIND = "turtlestudio.sprite"
SPRITE_RENDER_SOLID = "solid_palette_index"
SPRITE_RENDER_INDEXED_PIXELS = "indexed_pixels"
SPRITE_IMAGE_FORMAT_ROWS = "palette_rows"
# Tamano logico en celdas (evita sprites enormes en disco por error).
MAX_BLOCKS_PER_AXIS = 32
MAX_SPRITE_FRAMES = 32
DEFAULT_CELL_PX = 4
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
    origin_x: int = 0,
    origin_y: int = 0,
) -> dict[str, object]:
    """Sprite v0: rectangulo lleno; indice respecto a la paleta propia del sprite (no la de la escena)."""
    pal = normalize_palette_rel(palette_rel)
    bw = max(1, min(int(blocks_w), MAX_BLOCKS_PER_AXIS))
    bh = max(1, min(int(blocks_h), MAX_BLOCKS_PER_AXIS))
    cp = max(1, min(int(cell_px), 256))
    pi = clamp_paint_palette_index(palette_index, palette_len=PALETTE_SIZE)
    pw, ph = bw * cp, bh * cp
    ox, oy = parse_sprite_origin(
        {"origin_x": origin_x, "origin_y": origin_y}, pw=pw, ph=ph
    )
    return {
        "format_version": SPRITE_JSON_VERSION,
        "kind": SPRITE_JSON_KIND,
        "id": sprite_id,
        "notes": "",
        "palette": pal,
        "cell_px": cp,
        "blocks_w": bw,
        "blocks_h": bh,
        "pixel_w": pw,
        "pixel_h": ph,
        "origin_x": ox,
        "origin_y": oy,
        "render": {
            "mode": SPRITE_RENDER_SOLID,
            "palette_index": pi,
        },
        "image": None,
        "frame_count": 1,
        "frames": [],
    }


def sprite_json_path(project_root: Path, stem: str) -> Path:
    return sprites_dir(project_root) / f"{stem}.json"


def sprite_pixel_dimensions(data: dict[str, Any]) -> tuple[int, int, int]:
    """Devuelve (cell_px, pixel_w, pixel_h) acotados."""
    try:
        cp = int(data.get("cell_px", DEFAULT_CELL_PX))
    except (TypeError, ValueError):
        cp = DEFAULT_CELL_PX
    cp = max(1, min(cp, 256))
    try:
        bw = int(data.get("blocks_w", 1))
        bh = int(data.get("blocks_h", 1))
    except (TypeError, ValueError):
        bw, bh = 1, 1
    bw = max(1, min(bw, MAX_BLOCKS_PER_AXIS))
    bh = max(1, min(bh, MAX_BLOCKS_PER_AXIS))
    try:
        pw = int(data.get("pixel_w", bw * cp))
        ph = int(data.get("pixel_h", bh * cp))
    except (TypeError, ValueError):
        pw, ph = bw * cp, bh * cp
    pw = max(1, min(pw, MAX_BLOCKS_PER_AXIS * cp))
    ph = max(1, min(ph, MAX_BLOCKS_PER_AXIS * cp))
    return cp, pw, ph


def parse_sprite_origin(
    data: dict[str, Any],
    *,
    pw: int,
    ph: int,
) -> tuple[int, int]:
    """
    Punto de ancla en espacio sprite (0,0)=esquina inferior izquierda del bbox).
    En escena, (x,y) del objeto coincide con este punto, no con la esquina del bbox.
    """
    try:
        ox = int(data.get("origin_x", 0))
    except (TypeError, ValueError):
        ox = 0
    try:
        oy = int(data.get("origin_y", 0))
    except (TypeError, ValueError):
        oy = 0
    cap_w = max(1, int(pw))
    cap_h = max(1, int(ph))
    ox = max(0, min(cap_w - 1, ox))
    oy = max(0, min(cap_h - 1, oy))
    return ox, oy


def sprite_blit_bottom_left(
    anchor_x: int,
    anchor_y: int,
    origin_x: int,
    origin_y: int,
) -> tuple[int, int]:
    """Ancla en escena → esquina inferior izquierda del rectangulo a dibujar."""
    return anchor_x - int(origin_x), anchor_y - int(origin_y)


def parse_palette_rows_image(data: dict[str, Any]) -> list[list[int]] | None:
    """Matriz fila x columna (alto x ancho) de indices de paleta, o None."""
    im = data.get("image")
    if not isinstance(im, dict):
        return None
    if im.get("format") != SPRITE_IMAGE_FORMAT_ROWS:
        return None
    raw_rows = im.get("rows")
    if not isinstance(raw_rows, list) or not raw_rows:
        return None
    _, pw, ph = sprite_pixel_dimensions(data)
    out: list[list[int]] = []
    for y in range(ph):
        row: list[int] = []
        src = raw_rows[y] if y < len(raw_rows) else []
        if not isinstance(src, list):
            src = []
        for x in range(pw):
            try:
                v = int(src[x]) if x < len(src) else 0
            except (TypeError, ValueError):
                v = 0
            row.append(clamp_pixel_storage_index(v))
        out.append(row)
    return out


def parse_sprite_frame_count(data: dict[str, Any]) -> int:
    """Numero de fotogramas (>=1). Si falta, se infiere de image + frames[]."""
    try:
        fc = int(data.get("frame_count", 0))
    except (TypeError, ValueError):
        fc = 0
    extra = data.get("frames")
    n_extra = len(extra) if isinstance(extra, list) else 0
    if fc < 1:
        fc = 1 + n_extra if parse_palette_rows_image(data) is not None else 1
    return max(1, min(MAX_SPRITE_FRAMES, fc))


def _parse_palette_rows_from_image_dict(
    im: dict[str, Any],
    *,
    pw: int,
    ph: int,
) -> list[list[int]] | None:
    if im.get("format") != SPRITE_IMAGE_FORMAT_ROWS:
        return None
    raw_rows = im.get("rows")
    if not isinstance(raw_rows, list) or not raw_rows:
        return None
    out: list[list[int]] = []
    for y in range(ph):
        row: list[int] = []
        src = raw_rows[y] if y < len(raw_rows) else []
        if not isinstance(src, list):
            src = []
        for x in range(pw):
            try:
                v = int(src[x]) if x < len(src) else 0
            except (TypeError, ValueError):
                v = 0
            row.append(clamp_pixel_storage_index(v))
        out.append(row)
    return out


def parse_sprite_frame_rows_entry(
    entry: object,
    *,
    pw: int,
    ph: int,
    fill_index: int = 0,
) -> list[list[int]]:
    """Un fotograma desde frames[] (objeto con image o image directo)."""
    fi = clamp_pixel_storage_index(fill_index)
    if isinstance(entry, dict):
        im = entry.get("image")
        if isinstance(im, dict):
            parsed = _parse_palette_rows_from_image_dict(im, pw=pw, ph=ph)
            if parsed is not None:
                return parsed
        if entry.get("format") == SPRITE_IMAGE_FORMAT_ROWS:
            parsed = _parse_palette_rows_from_image_dict(entry, pw=pw, ph=ph)
            if parsed is not None:
                return parsed
    return solid_fill_indices(pw, ph, fi)


def parse_sprite_all_frame_rows(
    data: dict[str, Any],
    *,
    fill_index: int = 0,
) -> list[list[list[int]]]:
    """Lista de matrices [frame][y][x]; frame 0 = image principal."""
    _, pw, ph = sprite_pixel_dimensions(data)
    fc = parse_sprite_frame_count(data)
    fi = clamp_pixel_storage_index(fill_index)
    base = parse_palette_rows_image(data)
    if base is None:
        base = solid_fill_indices(pw, ph, fi)
    else:
        base = trim_palette_rows(base, pw, ph, fill_index=fi)
    out: list[list[list[int]]] = [base]
    raw_frames = data.get("frames")
    if isinstance(raw_frames, list):
        for entry in raw_frames:
            out.append(parse_sprite_frame_rows_entry(entry, pw=pw, ph=ph, fill_index=fi))
    while len(out) < fc:
        out.append(solid_fill_indices(pw, ph, fi))
    return out[:fc]


def serialize_sprite_frames(
    frame_rows: list[list[list[int]]],
    *,
    pw: int,
    ph: int,
    fill_index: int = 0,
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    """frame 0 → image; frames 1..N-1 → lista de {image: ...}."""
    fi = clamp_pixel_storage_index(fill_index)
    if not frame_rows:
        frame_rows = [solid_fill_indices(pw, ph, fi)]
    fc = max(1, min(MAX_SPRITE_FRAMES, len(frame_rows)))

    def pack(rows: list[list[int]]) -> dict[str, Any]:
        norm = trim_palette_rows(rows, pw, ph, fill_index=fi)
        return {"format": SPRITE_IMAGE_FORMAT_ROWS, "rows": norm}

    trimmed = [pack(fr) for fr in frame_rows[:fc]]
    while len(trimmed) < fc:
        trimmed.append(pack(solid_fill_indices(pw, ph, fi)))
    image0 = trimmed[0]
    extras = [{"image": block} for block in trimmed[1:]]
    return image0, extras, fc


def solid_fill_indices(pw: int, ph: int, fill_index: int) -> list[list[int]]:
    fi = clamp_pixel_storage_index(fill_index)
    return [[fi for _ in range(pw)] for _ in range(ph)]


def normalize_palette_rows(
    rows: list[list[int]] | None,
    pw: int,
    ph: int,
    *,
    fill_index: int = 0,
) -> list[list[int]]:
    """pw x ph indices; filas incompletas se rellenan con fill_index."""
    fi = clamp_pixel_storage_index(fill_index)
    out: list[list[int]] = []
    for y in range(ph):
        src = rows[y] if rows and y < len(rows) else []
        if not isinstance(src, list):
            src = []
        row: list[int] = []
        for x in range(pw):
            try:
                v = int(src[x]) if x < len(src) else fi
            except (TypeError, ValueError):
                v = fi
            row.append(clamp_pixel_storage_index(v))
        out.append(row)
    return out


def palette_rows_pixel_size(rows: list[list[int]] | None) -> tuple[int, int]:
    if not isinstance(rows, list) or not rows:
        return 0, 0
    ph = len(rows)
    pw = max((len(r) for r in rows if isinstance(r, list)), default=0)
    return pw, ph


def clone_palette_rows(rows: list[list[int]]) -> list[list[int]]:
    return [
        [clamp_pixel_storage_index(c) for c in (r if isinstance(r, list) else [])]
        for r in rows
    ]


def _merge_current_into_stash(
    stash: dict[str, Any],
    current: list[list[int]],
    old_pw: int,
    old_ph: int,
) -> dict[str, Any]:
    """Actualiza la esquina superior izquierda del stash con el lienzo activo."""
    sw = int(stash.get("pw", 0))
    sh = int(stash.get("ph", 0))
    raw = stash.get("rows")
    if sw <= 0 or sh <= 0 or not isinstance(raw, list):
        return {
            "pw": old_pw,
            "ph": old_ph,
            "rows": clone_palette_rows(current),
        }
    merged = normalize_palette_rows(raw, sw, sh, fill_index=0)
    for y in range(min(old_ph, sh)):
        src = current[y] if y < len(current) else []
        if not isinstance(src, list):
            continue
        for x in range(min(old_pw, sw)):
            if x < len(src):
                merged[y][x] = clamp_pixel_storage_index(src[x])
    return {"pw": sw, "ph": sh, "rows": merged}


def resize_palette_rows_with_stash(
    rows: list[list[int]] | None,
    stash: dict[str, Any] | None,
    new_pw: int,
    new_ph: int,
    *,
    fill_index: int,
) -> tuple[list[list[int]], dict[str, Any] | None]:
    """
  Redimensiona la matriz activa. Al encoger guarda el contenido previo en stash
  (para recuperarlo si se agranda de nuevo). Al guardar en disco usar solo
  trim_palette_rows al tamano final y descartar el stash.
    """
    new_pw = max(0, int(new_pw))
    new_ph = max(0, int(new_ph))
    if new_pw <= 0 or new_ph <= 0:
        return [], stash

    fi = clamp_pixel_storage_index(fill_index)
    old_pw, old_ph = palette_rows_pixel_size(
        rows if isinstance(rows, list) else None
    )
    if old_pw <= 0 or old_ph <= 0:
        return solid_fill_indices(new_pw, new_ph, fi), stash

    current = normalize_palette_rows(rows, old_pw, old_ph, fill_index=fi)
    shrinking = new_pw < old_pw or new_ph < old_ph
    growing = new_pw > old_pw or new_ph > old_ph

    if shrinking:
        if (
            isinstance(stash, dict)
            and int(stash.get("pw", 0)) >= old_pw
            and int(stash.get("ph", 0)) >= old_ph
        ):
            stash = _merge_current_into_stash(stash, current, old_pw, old_ph)
        else:
            stash = {
                "pw": old_pw,
                "ph": old_ph,
                "rows": clone_palette_rows(current),
            }
        return normalize_palette_rows(current, new_pw, new_ph, fill_index=fi), stash

    if growing:
        result = solid_fill_indices(new_pw, new_ph, fi)
        for y in range(min(old_ph, new_ph)):
            for x in range(min(old_pw, new_pw)):
                result[y][x] = current[y][x]
        if isinstance(stash, dict):
            sw = int(stash.get("pw", 0))
            sh = int(stash.get("ph", 0))
            srows = stash.get("rows")
            if sw > 0 and sh > 0 and isinstance(srows, list):
                sn = normalize_palette_rows(srows, sw, sh, fill_index=fi)
                for y in range(new_ph):
                    for x in range(new_pw):
                        if x < old_pw and y < old_ph:
                            continue
                        if x < sw and y < sh:
                            result[y][x] = sn[y][x]
        return result, stash

    return normalize_palette_rows(current, new_pw, new_ph, fill_index=fi), stash


def trim_palette_rows(
    rows: list[list[int]] | None,
    pw: int,
    ph: int,
    *,
    fill_index: int = 0,
) -> list[list[int]]:
    """Recorte estricto al tamano del sprite (p. ej. al guardar en JSON)."""
    return normalize_palette_rows(rows, pw, ph, fill_index=fill_index)


def replace_palette_index_in_rows(
    rows: list[list[int]] | None,
    from_index: int,
    to_index: int,
) -> list[list[int]] | None:
    """Sustituye todos los pixeles con from_index por to_index (matriz in-place nueva)."""
    if not isinstance(rows, list) or not rows:
        return rows
    src = clamp_pixel_storage_index(from_index)
    dst = clamp_pixel_storage_index(to_index)
    if src == dst:
        return rows
    out: list[list[int]] = []
    for row in rows:
        if not isinstance(row, list):
            out.append([])
            continue
        out.append(
            [
                dst if clamp_pixel_storage_index(c) == src else clamp_pixel_storage_index(c)
                for c in row
            ]
        )
    return out


def indexed_pixels_sprite_payload(
    sprite_id: str,
    *,
    palette_rel: str,
    cell_px: int,
    blocks_w: int,
    blocks_h: int,
    rows: list[list[int]],
    frame_rows: list[list[list[int]]] | None = None,
    origin_x: int = 0,
    origin_y: int = 0,
) -> dict[str, object]:
    sid = validate_sprite_id(sprite_id)
    pal = normalize_palette_rel(palette_rel)
    cp = max(1, min(int(cell_px), 256))
    bw = max(1, min(int(blocks_w), MAX_BLOCKS_PER_AXIS))
    bh = max(1, min(int(blocks_h), MAX_BLOCKS_PER_AXIS))
    pw = bw * cp
    ph = bh * cp
    all_frames = frame_rows if frame_rows else [rows]
    image0, extras, fc = serialize_sprite_frames(all_frames, pw=pw, ph=ph, fill_index=0)
    ox, oy = parse_sprite_origin(
        {"origin_x": origin_x, "origin_y": origin_y}, pw=pw, ph=ph
    )
    return {
        "format_version": SPRITE_JSON_VERSION,
        "kind": SPRITE_JSON_KIND,
        "id": sid,
        "notes": "",
        "palette": pal,
        "cell_px": cp,
        "blocks_w": bw,
        "blocks_h": bh,
        "pixel_w": pw,
        "pixel_h": ph,
        "origin_x": ox,
        "origin_y": oy,
        "frame_count": fc,
        "render": {"mode": SPRITE_RENDER_INDEXED_PIXELS},
        "image": image0,
        "frames": extras,
    }


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
    if isinstance(previous.get("frame_count"), int) and "frame_count" not in new:
        new["frame_count"] = previous["frame_count"]
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
    origin_x: int = 0,
    origin_y: int = 0,
) -> Path:
    """Crea o sobrescribe objects/Sprites/<id>.json (modo solido). Conserva notes y frames; borra image."""
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
    bw_ok = max(1, min(int(blocks_w), MAX_BLOCKS_PER_AXIS))
    bh_ok = max(1, min(int(blocks_h), MAX_BLOCKS_PER_AXIS))
    pw_i, ph_i = bw_ok * cp, bh_ok * cp
    ox, oy = parse_sprite_origin(
        {"origin_x": origin_x, "origin_y": origin_y}, pw=pw_i, ph=ph_i
    )
    payload = solid_sprite_payload(
        sid,
        palette_rel=pal_ok,
        blocks_w=blocks_w,
        blocks_h=blocks_h,
        palette_index=palette_index,
        cell_px=cp,
        origin_x=ox,
        origin_y=oy,
    )
    _preserve_sprite_extras(payload, previous)
    payload["image"] = None
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


def save_indexed_pixels_sprite_json(
    project_root: Path,
    sprite_id: str,
    *,
    palette_rel: str,
    blocks_w: int,
    blocks_h: int,
    rows: list[list[int]],
    frame_rows: list[list[list[int]]] | None = None,
    cell_px: int | None = None,
    origin_x: int = 0,
    origin_y: int = 0,
) -> Path:
    """Crea o sobrescribe sprite en modo indexed_pixels + image.palette_rows."""
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
    pw_i = len(rows[0]) if rows and rows[0] else 1
    ph_i = len(rows) if rows else 1
    ox, oy = parse_sprite_origin(
        {"origin_x": origin_x, "origin_y": origin_y}, pw=pw_i, ph=ph_i
    )
    all_frames = frame_rows if frame_rows is not None else [rows]
    payload = indexed_pixels_sprite_payload(
        sid,
        palette_rel=pal_ok,
        cell_px=cp,
        blocks_w=blocks_w,
        blocks_h=blocks_h,
        rows=rows,
        frame_rows=all_frames,
        origin_x=ox,
        origin_y=oy,
    )
    if isinstance(previous, dict) and isinstance(previous.get("notes"), str):
        payload["notes"] = previous["notes"]
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def sprite_is_indexed_pixels(data: dict[str, Any]) -> bool:
    render = data.get("render")
    if not isinstance(render, dict):
        return False
    return render.get("mode") == SPRITE_RENDER_INDEXED_PIXELS
