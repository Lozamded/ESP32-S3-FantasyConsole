"""Decodificador Python (espejo de firmware/turtle_asset_bin.cpp) para pruebas."""

from __future__ import annotations

import struct

MODE_SOLID = 0
MODE_RAW = 1
MODE_ROW_RLE = 2

TTS_MAGIC = b"TTS\0"
TTS_HEADER_SIZE = 10


def decode_mode_payload(
    mode: int, payload: bytes, *, pw: int, ph: int
) -> list[list[int]] | None:
    """Decodifica cuerpo tras byte `mode` (sin cabecera TBG/TSP)."""
    out: list[list[int]] = [[0] * pw for _ in range(ph)]
    if mode == MODE_SOLID:
        if not payload:
            return None
        ci = payload[0] & 0xFF
        for y in range(ph):
            out[y] = [ci] * pw
        return out
    if mode == MODE_RAW:
        need = pw * ph
        if len(payload) < need:
            return None
        for y in range(ph):
            off = y * pw
            out[y] = list(payload[off : off + pw])
        return out
    if mode == MODE_ROW_RLE:
        p = 0
        end = len(payload)
        for y in range(ph):
            if p + 2 > end:
                return None
            (nruns,) = struct.unpack_from("<H", payload, p)
            p += 2
            x = 0
            for _ in range(nruns):
                if p + 3 > end:
                    return None
                ci = payload[p]
                (cnt,) = struct.unpack_from("<H", payload, p + 1)
                p += 3
                for _ in range(cnt):
                    if x < pw:
                        out[y][x] = ci
                        x += 1
        return out
    return None


def decode_indexed_blob(
    data: bytes, *, expect_w: int, expect_h: int
) -> tuple[int, int, list[list[int]]] | None:
    if len(data) < 11 or data[3] != 0 or data[0] != ord("T"):
        return None
    if data[1:3] not in (b"BG", b"SP"):
        return None
    if data[4] != 0:
        return None
    pw, ph, mode = struct.unpack_from("<HHB", data, 6)
    if pw < 1 or ph < 1 or pw > expect_w or ph > expect_h:
        return None
    payload = data[11:]
    out: list[list[int]] = [[0] * pw for _ in range(ph)]

    rows = decode_mode_payload(mode, payload, pw=pw, ph=ph)
    if rows is None:
        return None
    return pw, ph, rows


def decode_sprite_tsp_frames(
    data: bytes, *, expect_w: int, expect_h: int
) -> tuple[int, int, list[list[list[int]]]] | None:
    """
    Decodifica .tsp v0 (un fotograma) o v1 (varios).
    Devuelve (pw, ph, lista de matrices por fotograma) o None.
    """
    if len(data) < 11 or data[:3] != b"TSP":
        return None
    ver = data[4]
    if ver == 0:
        got = decode_indexed_blob(data, expect_w=expect_w, expect_h=expect_h)
        if got is None:
            return None
        pw, ph, rows = got
        return pw, ph, [rows]

    if ver != 1 or len(data) < 12:
        return None
    pw, ph, fc = struct.unpack_from("<HHH", data, 6)
    if pw < 1 or ph < 1 or fc < 1:
        return None
    off = 12
    frames: list[list[list[int]]] = []
    for _ in range(fc):
        if off + 4 > len(data):
            return None
        (chunk_len,) = struct.unpack_from("<I", data, off)
        off += 4
        if chunk_len < 1 or off + chunk_len > len(data):
            return None
        chunk = data[off : off + chunk_len]
        off += chunk_len
        if len(chunk) < 1:
            return None
        mode = chunk[0]
        rows = decode_mode_payload(mode, chunk[1:], pw=pw, ph=ph)
        if rows is None:
            return None
        frames.append(rows)
    if not frames:
        return None
    return pw, ph, frames


def decode_tileset_blob(data: bytes) -> tuple[int, list[list[list[int]]]] | None:
    """
    Devuelve (tile_px, lista de matrices [tile][y][x]) desde un .tts exportado.
    """
    if len(data) < TTS_HEADER_SIZE or data[:4] != TTS_MAGIC:
        return None
    if data[4] != 0:
        return None
    px, count = struct.unpack_from("<HH", data, 6)
    if px < 1 or count < 0:
        return None
    off = TTS_HEADER_SIZE
    tiles: list[list[list[int]]] = []
    for _ in range(count):
        if off + 4 > len(data):
            return None
        (chunk_len,) = struct.unpack_from("<I", data, off)
        off += 4
        if chunk_len < 11 or off + chunk_len > len(data):
            return None
        chunk = data[off : off + chunk_len]
        off += chunk_len
        got = decode_indexed_blob(chunk, expect_w=px, expect_h=px)
        if got is None:
            return None
        _, _, rows = got
        tiles.append(rows)
    return px, tiles
