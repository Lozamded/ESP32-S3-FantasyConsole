"""Exportar fotogramas de sprite (matrices indexadas) a archivos PNG."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from turtlestudio.palette_policy import resolve_palette_color


def indexed_rows_to_export_rgba(
    rows: list[list[int]],
    rgbs: list[tuple[float, float, float]],
) -> tuple[int, int, list[float]]:
    """
    Convierte una matriz fila×columna de indices de paleta en RGBA 0..1 (fila 0 arriba).
    El indice transparente (31) se exporta con alpha 0.
    """
    ph = len(rows)
    pw = len(rows[0]) if rows else 0
    if pw <= 0 or ph <= 0:
        return 0, 0, []
    rgba: list[float] = [0.0] * (pw * ph * 4)
    for py in range(ph):
        row = rows[py] if py < len(rows) else []
        for lx in range(pw):
            try:
                idx = int(row[lx]) if lx < len(row) else 0
            except (TypeError, ValueError):
                idx = 0
            i = (py * pw + lx) * 4
            col = resolve_palette_color(idx, rgbs)
            if col is None:
                rgba[i : i + 4] = (0.0, 0.0, 0.0, 0.0)
            else:
                rgba[i] = col[0]
                rgba[i + 1] = col[1]
                rgba[i + 2] = col[2]
                rgba[i + 3] = 1.0
    return pw, ph, rgba


def write_rgba_float01_png(path: str | Path, width: int, height: int, rgba: list[float]) -> None:
    """Escribe un PNG RGBA 8-bit; rgba en 0..1, fila 0 = arriba."""
    w = int(width)
    h = int(height)
    if w <= 0 or h <= 0:
        raise ValueError("tamano de imagen invalido")
    need = w * h * 4
    if len(rgba) < need:
        raise ValueError("buffer RGBA mas pequeno que width*height")

    def _byte(v: float) -> int:
        return max(0, min(255, int(round(float(v) * 255.0))))

    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            i = (y * w + x) * 4
            raw.append(_byte(rgba[i]))
            raw.append(_byte(rgba[i + 1]))
            raw.append(_byte(rgba[i + 2]))
            raw.append(_byte(rgba[i + 3]))

    compressed = zlib.compress(bytes(raw), 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )
    out = Path(path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(png)


def export_sprite_frames_to_png_dir(
    output_dir: str | Path,
    base_name: str,
    frame_rows: list[list[list[int]]],
    rgbs: list[tuple[float, float, float]],
) -> list[Path]:
    """
    Escribe un PNG por fotograma en output_dir.
    Nombres: <base>_00.png, <base>_01.png, … (un solo fotograma → <base>.png).
    """
    if not frame_rows:
        raise ValueError("no hay fotogramas para exportar")
    stem = _sanitize_export_stem(base_name)
    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    multi = len(frame_rows) > 1
    for fi, rows in enumerate(frame_rows):
        pw, ph, rgba = indexed_rows_to_export_rgba(rows, rgbs)
        if pw <= 0 or ph <= 0:
            raise ValueError(f"fotograma {fi}: lienzo vacio")
        name = f"{stem}.png" if not multi else f"{stem}_{fi:02d}.png"
        path = out_dir / name
        write_rgba_float01_png(path, pw, ph, rgba)
        written.append(path)
    return written


def _sanitize_export_stem(raw: str) -> str:
    s = raw.strip()
    if not s:
        return "sprite"
    out: list[str] = []
    for ch in s:
        if ch.isalnum() or ch in "-_":
            out.append(ch)
        elif ch.isspace():
            out.append("_")
    stem = "".join(out).strip("._-")
    return stem or "sprite"
