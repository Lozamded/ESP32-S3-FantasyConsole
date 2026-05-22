"""Decodificador Python (espejo de firmware/turtle_asset_bin.cpp) para pruebas."""

from __future__ import annotations

import struct

MODE_SOLID = 0
MODE_RAW = 1
MODE_ROW_RLE = 2


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

    if mode == MODE_SOLID:
        if not payload:
            return None
        ci = payload[0] & 0xFF
        for y in range(ph):
            out[y] = [ci] * pw
        return pw, ph, out

    if mode == MODE_RAW:
        need = pw * ph
        if len(payload) < need:
            return None
        for y in range(ph):
            off = y * pw
            out[y] = list(payload[off : off + pw])
        return pw, ph, out

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
        return pw, ph, out

    return None
