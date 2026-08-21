"""Capas de tilemap en escena (hasta 4); rejilla alineada a `tile_px` del proyecto."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from turtlestudio.palette_policy import TRANSPARENT_PALETTE_INDEX, resolve_palette_color
from turtlestudio.project import SCENE_PIXEL_H, SCENE_PIXEL_W, scene_world_pixel_size
from turtlestudio.sprites import normalize_palette_rel, palette_paths_equivalent
from turtlestudio.tiles import (
    list_tileset_json_stems,
    normalize_tile_px,
    parse_tileset_all_tiles,
    read_tileset_file,
)

TILE_LAYER_COUNT = 4
EMPTY_TILE_CELL = TRANSPARENT_PALETTE_INDEX


@dataclass(frozen=True)
class SceneTileLayer:
    enabled: bool
    tileset: str
    cells: tuple[tuple[int, ...], ...]


def scene_tile_grid_dimensions(
    tile_px: int,
    *,
    world_w: int = SCENE_PIXEL_W,
    world_h: int = SCENE_PIXEL_H,
) -> tuple[int, int]:
    """(columnas, filas); fila 0 = arriba de la escena."""
    px = normalize_tile_px(tile_px)
    ww = max(1, int(world_w))
    wh = max(1, int(world_h))
    return (max(1, ww // px), max(1, wh // px))


def empty_tile_cells(
    tile_px: int,
    *,
    fill: int = EMPTY_TILE_CELL,
    world_w: int = SCENE_PIXEL_W,
    world_h: int = SCENE_PIXEL_H,
) -> list[list[int]]:
    cols, rows = scene_tile_grid_dimensions(tile_px, world_w=world_w, world_h=world_h)
    fi = max(0, min(255, int(fill)))
    return [[fi for _ in range(cols)] for _ in range(rows)]


def _normalize_cells_matrix(
    raw: Any,
    *,
    cols: int,
    rows: int,
    fill: int = EMPTY_TILE_CELL,
) -> list[list[int]]:
    fi = max(0, min(255, int(fill)))
    out: list[list[int]] = [[fi for _ in range(cols)] for _ in range(rows)]
    if not isinstance(raw, list):
        return out
    for gy in range(min(rows, len(raw))):
        row = raw[gy]
        if not isinstance(row, list):
            continue
        for gx in range(min(cols, len(row))):
            try:
                v = int(row[gx])
            except (TypeError, ValueError):
                v = fi
            out[gy][gx] = max(0, min(255, v))
    return out


def parse_tile_layers(
    raw: Any,
    *,
    tile_px: int,
    world_w: int = SCENE_PIXEL_W,
    world_h: int = SCENE_PIXEL_H,
) -> tuple[SceneTileLayer, ...]:
    cols, rows = scene_tile_grid_dimensions(tile_px, world_w=world_w, world_h=world_h)
    if not isinstance(raw, list):
        return default_tile_layers(tile_px)
    out: list[SceneTileLayer] = []
    for i in range(TILE_LAYER_COUNT):
        if i < len(raw) and isinstance(raw[i], dict):
            d = raw[i]
            en = bool(d.get("enabled"))
            ts = str(d.get("tileset", d.get("tileset_id", ""))).strip()
            cells = _normalize_cells_matrix(d.get("cells"), cols=cols, rows=rows)
            out.append(
                SceneTileLayer(
                    enabled=en,
                    tileset=ts,
                    cells=tuple(tuple(r) for r in cells),
                )
            )
        else:
            empty = empty_tile_cells(tile_px)
            out.append(
                SceneTileLayer(
                    False,
                    "",
                    tuple(tuple(r) for r in empty),
                )
            )
    return tuple(out)


def normalize_collision_tile_layer(raw: Any) -> int:
    """spec/scene-v0.md 'Capa de colision': indice 0..3 de la unica capa de tiles que
    bloquea actores (las otras 3 son decorativas). Sin dato / invalido -> 0."""
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return 0
    return max(0, min(TILE_LAYER_COUNT - 1, v))


def default_tile_layers(
    tile_px: int,
    *,
    world_w: int = SCENE_PIXEL_W,
    world_h: int = SCENE_PIXEL_H,
) -> tuple[SceneTileLayer, ...]:
    empty = empty_tile_cells(tile_px, world_w=world_w, world_h=world_h)
    imm = tuple(tuple(r) for r in empty)
    return tuple(SceneTileLayer(False, "", imm) for _ in range(TILE_LAYER_COUNT))


def tile_layers_to_json_list(layers: tuple[SceneTileLayer, ...]) -> list[dict[str, Any]]:
    return [
        {
            "enabled": ly.enabled,
            "tileset": ly.tileset,
            "cells": [list(r) for r in ly.cells],
        }
        for ly in layers
    ]


def resize_tile_layer_cells(
    cells: list[list[int]],
    *,
    old_tile_px: int,
    new_tile_px: int,
    world_w: int = SCENE_PIXEL_W,
    world_h: int = SCENE_PIXEL_H,
) -> list[list[int]]:
    if old_tile_px == new_tile_px:
        return cells
    oc, orow = scene_tile_grid_dimensions(
        old_tile_px, world_w=world_w, world_h=world_h
    )
    nc, nrow = scene_tile_grid_dimensions(
        new_tile_px, world_w=world_w, world_h=world_h
    )
    out = empty_tile_cells(new_tile_px, world_w=world_w, world_h=world_h)
    for gy in range(min(orow, nrow)):
        for gx in range(min(oc, nc)):
            if gy < len(cells) and gx < len(cells[gy]):
                out[gy][gx] = cells[gy][gx]
    return out


def scene_y_to_framebuffer_y(sy: int, *, fb_h: int = SCENE_PIXEL_H) -> int:
    """Coordenada escena (origen abajo-izquierda) → fila framebuffer (0 arriba)."""
    return (fb_h - 1) - int(sy)


def scene_cell_framebuffer_rect(
    gx: int,
    gy: int,
    *,
    tile_px: int,
    fb_w: int = SCENE_PIXEL_W,
    fb_h: int = SCENE_PIXEL_H,
) -> tuple[int, int, int, int]:
    """
    Rectangulo inclusivo en framebuffer para celda (gx, gy).
    gy=0 es la fila superior de la escena. Devuelve (x0, y0_fb, x1, y1_fb).
    """
    cols, rows = scene_tile_grid_dimensions(tile_px, world_w=fb_w, world_h=fb_h)
    px = normalize_tile_px(tile_px)
    sx0 = gx * px
    sx1 = min(fb_w - 1, sx0 + px - 1)
    sy_bottom = (rows - 1 - gy) * px
    sy_top = min(fb_h - 1, sy_bottom + px - 1)
    y1_fb = scene_y_to_framebuffer_y(sy_bottom, fb_h=fb_h)
    y0_fb = scene_y_to_framebuffer_y(sy_top, fb_h=fb_h)
    return sx0, y0_fb, sx1, y1_fb


def _blend_rgba_pixel_inplace(
    rgba: list[float],
    i: int,
    cr: float,
    cg: float,
    cb: float,
    ca: float,
) -> None:
    a = max(0.0, min(1.0, ca))
    inv = 1.0 - a
    rgba[i] = rgba[i] * inv + cr * a
    rgba[i + 1] = rgba[i + 1] * inv + cg * a
    rgba[i + 2] = rgba[i + 2] * inv + cb * a
    rgba[i + 3] = max(rgba[i + 3], a)


def draw_scene_step_bounds_on_rgba(
    rgba: list[float],
    fw: int,
    fh: int,
    *,
    step_w: int = SCENE_PIXEL_W,
    step_h: int = SCENE_PIXEL_H,
    line_rgba: tuple[float, float, float, float] = (0.42, 0.48, 0.62, 0.9),
) -> None:
    """Lineas cada viewport (paso) cuando el mundo es mas grande que una pantalla."""
    if fw <= step_w and fh <= step_h:
        return
    if fw <= 0 or fh <= 0 or len(rgba) < fw * fh * 4:
        return
    lr, lg, lb, la = line_rgba
    sw = max(1, int(step_w))
    sh = max(1, int(step_h))
    for sx in range(sw, fw, sw):
        xi = min(fw - 1, sx)
        for y_fb in range(fh):
            _blend_rgba_pixel_inplace(rgba, (y_fb * fw + xi) * 4, lr, lg, lb, la)
    for sy in range(sh, fh, sh):
        y_fb = scene_y_to_framebuffer_y(sy, fb_h=fh)
        if 0 <= y_fb < fh:
            row_base = y_fb * fw * 4
            for x in range(fw):
                _blend_rgba_pixel_inplace(rgba, row_base + x * 4, lr, lg, lb, la)


def draw_scene_tile_hover_on_rgba(
    rgba: list[float],
    fw: int,
    fh: int,
    tile_px: int,
    hover_cell: tuple[int, int],
    *,
    hover_rgba: tuple[float, float, float, float] = (1.0, 0.9, 0.2, 0.88),
) -> None:
    """Solo resalta la celda bajo el cursor (barato en mundos grandes)."""
    if fw <= 0 or fh <= 0 or len(rgba) < fw * fh * 4:
        return
    gx, gy = hover_cell
    x0, y0_fb, x1, y1_fb = scene_cell_framebuffer_rect(
        gx, gy, tile_px=tile_px, fb_w=fw, fb_h=fh
    )
    sr, sg, sb, sa = hover_rgba
    border = 2
    for t in range(border):
        for x in range(x0, x1 + 1):
            if 0 <= y0_fb + t < fh:
                _blend_rgba_pixel_inplace(
                    rgba, ((y0_fb + t) * fw + x) * 4, sr, sg, sb, sa
                )
            yb = y1_fb - t
            if 0 <= yb < fh:
                _blend_rgba_pixel_inplace(rgba, (yb * fw + x) * 4, sr, sg, sb, sa)
        for y_fb in range(y0_fb, y1_fb + 1):
            if 0 <= x0 + t < fw:
                _blend_rgba_pixel_inplace(
                    rgba, (y_fb * fw + (x0 + t)) * 4, sr, sg, sb, sa
                )
            xb = x1 - t
            if 0 <= xb < fw:
                _blend_rgba_pixel_inplace(rgba, (y_fb * fw + xb) * 4, sr, sg, sb, sa)


def draw_scene_tile_grid_on_rgba(
    rgba: list[float],
    fw: int,
    fh: int,
    tile_px: int,
    *,
    hover_cell: tuple[int, int] | None = None,
    grid_rgba: tuple[float, float, float, float] = (0.75, 0.82, 1.0, 0.72),
    hover_rgba: tuple[float, float, float, float] = (1.0, 0.9, 0.2, 0.88),
    full_grid: bool = True,
) -> None:
    """
    Rejilla alineada al tilemap de escena (origen abajo-izquierda, igual que pintar tiles).
    Con `full_grid=False` solo dibuja el hover (para mundos > 1 pantalla).
    """
    if fw <= 0 or fh <= 0 or len(rgba) < fw * fh * 4:
        return
    if hover_cell is not None and not full_grid:
        draw_scene_tile_hover_on_rgba(
            rgba, fw, fh, tile_px, hover_cell, hover_rgba=hover_rgba
        )
        return
    px = normalize_tile_px(tile_px)
    cols, rows = scene_tile_grid_dimensions(px, world_w=fw, world_h=fh)
    gr, gg, gb, ga = grid_rgba

    if full_grid:
        for gx in range(cols + 1):
            xi = min(fw - 1, gx * px) if fw > 0 else 0
            for y_fb in range(fh):
                _blend_rgba_pixel_inplace(rgba, (y_fb * fw + xi) * 4, gr, gg, gb, ga)

        for gy_row in range(rows + 1):
            sy = gy_row * px
            if sy >= fh:
                break
            y_fb = scene_y_to_framebuffer_y(sy, fb_h=fh)
            if 0 <= y_fb < fh:
                row_base = y_fb * fw * 4
                x_end = min(fw, cols * px)
                for x in range(x_end):
                    _blend_rgba_pixel_inplace(rgba, row_base + x * 4, gr, gg, gb, ga)

    if hover_cell is not None:
        draw_scene_tile_hover_on_rgba(
            rgba, fw, fh, tile_px, hover_cell, hover_rgba=hover_rgba
        )


def scene_coords_to_cell(
    sx: int,
    sy: int,
    *,
    tile_px: int,
    world_w: int = SCENE_PIXEL_W,
    world_h: int = SCENE_PIXEL_H,
) -> tuple[int, int] | None:
    cols, rows = scene_tile_grid_dimensions(
        tile_px, world_w=world_w, world_h=world_h
    )
    px = normalize_tile_px(tile_px)
    ww = max(1, int(world_w))
    wh = max(1, int(world_h))
    if sx < 0 or sy < 0 or sx >= ww or sy >= wh:
        return None
    gx = sx // px
    gy_bottom = sy // px
    gy = (rows - 1) - gy_bottom
    if gx < 0 or gy < 0 or gx >= cols or gy >= rows:
        return None
    return gx, gy


def set_cell_index(
    cells: list[list[int]],
    gx: int,
    gy: int,
    tile_index: int,
) -> None:
    if 0 <= gy < len(cells) and 0 <= gx < len(cells[gy]):
        cells[gy][gx] = max(0, min(255, int(tile_index)))


def get_cell_index(cells: list[list[int]], gx: int, gy: int) -> int | None:
    """Eyedropper support: the raw tile index at (gx, gy), or None if out of bounds."""
    if 0 <= gy < len(cells) and 0 <= gx < len(cells[gy]):
        return int(cells[gy][gx])
    return None


def flood_fill_cell_index(
    cells: list[list[int]],
    gx: int,
    gy: int,
    tile_index: int,
) -> None:
    """Paint-bucket tool: 4-connected flood fill from (gx, gy), replacing every cell
    reachable through cells sharing the origin's tile index with `tile_index`."""
    if not (0 <= gy < len(cells) and 0 <= gx < len(cells[gy])):
        return
    new_index = max(0, min(255, int(tile_index)))
    target = cells[gy][gx]
    if target == new_index:
        return
    stack = [(gx, gy)]
    while stack:
        x, y = stack.pop()
        if not (0 <= y < len(cells) and 0 <= x < len(cells[y])):
            continue
        if cells[y][x] != target:
            continue
        cells[y][x] = new_index
        stack.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))


def list_tileset_stems_for_palette(
    project_root: Any,
    scene_palette_rel: str,
) -> list[str]:
    from pathlib import Path

    root = Path(project_root)
    if not str(scene_palette_rel).strip():
        return []
    sp = normalize_palette_rel(scene_palette_rel)
    out: list[str] = []
    for stem in list_tileset_json_stems(root):
        try:
            data = read_tileset_file(root, stem)
        except ValueError:
            continue
        opal = str(data.get("palette", "")).strip()
        if opal and palette_paths_equivalent(opal, sp):
            out.append(stem)
    return sorted(out)


def validate_tileset_stem_for_scene(
    project_root: Any,
    stem: str,
    *,
    scene_palette_rel: str,
) -> str:
    from pathlib import Path

    s = str(stem).strip()
    if not s:
        return ""
    root = Path(project_root)
    data = read_tileset_file(root, s)
    opal = str(data.get("palette", "")).strip()
    if not opal:
        raise ValueError(f"Tileset {s!r}: falta campo palette.")
    if not palette_paths_equivalent(opal, normalize_palette_rel(scene_palette_rel)):
        raise ValueError(
            f"Tileset {s!r}: la paleta no coincide con la de la escena ({scene_palette_rel!r})."
        )
    return s


def validate_tile_layers_for_save(
    project_root: Any,
    raw_layers: Any,
    *,
    scene_palette_rel: str,
    tile_px: int,
    world_w: int = SCENE_PIXEL_W,
    world_h: int = SCENE_PIXEL_H,
) -> list[dict[str, Any]]:
    layers = parse_tile_layers(
        raw_layers, tile_px=tile_px, world_w=world_w, world_h=world_h
    )
    out_layers: list[SceneTileLayer] = []
    for ly in layers:
        ts = ly.tileset.strip()
        if ts:
            ts = validate_tileset_stem_for_scene(
                project_root, ts, scene_palette_rel=scene_palette_rel
            )
        out_layers.append(
            SceneTileLayer(ly.enabled, ts, ly.cells)
        )
    return tile_layers_to_json_list(tuple(out_layers))


def _blit_tile_at_scene_bottom_left(
    rgba: list[float],
    fw: int,
    fh: int,
    sx0: int,
    sy0: int,
    tile_rows: list[list[int]],
    tile_px: int,
    rgbs: list[tuple[float, float, float]],
) -> None:
    px = max(1, int(tile_px))
    for ly_top in range(min(px, len(tile_rows))):
        row = tile_rows[ly_top]
        if not isinstance(row, list):
            continue
        for lx in range(min(px, len(row))):
            try:
                idx = int(row[lx])
            except (TypeError, ValueError):
                continue
            if idx == TRANSPARENT_PALETTE_INDEX:
                continue
            col = resolve_palette_color(idx, rgbs)
            if col is None:
                continue
            scene_y = sy0 + (px - 1 - ly_top)
            scene_x = sx0 + lx
            if scene_x < 0 or scene_x >= fw or scene_y < 0 or scene_y >= fh:
                continue
            ly_fb = (fh - 1) - scene_y
            i = (ly_fb * fw + scene_x) * 4
            r, g, b = col
            rgba[i] = r
            rgba[i + 1] = g
            rgba[i + 2] = b
            rgba[i + 3] = 1.0


def paint_tile_layers_on_rgba(
    rgba: list[float],
    fw: int,
    fh: int,
    layers: tuple[SceneTileLayer, ...],
    project_root: Any,
    rgbs: list[tuple[float, float, float]],
    *,
    tile_px: int,
    tile_cache: dict[str, tuple[int, list[list[list[int]]]]] | None = None,
) -> None:
    """Pinta capas 0..3 de abajo a arriba sobre `rgba` (in-place)."""
    from pathlib import Path

    root = Path(project_root)
    px = normalize_tile_px(tile_px)
    cols, rows = scene_tile_grid_dimensions(px, world_w=fw, world_h=fh)
    cache = tile_cache if tile_cache is not None else {}

    for ly in layers:
        if not ly.enabled:
            continue
        stem = ly.tileset.strip()
        if not stem:
            continue
        cached = cache.get(stem)
        if cached is None:
            try:
                data = read_tileset_file(root, stem)
            except ValueError:
                continue
            tpx = int(data.get("tile_px", px))
            tiles = parse_tileset_all_tiles(data, fill_index=1)
            cached = (tpx, tiles)
            cache[stem] = cached
        tpx, tiles = cached
        if tpx != px:
            continue
        if len(ly.cells) != rows:
            continue
        for gy in range(rows):
            row_cells = ly.cells[gy]
            if len(row_cells) < cols:
                continue
            sy0 = (rows - 1 - gy) * px
            for gx in range(cols):
                try:
                    ti = int(row_cells[gx])
                except (TypeError, ValueError):
                    ti = EMPTY_TILE_CELL
                if ti == TRANSPARENT_PALETTE_INDEX or ti < 0:
                    continue
                if ti >= len(tiles):
                    continue
                tile_rows = tiles[ti]
                if not isinstance(tile_rows, list):
                    continue
                _blit_tile_at_scene_bottom_left(
                    rgba,
                    fw,
                    fh,
                    gx * px,
                    sy0,
                    tile_rows,
                    px,
                    rgbs,
                )
