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
BIN_VERSION = 0
TTS_HEADER_SIZE = 10

MODE_SOLID = 0
MODE_RAW = 1
MODE_ROW_RLE = 2


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


def sprite_json_to_tsp(data: dict[str, Any]) -> bytes:
    from turtlestudio.sprites import (
        parse_palette_rows_image,
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
    rows = parse_palette_rows_image(data)
    if rows is None:
        return _header(TSP_MAGIC, pw, ph, MODE_SOLID) + bytes([0])
    body = encode_indexed_rows(pw, ph, rows)
    return TSP_MAGIC + body[4:]  # mismo layout, distinto magic


def tileset_json_to_tts(data: dict[str, Any]) -> bytes:
    """
    Tileset completo: cabecera TTS + N bloques (u32 tamano + mini-blob TSP por tile).
    Cada tile es tile_px×tile_px indexado (misma codificacion que .tsp).
    """
    from turtlestudio.tiles import parse_tileset_all_tiles, tileset_file_pixel_dimensions

    px = tileset_file_pixel_dimensions(data)
    tiles = parse_tileset_all_tiles(data, fill_index=1)
    out = bytearray(TTS_MAGIC + bytes([BIN_VERSION, 0]) + _u16_le(px) + _u16_le(len(tiles)))
    for rows in tiles:
        inner = encode_indexed_rows(px, px, rows)
        chunk = TSP_MAGIC + inner[4:]
        out.extend(struct.pack("<I", len(chunk)))
        out.extend(chunk)
    return bytes(out)
