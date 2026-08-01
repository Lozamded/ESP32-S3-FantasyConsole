"""Codificacion compacta de matrices de indices (fondos/sprites)."""

from __future__ import annotations

from typing import Any

from turtlestudio.palette_policy import clamp_pixel_storage_index

FORMAT_ROWS = "palette_rows"
FORMAT_ROWS_RLE = "palette_rows_rle"


def detect_solid_palette_index(rows: list[list[int]], pw: int, ph: int) -> int | None:
    """Si todos los pixeles comparten indice, devuelve ese indice; si no, None."""
    first: int | None = None
    for y in range(ph):
        src = rows[y] if y < len(rows) else []
        for x in range(pw):
            try:
                v = int(src[x]) if x < len(src) else 0
            except (TypeError, ValueError):
                v = 0
            ci = clamp_pixel_storage_index(v)
            if first is None:
                first = ci
            elif ci != first:
                return None
    return first


def _encode_row_rle(row: list[int], pw: int) -> list[list[int]]:
    if pw <= 0:
        return []
    runs: list[list[int]] = []
    prev = clamp_pixel_storage_index(row[0] if row else 0)
    count = 1
    for x in range(1, pw):
        v = clamp_pixel_storage_index(row[x] if x < len(row) else prev)
        if v == prev:
            count += 1
        else:
            runs.append([prev, count])
            prev = v
            count = 1
    runs.append([prev, count])
    return runs


def encode_rows_as_rle(rows: list[list[int]], pw: int, ph: int) -> list[list[list[int]]]:
    out: list[list[list[int]]] = []
    for y in range(ph):
        src = rows[y] if y < len(rows) else []
        padded = [
            clamp_pixel_storage_index(src[x] if x < len(src) else 0) for x in range(pw)
        ]
        out.append(_encode_row_rle(padded, pw))
    return out


def _json_utf8_len(obj: object) -> int:
    import json

    return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def pack_palette_rows_image(
    rows: list[list[int]],
    *,
    pw: int,
    ph: int,
) -> dict[str, Any]:
    """
    Elige el formato mas pequeno: RLE por fila o matriz cruda (sin indent).
    """
    rle_rows = encode_rows_as_rle(rows, pw, ph)
    raw = {"format": FORMAT_ROWS, "rows": rows}
    rle = {"format": FORMAT_ROWS_RLE, "rows": rle_rows}
    if _json_utf8_len(rle) < _json_utf8_len(raw):
        return rle
    return raw


def decode_palette_rows_image(im: dict[str, Any], *, pw: int, ph: int) -> list[list[int]] | None:
    """Decodifica image.palette_rows o image.palette_rows_rle."""
    fmt = im.get("format")
    raw_rows = im.get("rows")
    if not isinstance(raw_rows, list):
        return None

    if fmt == FORMAT_ROWS_RLE:
        out: list[list[int]] = []
        for y in range(ph):
            row_out = [0] * pw
            x = 0
            src = raw_rows[y] if y < len(raw_rows) else []
            if not isinstance(src, list):
                src = []
            for run in src:
                if not isinstance(run, (list, tuple)) or len(run) < 2:
                    continue
                try:
                    idx = clamp_pixel_storage_index(int(run[0]))
                    cnt = int(run[1])
                except (TypeError, ValueError):
                    continue
                if cnt < 1:
                    continue
                for _ in range(cnt):
                    if x >= pw:
                        break
                    row_out[x] = idx
                    x += 1
            out.append(row_out)
        return out

    if fmt != FORMAT_ROWS:
        return None

    out = []
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
