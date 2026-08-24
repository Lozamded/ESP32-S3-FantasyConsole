"""Fuentes del proyecto: `objects/Fonts/<id>.json` (glifos indexados, cuadrados, multiplos de 4)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from turtlestudio.sprites import (
    SPRITE_IMAGE_FORMAT_ROWS,
    _parse_palette_rows_from_image_dict,
    normalize_palette_rel,
    solid_fill_indices,
    trim_palette_rows,
    validate_palette_file_under_project,
    validate_sprite_id,
)

FONT_JSON_VERSION = 1
FONT_JSON_KIND = "turtlestudio.font"
DEFAULT_GLYPH_PX = 8
MIN_GLYPH_PX = 4
MAX_GLYPH_PX = 32
GLYPH_PX_STEP = 4
FONT_GLYPH_SIZE_CHOICES: tuple[int, ...] = (4, 8, 12, 16)

# Alfabeto latino basico + digitos + espacio y puntuacion minima (v0 del editor).
LATIN_CHARSET: str = (
    " "
    + "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    + "abcdefghijklmnopqrstuvwxyz"
    + "0123456789"
    + ".,!?:;'-"
)


def font_char_label(ch: str) -> str:
    if ch == " ":
        return "(espacio)"
    if ch == "'":
        return "apostrofo (')"
    return ch


def font_char_from_label(label: str) -> str | None:
    s = str(label).strip()
    if s == "(espacio)":
        return " "
    if s.startswith("apostrofo"):
        return "'"
    if len(s) == 1 and s in LATIN_CHARSET:
        return s
    return None


def latin_charset_labels() -> list[str]:
    return [font_char_label(c) for c in LATIN_CHARSET]


def normalize_glyph_px(raw: object) -> int:
    try:
        n = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = DEFAULT_GLYPH_PX
    if n <= MIN_GLYPH_PX:
        return MIN_GLYPH_PX
    n = min(MAX_GLYPH_PX, n)
    snapped = int(round(n / float(GLYPH_PX_STEP))) * GLYPH_PX_STEP
    return max(MIN_GLYPH_PX, snapped)


def glyph_px_label(px: int) -> str:
    return f"{normalize_glyph_px(px)} px"


def glyph_px_from_label(label: str) -> int:
    s = str(label).strip().lower().replace("px", "").strip()
    try:
        return normalize_glyph_px(int(s))
    except (TypeError, ValueError):
        return DEFAULT_GLYPH_PX


def fonts_dir(project_root: Path) -> Path:
    return project_root / "objects" / "Fonts"


def validate_font_id(raw: str) -> str:
    return validate_sprite_id(raw)


def font_json_path(project_root: Path, stem: str) -> Path:
    fid = validate_font_id(stem)
    return fonts_dir(project_root) / f"{fid}.json"


def list_font_json_stems(project_root: Path) -> list[str]:
    d = fonts_dir(project_root)
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json") if p.is_file())


def read_font_file(project_root: Path, stem: str) -> dict[str, Any]:
    p = font_json_path(project_root, stem)
    if not p.is_file():
        raise ValueError(f"no existe la fuente {stem}.json en objects/Fonts/")
    try:
        data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON invalido en objects/Fonts/{stem}.json") from e
    if not isinstance(data, dict):
        raise ValueError(f"objects/Fonts/{stem}.json: raiz debe ser un objeto")
    if data.get("kind") != FONT_JSON_KIND:
        raise ValueError(
            f"objects/Fonts/{stem}.json: kind esperado {FONT_JSON_KIND!r}"
        )
    return data


def font_file_glyph_px(data: dict[str, Any]) -> int:
    try:
        px = int(data.get("glyph_px", DEFAULT_GLYPH_PX))
    except (TypeError, ValueError):
        px = DEFAULT_GLYPH_PX
    return normalize_glyph_px(px)


def empty_glyph_rows(px: int, *, fill_index: int = 1) -> list[list[int]]:
    return solid_fill_indices(px, px, fill_index)


def _pack_glyph_image(rows: list[list[int]], *, pw: int, ph: int, fill_index: int) -> dict[str, Any]:
    norm = trim_palette_rows(rows, pw, ph, fill_index=fill_index)
    return {"format": SPRITE_IMAGE_FORMAT_ROWS, "rows": norm}


def parse_font_glyphs(
    data: dict[str, Any],
    *,
    fill_index: int = 1,
) -> dict[str, list[list[int]]]:
    """Mapa carácter → matriz [y][x]; fila 0 arriba."""
    px = font_file_glyph_px(data)
    charset = str(data.get("charset", LATIN_CHARSET))
    out: dict[str, list[list[int]]] = {}
    raw = data.get("glyphs")
    by_ch: dict[str, dict[str, Any]] = {}
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            ch = str(entry.get("ch", entry.get("char", "")))
            if len(ch) == 1:
                by_ch[ch] = entry
    for ch in charset:
        if len(ch) != 1:
            continue
        entry = by_ch.get(ch)
        parsed: list[list[int]] | None = None
        if isinstance(entry, dict):
            im = entry.get("image")
            if isinstance(im, dict):
                parsed = _parse_palette_rows_from_image_dict(im, pw=px, ph=px)
        if parsed is None:
            parsed = empty_glyph_rows(px, fill_index=fill_index)
        out[ch] = parsed
    return out


def serialize_font_glyphs(
    glyphs: dict[str, list[list[int]]],
    *,
    charset: str,
    pw: int,
    ph: int,
    fill_index: int = 1,
) -> list[dict[str, Any]]:
    fi = max(0, int(fill_index))
    rows_out: list[dict[str, Any]] = []
    for ch in charset:
        if len(ch) != 1:
            continue
        rows = glyphs.get(ch)
        if not isinstance(rows, list):
            rows = empty_glyph_rows(pw, fill_index=fi)
        adv = pw
        rows_out.append(
            {
                "ch": ch,
                "advance": adv,
                "image": _pack_glyph_image(rows, pw=pw, ph=ph, fill_index=fi),
            }
        )
    return rows_out


def font_payload(
    font_id: str,
    *,
    palette_rel: str,
    glyph_px: int,
    glyphs: dict[str, list[list[int]]],
    charset: str = LATIN_CHARSET,
    line_height: int | None = None,
    baseline: int | None = None,
    fill_index: int = 1,
) -> dict[str, Any]:
    fid = validate_font_id(font_id)
    pal = normalize_palette_rel(palette_rel)
    px = normalize_glyph_px(glyph_px)
    lh = int(line_height) if line_height is not None else px
    bl = int(baseline) if baseline is not None else px
    return {
        "format_version": FONT_JSON_VERSION,
        "kind": FONT_JSON_KIND,
        "id": fid,
        "notes": "",
        "palette": pal,
        "glyph_px": px,
        "line_height": max(px, lh),
        "baseline": max(0, min(px, bl)),
        "charset": charset,
        "glyphs": serialize_font_glyphs(
            glyphs,
            charset=charset,
            pw=px,
            ph=px,
            fill_index=fill_index,
        ),
    }


def save_font_json(
    project_root: Path,
    font_id: str,
    *,
    palette_rel: str,
    glyph_px: int,
    glyphs: dict[str, list[list[int]]],
    charset: str = LATIN_CHARSET,
    fill_index: int = 1,
    line_height: int | None = None,
    baseline: int | None = None,
) -> Path:
    """Escribe/actualiza `objects/Fonts/<id>.json`.

    `line_height`/`baseline` explicitos tienen prioridad; si se omiten (None),
    se preserva el valor previo del archivo (o `glyph_px` si es un archivo nuevo).
    """
    fid = validate_font_id(font_id)
    validate_palette_file_under_project(project_root, palette_rel)
    px = normalize_glyph_px(glyph_px)
    d = fonts_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{fid}.json"
    previous: dict[str, Any] | None = None
    if path.is_file():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(previous, dict):
                previous = None
        except (OSError, json.JSONDecodeError):
            previous = None
    lh = px
    bl = px
    if isinstance(previous, dict):
        try:
            lh = int(previous.get("line_height", px))
        except (TypeError, ValueError):
            lh = px
        try:
            bl = int(previous.get("baseline", px))
        except (TypeError, ValueError):
            bl = px
    if line_height is not None:
        lh = int(line_height)
    if baseline is not None:
        bl = int(baseline)
    payload = font_payload(
        fid,
        palette_rel=palette_rel,
        glyph_px=px,
        glyphs=glyphs,
        charset=charset,
        line_height=lh,
        baseline=bl,
        fill_index=fill_index,
    )
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def font_charset_from_data(data: dict[str, Any]) -> str:
    cs = str(data.get("charset", LATIN_CHARSET))
    return cs if cs else LATIN_CHARSET


def font_metrics_from_data(data: dict[str, Any]) -> tuple[int, int, int]:
    """(glyph_px, line_height, baseline)."""
    px = font_file_glyph_px(data)
    try:
        lh = int(data.get("line_height", px))
    except (TypeError, ValueError):
        lh = px
    try:
        bl = int(data.get("baseline", px))
    except (TypeError, ValueError):
        bl = px
    lh = max(px, lh)
    bl = max(0, min(px, bl))
    return px, lh, bl


def parse_font_advances(data: dict[str, Any]) -> dict[str, int]:
    px = font_file_glyph_px(data)
    out: dict[str, int] = {}
    raw = data.get("glyphs")
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            ch = str(entry.get("ch", entry.get("char", "")))
            if len(ch) != 1:
                continue
            try:
                adv = int(entry.get("advance", px))
            except (TypeError, ValueError):
                adv = px
            out[ch] = max(1, min(255, adv))
    return out


def blit_text_scene(
    rgba: list[float],
    fw: int,
    fh: int,
    sx: int,
    sy: int,
    text: str,
    *,
    glyphs: dict[str, list[list[int]]],
    advances: dict[str, int],
    glyph_px: int,
    rgbs: list[tuple[float, float, float]],
    tint_index: int = -1,
    cam_x: int = 0,
    cam_y: int = 0,
) -> int:
    """Blits `text` onto a scene-space RGBA buffer (origin bottom-left, Y up -- same
    convention as turtle_font_draw_scene[_tint] in firmware). Shared by play_runtime.py
    (actor text overlays) and scene_editor.py (static scene text labels) so both preview
    paths match the firmware pixel-for-pixel. cam_x/cam_y: default (0, 0) preserves the
    "rgba = whole world" case; pass the camera to blit against a viewport-sized buffer."""
    from turtlestudio.palette_policy import is_transparent_palette_index, resolve_palette_color

    x = sx
    for ch in text:
        rows = glyphs.get(ch)
        adv = advances.get(ch, glyph_px)
        if rows is not None:
            for gy in range(glyph_px):
                row = rows[gy] if gy < len(rows) else []
                scene_y = sy + (glyph_px - 1 - gy) - cam_y
                ty = (fh - 1) - scene_y
                if ty < 0 or ty >= fh:
                    continue
                row_base = ty * fw * 4
                for gx in range(min(glyph_px, len(row))):
                    idx = row[gx]
                    if is_transparent_palette_index(idx):
                        continue
                    use_idx = tint_index if tint_index >= 0 else idx
                    col = resolve_palette_color(use_idx, rgbs)
                    if col is None:
                        continue
                    sxp = x + gx - cam_x
                    if sxp < 0 or sxp >= fw:
                        continue
                    i = row_base + sxp * 4
                    r, g, b = col
                    rgba[i] = r
                    rgba[i + 1] = g
                    rgba[i + 2] = b
                    rgba[i + 3] = 1.0
        x += adv
    return x - sx


def shrink_font_json_for_export(data: dict[str, Any]) -> dict[str, Any]:
    fid = str(data.get("id", "")).strip()
    px, lh, bl = font_metrics_from_data(data)
    return {
        "format_version": int(data.get("format_version", FONT_JSON_VERSION)),
        "kind": FONT_JSON_KIND,
        "id": fid,
        "palette": str(data.get("palette", "")).strip(),
        "glyph_px": px,
        "line_height": lh,
        "baseline": bl,
        "charset": font_charset_from_data(data),
        "glyphs": data.get("glyphs") if isinstance(data.get("glyphs"), list) else [],
    }


def render_font_preview_rgba(
    text: str,
    *,
    glyphs: dict[str, list[list[int]]],
    palette_rgb: list[tuple[float, float, float]],
    glyph_px: int,
    line_height: int,
    advances: dict[str, int] | None = None,
    canvas_fill_rgb: tuple[float, float, float] = (0.55, 0.55, 0.58),
    missing_ch: str = " ",
) -> tuple[list[float], int, int]:
    """
    Compone una linea de texto para vista previa (fila 0 = arriba).
    Devuelve (rgba, ancho, alto).
    """
    from turtlestudio.palette_policy import resolve_palette_color
    from turtlestudio.sprite_ref_image import _solid_fill_rgba_float01

    px = normalize_glyph_px(glyph_px)
    lh = max(px, int(line_height))
    adv_map = advances or {}
    miss = missing_ch if len(missing_ch) == 1 else " "

    total_w = 0
    for ch in text:
        c = ch if len(ch) == 1 else miss
        total_w += adv_map.get(c, px)
    if total_w < 1:
        total_w = px
    if not text:
        total_w = px

    fill = (
        max(0.0, min(1.0, float(canvas_fill_rgb[0]))),
        max(0.0, min(1.0, float(canvas_fill_rgb[1]))),
        max(0.0, min(1.0, float(canvas_fill_rgb[2]))),
    )
    out = _solid_fill_rgba_float01(total_w, lh, fill)
    y0 = lh - px
    x = 0
    for ch in text:
        c = ch if len(ch) == 1 else miss
        rows = glyphs.get(c)
        if not isinstance(rows, list):
            rows = glyphs.get(miss)
        if not isinstance(rows, list):
            rows = empty_glyph_rows(px, fill_index=1)
        adv = adv_map.get(c, px)
        for py in range(px):
            row = rows[py] if py < len(rows) else []
            dst_y = y0 + py
            if dst_y < 0 or dst_y >= lh:
                continue
            for lx in range(px):
                if lx >= len(row):
                    continue
                try:
                    idx = int(row[lx])
                except (TypeError, ValueError):
                    idx = 0
                col = resolve_palette_color(idx, palette_rgb)
                if col is None:
                    continue
                i = (dst_y * total_w + (x + lx)) * 4
                if i + 3 >= len(out):
                    continue
                out[i] = col[0]
                out[i + 1] = col[1]
                out[i + 2] = col[2]
                out[i + 3] = 1.0
        x += adv
    return out, total_w, lh


def write_font_json(
    project_root: Path,
    font_id: str,
    *,
    palette_rel: str,
    glyph_px: int,
    glyphs: dict[str, list[list[int]]],
    charset: str = LATIN_CHARSET,
    fill_index: int = 1,
) -> Path:
    fid = validate_font_id(font_id)
    validate_palette_file_under_project(project_root, palette_rel)
    path = font_json_path(project_root, fid)
    if path.is_file():
        raise ValueError(f"ya existe objects/Fonts/{path.name}")
    return save_font_json(
        project_root,
        fid,
        palette_rel=palette_rel,
        glyph_px=glyph_px,
        glyphs=glyphs,
        charset=charset,
        fill_index=fill_index,
    )
