"""Imagen de referencia (PNG/JPG) para el editor de sprites; no modifica la matriz guardada."""

from __future__ import annotations

from pathlib import Path

_REF_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def is_supported_ref_image_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in _REF_SUFFIXES


def load_image_rgba_float01(path: str | Path) -> tuple[int, int, list[float]]:
    """
    Carga imagen con Dear PyGui. Devuelve (ancho, alto, rgba 0..1 fila 0 arriba).
    """
    import dearpygui.dearpygui as dpg

    p = Path(path).expanduser()
    if not p.is_file():
        raise ValueError(f"no existe el archivo: {p}")
    if not is_supported_ref_image_path(p):
        raise ValueError("formato no soportado (usa .png, .jpg, .jpeg, .webp o .bmp)")

    loaded = dpg.load_image(str(p.resolve()))
    if not loaded:
        raise ValueError(f"no se pudo decodificar la imagen: {p.name}")

    w, h, ch, data = loaded
    w = int(w)
    h = int(h)
    ch = int(ch)
    if w <= 0 or h <= 0:
        raise ValueError("imagen vacia o tamano invalido")

    n = w * h * ch
    if ch == 4:
        rgba = [float(data[i]) for i in range(n)]
    elif ch == 3:
        rgba = []
        for i in range(0, n, 3):
            rgba.extend((float(data[i]), float(data[i + 1]), float(data[i + 2]), 1.0))
    elif ch == 1:
        rgba = []
        for i in range(n):
            g = float(data[i])
            rgba.extend((g, g, g, 1.0))
    else:
        raise ValueError(f"canales de imagen no soportados: {ch}")

    rgba = _coerce_rgba_float01(rgba)
    return w, h, rgba


def _coerce_rgba_float01(rgba: list[float]) -> list[float]:
    """DPG a veces devuelve 0..255 en lugar de 0..1."""
    if not rgba:
        return rgba
    peak = max(rgba)
    if peak <= 1.0 + 1e-6:
        return rgba
    inv = 1.0 / 255.0
    return [max(0.0, min(1.0, v * inv)) for v in rgba]


def resample_rgba_stretch(
    src: list[float],
    sw: int,
    sh: int,
    dw: int,
    dh: int,
) -> list[float]:
    """Escala la imagen al tamano del lienzo (dw x dh), interpolacion bilineal."""
    if sw <= 0 or sh <= 0 or dw <= 0 or dh <= 0:
        return []
    if sw == dw and sh == dh:
        return list(src)

    out = [0.0] * (dw * dh * 4)
    if dw == 1 and dh == 1:
        out[0:4] = _sample_bilinear(src, sw, sh, 0.0, 0.0)
        return out

    for dy in range(dh):
        sy = ((dy + 0.5) * sh / dh) - 0.5
        for dx in range(dw):
            sx = ((dx + 0.5) * sw / dw) - 0.5
            oi = (dy * dw + dx) * 4
            r, g, b, a = _sample_bilinear(src, sw, sh, sx, sy)
            out[oi] = r
            out[oi + 1] = g
            out[oi + 2] = b
            out[oi + 3] = a
    return out


def _sample_bilinear(
    src: list[float],
    sw: int,
    sh: int,
    sx: float,
    sy: float,
) -> tuple[float, float, float, float]:
    if sw <= 0 or sh <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    if sw == 1:
        x0 = x1 = 0
        tx = 0.0
    else:
        sx = max(0.0, min(float(sw - 1), sx))
        x0 = int(sx)
        x1 = min(x0 + 1, sw - 1)
        tx = sx - x0
    if sh == 1:
        y0 = y1 = 0
        ty = 0.0
    else:
        sy = max(0.0, min(float(sh - 1), sy))
        y0 = int(sy)
        y1 = min(y0 + 1, sh - 1)
        ty = sy - y0

    def px(x: int, y: int) -> tuple[float, float, float, float]:
        i = (y * sw + x) * 4
        return (src[i], src[i + 1], src[i + 2], src[i + 3])

    c00 = px(x0, y0)
    c10 = px(x1, y0)
    c01 = px(x0, y1)
    c11 = px(x1, y1)
    out: list[float] = []
    for k in range(4):
        top = c00[k] * (1.0 - tx) + c10[k] * tx
        bot = c01[k] * (1.0 - tx) + c11[k] * tx
        out.append(top * (1.0 - ty) + bot * ty)
    return (out[0], out[1], out[2], out[3])


def _rgb_close(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    eps: float = 0.02,
) -> bool:
    return (
        abs(a[0] - b[0]) <= eps
        and abs(a[1] - b[1]) <= eps
        and abs(a[2] - b[2]) <= eps
    )


def _solid_fill_rgba_float01(
    pw: int,
    ph: int,
    rgb: tuple[float, float, float],
) -> list[float]:
    out: list[float] = []
    for _ in range(pw * ph):
        out.extend((rgb[0], rgb[1], rgb[2], 1.0))
    return out


def blend_indexed_rows_on_rgba(
    base: list[float],
    rows: list[list[int]],
    rgbs: list[tuple[float, float, float]],
    *,
    alpha: float = 0.35,
) -> list[float]:
    """Mezcla pixeles opacos de una capa indexada sobre base RGBA (mismo tamano)."""
    from turtlestudio.palette_policy import resolve_palette_color

    ph = len(rows)
    pw = len(rows[0]) if rows else 0
    if pw <= 0 or ph <= 0 or len(base) != pw * ph * 4:
        return base
    fa = max(0.0, min(1.0, float(alpha)))
    if fa <= 0.0:
        return base
    out = list(base)
    inv = 1.0 - fa
    for py in range(ph):
        row = rows[py] if py < len(rows) else []
        for lx in range(pw):
            try:
                idx = int(row[lx]) if lx < len(row) else 0
            except (TypeError, ValueError):
                idx = 0
            col = resolve_palette_color(idx, rgbs)
            if col is None:
                continue
            i = (py * pw + lx) * 4
            br, bg, bb = out[i], out[i + 1], out[i + 2]
            out[i] = br * inv + col[0] * fa
            out[i + 1] = bg * inv + col[1] * fa
            out[i + 2] = bb * inv + col[2] * fa
            out[i + 3] = 1.0
    return out


def composite_sprite_editor_preview(
    rows: list[list[int]],
    rgbs: list[tuple[float, float, float]],
    ref_rgba: list[float] | None,
    *,
    canvas_fill_rgb: tuple[float, float, float] = (0.55, 0.55, 0.58),
    ref_alpha: float = 0.45,
    paint_alpha: float = 1.0,
    behind_rows: list[list[int]] | None = None,
    behind_alpha: float = 0.35,
    over_rows: list[list[int]] | None = None,
    over_alpha: float = 0.35,
) -> list[float]:
    """
    Vista previa del editor: relleno del lienzo, referencia opcional debajo,
    fotograma vecino opcional detras, pixeles del fotograma activo,
    fotograma vecino opcional encima (indice 31 = hueco en todas las capas).
    canvas_fill_rgb: color de fondo del lienzo (solo vista previa; no es paleta).
    """
    from turtlestudio.palette_policy import resolve_palette_color

    ph = len(rows)
    pw = len(rows[0]) if rows else 0
    if pw <= 0 or ph <= 0:
        return []
    fill = (
        max(0.0, min(1.0, float(canvas_fill_rgb[0]))),
        max(0.0, min(1.0, float(canvas_fill_rgb[1]))),
        max(0.0, min(1.0, float(canvas_fill_rgb[2]))),
    )

    underlay = _solid_fill_rgba_float01(pw, ph, fill)
    if ref_rgba is not None and len(ref_rgba) == len(underlay):
        underlay = composite_ref_for_sprite_editor(
            underlay,
            ref_rgba,
            ref_alpha=ref_alpha,
            canvas_fill_rgb=fill,
        )
    if behind_rows is not None:
        underlay = blend_indexed_rows_on_rgba(
            underlay, behind_rows, rgbs, alpha=behind_alpha
        )

    pa = max(0.0, min(1.0, float(paint_alpha)))
    if pa <= 0.0:
        out = list(underlay)
    else:
        out = list(underlay)
        for py in range(ph):
            row = rows[py] if py < len(rows) else []
            for lx in range(pw):
                try:
                    idx = int(row[lx]) if lx < len(row) else 0
                except (TypeError, ValueError):
                    idx = 0
                col = resolve_palette_color(idx, rgbs)
                if col is None:
                    continue
                i = (py * pw + lx) * 4
                if pa >= 1.0 - 1e-6:
                    out[i] = col[0]
                    out[i + 1] = col[1]
                    out[i + 2] = col[2]
                else:
                    inv = 1.0 - pa
                    br, bg, bb = out[i], out[i + 1], out[i + 2]
                    out[i] = br * inv + col[0] * pa
                    out[i + 1] = bg * inv + col[1] * pa
                    out[i + 2] = bb * inv + col[2] * pa
                out[i + 3] = 1.0

    if over_rows is not None:
        out = blend_indexed_rows_on_rgba(out, over_rows, rgbs, alpha=over_alpha)
    return out


def composite_ref_for_sprite_editor(
    pixel_rgba: list[float],
    ref_rgba: list[float],
    *,
    ref_alpha: float = 0.45,
    canvas_fill_rgb: tuple[float, float, float] | None = None,
) -> list[float]:
    """
    Referencia visible en celdas aun con color de relleno del lienzo; lo pintado tapa la ref.
    Si canvas_fill_rgb es None, mezcla la referencia encima de todo (calco).
    """
    if len(pixel_rgba) != len(ref_rgba):
        return pixel_rgba
    fa = max(0.0, min(1.0, float(ref_alpha)))
    if fa <= 0.0:
        return pixel_rgba

    out = list(pixel_rgba)
    inv = 1.0 - fa
    for i in range(0, len(out), 4):
        br, bg, bb = out[i], out[i + 1], out[i + 2]
        rr, rg, rb = ref_rgba[i], ref_rgba[i + 1], ref_rgba[i + 2]
        if canvas_fill_rgb is not None and _rgb_close((br, bg, bb), canvas_fill_rgb):
            out[i] = br * inv + rr * fa
            out[i + 1] = bg * inv + rg * fa
            out[i + 2] = bb * inv + rb * fa
        elif canvas_fill_rgb is None:
            out[i] = br * inv + rr * fa
            out[i + 1] = bg * inv + rg * fa
            out[i + 2] = bb * inv + rb * fa
        out[i + 3] = 1.0
    return out


def resample_rgba_nearest(
    src: list[float],
    sw: int,
    sh: int,
    dw: int,
    dh: int,
) -> list[float]:
    """Escala al tamano del lienzo; un pixel fuente por celda destino (pixel art)."""
    if sw <= 0 or sh <= 0 or dw <= 0 or dh <= 0:
        return []
    if sw == dw and sh == dh:
        return list(src)

    out = [0.0] * (dw * dh * 4)
    for dy in range(dh):
        sy = min(sh - 1, (dy * sh) // dh)
        for dx in range(dw):
            sx = min(sw - 1, (dx * sw) // dw)
            si = (sy * sw + sx) * 4
            oi = (dy * dw + dx) * 4
            out[oi] = src[si]
            out[oi + 1] = src[si + 1]
            out[oi + 2] = src[si + 2]
            out[oi + 3] = src[si + 3]
    return out


def nearest_opaque_palette_index(
    r: float,
    g: float,
    b: float,
    rgbs: list[tuple[float, float, float]],
) -> int:
    """Indice de paleta mas cercano en RGB (excluye el indice transparente 31)."""
    from turtlestudio.palette_policy import (
        TRANSPARENT_PALETTE_INDEX,
        is_transparent_palette_index,
    )

    if not rgbs:
        return 0
    best_i = 0
    best_d = float("inf")
    for i, (pr, pg, pb) in enumerate(rgbs):
        if is_transparent_palette_index(i):
            continue
        d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if d < best_d:
            best_d = d
            best_i = i
    if is_transparent_palette_index(best_i):
        return min(len(rgbs) - 1, TRANSPARENT_PALETTE_INDEX - 1)
    return best_i


def ref_rgba_to_palette_rows(
    rgba: list[float],
    pw: int,
    ph: int,
    rgbs: list[tuple[float, float, float]],
    *,
    alpha_cutoff: float = 0.5,
) -> list[list[int]]:
    """
    Convierte RGBA 0..1 (fila 0 arriba) en matriz de indices de paleta.
    Pixeles semitransparentes o transparentes → indice transparente (31).
    """
    from turtlestudio.palette_policy import TRANSPARENT_PALETTE_INDEX

    if pw <= 0 or ph <= 0:
        return []
    need = pw * ph * 4
    if len(rgba) < need:
        raise ValueError("buffer RGBA mas pequeno que el lienzo")
    ac = max(0.0, min(1.0, float(alpha_cutoff)))
    rows: list[list[int]] = []
    for y in range(ph):
        row: list[int] = []
        for x in range(pw):
            i = (y * pw + x) * 4
            a = rgba[i + 3]
            if a < ac:
                row.append(TRANSPARENT_PALETTE_INDEX)
            else:
                row.append(
                    nearest_opaque_palette_index(
                        rgba[i], rgba[i + 1], rgba[i + 2], rgbs
                    )
                )
        rows.append(row)
    return rows


def crop_ref_tile_rgba(
    ref_source: tuple[int, int, list[float]],
    grid_x: int,
    grid_y: int,
    tile_px: int,
    *,
    pad_rgba: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
) -> tuple[list[float], int, int]:
    """
    Recorta una celda de la rejilla (grid_x, grid_y) con origen arriba-izquierda.
    Devuelve rgba tile_px×tile_px (rellena pad si la imagen no alcanza).
    """
    sw, sh, src = ref_source
    px = max(1, int(tile_px))
    gx = max(0, int(grid_x))
    gy = max(0, int(grid_y))
    x0 = gx * px
    y0 = gy * px
    out = [0.0] * (px * px * 4)
    pr, pg, pb, pa = pad_rgba
    for y in range(px):
        for x in range(px):
            i = (y * px + x) * 4
            out[i] = pr
            out[i + 1] = pg
            out[i + 2] = pb
            out[i + 3] = pa
    if sw <= 0 or sh <= 0 or len(src) < sw * sh * 4:
        return out, px, px
    for ly in range(px):
        sy = y0 + ly
        if sy >= sh:
            continue
        for lx in range(px):
            sx = x0 + lx
            if sx >= sw:
                continue
            si = (sy * sw + sx) * 4
            oi = (ly * px + lx) * 4
            out[oi] = src[si]
            out[oi + 1] = src[si + 1]
            out[oi + 2] = src[si + 2]
            out[oi + 3] = src[si + 3]
    return out, px, px


def ref_grid_dimensions(sw: int, sh: int, tile_px: int) -> tuple[int, int]:
    """Numero de celdas (columnas, filas) que caben en la imagen."""
    px = max(1, int(tile_px))
    return (max(0, int(sw) // px), max(0, int(sh) // px))


def convert_ref_tile_to_palette_rows(
    ref_source: tuple[int, int, list[float]],
    grid_x: int,
    grid_y: int,
    tile_px: int,
    rgbs: list[tuple[float, float, float]],
    *,
    alpha_cutoff: float = 0.5,
) -> list[list[int]]:
    """Celda de la rejilla → matriz de indices de paleta (tamano tile_px)."""
    rgba, pw, ph = crop_ref_tile_rgba(ref_source, grid_x, grid_y, tile_px)
    return ref_rgba_to_palette_rows(rgba, pw, ph, rgbs, alpha_cutoff=alpha_cutoff)


def convert_ref_source_to_palette_rows(
    ref_source: tuple[int, int, list[float]],
    pw: int,
    ph: int,
    rgbs: list[tuple[float, float, float]],
    *,
    alpha_cutoff: float = 0.5,
) -> list[list[int]]:
    """Referencia (sw, sh, rgba) → matriz pw×ph con colores de paleta mas cercanos."""
    sw, sh, rgba = ref_source
    if sw <= 0 or sh <= 0 or pw <= 0 or ph <= 0:
        return []
    scaled = resample_rgba_nearest(rgba, sw, sh, pw, ph)
    return ref_rgba_to_palette_rows(
        scaled, pw, ph, rgbs, alpha_cutoff=alpha_cutoff
    )


def aspect_ratio_note(src_w: int, src_h: int, dst_w: int, dst_h: int) -> str | None:
    if src_w <= 0 or src_h <= 0 or dst_w <= 0 or dst_h <= 0:
        return None
    ar_s = src_w / float(src_h)
    ar_d = dst_w / float(dst_h)
    if abs(ar_s - ar_d) <= 0.02:
        return None
    return (
        f"referencia {src_w}x{src_h} escalada a lienzo {dst_w}x{dst_h} "
        f"(relacion de aspecto distinta)"
    )
