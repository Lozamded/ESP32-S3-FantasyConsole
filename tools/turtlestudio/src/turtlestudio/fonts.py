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
) -> Path:
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
