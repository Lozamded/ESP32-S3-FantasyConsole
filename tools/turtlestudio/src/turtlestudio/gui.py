"""Interfaz minima TurtleStudio (Dear PyGui)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from turtlestudio.backgrounds import (
    list_background_stems_for_palette,
    save_solid_background_json,
)
from turtlestudio.build import (
    collect_studio_bundle_files,
    load_palette_rgb01_for_preview,
    normalize_export_initial_scene,
    write_turtlecart_content,
)
from turtlestudio.palette_policy import (
    MAX_OPAQUE_PALETTE_INDEX,
    TRANSPARENT_PALETTE_INDEX,
    clamp_paint_palette_index,
    clamp_pixel_storage_index,
    is_transparent_palette_index,
    resolve_palette_color,
    swatch_indices_for_palette,
)
from turtlestudio.project import (
    BACKGROUND_LAYER_COUNT,
    BackgroundLayer,
    DEFAULT_ENTRY,
    DEFAULT_EXAMPLE_PALETTE_REL,
    DEFAULT_INITIAL_SCENE_ID,
    DEFAULT_TRANSPARENT_INDEX,
    ProjectInfo,
    SCENE_PIXEL_H,
    SCENE_PIXEL_W,
    background_layers_to_json_list,
    create_project,
    default_background_layers,
    firmware_background_index_from_layers,
    load_project,
    ordered_lua_relpaths_for_project,
    parse_background_layers,
    parse_scene_objects_raw,
    save_project,
    scene_lua_relpath,
    validate_scene_script_stem,
)
from turtlestudio.objects import (
    OBJECT_COLLISION_MODE_AABB,
    OBJECT_COLLISION_MODE_HEXAGON,
    OBJECT_COLLISION_MODE_TRIANGLE,
    default_collision_for_sprite_ref,
    list_object_ids_for_scene_palette,
    list_object_json_stems,
    normalize_object_animations,
    normalize_object_collision,
    parse_object_animations,
    parse_object_collision,
    read_object_file,
    save_object_json,
    validate_animation_name,
    write_object_json,
)

_OBJ_COLL_SHAPE_LABELS = ("Cuadrado", "Triangulo", "Hexagono")
_OBJ_COLL_SHAPE_MODES = (
    OBJECT_COLLISION_MODE_AABB,
    OBJECT_COLLISION_MODE_TRIANGLE,
    OBJECT_COLLISION_MODE_HEXAGON,
)
from turtlestudio.sprite_png_export import export_sprite_frames_to_png_dir
from turtlestudio.sprite_ref_image import (
    aspect_ratio_note,
    composite_sprite_editor_preview,
    convert_ref_source_to_palette_rows,
    load_image_rgba_float01,
    resample_rgba_stretch,
)
from turtlestudio.sprites import (
    DEFAULT_CELL_PX,
    MAX_SPRITE_FRAMES,
    list_sprite_json_stems,
    normalize_palette_rel,
    normalize_palette_rows,
    parse_palette_rows_image,
    parse_sprite_all_frame_rows,
    parse_sprite_origin,
    palette_rows_pixel_size,
    read_sprite_file,
    replace_palette_index_in_rows,
    resize_palette_rows_with_stash,
    save_indexed_pixels_sprite_json,
    solid_fill_indices,
    sprite_blit_bottom_left,
    sprite_is_indexed_pixels,
    sprite_pixel_dimensions,
    trim_palette_rows,
)

# Resolucion logica de consola (spec scene-v0; textura = raster Y hacia abajo)
_FB_W = SCENE_PIXEL_W
_FB_H = SCENE_PIXEL_H
_DEFAULT_CANVAS_SCALE = 2
_PALETTE_TRANSPARENT_NOTE = (
    f"Indice {TRANSPARENT_PALETTE_INDEX}: transparente (reservado; no seleccionable)"
)


def _max_selectable_palette_index(palette_len: int) -> int:
    if palette_len <= 0:
        return 0
    return min(palette_len - 1, MAX_OPAQUE_PALETTE_INDEX)


def _sprite_used_paint_indices(rows: list[list[int]] | None) -> list[int]:
    """Indices opacos presentes en la matriz del sprite (sin el 31 transparente)."""
    if not isinstance(rows, list):
        return []
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, list):
            continue
        for raw in row:
            try:
                v = clamp_pixel_storage_index(raw)
            except (TypeError, ValueError):
                continue
            if is_transparent_palette_index(v):
                continue
            seen.add(v)
    return sorted(seen)
# Alto del panel de vista previa (píxeles de pantalla); el zoom grande usa scroll dentro.
_SCENE_CANVAS_SCALE_MAX = 8
# Textura fija (tamano max con escala + huecos entre pixeles, como el editor de sprites).
_SCENE_PREVIEW_TEX_W = _FB_W * _SCENE_CANVAS_SCALE_MAX + max(0, _FB_W - 1)
_SCENE_PREVIEW_TEX_H = _FB_H * _SCENE_CANVAS_SCALE_MAX + max(0, _FB_H - 1)
_SCENE_PREVIEW_TEX_PAD_RGBA = (0.08, 0.08, 0.1, 1.0)
_SCENE_CANVAS_TEX_TAG = "preview_texture"
_SCENE_CANVAS_IMG_TAG = "ts_canvas_image"
_CANVAS_VIEWPORT_H = _FB_H * _DEFAULT_CANVAS_SCALE + 48
_GRID_STEP = 8
# Panel izquierdo: ancho del child modesto; los controles usan ancho FIJO para que no
# estiren con el panel y no roben espacio al canvas (Dear PyGui: width=-1 = 100% del padre).
_LEFT_FORM_WIDTH = 232
_LEFT_PANEL_WIDTH = _LEFT_FORM_WIDTH + 264
_LEFT_TEXT_WRAP = _LEFT_FORM_WIDTH
_SPRITE_SWATCH_WRAP = 420


_DEFAULT_LUA = """-- ENTRY por defecto (scripts/global.lua en un proyecto)
print("TurtleStudio")
cls(1)
flip()
"""


def _solid_rgba_float(width: int, height: int, r: float, g: float, b: float) -> list[float]:
    px = (r, g, b, 1.0)
    row: list[float] = []
    for _ in range(width):
        row.extend(px)
    out: list[float] = []
    for _ in range(height):
        out.extend(row)
    return out


def _composite_background_layers_rgba(
    layers: tuple[BackgroundLayer, ...],
    rgbs: list[tuple[float, float, float]],
    fw: int,
    fh: int,
    *,
    underlay_rgba: list[float] | None = None,
) -> list[float]:
    """Compone capas 0..3 de abajo a arriba; opacidad 0..255 solo en vista previa del estudio."""
    if not rgbs:
        return _solid_rgba_float(fw, fh, 0.06, 0.06, 0.08)
    n = len(rgbs)
    if underlay_rgba is not None and len(underlay_rgba) == fw * fh * 4:
        out = list(underlay_rgba)
    else:
        out = _solid_rgba_float(fw, fh, 0.06, 0.06, 0.08)
    for ly in layers:
        if not ly.enabled or ly.opacity <= 0:
            continue
        a = ly.opacity / 255.0
        col = resolve_palette_color(ly.color_index, rgbs)
        if col is None:
            continue
        r, g, b = col
        for i in range(0, fw * fh * 4, 4):
            out[i] = out[i] * (1.0 - a) + r * a
            out[i + 1] = out[i + 1] * (1.0 - a) + g * a
            out[i + 2] = out[i + 2] * (1.0 - a) + b * a
            out[i + 3] = 1.0
    return out


def _scene_background_asset_underlay(
    row: dict[str, Any],
    rgbs: list[tuple[float, float, float]],
    fw: int,
    fh: int,
    project_root: Path,
) -> list[float] | None:
    """Relleno solido pantalla completa desde `backgrounds/<stem>.json` (v0), o None."""
    from turtlestudio.backgrounds import scene_background_solid_palette_index

    stem = str(row.get("background", "")).strip()
    if not stem:
        return None
    pal = str(row.get("palette", "")).strip()
    idx = scene_background_solid_palette_index(
        project_root,
        stem,
        scene_palette_rel=pal,
    )
    if idx is None:
        return None
    n = len(rgbs)
    if n <= 0:
        return None
    col = resolve_palette_color(idx, rgbs)
    if col is None:
        return None
    r, g, b = col
    return _solid_rgba_float(fw, fh, r, g, b)


def _compose_preview_texture(
    base_rgba: list[float],
    width: int,
    height: int,
    show_grid: bool,
) -> list[float]:
    if not show_grid:
        return list(base_rgba)

    out = list(base_rgba)
    step = _GRID_STEP
    lr, lg, lb = 0.22, 0.24, 0.32
    blend = 0.65

    for y in range(height):
        for x in range(width):
            if (x % step == 0) or (y % step == 0):
                i = (y * width + x) * 4
                out[i] = out[i] * (1.0 - blend) + lr * blend
                out[i + 1] = out[i + 1] * (1.0 - blend) + lg * blend
                out[i + 2] = out[i + 2] * (1.0 - blend) + lb * blend
                out[i + 3] = 1.0
    return out


def _apply_grid_overlay_to_rgba(
    base_rgba: list[float],
    width: int,
    height: int,
    *,
    step: int,
    blend: float = 0.5,
) -> list[float]:
    """Lineas en multiples de step (>=1)."""
    st = max(1, min(64, int(step)))
    out = list(base_rgba)
    lr, lg, lb = 0.18, 0.2, 0.28
    b = max(0.0, min(1.0, float(blend)))
    for y in range(height):
        for x in range(width):
            if (x % st == 0) or (y % st == 0):
                i = (y * width + x) * 4
                out[i] = out[i] * (1.0 - b) + lr * b
                out[i + 1] = out[i + 1] * (1.0 - b) + lg * b
                out[i + 2] = out[i + 2] * (1.0 - b) + lb * b
                out[i + 3] = 1.0
    return out


def _apply_sprite_editor_grid_overlay(
    base_rgba: list[float],
    width: int,
    height: int,
    *,
    grid_step: int,
) -> list[float]:
    """Obsoleto en editor de sprites (se usan huecos entre pixeles). Mantener por compat."""
    st = _normalize_sprite_grid_step(grid_step)
    blend = 0.35 if st == 1 else 0.45
    return _apply_grid_overlay_to_rgba(base_rgba, width, height, step=st, blend=blend)


_SPRITE_EDITOR_PIXEL_GAP = 1
_SPRITE_EDITOR_GAP_RGBA = (0.14, 0.16, 0.22, 1.0)
_SPRITE_EDITOR_CELL_GAP_RGBA = (0.08, 0.1, 0.15, 1.0)


def _sprite_display_stride(scale: int) -> int:
    return max(1, int(scale)) + _SPRITE_EDITOR_PIXEL_GAP


def _sprite_display_size(
    pw: int,
    ph: int,
    scale: int,
    *,
    with_gaps: bool,
) -> tuple[int, int]:
    sc = max(1, int(scale))
    if pw <= 0 or ph <= 0:
        return 0, 0
    if not with_gaps:
        return pw * sc, ph * sc
    g = _SPRITE_EDITOR_PIXEL_GAP
    return pw * sc + max(0, pw - 1) * g, ph * sc + max(0, ph - 1) * g


def _scale_rgba_with_pixel_gaps(
    rgba: list[float],
    pw: int,
    ph: int,
    scale: int,
    *,
    grid_step: int,
) -> tuple[list[float], int, int]:
    """
    Escala entera con 1 px de separacion entre pixeles logicos (no tapa el arte).
    grid_step > 1 oscurece los huecos en bordes de celda (multiplos de step).
    """
    sc = max(1, int(scale))
    g = _SPRITE_EDITOR_PIXEL_GAP
    if pw <= 0 or ph <= 0:
        return [], 0, 0
    dw, dh = _sprite_display_size(pw, ph, sc, with_gaps=True)
    gr, gg, gb, ga = _SPRITE_EDITOR_GAP_RGBA
    out = [gr, gg, gb, ga] * (dw * dh)
    stride = sc + g
    st = _normalize_sprite_grid_step(grid_step)

    for sy in range(ph):
        for sx in range(pw):
            si = (sy * pw + sx) * 4
            px = (rgba[si], rgba[si + 1], rgba[si + 2], rgba[si + 3])
            x0 = sx * stride
            y0 = sy * stride
            for dy in range(sc):
                row_off = (y0 + dy) * dw * 4
                for dx in range(sc):
                    oi = row_off + (x0 + dx) * 4
                    out[oi] = px[0]
                    out[oi + 1] = px[1]
                    out[oi + 2] = px[2]
                    out[oi + 3] = px[3]

    if g > 0 and st > 1:
        cr, cg, cb, ca = _SPRITE_EDITOR_CELL_GAP_RGBA
        for sx in range(1, pw):
            if sx % st != 0:
                continue
            x0 = sx * stride - g
            for gy in range(dh):
                for gg in range(g):
                    x = x0 + gg
                    if 0 <= x < dw:
                        oi = (gy * dw + x) * 4
                        out[oi] = cr
                        out[oi + 1] = cg
                        out[oi + 2] = cb
                        out[oi + 3] = ca
        for sy in range(1, ph):
            if sy % st != 0:
                continue
            y0 = sy * stride - g
            for gy in range(g):
                y = y0 + gy
                if 0 <= y < dh:
                    row_off = y * dw * 4
                    for x in range(dw):
                        oi = row_off + x * 4
                        out[oi] = cr
                        out[oi + 1] = cg
                        out[oi + 2] = cb
                        out[oi + 3] = ca

    return out, dw, dh


def _sprite_pixel_from_display(
    rx: float,
    ry: float,
    pw: int,
    ph: int,
    scale: int,
    *,
    with_gaps: bool,
) -> tuple[int, int] | None:
    """Coordenada de lienzo (rx, ry) en espacio pantalla → indice logico (lx, ly)."""
    sc = max(1, int(scale))
    if with_gaps:
        stride = _sprite_display_stride(sc)
        lx = int(rx // stride)
        ly = int(ry // stride)
        if rx % stride >= sc or ry % stride >= sc:
            return None
    else:
        lx = int(rx // sc)
        ly = int(ry // sc)
    if lx < 0 or ly < 0 or lx >= pw or ly >= ph:
        return None
    return lx, ly


def _blend_rgba_at(
    rgba: list[float],
    i: int,
    r: float,
    g: float,
    b: float,
    *,
    alpha: float,
) -> None:
    a = max(0.0, min(1.0, float(alpha)))
    if a <= 0.0:
        return
    if a >= 1.0 - 1e-9:
        rgba[i] = r
        rgba[i + 1] = g
        rgba[i + 2] = b
        rgba[i + 3] = 1.0
        return
    inv = 1.0 - a
    rgba[i] = rgba[i] * inv + r * a
    rgba[i + 1] = rgba[i + 1] * inv + g * a
    rgba[i + 2] = rgba[i + 2] * inv + b * a
    rgba[i + 3] = 1.0


def _blit_solid_rect_scene(
    rgba: list[float],
    fw: int,
    fh: int,
    sx0: int,
    sy_bottom: int,
    pw: int,
    ph: int,
    r: float,
    g: float,
    b: float,
    *,
    alpha: float = 1.0,
) -> None:
    """Rellena un rectangulo en espacio escena; (sx0, sy_bottom) = esquina inferior izquierda."""
    for ly in range(ph):
        for lx in range(pw):
            scene_x = sx0 + lx
            scene_y = sy_bottom + ly
            if scene_x < 0 or scene_x >= fw or scene_y < 0 or scene_y >= fh:
                continue
            ty = (fh - 1) - scene_y
            tx = scene_x
            i = (ty * fw + tx) * 4
            _blend_rgba_at(rgba, i, r, g, b, alpha=alpha)


def _plot_scene_pixel_rgba(
    rgba: list[float],
    fw: int,
    fh: int,
    scene_x: int,
    scene_y: int,
    r: float,
    g: float,
    b: float,
) -> None:
    if scene_x < 0 or scene_x >= fw or scene_y < 0 or scene_y >= fh:
        return
    ty = (fh - 1) - scene_y
    tx = scene_x
    i = (ty * fw + tx) * 4
    rgba[i] = r
    rgba[i + 1] = g
    rgba[i + 2] = b
    rgba[i + 3] = 1.0


def _draw_scene_line_rgba(
    rgba: list[float],
    fw: int,
    fh: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    r: float,
    g: float,
    b: float,
) -> None:
    """Segmento en espacio escena (Y hacia arriba)."""
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    x, y = x0, y0
    while True:
        _plot_scene_pixel_rgba(rgba, fw, fh, x, y, r, g, b)
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy


def _draw_scene_polygon_outline_rgba(
    rgba: list[float],
    fw: int,
    fh: int,
    anchor_x: int,
    anchor_y: int,
    points: list[list[int]],
    r: float,
    g: float,
    b: float,
) -> None:
    if len(points) < 2:
        return
    n = len(points)
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        _draw_scene_line_rgba(
            rgba,
            fw,
            fh,
            anchor_x + int(x0),
            anchor_y + int(y0),
            anchor_x + int(x1),
            anchor_y + int(y1),
            r,
            g,
            b,
        )


def _draw_object_collision_outline_rgba(
    rgba: list[float],
    fw: int,
    fh: int,
    anchor_x: int,
    anchor_y: int,
    collision: dict[str, Any],
    r: float,
    g: float,
    b: float,
) -> None:
    mode = str(collision.get("mode", OBJECT_COLLISION_MODE_AABB))
    if mode == OBJECT_COLLISION_MODE_AABB:
        x0 = int(collision.get("x0", 0))
        y0 = int(collision.get("y0", 0))
        x1 = int(collision.get("x1", 0))
        y1 = int(collision.get("y1", 0))
        _draw_scene_polygon_outline_rgba(
            rgba,
            fw,
            fh,
            anchor_x,
            anchor_y,
            [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
            r,
            g,
            b,
        )
        return
    raw_pts = collision.get("points")
    if isinstance(raw_pts, list):
        pts: list[list[int]] = []
        for item in raw_pts:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                pts.append([int(item[0]), int(item[1])])
        if pts:
            _draw_scene_polygon_outline_rgba(
                rgba, fw, fh, anchor_x, anchor_y, pts, r, g, b
            )


def _draw_anchor_cross_rgba(
    rgba: list[float],
    fw: int,
    fh: int,
    sx: int,
    sy_bottom: int,
    cr: float,
    cg: float,
    cb: float,
    *,
    arm: int = 6,
) -> None:
    """Cruz en el ancla (esquina inferior izquierda del objeto en espacio escena)."""
    tex_x = max(0, min(fw - 1, sx))
    tex_y = (fh - 1) - max(0, min(fh - 1, sy_bottom))
    tex_y = max(0, min(fh - 1, tex_y))
    for d in range(-arm, arm + 1):
        u = tex_x + d
        v = tex_y
        if 0 <= u < fw and 0 <= v < fh:
            i = (v * fw + u) * 4
            rgba[i] = cr
            rgba[i + 1] = cg
            rgba[i + 2] = cb
            rgba[i + 3] = 1.0
    for d in range(-arm, arm + 1):
        u = tex_x
        v = tex_y + d
        if 0 <= u < fw and 0 <= v < fh:
            i = (v * fw + u) * 4
            rgba[i] = cr
            rgba[i + 1] = cg
            rgba[i + 2] = cb
            rgba[i + 3] = 1.0


_SPRITE_EDITOR_TEX_TAG = "ts_sprite_edit_texture"
_SPRITE_EDITOR_IMG_TAG = "ts_sprite_edit_image"
_SPRITE_EDITOR_SCALE_DEFAULT = 4
_SPRITE_EDITOR_GRID_STEP_DEFAULT = DEFAULT_CELL_PX
_SPRITE_EDITOR_GRID_STEP_MAX = 64
# Fondo del lienzo en el editor (solo vista previa; no se guarda en el sprite).
_SPRITE_EDITOR_CANVAS_BG_DEFAULT = (140, 140, 150, 255)


def _normalize_sprite_grid_step(v: object) -> int:
    """1 px o multiplos de 4 (4, 8, 12, …)."""
    try:
        n = int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _SPRITE_EDITOR_GRID_STEP_DEFAULT
    if n <= 1:
        return 1
    n = min(_SPRITE_EDITOR_GRID_STEP_MAX, n)
    snapped = int(round(n / 4.0)) * 4
    return max(4, snapped)
# Textura fija (no borrar/recrear): evita segfault en DPG al cambiar de sprite.
_SPRITE_EDITOR_TEX_MAX = 512
_SPRITE_EDITOR_TEX_PAD_RGBA = (0.1, 0.1, 0.14, 1.0)
_OBJ_COLL_PREVIEW_TEX_TAG = "ts_obj_coll_preview_tex"
_OBJ_COLL_PREVIEW_IMG_TAG = "ts_obj_coll_preview_img"
_OBJ_COLL_PREVIEW_TEX_MAX = 128
_OBJ_COLL_PREVIEW_SCALE_MAX = 6
_OBJ_COLL_PREVIEW_PAD_RGBA = (0.38, 0.4, 0.46, 1.0)


def _sprite_editor_uv_max(pw: int, ph: int) -> tuple[float, float]:
    mx = float(_SPRITE_EDITOR_TEX_MAX)
    return (max(0.0, min(1.0, pw / mx)), max(0.0, min(1.0, ph / mx)))


def _obj_coll_preview_uv_max(dw: int, dh: int) -> tuple[float, float]:
    mx = float(_OBJ_COLL_PREVIEW_TEX_MAX)
    return (max(0.0, min(1.0, dw / mx)), max(0.0, min(1.0, dh / mx)))


def _collision_outline_local_points(collision: dict[str, Any]) -> list[list[int]]:
    mode = str(collision.get("mode", OBJECT_COLLISION_MODE_AABB))
    if mode == OBJECT_COLLISION_MODE_AABB:
        x0 = int(collision.get("x0", 0))
        y0 = int(collision.get("y0", 0))
        x1 = int(collision.get("x1", 0))
        y1 = int(collision.get("y1", 0))
        return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    raw = collision.get("points")
    if not isinstance(raw, list):
        return []
    out: list[list[int]] = []
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            out.append([int(item[0]), int(item[1])])
    return out


def _plot_raster_pixel_rgba(
    rgba: list[float],
    lw: int,
    lh: int,
    tx: int,
    ty: int,
    r: float,
    g: float,
    b: float,
) -> None:
    if tx < 0 or tx >= lw or ty < 0 or ty >= lh:
        return
    i = (ty * lw + tx) * 4
    rgba[i] = r
    rgba[i + 1] = g
    rgba[i + 2] = b
    rgba[i + 3] = 1.0


def _draw_raster_line_rgba(
    rgba: list[float],
    lw: int,
    lh: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    r: float,
    g: float,
    b: float,
) -> None:
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    x, y = x0, y0
    while True:
        _plot_raster_pixel_rgba(rgba, lw, lh, x, y, r, g, b)
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy


def _local_to_raster_xy(lx: int, ly: int, min_x: int, max_y: int) -> tuple[int, int]:
    return lx - min_x, max_y - ly


def _draw_local_polygon_outline_rgba(
    rgba: list[float],
    lw: int,
    lh: int,
    min_x: int,
    max_y: int,
    local_points: list[list[int]],
    r: float,
    g: float,
    b: float,
) -> None:
    if len(local_points) < 2:
        return
    n = len(local_points)
    for i in range(n):
        x0, y0 = local_points[i]
        x1, y1 = local_points[(i + 1) % n]
        tx0, ty0 = _local_to_raster_xy(x0, y0, min_x, max_y)
        tx1, ty1 = _local_to_raster_xy(x1, y1, min_x, max_y)
        _draw_raster_line_rgba(rgba, lw, lh, tx0, ty0, tx1, ty1, r, g, b)


def _mark_local_anchor_cross_rgba(
    rgba: list[float],
    lw: int,
    lh: int,
    min_x: int,
    max_y: int,
    *,
    arm: int = 4,
) -> None:
    tx, ty = _local_to_raster_xy(0, 0, min_x, max_y)
    for dx, dy in ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)):
        _plot_raster_pixel_rgba(
            rgba, lw, lh, tx + dx * arm, ty + dy * arm, 1.0, 0.15, 0.95
        )


def _build_object_collision_preview_rgba(
    project_root: Path,
    sprite_id: str,
    collision: dict[str, Any],
) -> tuple[list[float], int, int] | None:
    """RGBA logico (Y local hacia arriba) + tamano; None si no hay sprite."""
    try:
        sd = read_sprite_file(project_root, sprite_id)
    except ValueError:
        return None
    _, pw, ph = sprite_pixel_dimensions(sd)
    ox, oy = parse_sprite_origin(sd, pw=pw, ph=ph)
    outline_pts = _collision_outline_local_points(collision)
    bounds_pts: list[list[int]] = list(outline_pts)
    bounds_pts.extend(
        [
            [-ox, -oy],
            [pw - 1 - ox, -oy],
            [pw - 1 - ox, ph - 1 - oy],
            [-ox, ph - 1 - oy],
            [0, 0],
        ]
    )
    if not bounds_pts:
        return None
    xs = [p[0] for p in bounds_pts]
    ys = [p[1] for p in bounds_pts]
    pad = 2
    min_x = min(xs) - pad
    max_x = max(xs) + pad
    min_y = min(ys) - pad
    max_y = max(ys) + pad
    lw = max(1, max_x - min_x + 1)
    lh = max(1, max_y - min_y + 1)
    bg = _OBJ_COLL_PREVIEW_PAD_RGBA
    rgba = [0.0] * (lw * lh * 4)
    for y in range(lh):
        for x in range(lw):
            i = (y * lw + x) * 4
            rgba[i] = bg[0]
            rgba[i + 1] = bg[1]
            rgba[i + 2] = bg[2]
            rgba[i + 3] = 1.0

    raw_pal = str(sd.get("palette", "")).strip()
    pal_file = None
    if raw_pal:
        rel = normalize_palette_rel(raw_pal)
        cand = (project_root / rel).resolve()
        if cand.is_file():
            pal_file = cand
    rgbs, _ = load_palette_rgb01_for_preview(pal_file)
    if not rgbs:
        rgbs = [(0.5, 0.5, 0.5)]

    if sprite_is_indexed_pixels(sd):
        frames = parse_sprite_all_frame_rows(sd, fill_index=0)
        rows = frames[0] if frames else None
        if isinstance(rows, list) and rows:
            for py_top in range(min(ph, len(rows))):
                row = rows[py_top] if py_top < len(rows) else []
                for lx in range(pw):
                    try:
                        idx = int(row[lx]) if lx < len(row) else 0
                    except (TypeError, ValueError):
                        idx = 0
                    col = resolve_palette_color(idx, rgbs)
                    if col is None:
                        continue
                    local_x = lx - ox
                    local_y = (ph - 1 - py_top) - oy
                    tx, ty = _local_to_raster_xy(local_x, local_y, min_x, max_y)
                    _plot_raster_pixel_rgba(
                        rgba, lw, lh, tx, ty, col[0], col[1], col[2]
                    )
    else:
        pi = 0
        render = sd.get("render")
        if isinstance(render, dict):
            try:
                pi = int(render.get("palette_index", 0))
            except (TypeError, ValueError):
                pi = 0
        pi = max(0, min(len(rgbs) - 1, pi))
        sr, sg, sb = rgbs[pi]
        for local_y in range(-oy, ph - oy):
            for local_x in range(-ox, pw - ox):
                tx, ty = _local_to_raster_xy(local_x, local_y, min_x, max_y)
                _plot_raster_pixel_rgba(rgba, lw, lh, tx, ty, sr, sg, sb)

    if outline_pts:
        _draw_local_polygon_outline_rgba(
            rgba, lw, lh, min_x, max_y, outline_pts, 0.95, 0.85, 0.15
        )
    _mark_local_anchor_cross_rgba(rgba, lw, lh, min_x, max_y)
    return rgba, lw, lh


def _scene_preview_uv_max(dw: int, dh: int) -> tuple[float, float]:
    mx = float(_SCENE_PREVIEW_TEX_W)
    my = float(_SCENE_PREVIEW_TEX_H)
    return (max(0.0, min(1.0, dw / mx)), max(0.0, min(1.0, dh / my)))


def _pack_scene_preview_rgba_into_tex_buffer(
    rgba: list[float],
    pw: int,
    ph: int,
) -> list[float]:
    """Copia pw×ph al rincón superior izquierdo de la textura de vista previa de escena."""
    tex_w, tex_h = _SCENE_PREVIEW_TEX_W, _SCENE_PREVIEW_TEX_H
    bg = _SCENE_PREVIEW_TEX_PAD_RGBA
    out = [0.0] * (tex_w * tex_h * 4)
    for y in range(tex_h):
        for x in range(tex_w):
            i = (y * tex_w + x) * 4
            if x < pw and y < ph:
                si = (y * pw + x) * 4
                out[i] = rgba[si]
                out[i + 1] = rgba[si + 1]
                out[i + 2] = rgba[si + 2]
                out[i + 3] = rgba[si + 3]
            else:
                out[i] = bg[0]
                out[i + 1] = bg[1]
                out[i + 2] = bg[2]
                out[i + 3] = bg[3]
    return out


def _scale_rgba_nearest(
    rgba: list[float],
    pw: int,
    ph: int,
    scale: int,
) -> tuple[list[float], int, int]:
    """Escala entera por bloques (sin interpolacion); evita blur de DPG al ampliar."""
    sc = max(1, int(scale))
    if sc == 1 or pw <= 0 or ph <= 0:
        return rgba, pw, ph
    dw, dh = pw * sc, ph * sc
    out = [0.0] * (dw * dh * 4)
    for sy in range(ph):
        for sx in range(pw):
            si = (sy * pw + sx) * 4
            px = (rgba[si], rgba[si + 1], rgba[si + 2], rgba[si + 3])
            for dy in range(sc):
                oy = sy * sc + dy
                row_base = oy * dw * 4
                for dx in range(sc):
                    oi = row_base + (sx * sc + dx) * 4
                    out[oi] = px[0]
                    out[oi + 1] = px[1]
                    out[oi + 2] = px[2]
                    out[oi + 3] = px[3]
    return out, dw, dh


def _pack_sprite_rgba_into_tex_buffer(
    rgba: list[float],
    pw: int,
    ph: int,
    *,
    tex_w: int = _SPRITE_EDITOR_TEX_MAX,
    tex_h: int = _SPRITE_EDITOR_TEX_MAX,
) -> list[float]:
    """Copia pw×ph al rincón superior izquierdo de una textura tex_w×tex_h."""
    bg = _SPRITE_EDITOR_TEX_PAD_RGBA
    out = [0.0] * (tex_w * tex_h * 4)
    for y in range(tex_h):
        for x in range(tex_w):
            i = (y * tex_w + x) * 4
            if x < pw and y < ph:
                si = (y * pw + x) * 4
                out[i] = rgba[si]
                out[i + 1] = rgba[si + 1]
                out[i + 2] = rgba[si + 2]
                out[i + 3] = rgba[si + 3]
            else:
                out[i] = bg[0]
                out[i + 1] = bg[1]
                out[i + 2] = bg[2]
                out[i + 3] = bg[3]
    return out


def _mark_sprite_origin_on_logical_rgba(
    rgba: list[float],
    pw: int,
    ph: int,
    origin_x: int,
    origin_y: int,
) -> None:
    """Cruz magenta en el origen del sprite (vista previa del editor)."""
    if pw <= 0 or ph <= 0 or len(rgba) != pw * ph * 4:
        return
    ox = max(0, min(pw - 1, int(origin_x)))
    oy = max(0, min(ph - 1, int(origin_y)))
    py = ph - 1 - oy
    for dx, dy in ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)):
        x, y = ox + dx, py + dy
        if 0 <= x < pw and 0 <= y < ph:
            i = (y * pw + x) * 4
            rgba[i] = 1.0
            rgba[i + 1] = 0.15
            rgba[i + 2] = 0.95
            rgba[i + 3] = 1.0


def _blit_indexed_rect_scene(
    rgba: list[float],
    fw: int,
    fh: int,
    sx0: int,
    sy_bottom: int,
    rows: list[list[int]],
    rgbs: list[tuple[float, float, float]],
    *,
    alpha: float = 1.0,
) -> None:
    """(sx0, sy_bottom) = esquina inferior izquierda del bbox del sprite."""
    ph = len(rows)
    pw = len(rows[0]) if rows else 0
    n = max(1, len(rgbs))
    for py in range(ph):
        scene_y = sy_bottom + (ph - 1 - py)
        row = rows[py] if py < len(rows) else []
        for lx in range(pw):
            scene_x = sx0 + lx
            if scene_x < 0 or scene_x >= fw or scene_y < 0 or scene_y >= fh:
                continue
            try:
                idx = int(row[lx]) if lx < len(row) else 0
            except (TypeError, ValueError):
                idx = 0
            if is_transparent_palette_index(idx):
                continue
            col = resolve_palette_color(idx, rgbs)
            if col is None:
                continue
            r, g, b = col
            ty = (fh - 1) - scene_y
            tx = scene_x
            i = (ty * fw + tx) * 4
            _blend_rgba_at(rgba, i, r, g, b, alpha=alpha)


def _resolve_object_sprite_preview(
    project_root: Path,
    object_id: str,
) -> dict[str, Any]:
    """Vista previa en escena: solido o indexed_pixels + paleta del sprite."""
    oid = object_id.strip()
    fb = {
        "mode": "solid",
        "pw": DEFAULT_CELL_PX,
        "ph": DEFAULT_CELL_PX,
        "rgb": (0.42, 0.42, 0.48),
        "origin_x": 0,
        "origin_y": 0,
    }
    if not oid:
        return fb
    try:
        od = read_object_file(project_root, oid)
    except ValueError:
        return fb
    spr = str(od.get("sprite_id", "")).strip()
    if not spr:
        return fb
    try:
        sd = read_sprite_file(project_root, spr)
    except ValueError:
        return fb
    _, pw0, ph0 = sprite_pixel_dimensions(sd)
    pw = max(1, min(pw0, SCENE_PIXEL_W))
    ph = max(1, min(ph0, SCENE_PIXEL_H))
    raw_pal = str(sd.get("palette", "")).strip()
    pal_file = None
    if raw_pal:
        rel = normalize_palette_rel(raw_pal)
        cand = (project_root / rel).resolve()
        if cand.is_file():
            pal_file = cand
    rgbs, _ = load_palette_rgb01_for_preview(pal_file)
    if not rgbs:
        rgbs = [(0.5, 0.5, 0.5)]
    ox, oy = parse_sprite_origin(sd, pw=pw, ph=ph)
    if sprite_is_indexed_pixels(sd):
        rows = parse_palette_rows_image(sd)
        if rows:
            return {
                "mode": "indexed",
                "pw": pw,
                "ph": ph,
                "rows": rows,
                "rgbs": rgbs,
                "origin_x": ox,
                "origin_y": oy,
            }
    pi = 0
    render = sd.get("render")
    if isinstance(render, dict):
        try:
            pi = int(render.get("palette_index", 0))
        except (TypeError, ValueError):
            pi = 0
    pi = max(0, min(len(rgbs) - 1, pi))
    r, g, b = rgbs[pi]
    return {
        "mode": "solid",
        "pw": pw,
        "ph": ph,
        "rgb": (r, g, b),
        "origin_x": ox,
        "origin_y": oy,
    }


def _paint_scene_objects_preview(
    rgba: list[float],
    fw: int,
    fh: int,
    project_root: Path,
    placements: list[dict[str, Any]],
    *,
    cross_rgb: tuple[float, float, float],
    layer_alpha: float = 1.0,
) -> None:
    """Compone sprites (solido o pixeles indexados) y una cruz en el ancla por instancia."""
    cr, cg, cb = cross_rgb
    a = max(0.0, min(1.0, float(layer_alpha)))
    for p in placements:
        try:
            oid = str(p.get("id", "")).strip()
            sx = int(p.get("x", 0))
            sy = int(p.get("y", 0))
        except (TypeError, ValueError):
            continue
        if not oid:
            continue
        sx = max(0, min(SCENE_PIXEL_W - 1, sx))
        sy = max(0, min(SCENE_PIXEL_H - 1, sy))
        info = _resolve_object_sprite_preview(project_root, oid)
        bx, by = sprite_blit_bottom_left(
            sx,
            sy,
            int(info.get("origin_x", 0)),
            int(info.get("origin_y", 0)),
        )
        if a > 0.0:
            if info.get("mode") == "indexed":
                _blit_indexed_rect_scene(
                    rgba,
                    fw,
                    fh,
                    bx,
                    by,
                    info["rows"],
                    info["rgbs"],
                    alpha=a,
                )
            else:
                pr, pg, pb = info["rgb"]
                _blit_solid_rect_scene(
                    rgba,
                    fw,
                    fh,
                    bx,
                    by,
                    info["pw"],
                    info["ph"],
                    pr,
                    pg,
                    pb,
                    alpha=a,
                )
        _draw_anchor_cross_rgba(rgba, fw, fh, sx, sy, cr, cg, cb)
        try:
            od = read_object_file(project_root, oid)
            coll = parse_object_collision(od)
            if coll is not None:
                _draw_object_collision_outline_rgba(
                    rgba, fw, fh, sx, sy, coll, 0.95, 0.85, 0.15
                )
        except ValueError:
            pass


def _paint_placement_crosses_only(
    rgba: list[float],
    fw: int,
    fh: int,
    placements: list[dict[str, Any]],
    cr: float,
    cg: float,
    cb: float,
) -> None:
    for p in placements:
        try:
            sx = int(p.get("x", 0))
            sy = int(p.get("y", 0))
        except (TypeError, ValueError):
            continue
        sx = max(0, min(SCENE_PIXEL_W - 1, sx))
        sy = max(0, min(SCENE_PIXEL_H - 1, sy))
        _draw_anchor_cross_rgba(rgba, fw, fh, sx, sy, cr, cg, cb)


def run_gui() -> int:
    try:
        import dearpygui.dearpygui as dpg
    except ImportError:
        print(
            "Falta Dear PyGui. Instala con: pip install dearpygui",
            file=sys.stderr,
        )
        return 1

    state: dict[str, object] = {
        "rgb": [],
        "hexes": [],
        "sprite_palette_rgb": [],
        "sprite_palette_hexes": [],
        "project_root": None,
        "scenes": [],
        "active_scene_id": DEFAULT_INITIAL_SCENE_ID,
        "pending_scene_object_id": None,
        "lua_sources": {},
        "lua_edit_rel": "",
        "project_entry": DEFAULT_ENTRY,
        "edit_bg_layer_slot": 0,
        "sprite_pixel_rows": None,
        "sprite_pixel_stash": None,
        "sprite_frame_pixels": None,
        "sprite_frame_stash": None,
        "sprite_active_frame": 0,
        "sprite_color_swap_active": False,
        "sprite_color_swap_source": None,
        "sprite_canvas_bg_rgb01": (
            _SPRITE_EDITOR_CANVAS_BG_DEFAULT[0] / 255.0,
            _SPRITE_EDITOR_CANVAS_BG_DEFAULT[1] / 255.0,
            _SPRITE_EDITOR_CANVAS_BG_DEFAULT[2] / 255.0,
        ),
        "sprite_edit_cell_px": DEFAULT_CELL_PX,
        "sprite_ui_silent": False,
        "sprite_brush_index": 1,
        "sprite_ref_source": None,
        "sprite_ref_path": "",
        "obj_animations": [],
    }

    def _scene_obj_dict_from_any(x: object) -> dict[str, Any] | None:
        t = parse_scene_objects_raw([x])
        if not t:
            return None
        p = t[0]
        return {"id": p.id, "x": p.x, "y": p.y}

    def _clear_pending_scene_placement() -> None:
        state["pending_scene_object_id"] = None

    def _texture_px_to_scene_coords(lx: int, ly_top: int) -> tuple[int, int]:
        sx = max(0, min(_FB_W - 1, lx))
        sy = (_FB_H - 1) - max(0, min(_FB_H - 1, ly_top))
        return sx, sy

    def _canvas_display_scale() -> int:
        if not dpg.does_item_exist("ts_canvas_scale"):
            return _DEFAULT_CANVAS_SCALE
        try:
            v = int(dpg.get_value("ts_canvas_scale"))
        except (TypeError, ValueError):
            v = _DEFAULT_CANVAS_SCALE
        return max(1, min(_SCENE_CANVAS_SCALE_MAX, v))

    def palette_reload_from_path() -> str:
        pal_s = str(dpg.get_value("ts_pal_path")).strip()
        path = Path(pal_s).expanduser() if pal_s else None
        msg = ""
        if pal_s and path is not None and not path.is_file():
            msg = f"Paleta no encontrada ({path}); uso paleta por defecto del firmware.\n"
        use_path = path if (path is not None and path.is_file()) else None
        rgbs, hexes = load_palette_rgb01_for_preview(use_path)
        state["rgb"] = rgbs
        state["hexes"] = hexes
        n = len(hexes)
        max_i = _max_selectable_palette_index(n)
        for tag in ("ts_bg_index", "ts_bg_new_idx"):
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, min_value=0, max_value=max_i)
                try:
                    cur_i = int(dpg.get_value(tag))
                except (TypeError, ValueError):
                    cur_i = 0
                dpg.set_value(tag, clamp_paint_palette_index(cur_i, palette_len=n))
        _rebuild_palette_swatches()
        return (
            msg
            + f"Paleta canvas: {len(hexes)} colores; pintar 0..{max_i}; "
            f"{TRANSPARENT_PALETTE_INDEX}=transparente.\n"
        )

    def _clipboard_push_hex(hexes: list[str], idx: int) -> None:
        if idx < 0 or idx >= len(hexes):
            return
        line = str(hexes[idx]).strip()
        if not line.startswith("#"):
            line = f"#{line}" if line else ""
        if not line:
            return
        try:
            dpg.set_clipboard_text(line)
        except Exception:
            pass

    def _on_canvas_palette_swatch_click(
        sender: object, app_data: object, user_data: object | None = None,
    ) -> None:
        idx = user_data if user_data is not None else dpg.get_item_user_data(sender)
        idx = int(idx)
        if is_transparent_palette_index(idx):
            return
        hexes = state.get("hexes")
        if not isinstance(hexes, list) or idx < 0 or idx >= len(hexes):
            return
        _clipboard_push_hex(hexes, idx)
        dpg.set_value("ts_bg_index", clamp_paint_palette_index(idx, palette_len=len(hexes)))
        if isinstance(state.get("project_root"), Path):
            _commit_background_for_active_scene()
        refresh_canvas_texture()

    def _on_sprite_palette_swatch_click(
        sender: object, app_data: object, user_data: object | None = None,
    ) -> None:
        idx = user_data if user_data is not None else dpg.get_item_user_data(sender)
        idx = int(idx)
        if is_transparent_palette_index(idx):
            return
        hexes = state.get("sprite_palette_hexes")
        if not isinstance(hexes, list) or idx < 0 or idx >= len(hexes):
            return
        if _sprite_color_swap_handle_pick(idx):
            return
        _clipboard_push_hex(hexes, idx)
        _set_sprite_brush_index(idx)

    def _on_sprite_used_swatch_click(
        sender: object, app_data: object, user_data: object | None = None,
    ) -> None:
        idx = user_data if user_data is not None else dpg.get_item_user_data(sender)
        idx = int(idx)
        if is_transparent_palette_index(idx):
            return
        hexes = state.get("sprite_palette_hexes")
        if _sprite_color_swap_handle_pick(idx):
            return
        if isinstance(hexes, list) and 0 <= idx < len(hexes):
            _clipboard_push_hex(hexes, idx)
        _set_sprite_brush_index(idx)

    def _sprite_color_swap_source_index() -> int | None:
        raw = state.get("sprite_color_swap_source")
        if raw is None:
            return None
        try:
            v = int(raw)
        except (TypeError, ValueError):
            return None
        if is_transparent_palette_index(v):
            return None
        return v

    def _sprite_color_swap_cancel() -> None:
        state["sprite_color_swap_active"] = False
        state["sprite_color_swap_source"] = None
        if dpg.does_item_exist("ts_btn_sprite_swap_color"):
            dpg.configure_item("ts_btn_sprite_swap_color", label="Intercambiar color")
        _update_sprite_swap_status_label()
        _rebuild_sprite_palette_swatches()
        _rebuild_sprite_used_swatches()

    def _set_sprite_color_swap_source(idx: int | None) -> None:
        if idx is not None and is_transparent_palette_index(idx):
            idx = None
        state["sprite_color_swap_source"] = idx
        _update_sprite_swap_status_label()
        _rebuild_sprite_palette_swatches()
        _rebuild_sprite_used_swatches()

    def _update_sprite_swap_status_label() -> None:
        if not dpg.does_item_exist("ts_sprite_swap_status"):
            return
        if not state.get("sprite_color_swap_active"):
            dpg.set_value("ts_sprite_swap_status", "")
            return
        src = _sprite_color_swap_source_index()
        if src is None:
            dpg.set_value(
                "ts_sprite_swap_status",
                "Paso 1/2: clic en el color a reemplazar (usados o paleta).",
            )
        else:
            dpg.set_value(
                "ts_sprite_swap_status",
                f"Paso 2/2: color {src} resaltado — clic en el color destino.",
            )

    def _apply_sprite_color_swap(from_idx: int, to_idx: int) -> None:
        from_idx = clamp_pixel_storage_index(from_idx)
        to_idx = clamp_pixel_storage_index(to_idx)
        if is_transparent_palette_index(from_idx) or is_transparent_palette_index(to_idx):
            return
        if from_idx == to_idx:
            return
        rows = state.get("sprite_pixel_rows")
        if isinstance(rows, list):
            state["sprite_pixel_rows"] = replace_palette_index_in_rows(
                rows, from_idx, to_idx
            )
        stash = state.get("sprite_pixel_stash")
        if isinstance(stash, dict) and isinstance(stash.get("rows"), list):
            stash = dict(stash)
            stash["rows"] = replace_palette_index_in_rows(
                stash["rows"], from_idx, to_idx
            )
            state["sprite_pixel_stash"] = stash
        _set_sprite_brush_index(to_idx)
        _refresh_sprite_edit_texture()
        prev = dpg.get_value("ts_log") or ""
        dpg.set_value(
            "ts_log",
            prev
            + f"Sprites: indice {from_idx} → {to_idx} en todo el lienzo "
            f"({len(_sprite_used_paint_indices(state.get('sprite_pixel_rows')))} colores usados).\n",
        )

    def _sprite_color_swap_handle_pick(idx: int) -> bool:
        """True si el clic se consumio en modo intercambio."""
        if not state.get("sprite_color_swap_active"):
            return False
        idx = clamp_paint_palette_index(
            idx, palette_len=_palette_len_sprite() or None
        )
        if is_transparent_palette_index(idx):
            return True
        src = _sprite_color_swap_source_index()
        if src is None:
            _set_sprite_color_swap_source(idx)
            return True
        if src == idx:
            _set_sprite_color_swap_source(None)
            return True
        _apply_sprite_color_swap(src, idx)
        _set_sprite_color_swap_source(None)
        return True

    def on_sprite_color_swap_click(_sender: object, _app_data: object) -> None:
        active = not bool(state.get("sprite_color_swap_active"))
        state["sprite_color_swap_active"] = active
        if not active:
            state["sprite_color_swap_source"] = None
            if dpg.does_item_exist("ts_btn_sprite_swap_color"):
                dpg.configure_item("ts_btn_sprite_swap_color", label="Intercambiar color")
        else:
            if dpg.does_item_exist("ts_btn_sprite_swap_color"):
                dpg.configure_item(
                    "ts_btn_sprite_swap_color",
                    label="Intercambiar color (activo)",
                )
        _update_sprite_swap_status_label()
        _rebuild_sprite_palette_swatches()
        _rebuild_sprite_used_swatches()

    def _bind_sprite_swatch_highlight(item: int | str, index: int) -> None:
        if (
            state.get("sprite_color_swap_active")
            and _sprite_color_swap_source_index() == index
            and dpg.does_item_exist("ts_sprite_swap_highlight_theme")
        ):
            dpg.bind_item_theme(item, "ts_sprite_swap_highlight_theme")

    def _rebuild_sprite_used_swatches() -> None:
        gid = "ts_sprite_used_swatches_group"
        if not dpg.does_item_exist(gid):
            return
        dpg.delete_item(gid, children_only=True)
        rows = state.get("sprite_pixel_rows")
        rgbs = state.get("sprite_palette_rgb")
        indices = _sprite_used_paint_indices(
            rows if isinstance(rows, list) else None
        )
        if not indices:
            dpg.add_text(
                "(sin colores opacos en el lienzo)",
                parent=gid,
                wrap=_SPRITE_SWATCH_WRAP,
            )
            return
        if not isinstance(rgbs, list) or not rgbs:
            dpg.add_text(
                "(carga la paleta del sprite)",
                parent=gid,
                wrap=_SPRITE_SWATCH_WRAP,
            )
            return
        sw = 18
        for i in indices:
            if i < 0 or i >= len(rgbs):
                continue
            rgb = rgbs[i]
            r8 = max(0, min(255, int(round(rgb[0] * 255.0))))
            g8 = max(0, min(255, int(round(rgb[1] * 255.0))))
            b8 = max(0, min(255, int(round(rgb[2] * 255.0))))
            btn = dpg.add_color_button(
                default_value=[r8, g8, b8, 255],
                width=sw,
                height=sw,
                enabled=True,
                parent=gid,
                label="",
                use_internal_label=True,
                user_data=i,
                callback=_on_sprite_used_swatch_click,
            )
            _bind_sprite_swatch_highlight(btn, i)

    def _add_palette_swatch_buttons(
        parent: str | int,
        rgbs: list[tuple[float, float, float]],
        callback: object,
        *,
        wrap: int,
        highlight_index: int | None = None,
    ) -> None:
        sw = 16
        for i in swatch_indices_for_palette(len(rgbs)):
            rgb = rgbs[i]
            r8 = max(0, min(255, int(round(rgb[0] * 255.0))))
            g8 = max(0, min(255, int(round(rgb[1] * 255.0))))
            b8 = max(0, min(255, int(round(rgb[2] * 255.0))))
            btn = dpg.add_color_button(
                default_value=[r8, g8, b8, 255],
                width=sw,
                height=sw,
                enabled=True,
                parent=parent,
                label="",
                use_internal_label=True,
                user_data=i,
                callback=callback,
            )
            hi = highlight_index
            if hi is None and state.get("sprite_color_swap_active"):
                hi = _sprite_color_swap_source_index()
            if hi is not None and i == hi:
                _bind_sprite_swatch_highlight(btn, i)
        if len(rgbs) > TRANSPARENT_PALETTE_INDEX:
            dpg.add_text(_PALETTE_TRANSPARENT_NOTE, parent=parent, wrap=wrap)

    def _rebuild_palette_swatches() -> None:
        gid = "ts_palette_swatches_group"
        if not dpg.does_item_exist(gid):
            return
        dpg.delete_item(gid, children_only=True)
        rgbs = state.get("rgb")
        if not isinstance(rgbs, list) or not rgbs:
            dpg.add_text("(sin paleta cargada)", parent=gid, wrap=_LEFT_TEXT_WRAP)
            return
        _add_palette_swatch_buttons(
            gid, rgbs, _on_canvas_palette_swatch_click, wrap=_LEFT_TEXT_WRAP
        )

    def _rebuild_sprite_palette_swatches() -> None:
        gid = "ts_sprite_palette_swatches_group"
        if not dpg.does_item_exist(gid):
            return
        dpg.delete_item(gid, children_only=True)
        rgbs = state.get("sprite_palette_rgb")
        if not isinstance(rgbs, list) or not rgbs:
            dpg.add_text(
                "(sin paleta cargada para el sprite)",
                parent=gid,
                wrap=_SPRITE_SWATCH_WRAP,
            )
            return
        hi = (
            _sprite_color_swap_source_index()
            if state.get("sprite_color_swap_active")
            else None
        )
        _add_palette_swatch_buttons(
            gid,
            rgbs,
            _on_sprite_palette_swatch_click,
            wrap=_SPRITE_SWATCH_WRAP,
            highlight_index=hi,
        )

    def _palette_len_canvas() -> int:
        rgbs = state.get("rgb")
        return len(rgbs) if isinstance(rgbs, list) else 0

    def _palette_len_sprite() -> int:
        rgbs = state.get("sprite_palette_rgb")
        return len(rgbs) if isinstance(rgbs, list) else 0

    def parse_bg_index() -> int:
        if not dpg.does_item_exist("ts_bg_index"):
            return 0
        try:
            v = int(dpg.get_value("ts_bg_index"))
        except (TypeError, ValueError):
            v = 0
        n = _palette_len_canvas()
        if n <= 0:
            return 0
        return clamp_paint_palette_index(v, palette_len=n)

    def _set_sprite_brush_index(idx: int) -> None:
        n = _palette_len_sprite()
        if n <= 0:
            state["sprite_brush_index"] = max(0, int(idx))
            return
        state["sprite_brush_index"] = clamp_paint_palette_index(int(idx), palette_len=n)

    def parse_sprite_palette_index() -> int:
        """Indice de pincel (paleta del sprite); no el modo solido del JSON."""
        try:
            v = int(state.get("sprite_brush_index", 1))
        except (TypeError, ValueError):
            v = 1
        n = _palette_len_sprite()
        if n <= 0:
            return max(0, v)
        return clamp_paint_palette_index(v, palette_len=n)

    def _palette_n_for_background() -> int:
        hexes = state.get("hexes")
        if isinstance(hexes, list) and hexes:
            return len(hexes)
        n = _palette_len_canvas()
        return max(1, n)

    def _parse_layer_slot_value(v: object) -> int:
        if isinstance(v, int):
            return max(0, min(BACKGROUND_LAYER_COUNT - 1, v))
        s = str(v).strip()
        if s.isdigit():
            return max(0, min(BACKGROUND_LAYER_COUNT - 1, int(s)))
        return 0

    def _normalize_row_background_layers_inplace(row: dict[str, Any]) -> None:
        n = _palette_n_for_background()
        try:
            bg = int(row.get("background_index", 1))
        except (TypeError, ValueError):
            bg = 1
        tpl = parse_background_layers(
            row.get("background_layers"),
            legacy_flat_index=bg,
            n_colors=n,
        )
        row["background_index"] = firmware_background_index_from_layers(tpl, fallback=bg)
        row["background_layers"] = background_layers_to_json_list(tpl)

    def _commit_widgets_to_background_row_for_slot(row: dict[str, Any], slot: int) -> None:
        n = _palette_n_for_background()
        try:
            bg = int(row.get("background_index", 1))
        except (TypeError, ValueError):
            bg = 1
        tpl = parse_background_layers(
            row.get("background_layers"),
            legacy_flat_index=bg,
            n_colors=n,
        )
        slot = max(0, min(BACKGROUND_LAYER_COUNT - 1, slot))
        ci = parse_bg_index()
        if dpg.does_item_exist("ts_bg_layer_opacity"):
            try:
                op = int(dpg.get_value("ts_bg_layer_opacity"))
            except (TypeError, ValueError):
                op = 255
        else:
            op = 255
        op = max(0, min(255, op))
        if dpg.does_item_exist("ts_bg_layer_enabled"):
            en = bool(dpg.get_value("ts_bg_layer_enabled"))
        else:
            en = True
        new_list = [tpl[i] for i in range(BACKGROUND_LAYER_COUNT)]
        new_list[slot] = BackgroundLayer(en, ci, op)
        tpl2 = tuple(new_list)
        row["background_layers"] = background_layers_to_json_list(tpl2)
        row["background_index"] = firmware_background_index_from_layers(tpl2, fallback=bg)

    def _load_background_widgets_from_row_for_slot(row: dict[str, Any], slot: int) -> None:
        if not dpg.does_item_exist("ts_bg_index"):
            return
        _normalize_row_background_layers_inplace(row)
        tpl = parse_background_layers(
            row.get("background_layers"),
            legacy_flat_index=int(row.get("background_index", 1)),
            n_colors=_palette_n_for_background(),
        )
        slot = max(0, min(BACKGROUND_LAYER_COUNT - 1, slot))
        ly = tpl[slot]
        if dpg.does_item_exist("ts_bg_layer_enabled"):
            dpg.set_value("ts_bg_layer_enabled", ly.enabled)
        if dpg.does_item_exist("ts_bg_layer_opacity"):
            dpg.set_value("ts_bg_layer_opacity", ly.opacity)
        dpg.set_value("ts_bg_index", ly.color_index)

    def _set_bg_index_widgets(idx: int) -> None:
        n = _palette_len_canvas()
        if n <= 0 or not dpg.does_item_exist("ts_bg_index"):
            return
        i = max(0, min(int(idx), n - 1))
        dpg.set_value("ts_bg_index", i)

    def _commit_background_for_scene_id(sid: str) -> None:
        scenes = state.get("scenes")
        if not isinstance(scenes, list) or not sid:
            return
        slot = int(state.get("edit_bg_layer_slot", 0))
        for row in scenes:
            if row.get("id") == sid:
                _commit_widgets_to_background_row_for_slot(row, slot)
                break

    def _commit_background_for_active_scene() -> None:
        _commit_background_for_scene_id(str(state.get("active_scene_id") or ""))

    def _commit_scene_background_for_scene_id(sid: str) -> None:
        if not dpg.does_item_exist("ts_scene_background"):
            return
        scenes = state.get("scenes")
        if not isinstance(scenes, list) or not sid:
            return
        raw = dpg.get_value("ts_scene_background")
        stem = ""
        if raw is not None:
            rs = str(raw).strip()
            if rs and not rs.startswith("("):
                stem = rs
        for row in scenes:
            if row.get("id") == sid:
                row["background"] = stem
                break

    def _commit_scene_background_for_active_scene() -> None:
        _commit_scene_background_for_scene_id(str(state.get("active_scene_id") or ""))

    def _refresh_scene_background_combo() -> None:
        if not dpg.does_item_exist("ts_scene_background"):
            return
        root = state.get("project_root")
        if not isinstance(root, Path):
            dpg.configure_item("ts_scene_background", items=["(abre un proyecto)"], enabled=False)
            if dpg.does_item_exist("ts_scene_background"):
                dpg.set_value("ts_scene_background", "(abre un proyecto)")
            return
        scenes = state.get("scenes")
        active = str(state.get("active_scene_id") or "")
        if not isinstance(scenes, list) or not active:
            return
        row = next((x for x in scenes if x.get("id") == active), None)
        if row is None:
            return
        pal_w = str(dpg.get_value("ts_scene_pal")).strip()
        pal = pal_w or str(row.get("palette", "")).strip() or DEFAULT_EXAMPLE_PALETTE_REL
        stems = list_background_stems_for_palette(root, pal)
        items = ["(ninguno)"] + stems
        dpg.configure_item("ts_scene_background", items=items, enabled=True)
        cur = str(row.get("background", "")).strip()
        if cur and cur not in stems:
            row["background"] = ""
            cur = ""
        pick = cur if cur in stems else "(ninguno)"
        dpg.set_value("ts_scene_background", pick)

    def _refresh_bg_tab_list() -> None:
        if not dpg.does_item_exist("ts_bg_tab_list"):
            return
        root = state.get("project_root")
        if not isinstance(root, Path):
            dpg.configure_item(
                "ts_bg_tab_list",
                items=["(abre un proyecto)"],
                enabled=False,
            )
            return
        pal = str(dpg.get_value("ts_bg_tab_pal")).strip() or DEFAULT_EXAMPLE_PALETTE_REL
        stems = list_background_stems_for_palette(root, pal)
        dpg.configure_item(
            "ts_bg_tab_list",
            items=stems if stems else ["(ningun fondo con esta paleta)"],
            enabled=True,
        )

    def _flush_lua_buffer_to_state() -> None:
        rel = str(state.get("lua_edit_rel") or "").strip()
        if not rel:
            return
        if not isinstance(state.get("lua_sources"), dict):
            state["lua_sources"] = {}
        lua_m: dict[str, str] = state["lua_sources"]  # type: ignore[assignment]
        lua_m[rel] = str(dpg.get_value("ts_lua_source"))

    def _ensure_lua_slot(rel: str, text: str | None = None) -> None:
        if not isinstance(state.get("lua_sources"), dict):
            state["lua_sources"] = {}
        lua_m: dict[str, str] = state["lua_sources"]  # type: ignore[assignment]
        if rel not in lua_m:
            lua_m[rel] = text if text is not None else f"-- {rel}\n"

    def _rebuild_lua_file_combo() -> None:
        if not dpg.does_item_exist("ts_lua_file_combo"):
            return
        root = state.get("project_root")
        labels: list[str]
        if not isinstance(root, Path):
            labels = ["(sin proyecto)"]
        else:
            entry = str(state.get("project_entry") or DEFAULT_ENTRY)
            scenes_list = [dict(x) for x in state.get("scenes", []) if isinstance(x, dict)]
            labels = list(ordered_lua_relpaths_for_project(entry, scenes_list))
        dpg.configure_item("ts_lua_file_combo", items=labels)
        cur = str(state.get("lua_edit_rel") or "")
        pick = cur if cur in labels else (labels[0] if labels else "")
        dpg.set_value("ts_lua_file_combo", pick)
        dpg.configure_item("ts_lua_file_combo", enabled=bool(labels) and labels[0] != "(sin proyecto)")

    def _load_project_lua_buffers(root: Path) -> None:
        entry = str(state.get("project_entry") or DEFAULT_ENTRY)
        scenes_list = [dict(x) for x in state.get("scenes", []) if isinstance(x, dict)]
        rels = ordered_lua_relpaths_for_project(entry, scenes_list)
        src: dict[str, str] = {}
        for rel in rels:
            p = root / rel
            if p.is_file():
                try:
                    src[rel] = p.read_text(encoding="utf-8")
                except OSError:
                    src[rel] = f"-- (no se pudo leer) {rel}\n"
            else:
                src[rel] = f"-- {rel}\n"
        state["lua_sources"] = src
        state["lua_edit_rel"] = entry
        dpg.set_value("ts_lua_source", src.get(entry, ""))
        _rebuild_lua_file_combo()

    def _commit_script_stem_from_widget(sid: str) -> None:
        if not sid or not dpg.does_item_exist("ts_scene_script"):
            return
        scenes = state.get("scenes")
        if not isinstance(scenes, list):
            return
        raw = str(dpg.get_value("ts_scene_script")).strip()
        try:
            stem = validate_scene_script_stem(raw if raw else None, fallback_scene_id=sid)
        except ValueError as e:
            prev = dpg.get_value("ts_log") or ""
            dpg.set_value("ts_log", prev + f"Escena script: {e}\n")
            row = next((x for x in scenes if x.get("id") == sid), None)
            if row is not None:
                dpg.set_value(
                    "ts_scene_script",
                    str(row.get("script", row.get("id", ""))),
                )
            return
        for row in scenes:
            if row.get("id") == sid:
                row["script"] = stem
                rel = scene_lua_relpath(stem)
                _ensure_lua_slot(rel)
                break

    def on_lua_file_combo(_sender: object, app_data: object) -> None:
        new_sel = str(app_data).strip() if app_data is not None else ""
        if not new_sel or new_sel.startswith("("):
            return
        _flush_lua_buffer_to_state()
        state["lua_edit_rel"] = new_sel
        src = state.get("lua_sources")
        body = ""
        if isinstance(src, dict):
            body = str(src.get(new_sel, ""))
        dpg.set_value("ts_lua_source", body)

    def _update_color_swatch(r: float, g: float, b: float) -> None:
        r8 = max(0, min(255, int(round(r * 255.0))))
        g8 = max(0, min(255, int(round(g * 255.0))))
        b8 = max(0, min(255, int(round(b * 255.0))))
        dpg.set_value("ts_swatch_theme_color", (r8, g8, b8, 255))

    def _scene_sprites_preview_visible() -> bool:
        if not dpg.does_item_exist("ts_scene_sprites_show"):
            return True
        return bool(dpg.get_value("ts_scene_sprites_show"))

    def _scene_sprites_preview_opacity() -> float:
        if not dpg.does_item_exist("ts_scene_sprites_opacity"):
            return 1.0
        try:
            v = int(dpg.get_value("ts_scene_sprites_opacity"))
        except (TypeError, ValueError):
            v = 255
        return max(0, min(255, v)) / 255.0

    def refresh_canvas_texture() -> None:
        rgbs = state["rgb"]
        if not rgbs:
            return
        scenes = state.get("scenes")
        active = str(state.get("active_scene_id") or "")
        row: dict[str, Any] | None = None
        if isinstance(scenes, list):
            row = next((x for x in scenes if x.get("id") == active), None)
        n_colors = len(rgbs)
        try:
            legacy = int(row.get("background_index", 1)) if row is not None else parse_bg_index()
        except (TypeError, ValueError):
            legacy = 1
        tpl = parse_background_layers(
            row.get("background_layers") if row is not None else None,
            legacy_flat_index=legacy,
            n_colors=n_colors,
        )
        under: list[float] | None = None
        root = state.get("project_root")
        if row is not None and isinstance(root, Path):
            under = _scene_background_asset_underlay(row, rgbs, _FB_W, _FB_H, root)
        base = _composite_background_layers_rgba(
            tpl, rgbs, _FB_W, _FB_H, underlay_rgba=under
        )
        slot = int(state.get("edit_bg_layer_slot", 0))
        slot = max(0, min(BACKGROUND_LAYER_COUNT - 1, slot))
        ly = tpl[slot]
        ci_sw = max(0, min(n_colors - 1, ly.color_index))
        r, g, b = rgbs[ci_sw]
        _update_color_swatch(r, g, b)
        placements: list[dict[str, Any]] = []
        if isinstance(scenes, list) and row is not None:
            raw_objs = row.get("objects")
            if isinstance(raw_objs, list):
                for x in raw_objs:
                    d = _scene_obj_dict_from_any(x)
                    if d is not None:
                        placements.append(d)
        idx = firmware_background_index_from_layers(tpl, fallback=legacy)
        if placements:
            nr = len(rgbs)
            mi = (idx + max(1, nr // 4)) % nr if nr else 0
            tr, tg, tb = rgbs[mi]
            root = state.get("project_root")
            show_sprites = _scene_sprites_preview_visible()
            sprite_a = _scene_sprites_preview_opacity() if show_sprites else 0.0
            if isinstance(root, Path):
                _paint_scene_objects_preview(
                    base,
                    _FB_W,
                    _FB_H,
                    root,
                    placements,
                    cross_rgb=(tr, tg, tb),
                    layer_alpha=sprite_a,
                )
            else:
                _paint_placement_crosses_only(
                    base, _FB_W, _FB_H, placements, tr, tg, tb
                )
        show = bool(dpg.get_value("ts_show_grid"))
        sc = _canvas_display_scale()
        if show:
            disp_rgba, dw, dh = _scale_rgba_with_pixel_gaps(
                base, _FB_W, _FB_H, sc, grid_step=_GRID_STEP
            )
        else:
            disp_rgba, dw, dh = _scale_rgba_nearest(base, _FB_W, _FB_H, sc)
        if dw > _SCENE_PREVIEW_TEX_W or dh > _SCENE_PREVIEW_TEX_H:
            dw = min(dw, _SCENE_PREVIEW_TEX_W)
            dh = min(dh, _SCENE_PREVIEW_TEX_H)
            disp_rgba = disp_rgba[: dw * dh * 4]
        tex_rgba = _pack_scene_preview_rgba_into_tex_buffer(disp_rgba, dw, dh)
        dpg.set_value(_SCENE_CANVAS_TEX_TAG, tex_rgba)
        _sync_scene_canvas_image_widget(dw, dh)

    def _sync_scene_canvas_image_widget(dw: int, dh: int) -> None:
        """dw×dh = pixeles en textura y en pantalla (1:1, sin estirado borroso)."""
        if not dpg.does_item_exist(_SCENE_CANVAS_IMG_TAG):
            return
        uv = _scene_preview_uv_max(dw, dh)
        dpg.configure_item(
            _SCENE_CANVAS_IMG_TAG,
            width=max(1, dw),
            height=max(1, dh),
            texture_tag=_SCENE_CANVAS_TEX_TAG,
            uv_min=(0.0, 0.0),
            uv_max=uv,
        )

    def _set_project_save_enabled(enabled: bool) -> None:
        dpg.configure_item("ts_menu_save_project", enabled=enabled)
        dpg.configure_item("ts_btn_save_project", enabled=enabled)
        for tag in (
            "ts_scene_combo",
            "ts_scene_pal",
            "ts_scene_script",
            "ts_btn_new_scene",
            "ts_scene_background",
            "ts_scene_obj_compat_list",
            "ts_btn_scene_obj_add",
            "ts_scene_obj_inscene_list",
            "ts_btn_scene_obj_remove",
            "ts_bg_layer",
            "ts_bg_layer_enabled",
            "ts_bg_layer_opacity",
            "ts_bg_index",
            "ts_sprite_palette_rel",
            "ts_btn_sprite_palette_reload",
            "ts_sprite_id",
            "ts_sprite_blocks_w",
            "ts_sprite_blocks_h",
            "ts_sprite_origin_x",
            "ts_sprite_origin_y",
            "ts_sprite_frame_count",
            "ts_btn_sprite_apply_size",
            "ts_sprite_editor_scale",
            "ts_sprite_editor_show_grid",
            "ts_sprite_editor_grid_step",
            "ts_sprite_canvas_bg",
            "ts_btn_sprite_fill_canvas",
            "ts_btn_sprite_clear_canvas",
            "ts_btn_sprite_swap_color",
            "ts_btn_sprite_ref_import",
            "ts_btn_sprite_ref_clear",
            "ts_btn_sprite_ref_convert",
            "ts_sprite_ref_show",
            "ts_sprite_ref_opacity",
            "ts_sprite_paint_opacity",
            "ts_sprite_onion_prev_show",
            "ts_sprite_onion_prev_opacity",
            "ts_sprite_onion_next_show",
            "ts_sprite_onion_next_opacity",
            "ts_btn_sprite_create",
            "ts_btn_sprite_save",
            "ts_btn_sprite_export_png",
            "ts_btn_sprite_refresh",
            "ts_sprite_list",
            "ts_obj_list",
            "ts_obj_id",
            "ts_obj_name",
            "ts_obj_sprite_combo",
            "ts_obj_coll_shape",
            "ts_obj_coll_x0",
            "ts_obj_coll_y0",
            "ts_obj_coll_x1",
            "ts_obj_coll_y1",
            "ts_obj_coll_t0x",
            "ts_obj_coll_t0y",
            "ts_obj_coll_t1x",
            "ts_obj_coll_t1y",
            "ts_obj_coll_t2x",
            "ts_obj_coll_t2y",
            "ts_obj_coll_h0x",
            "ts_obj_coll_h0y",
            "ts_obj_coll_h1x",
            "ts_obj_coll_h1y",
            "ts_obj_coll_h2x",
            "ts_obj_coll_h2y",
            "ts_obj_coll_h3x",
            "ts_obj_coll_h3y",
            "ts_obj_coll_h4x",
            "ts_obj_coll_h4y",
            "ts_obj_coll_h5x",
            "ts_obj_coll_h5y",
            "ts_btn_obj_coll_from_sprite",
            "ts_obj_anim_name",
            "ts_obj_anim_sprite_combo",
            "ts_btn_obj_anim_add",
            "ts_btn_obj_anim_remove",
            "ts_obj_anim_list",
            "ts_btn_obj_create",
            "ts_btn_obj_save",
            "ts_btn_obj_refresh",
            "ts_bg_tab_pal",
            "ts_btn_bg_tab_copy_scene_pal",
            "ts_btn_bg_tab_refresh",
            "ts_bg_tab_list",
            "ts_bg_new_id",
            "ts_bg_new_idx",
            "ts_btn_bg_tab_save",
        ):
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, enabled=enabled)
        if dpg.does_item_exist("ts_lua_file_combo"):
            dpg.configure_item("ts_lua_file_combo", enabled=enabled)

    def _refresh_sprite_file_list() -> None:
        root = state.get("project_root")
        if not isinstance(root, Path):
            dpg.configure_item("ts_sprite_list", items=["(abre un proyecto)"])
            _refresh_obj_sprite_combo()
            return
        stems = list_sprite_json_stems(root)
        dpg.configure_item(
            "ts_sprite_list",
            items=stems if stems else ["(ningun .json aun)"],
        )
        _refresh_obj_sprite_combo()

    def _refresh_obj_sprite_combo() -> None:
        root = state.get("project_root")
        if not dpg.does_item_exist("ts_obj_sprite_combo"):
            return
        if not isinstance(root, Path):
            dpg.configure_item("ts_obj_sprite_combo", items=["(abre un proyecto)"])
            dpg.set_value("ts_obj_sprite_combo", "(abre un proyecto)")
            _refresh_obj_anim_sprite_combo()
            return
        stems = list_sprite_json_stems(root)
        if not stems:
            items = ["(sin sprites — crea uno en Sprites)"]
            dpg.configure_item("ts_obj_sprite_combo", items=items)
            dpg.set_value("ts_obj_sprite_combo", items[0])
            _refresh_obj_anim_sprite_combo()
            return
        dpg.configure_item("ts_obj_sprite_combo", items=stems)
        cur = dpg.get_value("ts_obj_sprite_combo")
        if cur not in stems:
            dpg.set_value("ts_obj_sprite_combo", stems[0])
        _refresh_obj_anim_sprite_combo()

    def _refresh_obj_anim_sprite_combo() -> None:
        if not dpg.does_item_exist("ts_obj_anim_sprite_combo"):
            return
        root = state.get("project_root")
        if not isinstance(root, Path):
            dpg.configure_item("ts_obj_anim_sprite_combo", items=["(abre un proyecto)"])
            dpg.set_value("ts_obj_anim_sprite_combo", "(abre un proyecto)")
            return
        stems = list_sprite_json_stems(root)
        if not stems:
            items = ["(sin sprites — crea uno en Sprites)"]
            dpg.configure_item("ts_obj_anim_sprite_combo", items=items)
            dpg.set_value("ts_obj_anim_sprite_combo", items[0])
            return
        dpg.configure_item("ts_obj_anim_sprite_combo", items=stems)
        cur = dpg.get_value("ts_obj_anim_sprite_combo")
        if cur not in stems:
            dpg.set_value("ts_obj_anim_sprite_combo", stems[0])

    def _obj_animation_list_label(entry: dict[str, str]) -> str:
        return f"{entry['name']} → {entry['sprite_id']}"

    def _rebuild_obj_anim_listbox(*, select_name: str | None = None) -> None:
        if not dpg.does_item_exist("ts_obj_anim_list"):
            return
        anims = state.get("obj_animations")
        if not isinstance(anims, list):
            anims = []
            state["obj_animations"] = anims
        labels = [_obj_animation_list_label(a) for a in anims if isinstance(a, dict)]
        if not labels:
            labels = ["(sin animaciones)"]
        dpg.configure_item("ts_obj_anim_list", items=labels)
        pick = labels[0]
        if select_name:
            for a in anims:
                if isinstance(a, dict) and a.get("name") == select_name:
                    pick = _obj_animation_list_label(a)
                    break
        dpg.set_value("ts_obj_anim_list", pick)

    def _obj_anim_list_selected_name() -> str | None:
        if not dpg.does_item_exist("ts_obj_anim_list"):
            return None
        raw = dpg.get_value("ts_obj_anim_list")
        s = str(raw).strip() if raw is not None else ""
        if not s or s.startswith("("):
            return None
        if " → " in s:
            return s.split(" → ", 1)[0].strip()
        return None

    def _read_obj_animations_from_state() -> list[dict[str, str]]:
        raw = state.get("obj_animations")
        if not isinstance(raw, list):
            return []
        out: list[dict[str, str]] = []
        for item in raw:
            if isinstance(item, dict) and item.get("name") and item.get("sprite_id"):
                out.append(
                    {
                        "name": str(item["name"]),
                        "sprite_id": str(item["sprite_id"]),
                    }
                )
        return out

    def _refresh_object_file_list() -> None:
        root = state.get("project_root")
        if not isinstance(root, Path):
            dpg.configure_item("ts_obj_list", items=["(abre un proyecto)"])
            return
        stems = list_object_json_stems(root)
        dpg.configure_item(
            "ts_obj_list",
            items=stems if stems else ["(ningun objeto .json aun)"],
        )

    def _sprite_palette_reload_core(
        *, append_log: bool, preferred_palette_index: int | None = None
    ) -> str:
        root = state.get("project_root")
        if not isinstance(root, Path):
            state["sprite_palette_rgb"] = []
            state["sprite_palette_hexes"] = []
            _rebuild_sprite_palette_swatches()
            return ""
        raw = str(dpg.get_value("ts_sprite_palette_rel")).strip()
        rel = normalize_palette_rel(raw) if raw else ""
        if not rel:
            rel = DEFAULT_EXAMPLE_PALETTE_REL
            dpg.set_value("ts_sprite_palette_rel", rel)
        abs_p = (root / rel).resolve()
        msg = ""
        if not abs_p.is_file():
            msg = f"Paleta sprite: no existe {rel}; indices con paleta por defecto.\n"
            use_path = None
        else:
            use_path = abs_p
        rgbs, hexes = load_palette_rgb01_for_preview(use_path)
        state["sprite_palette_rgb"] = rgbs
        state["sprite_palette_hexes"] = hexes
        if preferred_palette_index is not None:
            _set_sprite_brush_index(int(preferred_palette_index))
        else:
            _set_sprite_brush_index(parse_sprite_palette_index())
        _rebuild_sprite_palette_swatches()
        rows_mx = state.get("sprite_pixel_rows")
        if isinstance(rows_mx, list) and rows_mx and rgbs:
            state["sprite_pixel_rows"] = [
                [
                    clamp_pixel_storage_index(c)
                    for c in (rw if isinstance(rw, list) else [])
                ]
                for rw in rows_mx
            ]
        elif rgbs:
            _ensure_sprite_edit_pixel_buffer()
        _refresh_sprite_edit_texture()
        max_paint = _max_selectable_palette_index(len(hexes))
        tail = (
            f"Sprite — pintar 0..{max_paint}; "
            f"{TRANSPARENT_PALETTE_INDEX}=transparente.\n"
        )
        if append_log:
            prev = dpg.get_value("ts_log") or ""
            dpg.set_value("ts_log", prev + msg + tail)
        return msg + tail

    def on_sprite_palette_reload_click(_sender: object, _app_data: object) -> None:
        _sprite_palette_reload_core(append_log=True)

    def enter_main_editor(*, log_append: str) -> None:
        _clear_pending_scene_placement()
        dpg.configure_item("ts_startup", show=False)
        dpg.configure_item("ts_main", show=True)
        dpg.set_primary_window("ts_main", True)
        if isinstance(state.get("project_root"), Path):
            _set_project_save_enabled(True)
        else:
            _set_project_save_enabled(False)
            state["scenes"] = []
            state["active_scene_id"] = DEFAULT_INITIAL_SCENE_ID
            dpg.configure_item("ts_scene_combo", items=["—"])
            dpg.set_value("ts_scene_combo", "—")
            dpg.set_value("ts_scene_pal", "")
            dpg.set_value("ts_sprite_palette_rel", "")
            state["sprite_brush_index"] = 1
            state["sprite_palette_rgb"] = []
            state["sprite_palette_hexes"] = []
            _rebuild_sprite_palette_swatches()
            state["sprite_pixel_rows"] = None
            state["sprite_pixel_stash"] = None
            state["sprite_frame_pixels"] = None
            state["sprite_frame_stash"] = None
            state["sprite_active_frame"] = 0
            state["sprite_ref_source"] = None
            state["sprite_ref_path"] = ""
            if dpg.does_item_exist("ts_sprite_ref_path_label"):
                dpg.set_value("ts_sprite_ref_path_label", "(sin referencia)")
            dpg.set_value("ts_obj_id", "")
            dpg.set_value("ts_obj_name", "")
            state["obj_animations"] = []
            _rebuild_obj_anim_listbox()
            if dpg.does_item_exist("ts_export_initial_scene"):
                dpg.set_value("ts_export_initial_scene", DEFAULT_INITIAL_SCENE_ID)
            state["lua_sources"] = {}
            state["lua_edit_rel"] = ""
            state["project_entry"] = DEFAULT_ENTRY
            if dpg.does_item_exist("ts_scene_script"):
                dpg.set_value("ts_scene_script", "")
                dpg.configure_item("ts_scene_script", enabled=False)
            _rebuild_lua_file_combo()
        _refresh_sprite_file_list()
        _refresh_object_file_list()
        if isinstance(state.get("project_root"), Path):
            sp = str(dpg.get_value("ts_scene_pal")).strip()
            dpg.set_value(
                "ts_sprite_palette_rel",
                sp if sp else DEFAULT_EXAMPLE_PALETTE_REL,
            )
            _sprite_palette_reload_core(append_log=False)
        log = palette_reload_from_path()
        refresh_canvas_texture()
        if isinstance(state.get("project_root"), Path):
            scenes = state.get("scenes")
            active = str(state.get("active_scene_id") or "")
            if isinstance(scenes, list) and scenes:
                row = next((x for x in scenes if x.get("id") == active), None)
                if row is not None:
                    _normalize_row_background_layers_inplace(row)
                    state["edit_bg_layer_slot"] = 0
                    if dpg.does_item_exist("ts_bg_layer"):
                        dpg.set_value("ts_bg_layer", "0")
                    _load_background_widgets_from_row_for_slot(row, 0)
                    refresh_canvas_texture()
        _refresh_scene_object_lists()
        dpg.set_value("ts_log", log_append + log)

    def show_project_startup_dialog(_sender: object | None = None, _app_data: object | None = None) -> None:
        root = state.get("project_root")
        if isinstance(root, Path):
            dpg.set_value("ts_open_project_path", str(root))
            dpg.set_value("ts_new_project_path", str(root.parent / "nuevo_proyecto"))
        dpg.set_value("ts_startup_log", "")
        dpg.configure_item("ts_main", show=False)
        dpg.configure_item("ts_startup", show=True)
        dpg.set_primary_window("ts_startup", True)
        dpg.focus_item("ts_startup")

    def _commit_palette_for_scene_id(sid: str) -> None:
        scenes = state.get("scenes")
        if not isinstance(scenes, list) or not sid:
            return
        pal = str(dpg.get_value("ts_scene_pal")).strip().replace("\\", "/")
        while pal.startswith("./"):
            pal = pal[2:]
        if not pal:
            return
        for row in scenes:
            if row.get("id") == sid:
                row["palette"] = pal
                break

    def _sync_canvas_palette_from_active_scene() -> None:
        root = state.get("project_root")
        active = str(state.get("active_scene_id") or "")
        scenes = state.get("scenes")
        if not isinstance(root, Path) or not isinstance(scenes, list):
            return
        row = next((x for x in scenes if x.get("id") == active), None)
        if not row:
            return
        rel = str(row.get("palette", "")).strip()
        if rel:
            dpg.set_value("ts_pal_path", str((root / rel).resolve()))

    def _refresh_scene_widgets() -> None:
        scenes = state.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            return
        ids = [str(x["id"]) for x in scenes]
        dpg.configure_item("ts_scene_combo", items=ids)
        active = str(state.get("active_scene_id") or ids[0])
        if active not in ids:
            active = ids[0]
        state["active_scene_id"] = active
        dpg.set_value("ts_scene_combo", active)
        pal = next((str(x["palette"]) for x in scenes if x["id"] == active), str(scenes[0]["palette"]))
        dpg.set_value("ts_scene_pal", pal)
        _sync_canvas_palette_from_active_scene()
        palette_reload_from_path()
        row = next((x for x in scenes if x["id"] == active), scenes[0])
        _normalize_row_background_layers_inplace(row)
        state["edit_bg_layer_slot"] = 0
        if dpg.does_item_exist("ts_bg_layer"):
            dpg.set_value("ts_bg_layer", "0")
        _load_background_widgets_from_row_for_slot(row, 0)
        if dpg.does_item_exist("ts_scene_script"):
            dpg.set_value("ts_scene_script", str(row.get("script", row.get("id", ""))))
            dpg.configure_item(
                "ts_scene_script",
                enabled=isinstance(state.get("project_root"), Path),
            )
        if dpg.does_item_exist("ts_bg_tab_pal"):
            dpg.set_value("ts_bg_tab_pal", pal)
        _refresh_scene_background_combo()
        _refresh_bg_tab_list()
        refresh_canvas_texture()
        _refresh_scene_object_lists()
        _clear_pending_scene_placement()

    def _scene_compat_obj_selected_stem() -> str | None:
        raw = dpg.get_value("ts_scene_obj_compat_list")
        if raw is None:
            return None
        s = str(raw).strip()
        if not s or s.startswith("("):
            return None
        return s

    def _scene_inscene_obj_selected_label() -> str | None:
        raw = dpg.get_value("ts_scene_obj_inscene_list")
        if raw is None:
            return None
        s = str(raw).strip()
        if not s or s.startswith("("):
            return None
        return s

    def _parse_placement_list_label(label: str) -> tuple[str, int, int] | None:
        if " @ " not in label:
            return None
        left, right = label.split(" @ ", 1)
        oid = left.strip()
        if "," not in right:
            return None
        xs, ys = right.split(",", 1)
        try:
            return oid, int(xs.strip()), int(ys.strip())
        except ValueError:
            return None

    def _refresh_scene_object_lists() -> None:
        root = state.get("project_root")
        scenes = state.get("scenes")
        if not dpg.does_item_exist("ts_scene_obj_compat_list"):
            return
        if not isinstance(root, Path) or not isinstance(scenes, list) or not scenes:
            dpg.configure_item("ts_scene_obj_compat_list", items=["(abre un proyecto)"])
            dpg.configure_item("ts_scene_obj_inscene_list", items=["(abre un proyecto)"])
            return
        active = str(state.get("active_scene_id") or "")
        row = next((x for x in scenes if x.get("id") == active), None)
        if row is None:
            return
        pal = str(row.get("palette", "")).strip()
        compat = list_object_ids_for_scene_palette(root, pal) if pal else []
        raw_in = row.get("objects", [])
        inscene: list[str] = []
        if isinstance(raw_in, list):
            for x in raw_in:
                d = _scene_obj_dict_from_any(x)
                if d is not None:
                    inscene.append(f'{d["id"]} @ {d["x"]},{d["y"]}')
        dpg.configure_item(
            "ts_scene_obj_compat_list",
            items=compat if compat else ["(ningun objeto con esta paleta)"],
        )
        dpg.configure_item(
            "ts_scene_obj_inscene_list",
            items=inscene if inscene else ["(ningun objeto en la escena)"],
        )

    def on_scene_add_object(_sender: object, _app_data: object) -> None:
        stem = _scene_compat_obj_selected_stem()
        if not stem:
            return
        scenes = state.get("scenes")
        active = str(state.get("active_scene_id") or "")
        if not isinstance(scenes, list) or not active:
            return
        row = next((x for x in scenes if x.get("id") == active), None)
        if row is None:
            return
        state["pending_scene_object_id"] = stem
        prev = dpg.get_value("ts_log") or ""
        dpg.set_value(
            "ts_log",
            prev
            + "Escena: pulsa en el canvas para colocar ese objeto. Coordenadas en espacio escena "
            + "(origen abajo-izquierda, Y hacia arriba; ver spec/scene-v0.md).\n",
        )

    def on_canvas_preview_click(_sender: object, _app_data: object) -> None:
        pending = state.get("pending_scene_object_id")
        if not isinstance(pending, str) or not pending.strip():
            return
        if not isinstance(state.get("project_root"), Path):
            return
        if not dpg.does_item_exist(_SCENE_CANVAS_IMG_TAG):
            return
        mx, my = dpg.get_mouse_pos(local=False)
        min_x, min_y = dpg.get_item_rect_min(_SCENE_CANVAS_IMG_TAG)
        rel_x = float(mx - min_x)
        rel_y = float(my - min_y)
        sc = _canvas_display_scale()
        show_grid = bool(dpg.get_value("ts_show_grid"))
        dw, dh = _sprite_display_size(
            _FB_W, _FB_H, sc, with_gaps=show_grid
        )
        if rel_x < 0 or rel_y < 0 or rel_x >= dw or rel_y >= dh:
            return
        hit = _sprite_pixel_from_display(
            rel_x, rel_y, _FB_W, _FB_H, sc, with_gaps=show_grid
        )
        if hit is None:
            return
        lx, ly_top = hit
        sx, sy = _texture_px_to_scene_coords(lx, ly_top)
        scenes = state.get("scenes")
        active = str(state.get("active_scene_id") or "")
        if not isinstance(scenes, list) or not active:
            return
        row = next((x for x in scenes if x.get("id") == active), None)
        if row is None:
            return
        if "objects" not in row:
            row["objects"] = []
        cur = row.get("objects")
        if not isinstance(cur, list):
            cur = []
        pid = pending.strip()
        cur.append({"id": pid, "x": sx, "y": sy})
        row["objects"] = cur
        state["pending_scene_object_id"] = None
        _refresh_scene_object_lists()
        refresh_canvas_texture()
        prev = dpg.get_value("ts_log") or ""
        dpg.set_value(
            "ts_log",
            prev + f"Escena: objeto {pid!r} colocado en ({sx}, {sy}). Guardar proyecto para persistir.\n",
        )

    def on_scene_remove_object(_sender: object, _app_data: object) -> None:
        label = _scene_inscene_obj_selected_label()
        parsed = _parse_placement_list_label(label) if label else None
        if parsed is None:
            return
        oid, tx, ty = parsed
        scenes = state.get("scenes")
        active = str(state.get("active_scene_id") or "")
        if not isinstance(scenes, list) or not active:
            return
        row = next((x for x in scenes if x.get("id") == active), None)
        if row is None:
            return
        if "objects" not in row:
            row["objects"] = []
        cur = row.get("objects")
        if not isinstance(cur, list):
            return
        cur2: list[object] = []
        removed = False
        for x in cur:
            d = _scene_obj_dict_from_any(x)
            if d is None:
                continue
            if (
                not removed
                and d["id"] == oid
                and int(d["x"]) == tx
                and int(d["y"]) == ty
            ):
                removed = True
                continue
            cur2.append(x)
        row["objects"] = cur2
        _refresh_scene_object_lists()
        refresh_canvas_texture()
        prev = dpg.get_value("ts_log") or ""
        dpg.set_value(
            "ts_log",
            prev + f"Escena: quitado {label} (Guardar proyecto para persistir).\n",
        )

    def _apply_project_scenes_from_info(info: ProjectInfo) -> None:
        _clear_pending_scene_placement()
        state["scenes"] = [
            {
                "id": s.id,
                "palette": s.palette,
                "background_index": s.background_index,
                "background_layers": background_layers_to_json_list(s.background_layers),
                "background": s.background,
                "script": s.script,
                "objects": [{"id": o.id, "x": o.x, "y": o.y} for o in s.objects],
            }
            for s in info.scenes
        ]
        state["active_scene_id"] = info.active_scene
        state["project_entry"] = info.entry
        if dpg.does_item_exist("ts_export_initial_scene"):
            dpg.set_value("ts_export_initial_scene", info.active_scene)
        _refresh_scene_widgets()

    def on_scene_combo(_sender: object, _app_data: object) -> None:
        _clear_pending_scene_placement()
        old_active = str(state.get("active_scene_id") or "")
        _commit_script_stem_from_widget(old_active)
        _commit_palette_for_scene_id(old_active)
        _commit_background_for_scene_id(old_active)
        _commit_scene_background_for_scene_id(old_active)
        new_id = str(dpg.get_value("ts_scene_combo")).strip()
        scenes = state.get("scenes")
        if not isinstance(scenes, list):
            return
        if new_id not in {x.get("id") for x in scenes}:
            dpg.set_value("ts_scene_combo", old_active)
            return
        state["active_scene_id"] = new_id
        _refresh_scene_widgets()
        prev_log = dpg.get_value("ts_log") or ""
        dpg.set_value("ts_log", prev_log + f"Escena activa: {new_id}\n")

    def on_new_scene(_sender: object, _app_data: object) -> None:
        if not isinstance(state.get("project_root"), Path):
            return
        cur = str(state.get("active_scene_id") or "")
        _commit_script_stem_from_widget(cur)
        _commit_palette_for_scene_id(cur)
        _commit_background_for_scene_id(cur)
        _commit_scene_background_for_scene_id(cur)
        scenes = state.get("scenes")
        if not isinstance(scenes, list):
            scenes = []
            state["scenes"] = scenes
        used = {str(x["id"]) for x in scenes}
        n = 1
        while f"scene_{n}" in used:
            n += 1
        new_id = f"scene_{n}"
        scenes.append(
            {
                "id": new_id,
                "palette": DEFAULT_EXAMPLE_PALETTE_REL,
                "background_index": 1,
                "background_layers": background_layers_to_json_list(
                    default_background_layers(1)
                ),
                "background": "",
                "script": new_id,
                "objects": [],
            }
        )
        state["active_scene_id"] = new_id
        _refresh_scene_widgets()
        rel = scene_lua_relpath(new_id)
        _ensure_lua_slot(rel)
        _rebuild_lua_file_combo()
        prev_log = dpg.get_value("ts_log") or ""
        dpg.set_value(
            "ts_log",
            prev_log + f"Nueva escena '{new_id}' (Guardar proyecto para persistir).\n",
        )

    def on_scene_background_change(_sender: object, _app_data: object) -> None:
        if isinstance(state.get("project_root"), Path):
            _commit_scene_background_for_active_scene()
        refresh_canvas_texture()

    def on_scene_palette_input_change(_sender: object, _app_data: object) -> None:
        _refresh_scene_background_combo()

    def on_bg_tab_copy_scene_pal(_sender: object, _app_data: object) -> None:
        if dpg.does_item_exist("ts_scene_pal"):
            dpg.set_value("ts_bg_tab_pal", str(dpg.get_value("ts_scene_pal")).strip())
        _refresh_bg_tab_list()
        prev = dpg.get_value("ts_log") or ""
        dpg.set_value("ts_log", prev + "Backgrounds: paleta copiada desde la escena activa.\n")

    def on_bg_tab_refresh_list(_sender: object, _app_data: object) -> None:
        _refresh_bg_tab_list()
        prev = dpg.get_value("ts_log") or ""
        dpg.set_value("ts_log", prev + "Backgrounds: lista actualizada.\n")

    def on_bg_tab_save_background(_sender: object, _app_data: object) -> None:
        root = state.get("project_root")
        if not isinstance(root, Path):
            return
        raw_id = str(dpg.get_value("ts_bg_new_id")).strip()
        if not raw_id:
            prev = dpg.get_value("ts_log") or ""
            dpg.set_value("ts_log", prev + "Backgrounds: indica un id (nombre del .json).\n")
            return
        try:
            pal = str(dpg.get_value("ts_bg_tab_pal")).strip() or DEFAULT_EXAMPLE_PALETTE_REL
            pal = normalize_palette_rel(pal)
            idx = int(dpg.get_value("ts_bg_new_idx"))
        except (TypeError, ValueError) as e:
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "") + f"Backgrounds: datos invalidos: {e}\n",
            )
            return
        try:
            save_solid_background_json(root, raw_id, palette_rel=pal, palette_index=idx)
        except ValueError as e:
            dpg.set_value("ts_log", (dpg.get_value("ts_log") or "") + f"Backgrounds: {e}\n")
            return
        _refresh_bg_tab_list()
        _refresh_scene_background_combo()
        refresh_canvas_texture()
        prev = dpg.get_value("ts_log") or ""
        dpg.set_value("ts_log", prev + f"Backgrounds: guardado backgrounds/{raw_id}.json\n")

    initial_black = _solid_rgba_float(
        _SCENE_PREVIEW_TEX_W, _SCENE_PREVIEW_TEX_H, 0.08, 0.08, 0.1
    )
    _scene_canvas_dw0, _scene_canvas_dh0 = _sprite_display_size(
        _FB_W, _FB_H, _DEFAULT_CANVAS_SCALE, with_gaps=False
    )

    dpg.create_context()

    with dpg.theme(tag="ts_swatch_theme"):
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(
                dpg.mvThemeCol_ChildBg,
                [22, 22, 28, 255],
                tag="ts_swatch_theme_color",
            )

    with dpg.theme(tag="ts_sprite_swap_highlight_theme"):
        with dpg.theme_component(dpg.mvColorButton):
            dpg.add_theme_style(
                dpg.mvStyleVar_FrameBorderSize, 2, category=dpg.mvThemeCat_Core
            )
            dpg.add_theme_color(
                dpg.mvThemeCol_Border, (255, 210, 64, 255), category=dpg.mvThemeCat_Core
            )

    with dpg.texture_registry(tag="ts_texture_registry"):
        dpg.add_dynamic_texture(
            width=_SCENE_PREVIEW_TEX_W,
            height=_SCENE_PREVIEW_TEX_H,
            default_value=initial_black,
            tag=_SCENE_CANVAS_TEX_TAG,
        )
        dpg.add_dynamic_texture(
            width=_SPRITE_EDITOR_TEX_MAX,
            height=_SPRITE_EDITOR_TEX_MAX,
            default_value=_solid_rgba_float(
                _SPRITE_EDITOR_TEX_MAX,
                _SPRITE_EDITOR_TEX_MAX,
                0.12,
                0.12,
                0.15,
            ),
            tag=_SPRITE_EDITOR_TEX_TAG,
        )
        dpg.add_dynamic_texture(
            width=_OBJ_COLL_PREVIEW_TEX_MAX,
            height=_OBJ_COLL_PREVIEW_TEX_MAX,
            default_value=_solid_rgba_float(
                _OBJ_COLL_PREVIEW_TEX_MAX,
                _OBJ_COLL_PREVIEW_TEX_MAX,
                _OBJ_COLL_PREVIEW_PAD_RGBA[0],
                _OBJ_COLL_PREVIEW_PAD_RGBA[1],
                _OBJ_COLL_PREVIEW_PAD_RGBA[2],
            ),
            tag=_OBJ_COLL_PREVIEW_TEX_TAG,
        )

    def on_load_lua_from_file(_sender: object, _app_data: object) -> None:
        p_s = str(dpg.get_value("ts_import_lua_path")).strip()
        if not p_s:
            dpg.set_value("ts_log", "Indica una ruta .lua para importar.\n")
            return
        p = Path(p_s).expanduser()
        if not p.is_file():
            dpg.set_value("ts_log", f"No existe el archivo: {p}\n")
            return
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as e:
            dpg.set_value("ts_log", f"No se pudo leer: {e}\n")
            return
        dpg.set_value("ts_lua_source", text)
        rel_ed = str(state.get("lua_edit_rel") or "").strip()
        lua_m = state.get("lua_sources")
        if rel_ed and isinstance(lua_m, dict):
            lua_m[rel_ed] = text
        if not str(dpg.get_value("ts_entry")).strip():
            pr = state.get("project_root")
            if isinstance(pr, Path):
                try:
                    rel_try = p.resolve().relative_to(pr.resolve())
                    dpg.set_value("ts_entry", rel_try.as_posix())
                except ValueError:
                    dpg.set_value("ts_entry", p.name)
            else:
                dpg.set_value("ts_entry", p.name)
        dpg.set_value("ts_log", f"Cargado en editor: {p} ({len(text)} caracteres)\n")

    def on_export(_sender: object, _app_data: object) -> None:
        _flush_lua_buffer_to_state()
        out_s = dpg.get_value("ts_out_path").strip()
        pal_s = dpg.get_value("ts_pal_path").strip()
        entry_s = str(dpg.get_value("ts_entry")).strip().replace("\\", "/")
        write_lua = bool(dpg.get_value("ts_write_lua_file"))

        if not out_s:
            dpg.set_value("ts_log", "Indica la ruta de salida del .turtlecart.\n")
            return

        out = Path(out_s).expanduser()
        pal: Path | None = Path(pal_s).expanduser() if pal_s else None
        if pal is not None and not pal.is_file():
            dpg.set_value("ts_log", f"No existe la paleta: {pal}\n")
            return

        entry = entry_s if entry_s else DEFAULT_ENTRY
        if not entry.lower().endswith(".lua"):
            entry = entry + ".lua"

        root = state.get("project_root")
        body = ""
        if isinstance(root, Path):
            src = state.get("lua_sources")
            if isinstance(src, dict) and entry in src:
                body = str(src[entry]).strip()
            elif (root / entry).is_file():
                try:
                    body = (root / entry).read_text(encoding="utf-8").strip()
                except OSError:
                    body = ""
        if not body:
            body = str(dpg.get_value("ts_lua_source")).strip()
        if not body:
            dpg.set_value(
                "ts_log",
                "Escribe algo en el script Lua (panel derecho) o importa un .lua.\n",
            )
            return

        try:
            raw_init = (
                str(dpg.get_value("ts_export_initial_scene"))
                if dpg.does_item_exist("ts_export_initial_scene")
                else ""
            )
            initial_scene_s = normalize_export_initial_scene(raw_init)
        except ValueError as e:
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "") + f"Exportar: {e}\n",
            )
            return

        embedded: list[tuple[str, str]] | None = None
        if isinstance(root, Path):
            scenes = state.get("scenes")
            if not isinstance(scenes, list):
                scenes = []
            try:
                embedded = collect_studio_bundle_files(
                    root,
                    scenes=scenes,
                    active_scene=initial_scene_s,
                    transparent_index=DEFAULT_TRANSPARENT_INDEX,
                    entry_relpath=entry,
                )
            except ValueError as e:
                dpg.set_value(
                    "ts_log",
                    (dpg.get_value("ts_log") or "")
                    + f"Exportar: datos del proyecto invalidos (ENTRY/rutas): {e}\n",
                )
                return

        try:
            cart_path, lua_path = write_turtlecart_content(
                out,
                entry_relpath=entry,
                main_lua_body=body,
                palette_path=pal,
                write_lua_file=write_lua,
                embedded_files=embedded,
                initial_scene=initial_scene_s,
            )
            n = cart_path.stat().st_size
            extra = f"  INITIAL_SCENE:{initial_scene_s}\n"
            if embedded:
                extra += (
                    "  Embebido: studio/project_bundle.json (Lua de escenas no van aqui; solo ENTRY + bundle).\n"
                )
            if lua_path is not None:
                m = lua_path.stat().st_size
                dpg.set_value(
                    "ts_log",
                    f"Exportado OK:\n  {cart_path} ({n} bytes)\n  {lua_path} ({m} bytes)\n"
                    + extra,
                )
            else:
                dpg.set_value(
                    "ts_log",
                    f"Exportado OK: {cart_path} ({n} bytes)\n" + extra,
                )
        except ValueError as e:
            dpg.set_value("ts_log", f"Error: {e}\n")
        except OSError as e:
            dpg.set_value("ts_log", f"Error de escritura: {e}\n")

    def on_grid_toggle(_sender: object, _app_data: object) -> None:
        refresh_canvas_texture()

    def on_canvas_scale_change(_sender: object, _app_data: object) -> None:
        refresh_canvas_texture()

    def on_bg_index_change(_sender: object, _app_data: object) -> None:
        if isinstance(state.get("project_root"), Path):
            _commit_background_for_active_scene()
        refresh_canvas_texture()

    def on_bg_layer_slot_change(_sender: object, app_data: object) -> None:
        new_slot = _parse_layer_slot_value(app_data)
        if app_data is None and dpg.does_item_exist("ts_bg_layer"):
            new_slot = _parse_layer_slot_value(dpg.get_value("ts_bg_layer"))
        old = int(state.get("edit_bg_layer_slot", 0))
        if new_slot == old:
            return
        scenes = state.get("scenes")
        active = str(state.get("active_scene_id") or "")
        if (
            isinstance(scenes, list)
            and isinstance(state.get("project_root"), Path)
            and active
        ):
            row = next((x for x in scenes if x.get("id") == active), None)
            if isinstance(row, dict):
                _commit_widgets_to_background_row_for_slot(row, old)
        state["edit_bg_layer_slot"] = new_slot
        if isinstance(scenes, list) and active:
            row2 = next((x for x in scenes if x.get("id") == active), None)
            if isinstance(row2, dict):
                _load_background_widgets_from_row_for_slot(row2, new_slot)
        refresh_canvas_texture()

    def on_bg_layer_enabled_change(_sender: object, _app_data: object) -> None:
        if isinstance(state.get("project_root"), Path):
            _commit_background_for_active_scene()
        refresh_canvas_texture()

    def on_bg_layer_opacity_change(_sender: object, _app_data: object) -> None:
        if isinstance(state.get("project_root"), Path):
            _commit_background_for_active_scene()
        refresh_canvas_texture()

    def on_scene_sprites_preview_change(_sender: object, _app_data: object) -> None:
        refresh_canvas_texture()

    def on_reload_palette_click(_sender: object, _app_data: object) -> None:
        log = palette_reload_from_path()
        prev = dpg.get_value("ts_log") or ""
        dpg.set_value("ts_log", prev + log)
        if isinstance(state.get("project_root"), Path):
            scenes = state.get("scenes")
            active = str(state.get("active_scene_id") or "")
            if isinstance(scenes, list):
                row = next((x for x in scenes if x.get("id") == active), None)
                if row is not None:
                    _normalize_row_background_layers_inplace(row)
                    slot = int(state.get("edit_bg_layer_slot", 0))
                    _load_background_widgets_from_row_for_slot(row, slot)
        refresh_canvas_texture()

    def on_save_project(_sender: object, _app_data: object) -> None:
        root = state.get("project_root")
        if not isinstance(root, Path):
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "")
                + "No hay proyecto abierto. Proyecto > Cambiar proyecto…\n",
            )
            return
        _flush_lua_buffer_to_state()
        active = str(state.get("active_scene_id") or "").strip()
        _commit_script_stem_from_widget(active)
        _commit_palette_for_scene_id(active)
        _commit_background_for_active_scene()
        _commit_scene_background_for_active_scene()
        pal_s = str(dpg.get_value("ts_pal_path")).strip()
        pal: Path | None = Path(pal_s).expanduser() if pal_s else None
        scenes_list = [dict(x) for x in state.get("scenes", []) if isinstance(x, dict)]
        entry = str(state.get("project_entry") or DEFAULT_ENTRY)
        rels = ordered_lua_relpaths_for_project(entry, scenes_list)
        raw_lua = state.get("lua_sources")
        lua_m: dict[str, str] = dict(raw_lua) if isinstance(raw_lua, dict) else {}
        lua_files: dict[str, str] = {}
        for rel in rels:
            lua_files[rel] = lua_m.get(rel, "")
        try:
            script_path, pal_updated, scenes_updated = save_project(
                root,
                lua_files=lua_files,
                palette_file=pal,
                scenes=scenes_list,
                active_scene=active,
                transparent_index=DEFAULT_TRANSPARENT_INDEX,
            )
        except ValueError as e:
            dpg.set_value("ts_log", (dpg.get_value("ts_log") or "") + f"Error al guardar: {e}\n")
            return
        except OSError as e:
            dpg.set_value("ts_log", (dpg.get_value("ts_log") or "") + f"Error de escritura: {e}\n")
            return
        _rebuild_lua_file_combo()
        bits = []
        if pal_updated:
            bits.append("default_palette")
        if scenes_updated:
            bits.append("escenas / transparent_index")
        extra = f" ({', '.join(bits)} en manifest)\n" if bits else "\n"
        dpg.set_value(
            "ts_log",
            (dpg.get_value("ts_log") or "")
            + f"Proyecto guardado: {script_path}{extra}",
        )

    def on_sprite_refresh(
        _sender: object | None = None, _app_data: object | None = None
    ) -> None:
        _refresh_sprite_file_list()
        root = state.get("project_root")
        if isinstance(root, Path):
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "") + "Sprites: lista actualizada.\n",
            )

    def on_sprite_create_empty(_sender: object, _app_data: object) -> None:
        root = state.get("project_root")
        if not isinstance(root, Path):
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "")
                + "Sprites: abre o crea un proyecto primero.\n",
            )
            return
        sid = str(dpg.get_value("ts_sprite_id")).strip()
        try:
            bw = int(dpg.get_value("ts_sprite_blocks_w"))
            bh = int(dpg.get_value("ts_sprite_blocks_h"))
        except (TypeError, ValueError):
            bw, bh = 1, 1
        pal_raw = str(dpg.get_value("ts_sprite_palette_rel")).strip()
        _resize_sprite_edit_matrix_for_widgets()
        cp = int(state.get("sprite_edit_cell_px") or DEFAULT_CELL_PX)
        try:
            all_frames = _trim_all_sprite_frames_for_save()
            rows2 = all_frames[0] if all_frames else []
            pw_o, ph_o = _expected_sprite_matrix_pixel_size()
            ox, oy = _clamp_sprite_origin_widgets(pw_o, ph_o)
            path = save_indexed_pixels_sprite_json(
                root,
                sid,
                palette_rel=pal_raw,
                blocks_w=bw,
                blocks_h=bh,
                rows=rows2,
                frame_rows=all_frames,
                cell_px=cp,
                origin_x=ox,
                origin_y=oy,
            )
        except ValueError as e:
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "") + f"Sprites: {e}\n",
            )
            return
        except OSError as e:
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "") + f"Sprites: error de escritura: {e}\n",
            )
            return
        rel = path.relative_to(root).as_posix()
        _refresh_sprite_file_list()
        if dpg.does_item_exist("ts_sprite_list"):
            dpg.set_value("ts_sprite_list", sid)
        dpg.set_value(
            "ts_log",
            (dpg.get_value("ts_log") or "") + f"Sprites: creado {rel}\n",
        )
        _refresh_scene_object_lists()
        _load_sprite_into_form(sid)

    def _sprite_list_selected_stem() -> str | None:
        raw = dpg.get_value("ts_sprite_list")
        if raw is None:
            return None
        s = str(raw).strip()
        if not s or s.startswith("("):
            return None
        return s

    def _sprite_editor_display_scale() -> int:
        if not dpg.does_item_exist("ts_sprite_editor_scale"):
            return _SPRITE_EDITOR_SCALE_DEFAULT
        try:
            v = int(dpg.get_value("ts_sprite_editor_scale"))
        except (TypeError, ValueError):
            v = _SPRITE_EDITOR_SCALE_DEFAULT
        return max(1, min(16, v))

    def _sprite_editor_grid_enabled() -> bool:
        if not dpg.does_item_exist("ts_sprite_editor_show_grid"):
            return True
        return bool(dpg.get_value("ts_sprite_editor_show_grid"))

    def _sprite_editor_effective_scale(pw: int, ph: int) -> int:
        """Escala en pantalla; acotada para caber en la textura 512×512."""
        sc = _sprite_editor_display_scale()
        if pw <= 0 or ph <= 0:
            return sc
        if _sprite_editor_grid_enabled():
            g = _SPRITE_EDITOR_PIXEL_GAP
            cap_w = (_SPRITE_EDITOR_TEX_MAX - max(0, pw - 1) * g) // pw
            cap_h = (_SPRITE_EDITOR_TEX_MAX - max(0, ph - 1) * g) // ph
            cap = min(cap_w, cap_h)
        else:
            cap = min(_SPRITE_EDITOR_TEX_MAX // pw, _SPRITE_EDITOR_TEX_MAX // ph)
        return max(1, min(sc, cap))

    def _expected_sprite_matrix_pixel_size() -> tuple[int, int]:
        try:
            bw = int(dpg.get_value("ts_sprite_blocks_w"))
            bh = int(dpg.get_value("ts_sprite_blocks_h"))
        except (TypeError, ValueError):
            bw, bh = 1, 1
        bw = max(1, min(32, bw))
        bh = max(1, min(32, bh))
        cp = int(state.get("sprite_edit_cell_px") or DEFAULT_CELL_PX)
        cp = max(1, min(256, cp))
        return bw * cp, bh * cp

    def _sync_sprite_matrix_from_widgets() -> None:
        """Alinea la matriz con Celdas W/H aunque el input_int no haya disparado callback."""
        pw_exp, ph_exp = _expected_sprite_matrix_pixel_size()
        rows = state.get("sprite_pixel_rows")
        pw, ph = palette_rows_pixel_size(rows if isinstance(rows, list) else None)
        if pw != pw_exp or ph != ph_exp:
            _resize_sprite_edit_matrix_for_widgets()

    def _sprite_matrix_fill_index(
        fill_from_index: int | None = None,
    ) -> int:
        if fill_from_index is not None:
            return clamp_pixel_storage_index(fill_from_index)
        fi = parse_sprite_palette_index()
        if fi == 0:
            fi = 1
        return clamp_pixel_storage_index(fi)

    def _resize_sprite_edit_matrix_for_widgets(
        *,
        fill_from_index: int | None = None,
    ) -> None:
        _sprite_flush_current_frame()
        pw, ph = _expected_sprite_matrix_pixel_size()
        fi = _sprite_matrix_fill_index(fill_from_index)
        frames = _ensure_sprite_frame_buffers()
        stashes = state.get("sprite_frame_stash")
        if not isinstance(stashes, list):
            stashes = [None] * len(frames)
        new_frames: list[list[list[int]]] = []
        new_stashes: list[dict[str, list[list[int]]] | None] = []
        for i, old in enumerate(frames):
            stash = stashes[i] if i < len(stashes) else None
            if not isinstance(stash, dict):
                stash = None
            if isinstance(old, list) and old and any(
                isinstance(r, list) and r for r in old
            ):
                rows, new_stash = resize_palette_rows_with_stash(
                    old, stash, pw, ph, fill_index=fi
                )
            else:
                rows = solid_fill_indices(pw, ph, fi)
                new_stash = stash
            new_frames.append(rows)
            new_stashes.append(new_stash)
        if not new_frames:
            new_frames = [solid_fill_indices(pw, ph, fi)]
            new_stashes = [None]
        state["sprite_frame_pixels"] = new_frames
        state["sprite_frame_stash"] = new_stashes
        _sprite_load_active_frame_into_editor()

    def _trim_sprite_pixel_rows_for_save() -> list[list[int]]:
        """Recorte del fotograma activo (compat); usar _trim_all_sprite_frames_for_save al guardar."""
        all_f = _trim_all_sprite_frames_for_save()
        idx = _sprite_active_frame_index()
        if idx < len(all_f):
            return all_f[idx]
        return all_f[0] if all_f else []

    def _trim_all_sprite_frames_for_save() -> list[list[list[int]]]:
        """Recorta todos los fotogramas al tamano activo."""
        _sprite_flush_current_frame()
        pw, ph = _expected_sprite_matrix_pixel_size()
        fi = _sprite_matrix_fill_index()
        frames = _ensure_sprite_frame_buffers()
        trimmed: list[list[list[int]]] = []
        for old in frames:
            trimmed.append(
                trim_palette_rows(
                    old if isinstance(old, list) else None,
                    pw,
                    ph,
                    fill_index=fi,
                )
            )
        state["sprite_frame_pixels"] = trimmed
        state["sprite_frame_stash"] = [None] * len(trimmed)
        _sprite_load_active_frame_into_editor()
        return trimmed

    def _sprite_active_frame_index() -> int:
        try:
            i = int(state.get("sprite_active_frame") or 0)
        except (TypeError, ValueError):
            i = 0
        frames = state.get("sprite_frame_pixels")
        n = len(frames) if isinstance(frames, list) else 1
        return max(0, min(max(0, n - 1), i))

    def _sprite_frame_count_from_state() -> int:
        frames = state.get("sprite_frame_pixels")
        if isinstance(frames, list) and frames:
            return len(frames)
        return 1

    def _ensure_sprite_frame_buffers() -> list[list[list[int]]]:
        frames = state.get("sprite_frame_pixels")
        rows = state.get("sprite_pixel_rows")
        if not isinstance(frames, list) or not frames:
            if isinstance(rows, list) and rows:
                state["sprite_frame_pixels"] = [rows]
            else:
                state["sprite_frame_pixels"] = []
            frames = state.get("sprite_frame_pixels")
        if not isinstance(frames, list):
            return []
        stashes = state.get("sprite_frame_stash")
        if not isinstance(stashes, list) or len(stashes) != len(frames):
            state["sprite_frame_stash"] = [None] * len(frames)
        return frames

    def _sprite_flush_current_frame() -> None:
        rows = state.get("sprite_pixel_rows")
        stash = state.get("sprite_pixel_stash")
        frames = _ensure_sprite_frame_buffers()
        if not frames:
            return
        idx = _sprite_active_frame_index()
        if isinstance(rows, list):
            frames[idx] = rows
        stashes = state.get("sprite_frame_stash")
        if isinstance(stashes, list) and idx < len(stashes):
            stashes[idx] = stash if isinstance(stash, dict) else None

    def _sprite_load_active_frame_into_editor() -> None:
        frames = _ensure_sprite_frame_buffers()
        if not frames:
            return
        idx = _sprite_active_frame_index()
        state["sprite_pixel_rows"] = frames[idx]
        stashes = state.get("sprite_frame_stash")
        if isinstance(stashes, list) and idx < len(stashes):
            state["sprite_pixel_stash"] = stashes[idx]
        else:
            state["sprite_pixel_stash"] = None

    def _read_sprite_frame_count_widget() -> int:
        if not dpg.does_item_exist("ts_sprite_frame_count"):
            return _sprite_frame_count_from_state()
        try:
            n = int(dpg.get_value("ts_sprite_frame_count"))
        except (TypeError, ValueError):
            n = 1
        return max(1, min(MAX_SPRITE_FRAMES, n))

    def _apply_sprite_frame_count(target: int) -> None:
        _sprite_flush_current_frame()
        target = max(1, min(MAX_SPRITE_FRAMES, int(target)))
        frames = _ensure_sprite_frame_buffers()
        stashes = state.get("sprite_frame_stash")
        if not isinstance(stashes, list):
            stashes = []
        pw, ph = _expected_sprite_matrix_pixel_size()
        fi = _sprite_matrix_fill_index()
        while len(frames) < target:
            if frames:
                last = frames[-1]
                dup = [list(r) for r in last if isinstance(r, list)]
                frames.append(trim_palette_rows(dup, pw, ph, fill_index=fi))
            else:
                frames.append(solid_fill_indices(pw, ph, fi))
            stashes.append(None)
        while len(frames) > target:
            frames.pop()
            if stashes:
                stashes.pop()
        state["sprite_frame_pixels"] = frames
        state["sprite_frame_stash"] = stashes
        if _sprite_active_frame_index() >= target:
            state["sprite_active_frame"] = target - 1
        _sprite_load_active_frame_into_editor()

    def _rebuild_sprite_frame_tabs(*, select_index: int | None = None) -> None:
        if not dpg.does_item_exist("ts_sprite_frame_tabs_group"):
            return
        if dpg.does_item_exist("ts_sprite_frame_tab_bar"):
            dpg.delete_item("ts_sprite_frame_tab_bar")
        n = _sprite_frame_count_from_state()
        idx = select_index if select_index is not None else _sprite_active_frame_index()
        idx = max(0, min(n - 1, idx))
        state["sprite_active_frame"] = idx
        state["sprite_ui_silent"] = True
        try:
            with dpg.tab_bar(
                tag="ts_sprite_frame_tab_bar",
                parent="ts_sprite_frame_tabs_group",
                callback=on_sprite_frame_tab_select,
            ):
                for i in range(n):
                    dpg.add_tab(
                        label=f"F{i}",
                        tag=f"ts_sprite_frame_tab_{i}",
                    )
        finally:
            state["sprite_ui_silent"] = False
        _sync_sprite_onion_controls()

    def _sync_sprite_onion_controls() -> None:
        """Habilita calcos de fotograma vecino solo si existen anterior/siguiente."""
        idx = _sprite_active_frame_index()
        n = _sprite_frame_count_from_state()
        has_prev = idx > 0
        has_next = idx < n - 1
        for tag, ok in (
            ("ts_sprite_onion_prev_show", has_prev),
            ("ts_sprite_onion_prev_opacity", has_prev),
            ("ts_sprite_onion_next_show", has_next),
            ("ts_sprite_onion_next_opacity", has_next),
        ):
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, enabled=ok)

    def _sprite_neighbor_frame_rows(offset: int) -> list[list[int]] | None:
        """Fotograma adyacente: offset -1 = anterior, +1 = siguiente."""
        _sprite_flush_current_frame()
        frames = _ensure_sprite_frame_buffers()
        if not frames:
            return None
        idx = _sprite_active_frame_index()
        j = idx + int(offset)
        if j < 0 or j >= len(frames):
            return None
        pw, ph = _expected_sprite_matrix_pixel_size()
        fi = _sprite_matrix_fill_index()
        old = frames[j]
        if not isinstance(old, list):
            return None
        return trim_palette_rows(old, pw, ph, fill_index=fi)

    def on_sprite_frame_tab_select(_sender: object, app_data: object) -> None:
        if state.get("sprite_ui_silent"):
            return
        _sprite_flush_current_frame()
        idx = 0
        if isinstance(app_data, str) and app_data.startswith("ts_sprite_frame_tab_"):
            try:
                idx = int(app_data.rsplit("_", 1)[-1])
            except ValueError:
                idx = 0
        else:
            try:
                idx = int(app_data)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                idx = _sprite_active_frame_index()
        state["sprite_active_frame"] = max(0, idx)
        _sprite_load_active_frame_into_editor()
        _sync_sprite_onion_controls()
        _refresh_sprite_edit_texture()

    def on_sprite_frame_count_change(_sender: object, _app_data: object) -> None:
        if state.get("sprite_ui_silent"):
            return
        target = _read_sprite_frame_count_widget()
        state["sprite_ui_silent"] = True
        try:
            if dpg.does_item_exist("ts_sprite_frame_count"):
                dpg.set_value("ts_sprite_frame_count", target)
        finally:
            state["sprite_ui_silent"] = False
        _apply_sprite_frame_count(target)
        _rebuild_sprite_frame_tabs()
        _sync_sprite_onion_controls()
        _refresh_sprite_edit_texture()

    def _clamp_sprite_origin_widgets(pw: int, ph: int) -> tuple[int, int]:
        try:
            ox_in = int(dpg.get_value("ts_sprite_origin_x"))
        except (TypeError, ValueError):
            ox_in = 0
        try:
            oy_in = int(dpg.get_value("ts_sprite_origin_y"))
        except (TypeError, ValueError):
            oy_in = 0
        ox, oy = parse_sprite_origin(
            {"origin_x": ox_in, "origin_y": oy_in},
            pw=pw,
            ph=ph,
        )
        max_x = max(0, pw - 1)
        max_y = max(0, ph - 1)
        if dpg.does_item_exist("ts_sprite_origin_x"):
            dpg.configure_item("ts_sprite_origin_x", max_value=max_x)
            dpg.configure_item("ts_sprite_origin_y", max_value=max_y)
        silent = bool(state.get("sprite_ui_silent"))
        if silent:
            dpg.set_value("ts_sprite_origin_x", ox)
            dpg.set_value("ts_sprite_origin_y", oy)
        else:
            state["sprite_ui_silent"] = True
            try:
                dpg.set_value("ts_sprite_origin_x", ox)
                dpg.set_value("ts_sprite_origin_y", oy)
            finally:
                state["sprite_ui_silent"] = False
        return ox, oy

    def on_sprite_origin_change(_sender: object, _app_data: object) -> None:
        if state.get("sprite_ui_silent"):
            return
        pw, ph = _expected_sprite_matrix_pixel_size()
        _clamp_sprite_origin_widgets(pw, ph)
        _refresh_sprite_edit_texture()

    def _ensure_sprite_edit_pixel_buffer() -> None:
        """Matriz en memoria para pintar; sin esto los clics no hacen nada."""
        rows = state.get("sprite_pixel_rows")
        if not isinstance(rows, list) or not rows:
            _resize_sprite_edit_matrix_for_widgets()
            return
        _sync_sprite_matrix_from_widgets()

    def _sprite_edit_paint_at_mouse(*, erase: bool = False) -> bool:
        _ensure_sprite_edit_pixel_buffer()
        rgbs_chk = state.get("sprite_palette_rgb")
        if (not isinstance(rgbs_chk, list) or not rgbs_chk) and isinstance(
            state.get("project_root"), Path
        ):
            _sprite_palette_reload_core(append_log=False)
        rows = state.get("sprite_pixel_rows")
        if not isinstance(rows, list) or not rows:
            return False
        if not dpg.does_item_exist(_SPRITE_EDITOR_IMG_TAG):
            return False
        pw, ph = _sprite_matrix_pixel_size(rows)
        if pw <= 0 or ph <= 0:
            return False
        sc = _sprite_editor_effective_scale(pw, ph)
        show_grid = _sprite_editor_grid_enabled()
        mx, my = dpg.get_mouse_pos(local=False)
        min_x, min_y = dpg.get_item_rect_min(_SPRITE_EDITOR_IMG_TAG)
        rx = float(mx - min_x)
        ry = float(my - min_y)
        dw, dh = _sprite_display_size(pw, ph, sc, with_gaps=show_grid)
        if rx < 0 or ry < 0 or rx >= dw or ry >= dh:
            return False
        hit = _sprite_pixel_from_display(rx, ry, pw, ph, sc, with_gaps=show_grid)
        if hit is None:
            return False
        lx, ly = hit
        color_i = (
            TRANSPARENT_PALETTE_INDEX
            if erase
            else parse_sprite_palette_index()
        )
        row = rows[ly]
        if isinstance(row, list) and lx < len(row):
            row[lx] = color_i
        _refresh_sprite_edit_texture()
        return True

    def _sprite_edit_paint_drag_common(*, erase: bool) -> None:
        if state.get("sprite_ui_silent"):
            return
        if not dpg.does_item_exist(_SPRITE_EDITOR_IMG_TAG):
            return
        try:
            if not dpg.is_item_hovered(_SPRITE_EDITOR_IMG_TAG):
                return
        except SystemError:
            return
        _sprite_edit_paint_at_mouse(erase=erase)

    def _sprite_matrix_pixel_size(rows: list[list[int]]) -> tuple[int, int]:
        ph = len(rows)
        if ph <= 0:
            return 0, 0
        pw = max((len(r) for r in rows if isinstance(r, list)), default=0)
        return pw, ph

    def _sync_sprite_edit_image_widget(dw: int, dh: int) -> None:
        """dw×dh = pixeles en textura y en pantalla (1:1, sin estirado borroso)."""
        uv = _sprite_editor_uv_max(dw, dh)
        if dpg.does_item_exist(_SPRITE_EDITOR_IMG_TAG):
            dpg.configure_item(
                _SPRITE_EDITOR_IMG_TAG,
                width=max(1, dw),
                height=max(1, dh),
                texture_tag=_SPRITE_EDITOR_TEX_TAG,
                uv_min=(0.0, 0.0),
                uv_max=uv,
            )

    def _apply_sprite_edit_rgba(pw: int, ph: int, rgba: list[float]) -> None:
        """Textura 512×512; escala entera en CPU para pixeles nitidos."""
        if pw <= 0 or ph <= 0 or not dpg.does_item_exist(_SPRITE_EDITOR_TEX_TAG):
            return
        expected_len = pw * ph * 4
        if len(rgba) != expected_len:
            return
        sc = _sprite_editor_effective_scale(pw, ph)
        show_grid = _sprite_editor_grid_enabled()
        if show_grid:
            gstep = (
                parse_sprite_editor_grid_step()
                if dpg.does_item_exist("ts_sprite_editor_grid_step")
                else _SPRITE_EDITOR_GRID_STEP_DEFAULT
            )
            disp_rgba, dw, dh = _scale_rgba_with_pixel_gaps(
                rgba, pw, ph, sc, grid_step=gstep
            )
        else:
            disp_rgba, dw, dh = _scale_rgba_nearest(rgba, pw, ph, sc)
        if dw > _SPRITE_EDITOR_TEX_MAX or dh > _SPRITE_EDITOR_TEX_MAX:
            dw = min(dw, _SPRITE_EDITOR_TEX_MAX)
            dh = min(dh, _SPRITE_EDITOR_TEX_MAX)
            disp_rgba = disp_rgba[: dw * dh * 4]
        tex_rgba = _pack_sprite_rgba_into_tex_buffer(disp_rgba, dw, dh)
        dpg.set_value(_SPRITE_EDITOR_TEX_TAG, tex_rgba)
        _sync_sprite_edit_image_widget(dw, dh)

    def _refresh_sprite_edit_texture() -> None:
        if not dpg.does_item_exist(_SPRITE_EDITOR_TEX_TAG):
            _rebuild_sprite_used_swatches()
            return
        if dpg.does_item_exist("ts_sprite_blocks_w"):
            _sync_sprite_matrix_from_widgets()
        rows = state.get("sprite_pixel_rows")
        rgbs = state.get("sprite_palette_rgb")
        if not isinstance(rows, list) or not rows:
            sc0 = _sprite_editor_effective_scale(
                DEFAULT_CELL_PX, DEFAULT_CELL_PX
            )
            _sync_sprite_edit_image_widget(
                DEFAULT_CELL_PX * sc0, DEFAULT_CELL_PX * sc0
            )
            _rebuild_sprite_used_swatches()
            return
        if not isinstance(rgbs, list) or not rgbs:
            sc0 = _sprite_editor_effective_scale(
                DEFAULT_CELL_PX, DEFAULT_CELL_PX
            )
            _sync_sprite_edit_image_widget(
                DEFAULT_CELL_PX * sc0, DEFAULT_CELL_PX * sc0
            )
            _rebuild_sprite_used_swatches()
            return
        pw_exp, ph_exp = _expected_sprite_matrix_pixel_size()
        pw_act, ph_act = _sprite_matrix_pixel_size(rows)
        if pw_act != pw_exp or ph_act != ph_exp:
            _resize_sprite_edit_matrix_for_widgets()
            rows = state.get("sprite_pixel_rows")
            if not isinstance(rows, list) or not rows:
                _rebuild_sprite_used_swatches()
                return
        pw, ph = pw_exp, ph_exp
        if pw <= 0 or ph <= 0:
            _rebuild_sprite_used_swatches()
            return
        pad_i = _sprite_matrix_fill_index()
        norm = trim_palette_rows(rows, pw, ph, fill_index=pad_i)
        if norm is not rows:
            state["sprite_pixel_rows"] = norm
        ref_layer = _sprite_ref_rgba_for_canvas(pw, ph)
        behind_rows: list[list[int]] | None = None
        over_rows: list[list[int]] | None = None
        if (
            dpg.does_item_exist("ts_sprite_onion_prev_show")
            and bool(dpg.get_value("ts_sprite_onion_prev_show"))
        ):
            behind_rows = _sprite_neighbor_frame_rows(-1)
        if (
            dpg.does_item_exist("ts_sprite_onion_next_show")
            and bool(dpg.get_value("ts_sprite_onion_next_show"))
        ):
            over_rows = _sprite_neighbor_frame_rows(1)
        base = composite_sprite_editor_preview(
            norm,
            rgbs,
            ref_layer,
            canvas_fill_rgb=_sprite_canvas_fill_rgb01(),
            ref_alpha=_sprite_ref_opacity(),
            paint_alpha=_sprite_paint_opacity(),
            behind_rows=behind_rows,
            behind_alpha=_sprite_onion_prev_opacity(),
            over_rows=over_rows,
            over_alpha=_sprite_onion_next_opacity(),
        )
        cp = int(state.get("sprite_edit_cell_px") or DEFAULT_CELL_PX)
        cp = max(1, min(256, cp))
        if len(base) != pw * ph * 4:
            _rebuild_sprite_used_swatches()
            return
        if dpg.does_item_exist("ts_sprite_origin_x"):
            try:
                ox_m = int(dpg.get_value("ts_sprite_origin_x"))
                oy_m = int(dpg.get_value("ts_sprite_origin_y"))
            except (TypeError, ValueError):
                ox_m, oy_m = 0, 0
            _mark_sprite_origin_on_logical_rgba(base, pw, ph, ox_m, oy_m)
        _apply_sprite_edit_rgba(pw, ph, base)
        _rebuild_sprite_used_swatches()
        if dpg.does_item_exist("ts_sprite_edit_size_label"):
            try:
                bw = int(dpg.get_value("ts_sprite_blocks_w"))
                bh = int(dpg.get_value("ts_sprite_blocks_h"))
            except (TypeError, ValueError):
                bw, bh = 1, 1
            dpg.set_value(
                "ts_sprite_edit_size_label",
                f"Vista: {pw}×{ph} px · {bw}×{bh} celdas de {cp}px",
            )

    def on_sprite_dimension_change(_sender: object, _app_data: object) -> None:
        if state.get("sprite_ui_silent"):
            return
        _sync_sprite_matrix_from_widgets()
        pw, ph = _expected_sprite_matrix_pixel_size()
        _clamp_sprite_origin_widgets(pw, ph)
        _refresh_sprite_edit_texture()

    def on_sprite_apply_size(_sender: object, _app_data: object) -> None:
        _resize_sprite_edit_matrix_for_widgets()
        pw, ph = _expected_sprite_matrix_pixel_size()
        _clamp_sprite_origin_widgets(pw, ph)
        _refresh_sprite_edit_texture()

    def on_sprite_editor_scale_change(_sender: object, _app_data: object) -> None:
        _refresh_sprite_edit_texture()

    def on_sprite_editor_grid_toggle(_sender: object, _app_data: object) -> None:
        _refresh_sprite_edit_texture()

    def _sprite_ref_opacity() -> float:
        if not dpg.does_item_exist("ts_sprite_ref_opacity"):
            return 0.45
        try:
            v = float(dpg.get_value("ts_sprite_ref_opacity"))
        except (TypeError, ValueError):
            v = 0.45
        return max(0.05, min(1.0, v))

    def _sprite_paint_opacity() -> float:
        if not dpg.does_item_exist("ts_sprite_paint_opacity"):
            return 1.0
        try:
            v = float(dpg.get_value("ts_sprite_paint_opacity"))
        except (TypeError, ValueError):
            v = 1.0
        return max(0.05, min(1.0, v))

    def _sprite_onion_prev_opacity() -> float:
        if not dpg.does_item_exist("ts_sprite_onion_prev_opacity"):
            return 0.35
        try:
            v = float(dpg.get_value("ts_sprite_onion_prev_opacity"))
        except (TypeError, ValueError):
            v = 0.35
        return max(0.05, min(1.0, v))

    def _sprite_onion_next_opacity() -> float:
        if not dpg.does_item_exist("ts_sprite_onion_next_opacity"):
            return 0.35
        try:
            v = float(dpg.get_value("ts_sprite_onion_next_opacity"))
        except (TypeError, ValueError):
            v = 0.35
        return max(0.05, min(1.0, v))

    def _sprite_canvas_fill_rgb01() -> tuple[float, float, float]:
        """Fondo del lienzo (solo editor); independiente de la paleta del sprite."""
        if dpg.does_item_exist("ts_sprite_canvas_bg"):
            raw = dpg.get_value("ts_sprite_canvas_bg")
            if isinstance(raw, (list, tuple)) and len(raw) >= 3:
                peak = max(float(raw[0]), float(raw[1]), float(raw[2]))
                if peak > 1.0 + 1e-6:
                    return (
                        max(0.0, min(1.0, float(raw[0]) / 255.0)),
                        max(0.0, min(1.0, float(raw[1]) / 255.0)),
                        max(0.0, min(1.0, float(raw[2]) / 255.0)),
                    )
                return (
                    max(0.0, min(1.0, float(raw[0]))),
                    max(0.0, min(1.0, float(raw[1]))),
                    max(0.0, min(1.0, float(raw[2]))),
                )
        cached = state.get("sprite_canvas_bg_rgb01")
        if isinstance(cached, (list, tuple)) and len(cached) >= 3:
            return (
                max(0.0, min(1.0, float(cached[0]))),
                max(0.0, min(1.0, float(cached[1]))),
                max(0.0, min(1.0, float(cached[2]))),
            )
        return (
            _SPRITE_EDITOR_CANVAS_BG_DEFAULT[0] / 255.0,
            _SPRITE_EDITOR_CANVAS_BG_DEFAULT[1] / 255.0,
            _SPRITE_EDITOR_CANVAS_BG_DEFAULT[2] / 255.0,
        )

    def on_sprite_canvas_bg_change(_sender: object, _app_data: object) -> None:
        state["sprite_canvas_bg_rgb01"] = _sprite_canvas_fill_rgb01()
        _refresh_sprite_edit_texture()

    def _sprite_ref_visible() -> bool:
        if not dpg.does_item_exist("ts_sprite_ref_show"):
            return True
        return bool(dpg.get_value("ts_sprite_ref_show"))

    def _sprite_ref_rgba_for_canvas(pw: int, ph: int) -> list[float] | None:
        if not _sprite_ref_visible():
            return None
        src = state.get("sprite_ref_source")
        if not isinstance(src, tuple) or len(src) != 3:
            return None
        sw, sh, rgba = src
        if not isinstance(rgba, list) or sw <= 0 or sh <= 0 or pw <= 0 or ph <= 0:
            return None
        return resample_rgba_stretch(rgba, int(sw), int(sh), pw, ph)

    def _update_sprite_ref_path_label() -> None:
        if not dpg.does_item_exist("ts_sprite_ref_path_label"):
            return
        p = str(state.get("sprite_ref_path") or "").strip()
        if not p:
            dpg.set_value("ts_sprite_ref_path_label", "(sin referencia)")
            return
        dpg.set_value("ts_sprite_ref_path_label", f"Referencia: {p}")

    def _load_sprite_ref_from_path(path: str) -> None:
        _ensure_sprite_edit_pixel_buffer()
        rows = state.get("sprite_pixel_rows")
        if not isinstance(rows, list) or not rows:
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "")
                + "Sprites: define tamano (celdas W/H) antes de importar referencia.\n",
            )
            return
        pw, ph = _sprite_matrix_pixel_size(rows)
        if pw <= 0 or ph <= 0:
            return
        try:
            sw, sh, rgba = load_image_rgba_float01(path)
        except ValueError as e:
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "") + f"Sprites referencia: {e}\n",
            )
            return
        state["sprite_ref_source"] = (sw, sh, rgba)
        state["sprite_ref_path"] = str(Path(path).expanduser())
        _update_sprite_ref_path_label()
        note = aspect_ratio_note(sw, sh, pw, ph)
        tail = f"Sprites: referencia cargada ({sw}×{sh} px)."
        if note:
            tail += f" {note}."
        tail += " No se guarda en el .json del sprite.\n"
        dpg.set_value("ts_log", (dpg.get_value("ts_log") or "") + tail)
        _refresh_sprite_edit_texture()

    def on_sprite_export_png_click(_sender: object, _app_data: object) -> None:
        root = state.get("project_root")
        if not isinstance(root, Path):
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "")
                + "Sprites: abre o crea un proyecto primero.\n",
            )
            return
        rgbs = state.get("sprite_palette_rgb")
        if not isinstance(rgbs, list) or not rgbs:
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "")
                + "Sprites: carga la paleta del sprite antes de exportar PNG.\n",
            )
            return
        _sprite_flush_current_frame()
        frames = _trim_all_sprite_frames_for_save()
        if not frames or not any(
            isinstance(fr, list) and fr and any(isinstance(r, list) and r for r in fr)
            for fr in frames
        ):
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "")
                + "Sprites: no hay pixeles para exportar; pinta o carga un sprite.\n",
            )
            return
        if dpg.does_item_exist("ts_sprite_export_dir_dialog"):
            dpg.show_item("ts_sprite_export_dir_dialog")

    def on_sprite_export_dir_picked(_sender: object, app_data: object) -> None:
        if not isinstance(app_data, dict):
            return
        out_dir = ""
        fp = app_data.get("file_path_name")
        if isinstance(fp, str) and fp.strip():
            out_dir = fp.strip()
        else:
            cp = app_data.get("current_path")
            if isinstance(cp, str) and cp.strip():
                out_dir = cp.strip()
            else:
                selections = app_data.get("selections")
                if isinstance(selections, dict) and selections:
                    out_dir = str(next(iter(selections.values()))).strip()
        if not out_dir:
            return
        rgbs = state.get("sprite_palette_rgb")
        if not isinstance(rgbs, list) or not rgbs:
            return
        _sprite_flush_current_frame()
        frames = _trim_all_sprite_frames_for_save()
        base = str(dpg.get_value("ts_sprite_id")).strip() if dpg.does_item_exist(
            "ts_sprite_id"
        ) else ""
        if not base:
            base = _sprite_list_selected_stem() or "sprite"
        try:
            written = export_sprite_frames_to_png_dir(
                out_dir, base, frames, rgbs
            )
        except (ValueError, OSError) as e:
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "") + f"Sprites exportar PNG: {e}\n",
            )
            return
        names = ", ".join(p.name for p in written)
        dpg.set_value(
            "ts_log",
            (dpg.get_value("ts_log") or "")
            + f"Sprites: exportados {len(written)} PNG en {out_dir} ({names}).\n",
        )

    def on_sprite_ref_import_click(_sender: object, _app_data: object) -> None:
        if dpg.does_item_exist("ts_sprite_ref_file_dialog"):
            dpg.show_item("ts_sprite_ref_file_dialog")

    def on_sprite_ref_file_picked(_sender: object, app_data: object) -> None:
        if not isinstance(app_data, dict):
            return
        path = ""
        fp = app_data.get("file_path_name")
        if isinstance(fp, str) and fp.strip():
            path = fp.strip()
        else:
            selections = app_data.get("selections")
            if isinstance(selections, dict) and selections:
                path = str(next(iter(selections.values()))).strip()
        if path:
            _load_sprite_ref_from_path(path)

    def on_sprite_ref_clear_click(_sender: object, _app_data: object) -> None:
        state["sprite_ref_source"] = None
        state["sprite_ref_path"] = ""
        _update_sprite_ref_path_label()
        _refresh_sprite_edit_texture()
        dpg.set_value(
            "ts_log",
            (dpg.get_value("ts_log") or "") + "Sprites: referencia quitada.\n",
        )

    def on_sprite_ref_convert_click(_sender: object, _app_data: object) -> None:
        _ensure_sprite_edit_pixel_buffer()
        rgbs = state.get("sprite_palette_rgb")
        if not isinstance(rgbs, list) or not rgbs:
            if isinstance(state.get("project_root"), Path):
                _sprite_palette_reload_core(append_log=False)
            rgbs = state.get("sprite_palette_rgb")
        if not isinstance(rgbs, list) or not rgbs:
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "")
                + "Sprites: carga la paleta del sprite antes de convertir.\n",
            )
            return
        src = state.get("sprite_ref_source")
        if not isinstance(src, tuple) or len(src) != 3:
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "")
                + "Sprites: importa una referencia antes de convertir.\n",
            )
            return
        pw, ph = _expected_sprite_matrix_pixel_size()
        if pw <= 0 or ph <= 0:
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "")
                + "Sprites: define tamano (celdas W/H) antes de convertir.\n",
            )
            return
        try:
            rows = convert_ref_source_to_palette_rows(src, pw, ph, rgbs)
        except ValueError as e:
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "") + f"Sprites convertir: {e}\n",
            )
            return
        if not rows:
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "") + "Sprites convertir: lienzo vacio.\n",
            )
            return
        _sprite_flush_current_frame()
        frames = _ensure_sprite_frame_buffers()
        idx = _sprite_active_frame_index()
        if idx < len(frames):
            frames[idx] = rows
        else:
            frames.append(rows)
        state["sprite_frame_pixels"] = frames
        state["sprite_pixel_rows"] = rows
        stashes = state.get("sprite_frame_stash")
        if isinstance(stashes, list) and idx < len(stashes):
            stashes[idx] = None
        state["sprite_pixel_stash"] = None
        _sprite_color_swap_cancel()
        _refresh_sprite_edit_texture()
        sw, sh, _rgba = src
        n_used = len(_sprite_used_paint_indices(rows))
        dpg.set_value(
            "ts_log",
            (dpg.get_value("ts_log") or "")
            + f"Sprites: referencia {sw}×{sh} → lienzo {pw}×{ph} px "
            f"({n_used} colores de paleta). Revisa y guarda el sprite.\n",
        )

    def on_sprite_editor_preview_change(_sender: object, _app_data: object) -> None:
        _refresh_sprite_edit_texture()

    def parse_sprite_editor_grid_step() -> int:
        if not dpg.does_item_exist("ts_sprite_editor_grid_step"):
            return _SPRITE_EDITOR_GRID_STEP_DEFAULT
        return _normalize_sprite_grid_step(dpg.get_value("ts_sprite_editor_grid_step"))

    def on_sprite_editor_grid_step_change(_sender: object, app_data: object) -> None:
        if not dpg.does_item_exist("ts_sprite_editor_grid_step"):
            return
        if app_data is not None and not isinstance(app_data, dict):
            try:
                raw: object = int(app_data)
            except (TypeError, ValueError):
                raw = dpg.get_value("ts_sprite_editor_grid_step")
        else:
            raw = dpg.get_value("ts_sprite_editor_grid_step")
        norm = _normalize_sprite_grid_step(raw)
        try:
            cur = int(dpg.get_value("ts_sprite_editor_grid_step"))
        except (TypeError, ValueError):
            cur = norm
        if cur != norm:
            dpg.set_value("ts_sprite_editor_grid_step", norm)
        _refresh_sprite_edit_texture()

    def on_sprite_fill_canvas(_sender: object, _app_data: object) -> None:
        fi = parse_sprite_palette_index()
        _resize_sprite_edit_matrix_for_widgets(fill_from_index=fi)
        _refresh_sprite_edit_texture()

    def on_sprite_clear_canvas(_sender: object, _app_data: object) -> None:
        _ensure_sprite_edit_pixel_buffer()
        rows = state.get("sprite_pixel_rows")
        if not isinstance(rows, list) or not rows:
            _resize_sprite_edit_matrix_for_widgets()
            rows = state.get("sprite_pixel_rows")
        if not isinstance(rows, list) or not rows:
            return
        pw, ph = _sprite_matrix_pixel_size(rows)
        if pw <= 0 or ph <= 0:
            return
        state["sprite_pixel_rows"] = solid_fill_indices(
            pw, ph, TRANSPARENT_PALETTE_INDEX
        )
        state["sprite_pixel_stash"] = None
        _sprite_color_swap_cancel()
        _refresh_sprite_edit_texture()

    def on_sprite_edit_canvas_click(_sender: object, _app_data: object) -> None:
        _sprite_edit_paint_at_mouse(erase=False)

    def on_sprite_edit_canvas_erase_click(_sender: object, _app_data: object) -> None:
        _sprite_edit_paint_at_mouse(erase=True)

    def on_sprite_edit_paint_drag(_sender: object, _app_data: object) -> None:
        _sprite_edit_paint_drag_common(erase=False)

    def on_sprite_edit_erase_drag(_sender: object, _app_data: object) -> None:
        _sprite_edit_paint_drag_common(erase=True)

    def _load_sprite_into_form(stem: str, *, quiet: bool = False) -> None:
        root = state.get("project_root")
        if not isinstance(root, Path):
            return
        try:
            data = read_sprite_file(root, stem)
        except ValueError as e:
            dpg.set_value("ts_log", (dpg.get_value("ts_log") or "") + f"Sprites: {e}\n")
            return
        sid = str(data.get("id", stem)).strip() or stem
        dpg.set_value("ts_sprite_id", sid)
        pal = str(data.get("palette", "")).strip().replace("\\", "/")
        if not pal:
            pal = DEFAULT_EXAMPLE_PALETTE_REL
        dpg.set_value("ts_sprite_palette_rel", pal)
        render = data.get("render")
        pi = 0
        if isinstance(render, dict):
            try:
                pi = int(render.get("palette_index", 0))
            except (TypeError, ValueError):
                pi = 0
        try:
            cp = int(data.get("cell_px", DEFAULT_CELL_PX))
        except (TypeError, ValueError):
            cp = DEFAULT_CELL_PX
        cp = max(1, min(cp, 256))
        bw, bh = 1, 1
        try:
            bw = int(data.get("blocks_w", 1))
            bh = int(data.get("blocks_h", 1))
        except (TypeError, ValueError):
            bw, bh = 1, 1
        if "blocks_w" not in data and "blocks_h" not in data:
            try:
                pw = int(data.get("pixel_w", cp))
                ph = int(data.get("pixel_h", cp))
                bw = max(1, pw // cp)
                bh = max(1, ph // cp)
            except (TypeError, ValueError):
                bw, bh = 1, 1
        bw = max(1, min(bw, 32))
        bh = max(1, min(bh, 32))
        state["sprite_edit_cell_px"] = cp
        pw, ph = bw * cp, bh * cp
        _sprite_color_swap_cancel()
        all_frames = parse_sprite_all_frame_rows(data, fill_index=pi)
        state["sprite_frame_pixels"] = all_frames
        state["sprite_frame_stash"] = [None] * len(all_frames)
        state["sprite_active_frame"] = 0
        _sprite_load_active_frame_into_editor()
        ox, oy = parse_sprite_origin(data, pw=pw, ph=ph)
        fc = len(all_frames)
        state["sprite_ui_silent"] = True
        try:
            dpg.set_value("ts_sprite_blocks_w", bw)
            dpg.set_value("ts_sprite_blocks_h", bh)
            if dpg.does_item_exist("ts_sprite_origin_x"):
                dpg.configure_item("ts_sprite_origin_x", max_value=max(0, pw - 1))
                dpg.configure_item("ts_sprite_origin_y", max_value=max(0, ph - 1))
                dpg.set_value("ts_sprite_origin_x", ox)
                dpg.set_value("ts_sprite_origin_y", oy)
            if dpg.does_item_exist("ts_sprite_frame_count"):
                dpg.set_value("ts_sprite_frame_count", fc)
        finally:
            state["sprite_ui_silent"] = False
        _rebuild_sprite_frame_tabs(select_index=0)
        _sync_sprite_onion_controls()
        _set_sprite_brush_index(pi)
        _sprite_palette_reload_core(append_log=False, preferred_palette_index=pi)
        _refresh_sprite_edit_texture()
        if not quiet:
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "") + f"Sprites: cargado {stem}.json\n",
            )

    def on_sprite_list_pick(_sender: object, _app_data: object) -> None:
        stem = _sprite_list_selected_stem()
        if stem:
            _load_sprite_into_form(stem)

    def on_sprite_save(_sender: object, _app_data: object) -> None:
        root = state.get("project_root")
        if not isinstance(root, Path):
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "")
                + "Sprites: abre o crea un proyecto primero.\n",
            )
            return
        prev_stem = _sprite_list_selected_stem()
        sid = str(dpg.get_value("ts_sprite_id")).strip()
        try:
            bw = int(dpg.get_value("ts_sprite_blocks_w"))
            bh = int(dpg.get_value("ts_sprite_blocks_h"))
        except (TypeError, ValueError):
            bw, bh = 1, 1
        pal_raw = str(dpg.get_value("ts_sprite_palette_rel")).strip()
        try:
            _resize_sprite_edit_matrix_for_widgets()
            all_frames = _trim_all_sprite_frames_for_save()
            if not all_frames:
                raise ValueError("matriz de pixeles vacia; recarga el sprite o la paleta.")
            rows2 = all_frames[0]
            pw_o, ph_o = _expected_sprite_matrix_pixel_size()
            ox, oy = _clamp_sprite_origin_widgets(pw_o, ph_o)
            path = save_indexed_pixels_sprite_json(
                root,
                sid,
                palette_rel=pal_raw,
                blocks_w=bw,
                blocks_h=bh,
                rows=rows2,
                frame_rows=all_frames,
                cell_px=int(
                    state.get("sprite_edit_cell_px") or DEFAULT_CELL_PX
                ),
                origin_x=ox,
                origin_y=oy,
            )
        except ValueError as e:
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "") + f"Sprites: {e}\n",
            )
            return
        except OSError as e:
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "") + f"Sprites: error de escritura: {e}\n",
            )
            return
        rel = path.relative_to(root).as_posix()
        _refresh_sprite_file_list()
        if dpg.does_item_exist("ts_sprite_list"):
            dpg.set_value("ts_sprite_list", sid)
        if prev_stem and prev_stem != sid:
            log_line = (
                f"Sprites: guardado {rel}. Sigue existiendo {prev_stem}.json "
                "(borralo si renombraste el ID).\n"
            )
        else:
            log_line = f"Sprites: guardado {rel}\n"
        dpg.set_value("ts_log", (dpg.get_value("ts_log") or "") + log_line)
        _refresh_scene_object_lists()
        refresh_canvas_texture()
        _load_sprite_into_form(sid, quiet=True)

    def _obj_list_selected_stem() -> str | None:
        raw = dpg.get_value("ts_obj_list")
        if raw is None:
            return None
        s = str(raw).strip()
        if not s or s.startswith("("):
            return None
        return s

    def _load_object_into_form(stem: str) -> None:
        root = state.get("project_root")
        if not isinstance(root, Path):
            return
        try:
            data = read_object_file(root, stem)
        except ValueError as e:
            dpg.set_value("ts_log", (dpg.get_value("ts_log") or "") + f"Objetos: {e}\n")
            return
        oid = str(data.get("id", stem)).strip() or stem
        dpg.set_value("ts_obj_id", oid)
        dpg.set_value("ts_obj_name", str(data.get("name", oid)).strip() or oid)
        sp = str(data.get("sprite_id", "")).strip()
        _refresh_obj_sprite_combo()
        items = dpg.get_item_configuration("ts_obj_sprite_combo").get("items") or []
        if sp and sp in items:
            dpg.set_value("ts_obj_sprite_combo", sp)
        elif items and not str(items[0]).startswith("("):
            dpg.set_value("ts_obj_sprite_combo", items[0])
        state["obj_animations"] = parse_object_animations(data)
        _rebuild_obj_anim_listbox()
        if dpg.does_item_exist("ts_obj_anim_name"):
            dpg.set_value("ts_obj_anim_name", "")
        _set_object_collision_widgets_from_data(root, data, sprite_id=sp)
        _refresh_object_collision_preview()
        dpg.set_value(
            "ts_log",
            (dpg.get_value("ts_log") or "") + f"Objetos: cargado {stem}.json\n",
        )

    def _object_collision_mode_from_combo() -> str:
        if not dpg.does_item_exist("ts_obj_coll_shape"):
            return OBJECT_COLLISION_MODE_AABB
        label = str(dpg.get_value("ts_obj_coll_shape"))
        for i, lab in enumerate(_OBJ_COLL_SHAPE_LABELS):
            if label == lab:
                return _OBJ_COLL_SHAPE_MODES[i]
        return OBJECT_COLLISION_MODE_AABB

    def _sync_object_collision_shape_ui() -> None:
        mode = _object_collision_mode_from_combo()
        show_square = mode == OBJECT_COLLISION_MODE_AABB
        show_tri = mode == OBJECT_COLLISION_MODE_TRIANGLE
        show_hex = mode == OBJECT_COLLISION_MODE_HEXAGON
        for tag, vis in (
            ("ts_obj_coll_square_grp", show_square),
            ("ts_obj_coll_triangle_grp", show_tri),
            ("ts_obj_coll_hexagon_grp", show_hex),
        ):
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, show=vis)

    def _set_object_collision_widgets(coll: dict[str, Any]) -> None:
        mode = str(coll.get("mode", OBJECT_COLLISION_MODE_AABB))
        label = _OBJ_COLL_SHAPE_LABELS[0]
        for i, m in enumerate(_OBJ_COLL_SHAPE_MODES):
            if m == mode:
                label = _OBJ_COLL_SHAPE_LABELS[i]
                break
        if dpg.does_item_exist("ts_obj_coll_shape"):
            dpg.set_value("ts_obj_coll_shape", label)
        if mode == OBJECT_COLLISION_MODE_AABB:
            for tag, key in (
                ("ts_obj_coll_x0", "x0"),
                ("ts_obj_coll_y0", "y0"),
                ("ts_obj_coll_x1", "x1"),
                ("ts_obj_coll_y1", "y1"),
            ):
                if dpg.does_item_exist(tag):
                    dpg.set_value(tag, int(coll[key]))
        else:
            pts = coll.get("points")
            if not isinstance(pts, list):
                return
            if mode == OBJECT_COLLISION_MODE_TRIANGLE:
                tags = (
                    "ts_obj_coll_t0x",
                    "ts_obj_coll_t0y",
                    "ts_obj_coll_t1x",
                    "ts_obj_coll_t1y",
                    "ts_obj_coll_t2x",
                    "ts_obj_coll_t2y",
                )
            else:
                tags = (
                    "ts_obj_coll_h0x",
                    "ts_obj_coll_h0y",
                    "ts_obj_coll_h1x",
                    "ts_obj_coll_h1y",
                    "ts_obj_coll_h2x",
                    "ts_obj_coll_h2y",
                    "ts_obj_coll_h3x",
                    "ts_obj_coll_h3y",
                    "ts_obj_coll_h4x",
                    "ts_obj_coll_h4y",
                    "ts_obj_coll_h5x",
                    "ts_obj_coll_h5y",
                )
            flat: list[int] = []
            for p in pts:
                if isinstance(p, (list, tuple)) and len(p) >= 2:
                    flat.extend((int(p[0]), int(p[1])))
            for tag, val in zip(tags, flat, strict=False):
                if dpg.does_item_exist(tag):
                    dpg.set_value(tag, val)
        _sync_object_collision_shape_ui()

    def _set_object_collision_widgets_from_data(
        root: Path,
        data: dict[str, Any],
        *,
        sprite_id: str,
    ) -> None:
        coll = parse_object_collision(data)
        if coll is None and sprite_id:
            try:
                coll = default_collision_for_sprite_ref(
                    root, sprite_id, mode=OBJECT_COLLISION_MODE_AABB
                )
            except ValueError:
                coll = {
                    "mode": OBJECT_COLLISION_MODE_AABB,
                    "x0": 0,
                    "y0": 0,
                    "x1": 0,
                    "y1": 0,
                }
        if coll is not None:
            _set_object_collision_widgets(coll)
        else:
            _sync_object_collision_shape_ui()

    def _read_object_collision_from_widgets() -> dict[str, Any]:
        def _iv(tag: str) -> int:
            try:
                return int(dpg.get_value(tag))
            except (TypeError, ValueError):
                return 0

        mode = _object_collision_mode_from_combo()
        if mode == OBJECT_COLLISION_MODE_AABB:
            return {
                "mode": mode,
                "x0": _iv("ts_obj_coll_x0"),
                "y0": _iv("ts_obj_coll_y0"),
                "x1": _iv("ts_obj_coll_x1"),
                "y1": _iv("ts_obj_coll_y1"),
            }
        if mode == OBJECT_COLLISION_MODE_TRIANGLE:
            return {
                "mode": mode,
                "points": [
                    [_iv("ts_obj_coll_t0x"), _iv("ts_obj_coll_t0y")],
                    [_iv("ts_obj_coll_t1x"), _iv("ts_obj_coll_t1y")],
                    [_iv("ts_obj_coll_t2x"), _iv("ts_obj_coll_t2y")],
                ],
            }
        return {
            "mode": OBJECT_COLLISION_MODE_HEXAGON,
            "points": [
                [_iv("ts_obj_coll_h0x"), _iv("ts_obj_coll_h0y")],
                [_iv("ts_obj_coll_h1x"), _iv("ts_obj_coll_h1y")],
                [_iv("ts_obj_coll_h2x"), _iv("ts_obj_coll_h2y")],
                [_iv("ts_obj_coll_h3x"), _iv("ts_obj_coll_h3y")],
                [_iv("ts_obj_coll_h4x"), _iv("ts_obj_coll_h4y")],
                [_iv("ts_obj_coll_h5x"), _iv("ts_obj_coll_h5y")],
            ],
        }

    def on_object_collision_shape_change(_sender: object, _app_data: object) -> None:
        _sync_object_collision_shape_ui()
        _refresh_object_collision_preview()

    def _sync_obj_coll_preview_image_widget(dw: int, dh: int) -> None:
        if not dpg.does_item_exist(_OBJ_COLL_PREVIEW_IMG_TAG):
            return
        uv = _obj_coll_preview_uv_max(dw, dh)
        dpg.configure_item(
            _OBJ_COLL_PREVIEW_IMG_TAG,
            width=max(1, dw),
            height=max(1, dh),
            texture_tag=_OBJ_COLL_PREVIEW_TEX_TAG,
            uv_min=(0.0, 0.0),
            uv_max=uv,
        )

    def _refresh_object_collision_preview() -> None:
        if not dpg.does_item_exist(_OBJ_COLL_PREVIEW_TEX_TAG):
            return
        root = state.get("project_root")
        label = "(carga un objeto y sprite)"
        if not isinstance(root, Path):
            if dpg.does_item_exist("ts_obj_coll_preview_label"):
                dpg.set_value("ts_obj_coll_preview_label", label)
            return
        sp = ""
        if dpg.does_item_exist("ts_obj_sprite_combo"):
            sp = str(dpg.get_value("ts_obj_sprite_combo")).strip()
        if sp.startswith("(") or not sp:
            tex = _solid_rgba_float(
                _OBJ_COLL_PREVIEW_TEX_MAX,
                _OBJ_COLL_PREVIEW_TEX_MAX,
                _OBJ_COLL_PREVIEW_PAD_RGBA[0],
                _OBJ_COLL_PREVIEW_PAD_RGBA[1],
                _OBJ_COLL_PREVIEW_PAD_RGBA[2],
            )
            dpg.set_value(_OBJ_COLL_PREVIEW_TEX_TAG, tex)
            _sync_obj_coll_preview_image_widget(64, 64)
            if dpg.does_item_exist("ts_obj_coll_preview_label"):
                dpg.set_value("ts_obj_coll_preview_label", label)
            return
        try:
            raw_coll = _read_object_collision_from_widgets()
            collision = normalize_object_collision(raw_coll)
        except ValueError:
            collision = None
        if collision is None:
            try:
                collision = default_collision_for_sprite_ref(
                    root,
                    sp,
                    mode=_object_collision_mode_from_combo(),
                )
            except ValueError:
                collision = None
        built = (
            _build_object_collision_preview_rgba(root, sp, collision)
            if collision is not None
            else None
        )
        if built is None:
            tex = _solid_rgba_float(
                _OBJ_COLL_PREVIEW_TEX_MAX,
                _OBJ_COLL_PREVIEW_TEX_MAX,
                _OBJ_COLL_PREVIEW_PAD_RGBA[0],
                _OBJ_COLL_PREVIEW_PAD_RGBA[1],
                _OBJ_COLL_PREVIEW_PAD_RGBA[2],
            )
            dpg.set_value(_OBJ_COLL_PREVIEW_TEX_TAG, tex)
            _sync_obj_coll_preview_image_widget(64, 64)
            if dpg.does_item_exist("ts_obj_coll_preview_label"):
                dpg.set_value(
                    "ts_obj_coll_preview_label",
                    f"Vista collision: (sin sprite {sp!r})",
                )
            return
        logical, lw, lh = built
        sc = max(
            1,
            min(
                _OBJ_COLL_PREVIEW_SCALE_MAX,
                _OBJ_COLL_PREVIEW_TEX_MAX // max(lw, lh, 1),
            ),
        )
        disp, dw, dh = _scale_rgba_nearest(logical, lw, lh, sc)
        tex = _pack_sprite_rgba_into_tex_buffer(
            disp,
            dw,
            dh,
            tex_w=_OBJ_COLL_PREVIEW_TEX_MAX,
            tex_h=_OBJ_COLL_PREVIEW_TEX_MAX,
        )
        dpg.set_value(_OBJ_COLL_PREVIEW_TEX_TAG, tex)
        _sync_obj_coll_preview_image_widget(dw, dh)
        if dpg.does_item_exist("ts_obj_coll_preview_label"):
            mode_lbl = _object_collision_mode_from_combo()
            for i, m in enumerate(_OBJ_COLL_SHAPE_MODES):
                if m == mode_lbl:
                    mode_lbl = _OBJ_COLL_SHAPE_LABELS[i]
                    break
            dpg.set_value(
                "ts_obj_coll_preview_label",
                f"Vista collision: {sp!r} · {mode_lbl} · magenta=ancla",
            )

    def on_object_collision_preview_change(
        _sender: object, _app_data: object
    ) -> None:
        _refresh_object_collision_preview()

    def on_object_sprite_combo_change(_sender: object, _app_data: object) -> None:
        _refresh_object_collision_preview()

    def on_object_collision_from_sprite(_sender: object, _app_data: object) -> None:
        root = state.get("project_root")
        if not isinstance(root, Path):
            return
        sp = str(dpg.get_value("ts_obj_sprite_combo")).strip()
        if sp.startswith("("):
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "")
                + "Objetos collision: elige un sprite por defecto.\n",
            )
            return
        mode = _object_collision_mode_from_combo()
        try:
            coll = default_collision_for_sprite_ref(root, sp, mode=mode)
        except ValueError as e:
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "") + f"Objetos collision: {e}\n",
            )
            return
        _set_object_collision_widgets(coll)
        shape_lbl = (
            str(dpg.get_value("ts_obj_coll_shape"))
            if dpg.does_item_exist("ts_obj_coll_shape")
            else mode
        )
        dpg.set_value(
            "ts_log",
            (dpg.get_value("ts_log") or "")
            + f"Objetos: collision ({shape_lbl}) desde sprite {sp!r}. Guarda el objeto.\n",
        )
        _refresh_object_collision_preview()

    def on_object_anim_list_pick(_sender: object, _app_data: object) -> None:
        name = _obj_anim_list_selected_name()
        if not name:
            return
        anims = _read_obj_animations_from_state()
        for a in anims:
            if a["name"] == name:
                if dpg.does_item_exist("ts_obj_anim_name"):
                    dpg.set_value("ts_obj_anim_name", a["name"])
                _refresh_obj_anim_sprite_combo()
                items = (
                    dpg.get_item_configuration("ts_obj_anim_sprite_combo").get("items")
                    or []
                )
                if a["sprite_id"] in items:
                    dpg.set_value("ts_obj_anim_sprite_combo", a["sprite_id"])
                break

    def on_object_anim_add(_sender: object, _app_data: object) -> None:
        root = state.get("project_root")
        if not isinstance(root, Path):
            return
        try:
            name = validate_animation_name(str(dpg.get_value("ts_obj_anim_name")))
        except ValueError as e:
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "") + f"Objetos animacion: {e}\n",
            )
            return
        sp = str(dpg.get_value("ts_obj_anim_sprite_combo")).strip()
        if sp.startswith("("):
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "")
                + "Objetos animacion: elige un sprite en el desplegable.\n",
            )
            return
        try:
            normalize_object_animations(
                root, [{"name": name, "sprite_id": sp}]
            )
        except ValueError as e:
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "") + f"Objetos animacion: {e}\n",
            )
            return
        anims = _read_obj_animations_from_state()
        anims = [a for a in anims if a["name"] != name]
        anims.append({"name": name, "sprite_id": sp})
        state["obj_animations"] = anims
        _rebuild_obj_anim_listbox(select_name=name)
        dpg.set_value(
            "ts_log",
            (dpg.get_value("ts_log") or "")
            + f"Objetos: animacion {name!r} → {sp} (guarda el objeto para escribir JSON).\n",
        )

    def on_object_anim_remove(_sender: object, _app_data: object) -> None:
        name = _obj_anim_list_selected_name()
        if not name:
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "")
                + "Objetos animacion: elige una entrada de la lista.\n",
            )
            return
        anims = [a for a in _read_obj_animations_from_state() if a["name"] != name]
        state["obj_animations"] = anims
        _rebuild_obj_anim_listbox()
        if dpg.does_item_exist("ts_obj_anim_name"):
            dpg.set_value("ts_obj_anim_name", "")
        dpg.set_value(
            "ts_log",
            (dpg.get_value("ts_log") or "")
            + f"Objetos: quitada animacion {name!r} (guarda el objeto para escribir JSON).\n",
        )

    def on_object_list_pick(_sender: object, _app_data: object) -> None:
        stem = _obj_list_selected_stem()
        if stem:
            _load_object_into_form(stem)

    def on_object_refresh(_sender: object | None = None, _app_data: object | None = None) -> None:
        _refresh_object_file_list()
        _refresh_obj_sprite_combo()
        root = state.get("project_root")
        if isinstance(root, Path):
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "") + "Objetos: lista actualizada.\n",
            )
        _refresh_scene_object_lists()
        refresh_canvas_texture()

    def on_object_create(_sender: object, _app_data: object) -> None:
        root = state.get("project_root")
        if not isinstance(root, Path):
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "") + "Objetos: abre o crea un proyecto primero.\n",
            )
            return
        oid = str(dpg.get_value("ts_obj_id")).strip()
        name = str(dpg.get_value("ts_obj_name")).strip()
        sp = str(dpg.get_value("ts_obj_sprite_combo")).strip()
        if sp.startswith("("):
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "") + "Objetos: elige un sprite valido en el desplegable.\n",
            )
            return
        anims = _read_obj_animations_from_state()
        try:
            coll = normalize_object_collision(_read_object_collision_from_widgets())
        except ValueError as e:
            dpg.set_value("ts_log", (dpg.get_value("ts_log") or "") + f"Objetos: {e}\n")
            return
        try:
            path = write_object_json(
                root,
                oid,
                name=name,
                sprite_id=sp,
                animations=anims,
                collision=coll,
            )
        except ValueError as e:
            dpg.set_value("ts_log", (dpg.get_value("ts_log") or "") + f"Objetos: {e}\n")
            return
        except OSError as e:
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "") + f"Objetos: error de escritura: {e}\n",
            )
            return
        rel = path.relative_to(root).as_posix()
        _refresh_object_file_list()
        if dpg.does_item_exist("ts_obj_list"):
            dpg.set_value("ts_obj_list", oid)
        dpg.set_value("ts_log", (dpg.get_value("ts_log") or "") + f"Objetos: creado {rel}\n")
        _load_object_into_form(oid)
        _refresh_scene_object_lists()
        refresh_canvas_texture()

    def on_object_save(_sender: object, _app_data: object) -> None:
        root = state.get("project_root")
        if not isinstance(root, Path):
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "") + "Objetos: abre o crea un proyecto primero.\n",
            )
            return
        prev_stem = _obj_list_selected_stem()
        oid = str(dpg.get_value("ts_obj_id")).strip()
        name = str(dpg.get_value("ts_obj_name")).strip()
        sp = str(dpg.get_value("ts_obj_sprite_combo")).strip()
        if sp.startswith("("):
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "") + "Objetos: elige un sprite valido en el desplegable.\n",
            )
            return
        anims = _read_obj_animations_from_state()
        try:
            coll = normalize_object_collision(_read_object_collision_from_widgets())
        except ValueError as e:
            dpg.set_value("ts_log", (dpg.get_value("ts_log") or "") + f"Objetos: {e}\n")
            return
        try:
            path = save_object_json(
                root,
                oid,
                name=name,
                sprite_id=sp,
                animations=anims,
                collision=coll,
            )
        except ValueError as e:
            dpg.set_value("ts_log", (dpg.get_value("ts_log") or "") + f"Objetos: {e}\n")
            return
        except OSError as e:
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "") + f"Objetos: error de escritura: {e}\n",
            )
            return
        rel = path.relative_to(root).as_posix()
        _refresh_object_file_list()
        if dpg.does_item_exist("ts_obj_list"):
            dpg.set_value("ts_obj_list", oid)
        if prev_stem and prev_stem != oid:
            log_line = (
                f"Objetos: guardado {rel}. Sigue existiendo {prev_stem}.json "
                "(borralo si renombraste el ID).\n"
            )
        else:
            log_line = f"Objetos: guardado {rel}\n"
        dpg.set_value("ts_log", (dpg.get_value("ts_log") or "") + log_line)
        _refresh_scene_object_lists()
        refresh_canvas_texture()
        _load_object_into_form(oid)

    def on_startup_create(_sender: object, _app_data: object) -> None:
        root_s = str(dpg.get_value("ts_new_project_path")).strip()
        name_s = str(dpg.get_value("ts_new_project_name")).strip()
        if not root_s:
            dpg.set_value("ts_startup_log", "Indica la carpeta donde crear el proyecto.\n")
            return
        root = Path(root_s).expanduser()
        display_name = name_s if name_s else None
        try:
            mp = create_project(root, display_name=display_name, force=False)
        except ValueError as e:
            dpg.set_value("ts_startup_log", f"{e}\nUsa CLI: turtlestudio project init ... --force\n")
            return
        except OSError as e:
            dpg.set_value("ts_startup_log", f"Error de escritura: {e}\n")
            return
        state["project_root"] = root.resolve()
        pr = root.resolve()
        try:
            pinfo = load_project(pr)
        except ValueError as e:
            dpg.set_value("ts_startup_log", f"Proyecto creado pero no se pudo leer el manifest: {e}\n")
            return
        _apply_project_scenes_from_info(pinfo)
        _load_project_lua_buffers(pr)
        dpg.set_value("ts_entry", pinfo.entry)
        if pinfo.default_palette:
            dpg.set_value("ts_pal_path", str((pr / pinfo.default_palette).resolve()))
        else:
            dpg.set_value("ts_pal_path", "")
        out_default = pr / "build" / "main.turtlecart"
        dpg.set_value("ts_out_path", str(out_default))
        enter_main_editor(log_append=f"Proyecto creado.\n  {mp}\n")

    def on_startup_open(_sender: object, _app_data: object) -> None:
        root_s = str(dpg.get_value("ts_open_project_path")).strip()
        if not root_s:
            dpg.set_value("ts_startup_log", "Indica la carpeta que contiene turtlestudio.json\n")
            return
        root = Path(root_s).expanduser()
        try:
            info = load_project(root)
        except ValueError as e:
            dpg.set_value("ts_startup_log", f"{e}\n")
            return
        state["project_root"] = info.root
        _apply_project_scenes_from_info(info)
        _load_project_lua_buffers(info.root)
        dpg.set_value("ts_entry", info.entry)
        out_default = info.root / "build" / "main.turtlecart"
        dpg.set_value("ts_out_path", str(out_default))
        enter_main_editor(
            log_append=(
                f"Proyecto abierto: {info.name}\n"
                f"  root: {info.root}\n"
                f"  entry: {info.entry}\n"
            ),
        )

    def on_startup_skip_project(_sender: object, _app_data: object) -> None:
        state["project_root"] = None
        state["scenes"] = []
        state["active_scene_id"] = DEFAULT_INITIAL_SCENE_ID
        state["lua_sources"] = {}
        state["lua_edit_rel"] = ""
        state["project_entry"] = DEFAULT_ENTRY
        dpg.set_value("ts_lua_source", _DEFAULT_LUA)
        dpg.set_value("ts_entry", DEFAULT_ENTRY)
        dpg.set_value("ts_pal_path", "")
        dpg.set_value("ts_out_path", "main.turtlecart")
        enter_main_editor(log_append="Modo sin proyecto (solo editor y export manual).\n")

    with dpg.window(
        tag="ts_startup",
        label="TurtleStudio — Proyecto",
        modal=True,
        no_resize=True,
        no_move=False,
        autosize=True,
        show=True,
    ):
        dpg.add_text("Elige como empezar. Un proyecto es una carpeta con turtlestudio.json.")
        dpg.add_separator()
        dpg.add_text("Nuevo proyecto", color=(200, 220, 255, 255))
        dpg.add_input_text(
            tag="ts_new_project_path",
            label="Carpeta (se crea si no existe)",
            width=480,
            hint="/home/usuario/MisJuegos/MiCartucho",
        )
        dpg.add_input_text(
            tag="ts_new_project_name",
            label="Nombre en manifest (opc.)",
            width=480,
            hint="Si vacio, se usa el nombre de la carpeta",
        )
        dpg.add_button(label="Crear proyecto", width=480, callback=on_startup_create)
        dpg.add_separator()
        dpg.add_text("Abrir proyecto existente", color=(200, 220, 255, 255))
        dpg.add_input_text(
            tag="ts_open_project_path",
            label="Carpeta con turtlestudio.json",
            width=480,
            hint="/home/usuario/MisJuegos/MiCartucho",
            default_value="exampleprojects/demo1",
        )
        dpg.add_button(label="Abrir", width=480, callback=on_startup_open)
        dpg.add_separator()
        dpg.add_button(
            label="Continuar sin proyecto",
            width=480,
            callback=on_startup_skip_project,
        )
        dpg.add_spacer(height=6)
        dpg.add_input_text(
            tag="ts_startup_log",
            label="Mensajes",
            multiline=True,
            readonly=True,
            width=480,
            height=72,
            default_value="",
        )

    with dpg.window(
        tag="ts_main",
        label="TurtleStudio",
        no_resize=False,
        show=False,
    ):
        with dpg.menu_bar():
            with dpg.menu(label="Proyecto"):
                dpg.add_menu_item(
                    tag="ts_menu_save_project",
                    label="Guardar proyecto",
                    callback=on_save_project,
                    enabled=False,
                )
                dpg.add_menu_item(
                    label="Cambiar proyecto…",
                    callback=show_project_startup_dialog,
                )

        with dpg.tab_bar():
            with dpg.tab(label="Editor"):
                with dpg.group(horizontal=True):
                    with dpg.child_window(width=_LEFT_PANEL_WIDTH, border=True):
                        dpg.add_text("Cartucho / paleta")
                        dpg.add_text(
                            "El ENTRY (global) se define en Exportar; al exportar main.turtlecart va en el "
                            "bloque principal. El bundle solo incluye datos de estudio; los Lua de escena "
                            "se editan aqui y pueden ir en otros archivos al empaquetar.",
                            wrap=_LEFT_TEXT_WRAP,
                        )
                        dpg.add_input_text(
                            tag="ts_pal_path",
                            label="Paleta (opc.)",
                            width=_LEFT_FORM_WIDTH,
                            hint="palette.txt",
                            use_internal_label=False,
                        )
                        dpg.add_separator()
                        dpg.add_text("Importar script (opc.)")
                        dpg.add_input_text(
                            tag="ts_import_lua_path",
                            label="Ruta .lua",
                            width=_LEFT_FORM_WIDTH,
                            hint="/ruta/a/main.lua",
                            use_internal_label=False,
                        )
                        dpg.add_button(
                            label="Cargar en editor",
                            width=_LEFT_FORM_WIDTH,
                            callback=on_load_lua_from_file,
                        )
                        dpg.add_button(
                            tag="ts_btn_save_project",
                            label="Guardar proyecto",
                            width=_LEFT_FORM_WIDTH,
                            callback=on_save_project,
                            enabled=False,
                        )
                        dpg.add_separator()
                        dpg.add_text("Escenas (proyecto)")
                        dpg.add_combo(
                            tag="ts_scene_combo",
                            label="Escena activa",
                            width=_LEFT_FORM_WIDTH,
                            items=[DEFAULT_INITIAL_SCENE_ID],
                            default_value=DEFAULT_INITIAL_SCENE_ID,
                            callback=on_scene_combo,
                            enabled=False,
                            use_internal_label=False,
                        )
                        dpg.add_input_text(
                            tag="ts_scene_pal",
                            label="Paleta (ruta relativa al proyecto)",
                            width=_LEFT_FORM_WIDTH,
                            hint="palettes/palette.txt",
                            enabled=False,
                            use_internal_label=False,
                            callback=on_scene_palette_input_change,
                        )
                        dpg.add_input_text(
                            tag="ts_scene_script",
                            label="Lua escena (stem → scripts/<stem>.lua)",
                            width=_LEFT_FORM_WIDTH,
                            hint=DEFAULT_INITIAL_SCENE_ID,
                            enabled=False,
                            use_internal_label=False,
                        )
                        dpg.add_button(
                            tag="ts_btn_new_scene",
                            label="Nueva escena",
                            width=_LEFT_FORM_WIDTH,
                            callback=on_new_scene,
                            enabled=False,
                        )
                        dpg.add_combo(
                            tag="ts_scene_background",
                            label="Recurso fondo (backgrounds/*.json)",
                            width=_LEFT_FORM_WIDTH,
                            items=["(abre un proyecto)"],
                            default_value="(abre un proyecto)",
                            callback=on_scene_background_change,
                            enabled=False,
                            use_internal_label=False,
                        )
                        dpg.add_text(
                            "Objetos en escena (misma paleta que la escena). "
                            "Anadir: elige uno en la lista y pulsa en el canvas para fijar posicion "
                            f"(x,y en espacio escena {_FB_W}x{_FB_H}, origen abajo-izquierda, Y arriba).",
                            wrap=_LEFT_TEXT_WRAP,
                        )
                        dpg.add_listbox(
                            tag="ts_scene_obj_compat_list",
                            label="Puedes anadir",
                            width=_LEFT_FORM_WIDTH,
                            num_items=5,
                            items=["(abre un proyecto)"],
                            enabled=False,
                        )
                        dpg.add_button(
                            tag="ts_btn_scene_obj_add",
                            label="Anadir a la escena",
                            width=_LEFT_FORM_WIDTH,
                            callback=on_scene_add_object,
                            enabled=False,
                        )
                        dpg.add_listbox(
                            tag="ts_scene_obj_inscene_list",
                            label="En esta escena",
                            width=_LEFT_FORM_WIDTH,
                            num_items=5,
                            items=["(abre un proyecto)"],
                            enabled=False,
                        )
                        dpg.add_button(
                            tag="ts_btn_scene_obj_remove",
                            label="Quitar de la escena",
                            width=_LEFT_FORM_WIDTH,
                            callback=on_scene_remove_object,
                            enabled=False,
                        )
                        dpg.add_text(
                            "Capa de sprites en la vista previa (solo estudio; no afecta al firmware).",
                            wrap=_LEFT_TEXT_WRAP,
                        )
                        dpg.add_checkbox(
                            tag="ts_scene_sprites_show",
                            label="Mostrar sprites",
                            default_value=True,
                            callback=on_scene_sprites_preview_change,
                        )
                        dpg.add_slider_int(
                            tag="ts_scene_sprites_opacity",
                            label="Opacidad sprites (vista previa)",
                            min_value=0,
                            max_value=255,
                            default_value=255,
                            clamped=True,
                            width=_LEFT_FORM_WIDTH,
                            callback=on_scene_sprites_preview_change,
                            use_internal_label=False,
                        )
                        dpg.add_text(
                            f"Transparente: indice {TRANSPARENT_PALETTE_INDEX} (fijo en todas las paletas)",
                            wrap=_LEFT_TEXT_WRAP,
                        )
                        dpg.add_text(
                            "Fondo: 4 capas a pantalla completa (mismo tamano que la escena). "
                            "Solo la vista previa del estudio mezcla opacidad; el firmware usa un unico "
                            "indice cls() derivado de la capa visible superior.",
                            wrap=_LEFT_TEXT_WRAP,
                        )
                        dpg.add_combo(
                            tag="ts_bg_layer",
                            label="Capa fondo",
                            items=[str(i) for i in range(BACKGROUND_LAYER_COUNT)],
                            default_value="0",
                            width=_LEFT_FORM_WIDTH,
                            callback=on_bg_layer_slot_change,
                            enabled=False,
                            use_internal_label=False,
                        )
                        dpg.add_checkbox(
                            tag="ts_bg_layer_enabled",
                            label="Capa activa",
                            default_value=True,
                            callback=on_bg_layer_enabled_change,
                            enabled=False,
                        )
                        dpg.add_slider_int(
                            tag="ts_bg_layer_opacity",
                            label="Opacidad (vista previa)",
                            min_value=0,
                            max_value=255,
                            default_value=255,
                            clamped=True,
                            width=_LEFT_FORM_WIDTH,
                            callback=on_bg_layer_opacity_change,
                            enabled=False,
                        )
                        dpg.add_text(
                            "Color de la capa (indice en la paleta; cuadrado = muestra de esa capa)",
                            wrap=_LEFT_TEXT_WRAP,
                        )
                        with dpg.group(horizontal=True):
                            dpg.add_input_int(
                                tag="ts_bg_index",
                                label="Indice",
                                width=72,
                                default_value=0,
                                min_value=0,
                                max_value=255,
                                min_clamped=True,
                                max_clamped=True,
                                callback=on_bg_index_change,
                                use_internal_label=False,
                            )
                            with dpg.child_window(
                                tag="ts_color_swatch",
                                width=36,
                                height=24,
                                border=True,
                                no_scrollbar=True,
                            ):
                                dpg.add_spacer(width=2, height=2)
                            dpg.bind_item_theme("ts_color_swatch", "ts_swatch_theme")
                        dpg.add_text(
                            "Paleta: clic en un color copia #RRGGBB al portapapeles y fija indice de fondo",
                            wrap=_LEFT_TEXT_WRAP,
                        )
                        with dpg.child_window(
                            width=_LEFT_FORM_WIDTH,
                            height=52,
                            border=True,
                            horizontal_scrollbar=True,
                        ):
                            dpg.add_group(
                                tag="ts_palette_swatches_group",
                                horizontal=True,
                                horizontal_spacing=3,
                            )
                        dpg.add_button(
                            label="Recargar paleta en canvas",
                            width=_LEFT_FORM_WIDTH,
                            callback=on_reload_palette_click,
                        )
                        dpg.add_separator()
                        dpg.add_input_text(
                            tag="ts_log",
                            label="Registro",
                            multiline=True,
                            readonly=True,
                            width=_LEFT_FORM_WIDTH,
                            height=100,
                            default_value="",
                            use_internal_label=False,
                        )
        
                    with dpg.child_window(border=True):
                        with dpg.group(horizontal=True):
                            dpg.add_text(
                                f"Canvas · {_FB_W}×{_FB_H} (vista previa · rejilla cada {_GRID_STEP}px)"
                            )
                            dpg.add_checkbox(
                                tag="ts_show_grid",
                                label="Mostrar rejilla",
                                default_value=False,
                                callback=on_grid_toggle,
                            )
                            dpg.add_slider_int(
                                tag="ts_canvas_scale",
                                label="Escala",
                                min_value=1,
                                max_value=8,
                                default_value=_DEFAULT_CANVAS_SCALE,
                                format="x%d",
                                clamped=True,
                                width=160,
                                callback=on_canvas_scale_change,
                            )
                        dpg.add_text(
                            "Escala entera en CPU (pixeles nitidos). Con zoom alto o rejilla, "
                            "desplazate dentro del marco (barras horizontal y vertical).",
                            wrap=400,
                        )
                        with dpg.child_window(
                            tag="ts_canvas_viewport",
                            width=-1,
                            border=True,
                            horizontal_scrollbar=True,
                            height=_CANVAS_VIEWPORT_H,
                            autosize_x=False,
                            autosize_y=False,
                        ):
                            dpg.add_image(
                                _SCENE_CANVAS_TEX_TAG,
                                tag=_SCENE_CANVAS_IMG_TAG,
                                width=_scene_canvas_dw0,
                                height=_scene_canvas_dh0,
                                uv_min=(0.0, 0.0),
                                uv_max=_scene_preview_uv_max(
                                    _scene_canvas_dw0, _scene_canvas_dh0
                                ),
                            )
                            with dpg.item_handler_registry(tag="ts_canvas_click_reg"):
                                dpg.add_item_clicked_handler(callback=on_canvas_preview_click)
                            dpg.bind_item_handler_registry(
                                _SCENE_CANVAS_IMG_TAG, "ts_canvas_click_reg"
                            )
                        dpg.add_separator()
                        dpg.add_text(
                            "Scripts Lua: global = ENTRY en main.turtlecart; cada escena tiene su stem "
                            "(arriba). Los Lua de escena no se meten en main.turtlecart al exportar. "
                            "El desplegable elige que archivo editas.",
                            wrap=400,
                        )
                        dpg.add_combo(
                            tag="ts_lua_file_combo",
                            label="Archivo Lua",
                            width=400,
                            items=["(sin proyecto)"],
                            default_value="(sin proyecto)",
                            callback=on_lua_file_combo,
                            enabled=False,
                            use_internal_label=False,
                        )
                        dpg.add_input_text(
                            tag="ts_lua_source",
                            label="",
                            multiline=True,
                            width=-1,
                            height=220,
                            default_value=_DEFAULT_LUA,
                            tracked=True,
                        )

            with dpg.tab(label="Backgrounds"):
                dpg.add_text(
                    "Crea fondos en `backgrounds/<id>.json`. Cada fondo declara una paleta; en la pestaña "
                    "Editor solo podras asignar a la escena fondos cuya paleta coincida con la de esa escena.",
                    wrap=520,
                )
                dpg.add_spacer(height=6)
                dpg.add_input_text(
                    tag="ts_bg_tab_pal",
                    label="Paleta (ruta relativa al proyecto)",
                    width=480,
                    hint=DEFAULT_EXAMPLE_PALETTE_REL,
                    default_value=DEFAULT_EXAMPLE_PALETTE_REL,
                    enabled=False,
                    use_internal_label=False,
                )
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        tag="ts_btn_bg_tab_copy_scene_pal",
                        label="Copiar paleta de la escena activa",
                        width=240,
                        callback=on_bg_tab_copy_scene_pal,
                        enabled=False,
                    )
                    dpg.add_button(
                        tag="ts_btn_bg_tab_refresh",
                        label="Actualizar lista",
                        width=200,
                        callback=on_bg_tab_refresh_list,
                        enabled=False,
                    )
                dpg.add_text(
                    "Fondos con esta paleta (archivos en backgrounds/):",
                    wrap=520,
                )
                dpg.add_listbox(
                    tag="ts_bg_tab_list",
                    width=480,
                    num_items=8,
                    items=["(abre un proyecto)"],
                    enabled=False,
                )
                dpg.add_separator()
                dpg.add_text("Nuevo fondo (v0: relleno solido por indice de paleta)", wrap=520)
                dpg.add_input_text(
                    tag="ts_bg_new_id",
                    label="Id (nombre del .json)",
                    width=480,
                    hint="cielo_noche",
                    enabled=False,
                    use_internal_label=False,
                )
                dpg.add_input_int(
                    tag="ts_bg_new_idx",
                    label="Indice de color en la paleta",
                    width=200,
                    default_value=1,
                    min_value=0,
                    max_value=255,
                    min_clamped=True,
                    max_clamped=True,
                    enabled=False,
                    use_internal_label=False,
                )
                dpg.add_button(
                    tag="ts_btn_bg_tab_save",
                    label="Guardar fondo",
                    width=280,
                    callback=on_bg_tab_save_background,
                    enabled=False,
                )
                dpg.add_spacer(height=6)
                dpg.add_text(
                    f"Las cuatro capas de tinte y opacidad siguen en Editor; el recurso se dibuja debajo "
                    f"como base a pantalla completa ({_FB_W}×{_FB_H}). Mas adelante: editor de pixeles.",
                    wrap=520,
                    color=(180, 190, 210, 255),
                )

            with dpg.tab(label="Exportar"):
                dpg.add_text(
                    "El cuerpo del ENTRY es el del archivo indicado (memoria del editor si el proyecto "
                    "esta abierto). La paleta embebida usa la ruta Paleta (opc.) del Editor.",
                    wrap=520,
                )
                dpg.add_spacer(height=6)
                dpg.add_input_text(
                    tag="ts_out_path",
                    label="Salida .turtlecart",
                    width=480,
                    default_value="main.turtlecart",
                    use_internal_label=False,
                )
                dpg.add_input_text(
                    tag="ts_entry",
                    label="ENTRY (ruta en el cartucho)",
                    width=480,
                    default_value="scripts/global.lua",
                    hint="p. ej. scripts/global.lua",
                    use_internal_label=False,
                )
                dpg.add_checkbox(
                    tag="ts_write_lua_file",
                    label="Volcar ENTRY como .lua junto al cartucho (opcional, depuracion)",
                    default_value=False,
                    use_internal_label=False,
                )
                dpg.add_input_text(
                    tag="ts_export_initial_scene",
                    label="Escena inicial (cartucho)",
                    width=480,
                    default_value=DEFAULT_INITIAL_SCENE_ID,
                    hint="id de escena (p. ej. intro). El id 'main' esta reservado (cartucho principal main.turtlecart).",
                    use_internal_label=False,
                )
                dpg.add_text(
                    "Con proyecto abierto: solo se embebe studio/project_bundle.json. "
                    "El ENTRY (global) va en el bloque principal; los Lua de escena siguen en el proyecto "
                    "y pueden empaquetarse aparte (otros .turtlecart o archivos).",
                    wrap=520,
                )
                dpg.add_separator()
                dpg.add_button(
                    label="Exportar .turtlecart",
                    width=280,
                    callback=on_export,
                )

            with dpg.tab(label="Sprites"):
                dpg.add_text(
                    "Paleta del sprite: ruta relativa al proyecto (independiente de la escena / canvas). "
                    "El color es un indice en esa paleta. Mas adelante: al colocar en escena se validara "
                    "contra la paleta de la escena.",
                    wrap=520,
                )
                dpg.add_spacer(height=6)
                dpg.add_text("Archivos en objects/Sprites/:", color=(200, 220, 255, 255))
                dpg.add_listbox(
                    tag="ts_sprite_list",
                    width=420,
                    num_items=8,
                    items=["(abre un proyecto)"],
                    callback=on_sprite_list_pick,
                )
                dpg.add_text(
                    "Al elegir un archivo se carga en el formulario de abajo. Guardar sprite escribe el JSON.",
                    wrap=520,
                )
                dpg.add_separator()
                dpg.add_input_text(
                    tag="ts_sprite_palette_rel",
                    label="Paleta del sprite (relativa al proyecto)",
                    width=400,
                    hint="palettes/palette.txt",
                    default_value="",
                    enabled=False,
                )
                dpg.add_button(
                    tag="ts_btn_sprite_palette_reload",
                    label="Cargar paleta del sprite (actualiza colores)",
                    width=400,
                    callback=on_sprite_palette_reload_click,
                    enabled=False,
                )
                dpg.add_text(
                    "Paleta del sprite: clic en un color = pincel (copia #RRGGBB al portapapeles).",
                    color=(200, 220, 255, 255),
                )
                with dpg.child_window(
                    width=420,
                    height=52,
                    border=True,
                    horizontal_scrollbar=True,
                ):
                    dpg.add_group(
                        tag="ts_sprite_palette_swatches_group",
                        horizontal=True,
                        horizontal_spacing=3,
                    )
                dpg.add_text(
                    "Tamano en celdas de 4×4 px por defecto (ej. 4×4 celdas = 16×16 px). Tras cambiar W/H: Enter, "
                    "clic fuera o «Aplicar tamano».",
                    wrap=520,
                )
                with dpg.item_handler_registry(tag="ts_sprite_grid_step_handlers"):
                    dpg.add_item_deactivated_handler(
                        callback=on_sprite_editor_grid_step_change,
                    )
                with dpg.item_handler_registry(tag="ts_sprite_blocks_dim_handlers"):
                    dpg.add_item_deactivated_handler(callback=on_sprite_dimension_change)
                with dpg.group(horizontal=True):
                    dpg.add_input_int(
                        tag="ts_sprite_blocks_w",
                        label="Celdas W",
                        width=120,
                        default_value=1,
                        min_value=1,
                        max_value=32,
                        min_clamped=True,
                        max_clamped=True,
                        enabled=False,
                        callback=on_sprite_dimension_change,
                    )
                    dpg.add_input_int(
                        tag="ts_sprite_blocks_h",
                        label="Celdas H",
                        width=120,
                        default_value=1,
                        min_value=1,
                        max_value=32,
                        min_clamped=True,
                        max_clamped=True,
                        enabled=False,
                        callback=on_sprite_dimension_change,
                    )
                    dpg.add_button(
                        tag="ts_btn_sprite_apply_size",
                        label="Aplicar tamano",
                        width=120,
                        callback=on_sprite_apply_size,
                        enabled=False,
                    )
                dpg.bind_item_handler_registry("ts_sprite_blocks_w", "ts_sprite_blocks_dim_handlers")
                dpg.bind_item_handler_registry("ts_sprite_blocks_h", "ts_sprite_blocks_dim_handlers")
                with dpg.group(horizontal=True):
                    dpg.add_input_int(
                        tag="ts_sprite_origin_x",
                        label="Origen X",
                        width=120,
                        default_value=0,
                        min_value=0,
                        max_value=0,
                        min_clamped=True,
                        max_clamped=True,
                        enabled=False,
                        callback=on_sprite_origin_change,
                    )
                    dpg.add_input_int(
                        tag="ts_sprite_origin_y",
                        label="Origen Y",
                        width=120,
                        default_value=0,
                        min_value=0,
                        max_value=0,
                        min_clamped=True,
                        max_clamped=True,
                        enabled=False,
                        callback=on_sprite_origin_change,
                    )
                dpg.add_text(
                    "Origen en px (0,0)=esquina inferior izquierda del sprite. "
                    "En escena, (x,y) del objeto marca ese punto (cruz magenta en el editor).",
                    wrap=520,
                )
                with dpg.group(horizontal=True):
                    dpg.add_slider_int(
                        tag="ts_sprite_editor_scale",
                        label="Escala cuadricula (editor)",
                        min_value=1,
                        max_value=12,
                        default_value=_SPRITE_EDITOR_SCALE_DEFAULT,
                        clamped=True,
                        width=220,
                        callback=on_sprite_editor_scale_change,
                        enabled=False,
                    )
                    dpg.add_checkbox(
                        tag="ts_sprite_editor_show_grid",
                        label="Rejilla",
                        default_value=True,
                        callback=on_sprite_editor_grid_toggle,
                        enabled=False,
                    )
                    dpg.add_input_int(
                        tag="ts_sprite_editor_grid_step",
                        label="Paso rejilla (px)",
                        width=100,
                        default_value=_SPRITE_EDITOR_GRID_STEP_DEFAULT,
                        min_value=1,
                        max_value=_SPRITE_EDITOR_GRID_STEP_MAX,
                        step=4,
                        step_fast=8,
                        min_clamped=True,
                        max_clamped=True,
                        enabled=False,
                        callback=on_sprite_editor_grid_step_change,
                    )
                dpg.bind_item_handler_registry(
                    "ts_sprite_editor_grid_step", "ts_sprite_grid_step_handlers"
                )
                dpg.add_color_edit(
                    tag="ts_sprite_canvas_bg",
                    label="Fondo del lienzo (solo editor, no es paleta)",
                    default_value=_SPRITE_EDITOR_CANVAS_BG_DEFAULT,
                    no_alpha=True,
                    width=280,
                    enabled=False,
                    callback=on_sprite_canvas_bg_change,
                )
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        tag="ts_btn_sprite_fill_canvas",
                        label="Rellenar lienzo (indice actual)",
                        width=200,
                        callback=on_sprite_fill_canvas,
                        enabled=False,
                    )
                    dpg.add_button(
                        tag="ts_btn_sprite_clear_canvas",
                        label="Borrar todo",
                        width=120,
                        callback=on_sprite_clear_canvas,
                        enabled=False,
                    )
                dpg.add_text(
                    "Referencia (PNG/JPG): debajo del arte; «Convertir en sprite» cuantiza cada "
                    "pixel al color mas cercano de la paleta (alpha bajo → indice 31).",
                    wrap=520,
                    color=(200, 220, 255, 255),
                )
                dpg.add_text(
                    tag="ts_sprite_ref_path_label",
                    default_value="(sin referencia)",
                    wrap=520,
                )
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        tag="ts_btn_sprite_ref_import",
                        label="Importar referencia…",
                        width=160,
                        callback=on_sprite_ref_import_click,
                        enabled=False,
                    )
                    dpg.add_button(
                        tag="ts_btn_sprite_ref_clear",
                        label="Quitar referencia",
                        width=132,
                        callback=on_sprite_ref_clear_click,
                        enabled=False,
                    )
                    dpg.add_button(
                        tag="ts_btn_sprite_ref_convert",
                        label="Convertir en sprite",
                        width=140,
                        callback=on_sprite_ref_convert_click,
                        enabled=False,
                    )
                    dpg.add_checkbox(
                        tag="ts_sprite_ref_show",
                        label="Mostrar ref.",
                        default_value=True,
                        callback=on_sprite_editor_preview_change,
                        enabled=False,
                    )
                dpg.add_slider_float(
                    tag="ts_sprite_ref_opacity",
                    label="Opacidad referencia",
                    min_value=0.05,
                    max_value=1.0,
                    default_value=0.45,
                    clamped=True,
                    width=280,
                    callback=on_sprite_editor_preview_change,
                    enabled=False,
                )
                dpg.add_slider_float(
                    tag="ts_sprite_paint_opacity",
                    label="Opacidad capa pintada",
                    min_value=0.05,
                    max_value=1.0,
                    default_value=1.0,
                    clamped=True,
                    width=280,
                    callback=on_sprite_editor_preview_change,
                    enabled=False,
                )
                dpg.add_text(
                    tag="ts_sprite_edit_size_label",
                    default_value="Vista: (carga paleta y ajusta celdas)",
                    wrap=520,
                )
                dpg.add_text(
                    "Pincel = color en la paleta. Clic izquierdo o arrastrar: pintar. "
                    "Clic derecho o arrastrar: borrar (indice transparente 31). "
                    "«Guardar sprite» guarda los pixeles pintados.",
                    wrap=520,
                )
                with dpg.group(horizontal=True):
                    dpg.add_input_int(
                        tag="ts_sprite_frame_count",
                        label="Fotogramas",
                        width=120,
                        default_value=1,
                        min_value=1,
                        max_value=MAX_SPRITE_FRAMES,
                        min_clamped=True,
                        max_clamped=True,
                        enabled=False,
                        callback=on_sprite_frame_count_change,
                    )
                dpg.add_text(
                    "Pestañas F0, F1, …: un lienzo por fotograma. F0 → image; resto → frames[]. "
                    "La escena usa F0 por ahora.",
                    wrap=520,
                )
                dpg.add_group(tag="ts_sprite_frame_tabs_group", horizontal=True)
                with dpg.group(horizontal=True):
                    dpg.add_checkbox(
                        tag="ts_sprite_onion_prev_show",
                        label="Mostrar fotograma anterior detrás",
                        default_value=False,
                        callback=on_sprite_editor_preview_change,
                        enabled=False,
                    )
                    dpg.add_slider_float(
                        tag="ts_sprite_onion_prev_opacity",
                        label="Opacidad anterior",
                        min_value=0.05,
                        max_value=1.0,
                        default_value=0.35,
                        clamped=True,
                        width=180,
                        callback=on_sprite_editor_preview_change,
                        enabled=False,
                    )
                with dpg.group(horizontal=True):
                    dpg.add_checkbox(
                        tag="ts_sprite_onion_next_show",
                        label="Mostrar fotograma siguiente encima",
                        default_value=False,
                        callback=on_sprite_editor_preview_change,
                        enabled=False,
                    )
                    dpg.add_slider_float(
                        tag="ts_sprite_onion_next_opacity",
                        label="Opacidad siguiente",
                        min_value=0.05,
                        max_value=1.0,
                        default_value=0.35,
                        clamped=True,
                        width=180,
                        callback=on_sprite_editor_preview_change,
                        enabled=False,
                    )
                with dpg.item_handler_registry(tag="ts_sprite_edit_click_reg"):
                    dpg.add_item_clicked_handler(
                        button=dpg.mvMouseButton_Left,
                        callback=on_sprite_edit_canvas_click,
                    )
                    dpg.add_item_clicked_handler(
                        button=dpg.mvMouseButton_Right,
                        callback=on_sprite_edit_canvas_erase_click,
                    )
                with dpg.child_window(
                    tag="ts_sprite_edit_viewport",
                    border=True,
                    width=520,
                    height=320,
                    horizontal_scrollbar=True,
                ):
                    dpg.add_image(
                        _SPRITE_EDITOR_TEX_TAG,
                        tag=_SPRITE_EDITOR_IMG_TAG,
                        width=DEFAULT_CELL_PX * _SPRITE_EDITOR_SCALE_DEFAULT,
                        height=DEFAULT_CELL_PX * _SPRITE_EDITOR_SCALE_DEFAULT,
                        uv_min=(0.0, 0.0),
                        uv_max=_sprite_editor_uv_max(
                            DEFAULT_CELL_PX * _SPRITE_EDITOR_SCALE_DEFAULT,
                            DEFAULT_CELL_PX * _SPRITE_EDITOR_SCALE_DEFAULT,
                        ),
                    )
                dpg.bind_item_handler_registry(
                    _SPRITE_EDITOR_IMG_TAG, "ts_sprite_edit_click_reg"
                )
                dpg.add_text(
                    "Colores usados (clic = pincel). Intercambiar: sustituye un indice "
                    "por otro en todo el lienzo.",
                    color=(200, 220, 255, 255),
                    wrap=520,
                )
                with dpg.group(horizontal=True):
                    with dpg.child_window(
                        width=400,
                        height=40,
                        border=True,
                        horizontal_scrollbar=True,
                    ):
                        dpg.add_group(
                            tag="ts_sprite_used_swatches_group",
                            horizontal=True,
                            horizontal_spacing=3,
                        )
                    dpg.add_button(
                        tag="ts_btn_sprite_swap_color",
                        label="Intercambiar color",
                        width=116,
                        height=40,
                        callback=on_sprite_color_swap_click,
                        enabled=False,
                    )
                dpg.add_text(
                    tag="ts_sprite_swap_status",
                    default_value="",
                    wrap=520,
                    color=(255, 210, 120, 255),
                )
                dpg.add_input_text(
                    tag="ts_sprite_id",
                    label="ID del sprite (nombre del archivo sin .json)",
                    width=400,
                    hint="p. ej. bloque_rojo",
                    default_value="",
                    enabled=False,
                )
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        tag="ts_btn_sprite_create",
                        label="Crear JSON sprite",
                        width=132,
                        callback=on_sprite_create_empty,
                        enabled=False,
                    )
                    dpg.add_button(
                        tag="ts_btn_sprite_save",
                        label="Guardar sprite",
                        width=132,
                        callback=on_sprite_save,
                        enabled=False,
                    )
                    dpg.add_button(
                        tag="ts_btn_sprite_export_png",
                        label="Exportar PNG…",
                        width=132,
                        callback=on_sprite_export_png_click,
                        enabled=False,
                    )
                    dpg.add_button(
                        tag="ts_btn_sprite_refresh",
                        label="Actualizar lista",
                        width=132,
                        callback=on_sprite_refresh,
                        enabled=False,
                    )

            with dpg.tab(label="Objetos"):
                dpg.add_text(
                    "Definiciones en objects/Objects/: vincula un nombre de objeto con un sprite "
                    "(stem en objects/Sprites/*.json). Mas adelante: scripts, capas, etc.",
                    wrap=520,
                )
                dpg.add_spacer(height=6)
                dpg.add_text("Archivos en objects/Objects/:", color=(200, 220, 255, 255))
                dpg.add_listbox(
                    tag="ts_obj_list",
                    width=420,
                    num_items=8,
                    items=["(abre un proyecto)"],
                    callback=on_object_list_pick,
                )
                dpg.add_text(
                    "Elige un .json para cargar. El sprite debe existir antes (pestana Sprites).",
                    wrap=520,
                )
                dpg.add_separator()
                dpg.add_input_text(
                    tag="ts_obj_id",
                    label="ID del objeto (archivo sin .json)",
                    width=400,
                    hint="p. ej. jugador",
                    default_value="",
                    enabled=False,
                )
                dpg.add_input_text(
                    tag="ts_obj_name",
                    label="Nombre visible",
                    width=400,
                    hint="p. ej. Jugador 1",
                    default_value="",
                    enabled=False,
                )
                dpg.add_combo(
                    tag="ts_obj_sprite_combo",
                    label="Sprite por defecto (objects/Sprites/)",
                    width=400,
                    items=["(abre un proyecto)"],
                    default_value="(abre un proyecto)",
                    enabled=False,
                    callback=on_object_sprite_combo_change,
                )
                dpg.add_separator()
                dpg.add_text(
                    "Collision (v0): forma respecto al ancla (0,0)=origen del sprite; Y hacia arriba. "
                    "Contorno amarillo en vista escena.",
                    wrap=520,
                    color=(200, 220, 255, 255),
                )
                with dpg.group(horizontal=True):
                    dpg.add_combo(
                        tag="ts_obj_coll_shape",
                        label="Forma",
                        width=140,
                        items=list(_OBJ_COLL_SHAPE_LABELS),
                        default_value=_OBJ_COLL_SHAPE_LABELS[0],
                        callback=on_object_collision_shape_change,
                        enabled=False,
                    )
                    dpg.add_button(
                        tag="ts_btn_obj_coll_from_sprite",
                        label="Desde sprite",
                        width=100,
                        callback=on_object_collision_from_sprite,
                        enabled=False,
                    )
                with dpg.group(tag="ts_obj_coll_square_grp", horizontal=True):
                    dpg.add_input_int(
                        tag="ts_obj_coll_x0",
                        label="X0 (izq)",
                        width=88,
                        default_value=0,
                        min_value=-256,
                        max_value=256,
                        min_clamped=True,
                        max_clamped=True,
                        enabled=False,
                        callback=on_object_collision_preview_change,
                    )
                    dpg.add_input_int(
                        tag="ts_obj_coll_y0",
                        label="Y0 (abajo)",
                        width=88,
                        default_value=0,
                        min_value=-256,
                        max_value=256,
                        min_clamped=True,
                        max_clamped=True,
                        enabled=False,
                        callback=on_object_collision_preview_change,
                    )
                    dpg.add_input_int(
                        tag="ts_obj_coll_x1",
                        label="X1 (der)",
                        width=88,
                        default_value=0,
                        min_value=-256,
                        max_value=256,
                        min_clamped=True,
                        max_clamped=True,
                        enabled=False,
                        callback=on_object_collision_preview_change,
                    )
                    dpg.add_input_int(
                        tag="ts_obj_coll_y1",
                        label="Y1 (arriba)",
                        width=88,
                        default_value=0,
                        min_value=-256,
                        max_value=256,
                        min_clamped=True,
                        max_clamped=True,
                        enabled=False,
                        callback=on_object_collision_preview_change,
                    )
                with dpg.group(tag="ts_obj_coll_triangle_grp", horizontal=True, show=False):
                    for i, lbl in enumerate(("V0", "V1", "V2")):
                        dpg.add_input_int(
                            tag=f"ts_obj_coll_t{i}x",
                            label=f"{lbl} X",
                            width=72,
                            default_value=0,
                            min_value=-256,
                            max_value=256,
                            min_clamped=True,
                            max_clamped=True,
                            enabled=False,
                            callback=on_object_collision_preview_change,
                        )
                        dpg.add_input_int(
                            tag=f"ts_obj_coll_t{i}y",
                            label=f"{lbl} Y",
                            width=72,
                            default_value=0,
                            min_value=-256,
                            max_value=256,
                            min_clamped=True,
                            max_clamped=True,
                            enabled=False,
                            callback=on_object_collision_preview_change,
                        )
                with dpg.group(tag="ts_obj_coll_hexagon_grp", show=False):
                    with dpg.group(horizontal=True):
                        for i in range(3):
                            dpg.add_input_int(
                                tag=f"ts_obj_coll_h{i}x",
                                label=f"P{i} X",
                                width=72,
                                default_value=0,
                                min_value=-256,
                                max_value=256,
                                min_clamped=True,
                                max_clamped=True,
                                enabled=False,
                                callback=on_object_collision_preview_change,
                            )
                            dpg.add_input_int(
                                tag=f"ts_obj_coll_h{i}y",
                                label=f"P{i} Y",
                                width=72,
                                default_value=0,
                                min_value=-256,
                                max_value=256,
                                min_clamped=True,
                                max_clamped=True,
                                enabled=False,
                                callback=on_object_collision_preview_change,
                            )
                    with dpg.group(horizontal=True):
                        for i in range(3, 6):
                            dpg.add_input_int(
                                tag=f"ts_obj_coll_h{i}x",
                                label=f"P{i} X",
                                width=72,
                                default_value=0,
                                min_value=-256,
                                max_value=256,
                                min_clamped=True,
                                max_clamped=True,
                                enabled=False,
                                callback=on_object_collision_preview_change,
                            )
                            dpg.add_input_int(
                                tag=f"ts_obj_coll_h{i}y",
                                label=f"P{i} Y",
                                width=72,
                                default_value=0,
                                min_value=-256,
                                max_value=256,
                                min_clamped=True,
                                max_clamped=True,
                                enabled=False,
                                callback=on_object_collision_preview_change,
                            )
                dpg.add_text(
                    tag="ts_obj_coll_preview_label",
                    default_value="Vista collision: (carga un objeto)",
                    wrap=520,
                    color=(200, 220, 255, 255),
                )
                with dpg.child_window(
                    tag="ts_obj_coll_preview_viewport",
                    border=True,
                    width=280,
                    height=200,
                    horizontal_scrollbar=True,
                ):
                    dpg.add_image(
                        _OBJ_COLL_PREVIEW_TEX_TAG,
                        tag=_OBJ_COLL_PREVIEW_IMG_TAG,
                        width=64,
                        height=64,
                        uv_min=(0.0, 0.0),
                        uv_max=(0.5, 0.5),
                    )
                dpg.add_separator()
                dpg.add_text(
                    "Animaciones: nombre logico → otro sprite (p. ej. walk, jump). "
                    "Se guardan en el JSON del objeto; «Guardar objeto» para persistir.",
                    wrap=520,
                    color=(200, 220, 255, 255),
                )
                with dpg.group(horizontal=True):
                    dpg.add_input_text(
                        tag="ts_obj_anim_name",
                        label="Nombre animacion",
                        width=180,
                        hint="walk",
                        default_value="",
                        enabled=False,
                    )
                    dpg.add_combo(
                        tag="ts_obj_anim_sprite_combo",
                        label="Sprite",
                        width=220,
                        items=["(abre un proyecto)"],
                        default_value="(abre un proyecto)",
                        enabled=False,
                    )
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        tag="ts_btn_obj_anim_add",
                        label="Añadir animacion",
                        width=140,
                        callback=on_object_anim_add,
                        enabled=False,
                    )
                    dpg.add_button(
                        tag="ts_btn_obj_anim_remove",
                        label="Quitar animacion",
                        width=140,
                        callback=on_object_anim_remove,
                        enabled=False,
                    )
                dpg.add_listbox(
                    tag="ts_obj_anim_list",
                    label="Animaciones del objeto",
                    width=420,
                    num_items=6,
                    items=["(sin animaciones)"],
                    callback=on_object_anim_list_pick,
                )
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        tag="ts_btn_obj_create",
                        label="Crear JSON objeto",
                        width=132,
                        callback=on_object_create,
                        enabled=False,
                    )
                    dpg.add_button(
                        tag="ts_btn_obj_save",
                        label="Guardar objeto",
                        width=132,
                        callback=on_object_save,
                        enabled=False,
                    )
                    dpg.add_button(
                        tag="ts_btn_obj_refresh",
                        label="Actualizar lista",
                        width=132,
                        callback=on_object_refresh,
                        enabled=False,
                    )

    with dpg.handler_registry(tag="ts_sprite_paint_drag_reg"):
        dpg.add_mouse_drag_handler(
            button=dpg.mvMouseButton_Left,
            callback=on_sprite_edit_paint_drag,
        )
        dpg.add_mouse_drag_handler(
            button=dpg.mvMouseButton_Right,
            callback=on_sprite_edit_erase_drag,
        )

    with dpg.file_dialog(
        directory_selector=False,
        show=False,
        callback=on_sprite_ref_file_picked,
        tag="ts_sprite_ref_file_dialog",
        width=700,
        height=400,
        modal=True,
    ):
        dpg.add_file_extension(".png", color=(150, 255, 150, 255))
        dpg.add_file_extension(".jpg")
        dpg.add_file_extension(".jpeg")
        dpg.add_file_extension(".webp")
        dpg.add_file_extension(".bmp")

    with dpg.file_dialog(
        directory_selector=True,
        show=False,
        callback=on_sprite_export_dir_picked,
        tag="ts_sprite_export_dir_dialog",
        width=700,
        height=400,
        modal=True,
    ):
        pass

    _rebuild_sprite_frame_tabs(select_index=0)

    dpg.create_viewport(
        title="TurtleStudio",
        width=1080,
        height=760,
    )
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("ts_startup", True)
    dpg.start_dearpygui()
    dpg.destroy_context()
    return 0
