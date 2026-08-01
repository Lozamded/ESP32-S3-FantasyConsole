"""
Formato binario para assets en la microSD (exportacion).

El proyecto TurtleStudio sigue usando JSON en disco; al exportar el paquete SD
se convierte a .tbg (fondo) / .tsp (sprite) para carga rapida en ESP32.
"""

from __future__ import annotations

import struct
from typing import Any

from turtlestudio.palette_policy import clamp_pixel_storage_index

TBG_MAGIC = b"TBG\0"
TSP_MAGIC = b"TSP\0"
TTS_MAGIC = b"TTS\0"
TFN_MAGIC = b"TFN\0"
BIN_VERSION = 0
TTS_HEADER_SIZE = 10
TFN_HEADER_SIZE = 14

MODE_SOLID = 0
MODE_RAW = 1
MODE_ROW_RLE = 2

# .tts v1: agrega bloque de colision por tile (10 bytes/tile) tras los chunks de pixeles.
# Ver spec/asset-bin-v0.md.
TTS_VERSION_WITH_COLLISION = 1
_TILE_COLL_KIND_TO_INT = {"solid": 0, "none": 1, "shape": 2}
_TILE_COLL_DIR_TO_INT = {"up": 0, "down": 1, "left": 2, "right": 3}


def _u16_le(n: int) -> bytes:
    return struct.pack("<H", max(0, min(65535, int(n))))


def _header(magic: bytes, pw: int, ph: int, mode: int) -> bytes:
    return magic + bytes([BIN_VERSION, 0]) + _u16_le(pw) + _u16_le(ph) + bytes([mode & 0xFF])


def encode_indexed_rows(pw: int, ph: int, rows: list[list[int]]) -> bytes:
    """Elige solid / raw / row-RLE (el mas pequeno)."""
    from turtlestudio.pixel_rows_codec import detect_solid_palette_index, encode_rows_as_rle

    solid = detect_solid_palette_index(rows, pw, ph)
    if solid is not None:
        return _header(TBG_MAGIC, pw, ph, MODE_SOLID) + bytes([clamp_pixel_storage_index(solid)])

    raw_body = bytearray(pw * ph)
    for y in range(ph):
        src = rows[y] if y < len(rows) else []
        off = y * pw
        for x in range(pw):
            try:
                v = int(src[x]) if x < len(src) else 0
            except (TypeError, ValueError):
                v = 0
            raw_body[off + x] = clamp_pixel_storage_index(v)

    rle_body = bytearray()
    rle_rows = encode_rows_as_rle(rows, pw, ph)
    for y in range(ph):
        row_runs = rle_rows[y] if y < len(rle_rows) else []
        rle_body.extend(_u16_le(len(row_runs)))
        for run in row_runs:
            if not isinstance(run, (list, tuple)) or len(run) < 2:
                continue
            idx = clamp_pixel_storage_index(int(run[0]))
            cnt = max(1, min(65535, int(run[1])))
            rle_body.append(idx)
            rle_body.extend(_u16_le(cnt))

    raw_pack = _header(TBG_MAGIC, pw, ph, MODE_RAW) + bytes(raw_body)
    rle_pack = _header(TBG_MAGIC, pw, ph, MODE_ROW_RLE) + bytes(rle_body)
    return rle_pack if len(rle_pack) < len(raw_pack) else raw_pack


def background_json_to_tbg(data: dict[str, Any]) -> bytes:
    from turtlestudio.backgrounds import (
        background_is_indexed_pixels,
        background_pixel_dimensions,
        parse_background_palette_rows,
        parse_background_solid_palette_index,
    )

    pw, ph = background_pixel_dimensions(data)
    if not background_is_indexed_pixels(data):
        idx = parse_background_solid_palette_index(data)
        return _header(TBG_MAGIC, pw, ph, MODE_SOLID) + bytes([clamp_pixel_storage_index(idx)])
    rows = parse_background_palette_rows(data)
    if rows is None:
        return _header(TBG_MAGIC, pw, ph, MODE_SOLID) + bytes([0])
    return encode_indexed_rows(pw, ph, rows)


def _indexed_frame_payload(pw: int, ph: int, rows: list[list[int]]) -> bytes:
    """Byte `mode` + payload (sin cabecera magic/dimensiones)."""
    pack = encode_indexed_rows(pw, ph, rows)
    return pack[10:]


def sprite_json_to_tsp(data: dict[str, Any]) -> bytes:
    from turtlestudio.sprites import (
        parse_palette_rows_image,
        parse_sprite_all_frame_rows,
        parse_sprite_frame_count,
        sprite_is_indexed_pixels,
        sprite_pixel_dimensions,
    )

    _, pw, ph = sprite_pixel_dimensions(data)
    if not sprite_is_indexed_pixels(data):
        render = data.get("render")
        idx = 0
        if isinstance(render, dict):
            try:
                idx = int(render.get("palette_index", 0))
            except (TypeError, ValueError):
                idx = 0
        return _header(TSP_MAGIC, pw, ph, MODE_SOLID) + bytes([clamp_pixel_storage_index(idx)])

    frame_count = parse_sprite_frame_count(data)
    if frame_count > 1:
        frames = parse_sprite_all_frame_rows(data)
        fc = max(1, min(len(frames), frame_count))
        out = bytearray(TSP_MAGIC + bytes([1, 0]) + _u16_le(pw) + _u16_le(ph) + _u16_le(fc))
        for i in range(fc):
            payload = _indexed_frame_payload(pw, ph, frames[i])
            out.extend(struct.pack("<I", len(payload)))
            out.extend(payload)
        return bytes(out)

    rows = parse_palette_rows_image(data)
    if rows is None:
        return _header(TSP_MAGIC, pw, ph, MODE_SOLID) + bytes([0])
    body = encode_indexed_rows(pw, ph, rows)
    return TSP_MAGIC + body[4:]  # mismo layout, distinto magic


def _encode_tile_collision_block(meta_list: list[dict[str, Any]], tile_count: int) -> bytes:
    """10 bytes/tile: kind u8, flags u8 (oneway|dir<<1), x0/y0/x1/y1 i16 LE (solo kind=shape)."""
    from turtlestudio.tile_collision import normalize_tile_collision_meta_list

    def clamp16(v: object) -> int:
        return max(-32768, min(32767, int(v)))  # type: ignore[arg-type]

    meta = normalize_tile_collision_meta_list(meta_list, tile_count)
    out = bytearray()
    for m in meta:
        kind = _TILE_COLL_KIND_TO_INT.get(str(m.get("kind")), 0)
        oneway = 1 if m.get("oneway") else 0
        direction = _TILE_COLL_DIR_TO_INT.get(str(m.get("oneway_direction")), 0)
        flags = (oneway & 0x01) | ((direction & 0x03) << 1)
        shape = m.get("shape") if kind == 2 else None
        if isinstance(shape, dict):
            x0, y0 = clamp16(shape.get("x0", 0)), clamp16(shape.get("y0", 0))
            x1, y1 = clamp16(shape.get("x1", 0)), clamp16(shape.get("y1", 0))
        else:
            x0 = y0 = x1 = y1 = 0
        out.append(kind & 0xFF)
        out.append(flags & 0xFF)
        out.extend(struct.pack("<hhhh", x0, y0, x1, y1))
    return bytes(out)


def tileset_json_to_tts(data: dict[str, Any]) -> bytes:
    """
    Tileset completo: cabecera TTS (v1) + N bloques (u32 tamano + mini-blob TSP por tile) +
    bloque de colision por tile (ver _encode_tile_collision_block / spec/asset-bin-v0.md).
    Cada tile es tile_px×tile_px indexado (misma codificacion que .tsp).
    """
    from turtlestudio.tile_collision import parse_tileset_collision_meta
    from turtlestudio.tiles import parse_tileset_all_tiles, tileset_file_pixel_dimensions

    px = tileset_file_pixel_dimensions(data)
    tiles = parse_tileset_all_tiles(data, fill_index=1)
    out = bytearray(
        TTS_MAGIC + bytes([TTS_VERSION_WITH_COLLISION, 0]) + _u16_le(px) + _u16_le(len(tiles))
    )
    for rows in tiles:
        inner = encode_indexed_rows(px, px, rows)
        chunk = TSP_MAGIC + inner[4:]
        out.extend(struct.pack("<I", len(chunk)))
        out.extend(chunk)
    out.extend(_encode_tile_collision_block(parse_tileset_collision_meta(data), len(tiles)))
    return bytes(out)


def font_json_to_tfn(data: dict[str, Any]) -> bytes:
    """
    Fuente completa: cabecera TFN + N bloques (u8 advance + u32 tamano + mini-blob TSP).
    Orden de glifos = `charset` del JSON.
    """
    from turtlestudio.fonts import (
        font_charset_from_data,
        font_metrics_from_data,
        parse_font_advances,
        parse_font_glyphs,
    )

    px, lh, bl = font_metrics_from_data(data)
    charset = font_charset_from_data(data)
    glyphs = parse_font_glyphs(data, fill_index=1)
    advances = parse_font_advances(data)
    chars = [c for c in charset if len(c) == 1]
    out = bytearray(
        TFN_MAGIC
        + bytes([BIN_VERSION, 0])
        + _u16_le(px)
        + _u16_le(lh)
        + _u16_le(bl)
        + _u16_le(len(chars))
    )
    for ch in chars:
        adv = max(1, min(255, int(advances.get(ch, px))))
        rows = glyphs.get(ch)
        if not isinstance(rows, list):
            rows = [[1] * px for _ in range(px)]
        inner = encode_indexed_rows(px, px, rows)
        chunk = TSP_MAGIC + inner[4:]
        out.append(adv & 0xFF)
        out.extend(struct.pack("<I", len(chunk)))
        out.extend(chunk)
    return bytes(out)
