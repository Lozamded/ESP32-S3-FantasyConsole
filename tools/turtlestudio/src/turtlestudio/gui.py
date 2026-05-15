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
    list_object_ids_for_scene_palette,
    list_object_json_stems,
    read_object_file,
    save_object_json,
    write_object_json,
)
from turtlestudio.sprites import (
    list_sprite_json_stems,
    normalize_palette_rel,
    normalize_palette_rows,
    parse_palette_rows_image,
    read_sprite_file,
    save_indexed_pixels_sprite_json,
    solid_fill_indices,
    sprite_is_indexed_pixels,
    sprite_pixel_dimensions,
)

# Resolucion logica de consola (spec scene-v0; textura = raster Y hacia abajo)
_FB_W = SCENE_PIXEL_W
_FB_H = SCENE_PIXEL_H
_DEFAULT_CANVAS_SCALE = 2
# Alto del panel de vista previa (píxeles de pantalla); el zoom grande usa scroll dentro.
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
        ci = max(0, min(n - 1, ly.color_index))
        r, g, b = rgbs[ci]
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
    ci = max(0, min(n - 1, idx))
    r, g, b = rgbs[ci]
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
    """Rejilla con paso en px: 1 o multiplo de 4."""
    st = _normalize_sprite_grid_step(grid_step)
    blend = 0.35 if st == 1 else 0.45
    return _apply_grid_overlay_to_rgba(base_rgba, width, height, step=st, blend=blend)


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
            rgba[i] = r
            rgba[i + 1] = g
            rgba[i + 2] = b
            rgba[i + 3] = 1.0


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
_SPRITE_EDITOR_GRID_STEP_DEFAULT = 8
_SPRITE_EDITOR_GRID_STEP_MAX = 64


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


def _sprite_editor_uv_max(pw: int, ph: int) -> tuple[float, float]:
    mx = float(_SPRITE_EDITOR_TEX_MAX)
    return (max(0.0, min(1.0, pw / mx)), max(0.0, min(1.0, ph / mx)))


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


def _blit_indexed_rect_scene(
    rgba: list[float],
    fw: int,
    fh: int,
    sx0: int,
    sy_bottom: int,
    rows: list[list[int]],
    rgbs: list[tuple[float, float, float]],
) -> None:
    """Ancla igual que rectangulo solido: (sx0, sy_bottom) esquina inferior izquierda del bbox."""
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
            ci = max(0, min(n - 1, idx))
            r, g, b = rgbs[ci]
            ty = (fh - 1) - scene_y
            tx = scene_x
            i = (ty * fw + tx) * 4
            rgba[i] = r
            rgba[i + 1] = g
            rgba[i + 2] = b
            rgba[i + 3] = 1.0


def _sprite_rows_to_rgba_float01(
    rows: list[list[int]],
    rgbs: list[tuple[float, float, float]],
) -> list[float]:
    """Textura DPG: fila 0 arriba."""
    ph = len(rows)
    pw = len(rows[0]) if rows else 0
    n = max(1, len(rgbs))
    out: list[float] = []
    for py in range(ph):
        row = rows[py] if py < len(rows) else []
        for lx in range(pw):
            try:
                idx = int(row[lx]) if lx < len(row) else 0
            except (TypeError, ValueError):
                idx = 0
            ci = max(0, min(n - 1, idx))
            r, g, b = rgbs[ci]
            out.extend((r, g, b, 1.0))
    return out


def _resolve_object_sprite_preview(
    project_root: Path,
    object_id: str,
) -> dict[str, Any]:
    """Vista previa en escena: solido o indexed_pixels + paleta del sprite."""
    oid = object_id.strip()
    fb = {"mode": "solid", "pw": 8, "ph": 8, "rgb": (0.42, 0.42, 0.48)}
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
    if sprite_is_indexed_pixels(sd):
        rows = parse_palette_rows_image(sd)
        if rows:
            return {"mode": "indexed", "pw": pw, "ph": ph, "rows": rows, "rgbs": rgbs}
    pi = 0
    render = sd.get("render")
    if isinstance(render, dict):
        try:
            pi = int(render.get("palette_index", 0))
        except (TypeError, ValueError):
            pi = 0
    pi = max(0, min(len(rgbs) - 1, pi))
    r, g, b = rgbs[pi]
    return {"mode": "solid", "pw": pw, "ph": ph, "rgb": (r, g, b)}


def _paint_scene_objects_preview(
    rgba: list[float],
    fw: int,
    fh: int,
    project_root: Path,
    placements: list[dict[str, Any]],
    *,
    cross_rgb: tuple[float, float, float],
) -> None:
    """Compone sprites (solido o pixeles indexados) y una cruz en el ancla por instancia."""
    cr, cg, cb = cross_rgb
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
        if info.get("mode") == "indexed":
            _blit_indexed_rect_scene(
                rgba,
                fw,
                fh,
                sx,
                sy,
                info["rows"],
                info["rgbs"],
            )
        else:
            pr, pg, pb = info["rgb"]
            _blit_solid_rect_scene(
                rgba, fw, fh, sx, sy, info["pw"], info["ph"], pr, pg, pb
            )
        _draw_anchor_cross_rgba(rgba, fw, fh, sx, sy, cr, cg, cb)


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
        "sprite_edit_cell_px": 8,
        "sprite_ui_silent": False,
        "sprite_brush_index": 1,
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
        return max(1, min(8, v))

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
        max_i = max(0, n - 1)
        if dpg.does_item_exist("ts_bg_index"):
            dpg.configure_item("ts_bg_index", min_value=0, max_value=max_i)
            try:
                cur_i = int(dpg.get_value("ts_bg_index"))
            except (TypeError, ValueError):
                cur_i = 0
            dpg.set_value("ts_bg_index", max(0, min(cur_i, max_i)))
        _rebuild_palette_swatches()
        return msg + f"Paleta canvas: {len(hexes)} colores (indices 0..{len(hexes) - 1}).\n"

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
        hexes = state.get("hexes")
        if not isinstance(hexes, list) or idx < 0 or idx >= len(hexes):
            return
        _clipboard_push_hex(hexes, idx)
        dpg.set_value("ts_bg_index", idx)
        if isinstance(state.get("project_root"), Path):
            _commit_background_for_active_scene()
        refresh_canvas_texture()

    def _on_sprite_palette_swatch_click(
        sender: object, app_data: object, user_data: object | None = None,
    ) -> None:
        idx = user_data if user_data is not None else dpg.get_item_user_data(sender)
        idx = int(idx)
        hexes = state.get("sprite_palette_hexes")
        if not isinstance(hexes, list) or idx < 0 or idx >= len(hexes):
            return
        _clipboard_push_hex(hexes, idx)
        _set_sprite_brush_index(idx)

    def _rebuild_palette_swatches() -> None:
        gid = "ts_palette_swatches_group"
        if not dpg.does_item_exist(gid):
            return
        dpg.delete_item(gid, children_only=True)
        rgbs = state.get("rgb")
        if not isinstance(rgbs, list) or not rgbs:
            dpg.add_text("(sin paleta cargada)", parent=gid, wrap=_LEFT_TEXT_WRAP)
            return
        sw = 16
        for i, rgb in enumerate(rgbs):
            r8 = max(0, min(255, int(round(rgb[0] * 255.0))))
            g8 = max(0, min(255, int(round(rgb[1] * 255.0))))
            b8 = max(0, min(255, int(round(rgb[2] * 255.0))))
            dpg.add_color_button(
                default_value=[r8, g8, b8, 255],
                width=sw,
                height=sw,
                enabled=True,
                parent=gid,
                label="",
                use_internal_label=True,
                user_data=i,
                callback=_on_canvas_palette_swatch_click,
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
        sw = 16
        for i, rgb in enumerate(rgbs):
            r8 = max(0, min(255, int(round(rgb[0] * 255.0))))
            g8 = max(0, min(255, int(round(rgb[1] * 255.0))))
            b8 = max(0, min(255, int(round(rgb[2] * 255.0))))
            dpg.add_color_button(
                default_value=[r8, g8, b8, 255],
                width=sw,
                height=sw,
                enabled=True,
                parent=gid,
                label="",
                use_internal_label=True,
                user_data=i,
                callback=_on_sprite_palette_swatch_click,
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
        return max(0, min(v, n - 1))

    def _set_sprite_brush_index(idx: int) -> None:
        n = _palette_len_sprite()
        if n <= 0:
            state["sprite_brush_index"] = max(0, int(idx))
            return
        state["sprite_brush_index"] = max(0, min(int(idx), n - 1))

    def parse_sprite_palette_index() -> int:
        """Indice de pincel (paleta del sprite); no el modo solido del JSON."""
        try:
            v = int(state.get("sprite_brush_index", 1))
        except (TypeError, ValueError):
            v = 1
        n = _palette_len_sprite()
        if n <= 0:
            return max(0, v)
        return max(0, min(v, n - 1))

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
            if isinstance(root, Path):
                _paint_scene_objects_preview(
                    base,
                    _FB_W,
                    _FB_H,
                    root,
                    placements,
                    cross_rgb=(tr, tg, tb),
                )
            else:
                _paint_placement_crosses_only(
                    base, _FB_W, _FB_H, placements, tr, tg, tb
                )
        show = bool(dpg.get_value("ts_show_grid"))
        data = _compose_preview_texture(base, _FB_W, _FB_H, show)
        dpg.set_value("preview_texture", data)

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
            "ts_transparent_idx",
            "ts_bg_layer",
            "ts_bg_layer_enabled",
            "ts_bg_layer_opacity",
            "ts_bg_index",
            "ts_sprite_palette_rel",
            "ts_btn_sprite_palette_reload",
            "ts_sprite_id",
            "ts_sprite_blocks_w",
            "ts_sprite_blocks_h",
            "ts_btn_sprite_apply_size",
            "ts_sprite_editor_scale",
            "ts_sprite_editor_show_grid",
            "ts_sprite_editor_grid_step",
            "ts_btn_sprite_fill_canvas",
            "ts_btn_sprite_create",
            "ts_btn_sprite_save",
            "ts_btn_sprite_refresh",
            "ts_sprite_list",
            "ts_obj_list",
            "ts_obj_id",
            "ts_obj_name",
            "ts_obj_sprite_combo",
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
            return
        stems = list_sprite_json_stems(root)
        if not stems:
            items = ["(sin sprites — crea uno en Sprites)"]
            dpg.configure_item("ts_obj_sprite_combo", items=items)
            dpg.set_value("ts_obj_sprite_combo", items[0])
            return
        dpg.configure_item("ts_obj_sprite_combo", items=stems)
        cur = dpg.get_value("ts_obj_sprite_combo")
        if cur not in stems:
            dpg.set_value("ts_obj_sprite_combo", stems[0])

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
            nm = max(0, len(rgbs) - 1)
            state["sprite_pixel_rows"] = [
                [max(0, min(nm, int(c))) for c in (rw if isinstance(rw, list) else [])]
                for rw in rows_mx
            ]
        elif rgbs:
            _ensure_sprite_edit_pixel_buffer()
        _refresh_sprite_edit_texture()
        tail = f"Sprite — indices en esta paleta: 0..{len(hexes) - 1}.\n"
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
            dpg.set_value("ts_transparent_idx", DEFAULT_TRANSPARENT_INDEX)
            dpg.set_value("ts_sprite_palette_rel", "")
            state["sprite_brush_index"] = 1
            state["sprite_palette_rgb"] = []
            state["sprite_palette_hexes"] = []
            _rebuild_sprite_palette_swatches()
            state["sprite_pixel_rows"] = None
            dpg.set_value("ts_obj_id", "")
            dpg.set_value("ts_obj_name", "")
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
        if not dpg.does_item_exist("ts_canvas_image"):
            return
        mx, my = dpg.get_mouse_pos(local=False)
        min_x, min_y = dpg.get_item_rect_min("ts_canvas_image")
        rel_x = float(mx - min_x)
        rel_y = float(my - min_y)
        sc = _canvas_display_scale()
        lw = float(_FB_W * sc)
        lh = float(_FB_H * sc)
        if rel_x < 0 or rel_y < 0 or rel_x >= lw or rel_y >= lh:
            return
        lx = int(rel_x // sc)
        ly_top = int(rel_y // sc)
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
        dpg.set_value("ts_transparent_idx", info.transparent_index)
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

    initial_black = _solid_rgba_float(_FB_W, _FB_H, 0.08, 0.08, 0.1)

    dpg.create_context()

    with dpg.theme(tag="ts_swatch_theme"):
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(
                dpg.mvThemeCol_ChildBg,
                [22, 22, 28, 255],
                tag="ts_swatch_theme_color",
            )

    with dpg.texture_registry(tag="ts_texture_registry"):
        dpg.add_dynamic_texture(
            width=_FB_W,
            height=_FB_H,
            default_value=initial_black,
            tag="preview_texture",
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
                ti = int(dpg.get_value("ts_transparent_idx"))
            except (TypeError, ValueError):
                ti = DEFAULT_TRANSPARENT_INDEX
            try:
                embedded = collect_studio_bundle_files(
                    root,
                    scenes=scenes,
                    active_scene=initial_scene_s,
                    transparent_index=ti,
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
        if not dpg.does_item_exist("ts_canvas_image"):
            return
        s = _canvas_display_scale()
        dpg.configure_item("ts_canvas_image", width=_FB_W * s, height=_FB_H * s)

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
            ti = int(dpg.get_value("ts_transparent_idx"))
        except (TypeError, ValueError):
            ti = DEFAULT_TRANSPARENT_INDEX
        try:
            script_path, pal_updated, scenes_updated = save_project(
                root,
                lua_files=lua_files,
                palette_file=pal,
                scenes=scenes_list,
                active_scene=active,
                transparent_index=ti,
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
        cp = int(state.get("sprite_edit_cell_px") or 8)
        fi = parse_sprite_palette_index()
        rows = state.get("sprite_pixel_rows")
        if not isinstance(rows, list) or not rows:
            pw, ph = bw * cp, bh * cp
            rows = solid_fill_indices(pw, ph, fi)
            state["sprite_pixel_rows"] = rows
        try:
            n = max(1, _palette_len_sprite())
            rows2: list[list[int]] = [
                [max(0, min(n - 1, int(c))) for c in (r if isinstance(r, list) else [])]
                for r in rows
            ]
            path = save_indexed_pixels_sprite_json(
                root,
                sid,
                palette_rel=pal_raw,
                blocks_w=bw,
                blocks_h=bh,
                rows=rows2,
                cell_px=cp,
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

    def _sprite_editor_effective_scale(pw: int, ph: int) -> int:
        """Escala en pantalla; acotada para caber en la textura 512×512."""
        sc = _sprite_editor_display_scale()
        if pw <= 0 or ph <= 0:
            return sc
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
        cp = int(state.get("sprite_edit_cell_px") or 8)
        cp = max(1, min(256, cp))
        return bw * cp, bh * cp

    def _sync_sprite_matrix_from_widgets() -> None:
        """Alinea la matriz con Celdas W/H aunque el input_int no haya disparado callback."""
        pw_exp, ph_exp = _expected_sprite_matrix_pixel_size()
        rows = state.get("sprite_pixel_rows")
        pw, ph = 0, 0
        if isinstance(rows, list) and rows:
            pw, ph = _sprite_matrix_pixel_size(rows)
        if pw != pw_exp or ph != ph_exp:
            _resize_sprite_edit_matrix_for_widgets()

    def _resize_sprite_edit_matrix_for_widgets(
        *,
        fill_from_index: int | None = None,
    ) -> None:
        try:
            bw = int(dpg.get_value("ts_sprite_blocks_w"))
            bh = int(dpg.get_value("ts_sprite_blocks_h"))
        except (TypeError, ValueError):
            bw, bh = 1, 1
        bw = max(1, min(32, bw))
        bh = max(1, min(32, bh))
        cp = int(state.get("sprite_edit_cell_px") or 8)
        cp = max(1, min(256, cp))
        pw, ph = bw * cp, bh * cp
        fi = (
            parse_sprite_palette_index()
            if fill_from_index is None
            else max(0, int(fill_from_index))
        )
        if fill_from_index is None and fi == 0:
            fi = 1
        old = state.get("sprite_pixel_rows")
        if isinstance(old, list) and old and any(isinstance(r, list) and r for r in old):
            state["sprite_pixel_rows"] = normalize_palette_rows(old, pw, ph, fill_index=fi)
        else:
            state["sprite_pixel_rows"] = solid_fill_indices(pw, ph, fi)

    def _ensure_sprite_edit_pixel_buffer() -> None:
        """Matriz en memoria para pintar; sin esto los clics no hacen nada."""
        rows = state.get("sprite_pixel_rows")
        if not isinstance(rows, list) or not rows:
            _resize_sprite_edit_matrix_for_widgets()
            return
        _sync_sprite_matrix_from_widgets()

    def _sprite_edit_paint_at_mouse() -> bool:
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
        mx, my = dpg.get_mouse_pos(local=False)
        min_x, min_y = dpg.get_item_rect_min(_SPRITE_EDITOR_IMG_TAG)
        rx = float(mx - min_x)
        ry = float(my - min_y)
        lw = float(pw * sc)
        lh = float(ph * sc)
        if rx < 0 or ry < 0 or rx >= lw or ry >= lh:
            return False
        lx = int(rx // sc)
        ly = int(ry // sc)
        if ly < 0 or ly >= ph or lx < 0 or lx >= pw:
            return False
        color_i = parse_sprite_palette_index()
        row = rows[ly]
        if isinstance(row, list) and lx < len(row):
            row[lx] = color_i
        _refresh_sprite_edit_texture()
        return True

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
            return
        if dpg.does_item_exist("ts_sprite_blocks_w"):
            _sync_sprite_matrix_from_widgets()
        rows = state.get("sprite_pixel_rows")
        rgbs = state.get("sprite_palette_rgb")
        if not isinstance(rows, list) or not rows:
            sc0 = _sprite_editor_effective_scale(8, 8)
            _sync_sprite_edit_image_widget(8 * sc0, 8 * sc0)
            return
        if not isinstance(rgbs, list) or not rgbs:
            sc0 = _sprite_editor_effective_scale(8, 8)
            _sync_sprite_edit_image_widget(8 * sc0, 8 * sc0)
            return
        pw, ph = _sprite_matrix_pixel_size(rows)
        if pw <= 0 or ph <= 0:
            return
        pad_i = parse_sprite_palette_index()
        norm = normalize_palette_rows(rows, pw, ph, fill_index=pad_i)
        state["sprite_pixel_rows"] = norm
        base = _sprite_rows_to_rgba_float01(norm, rgbs)
        cp = int(state.get("sprite_edit_cell_px") or 8)
        cp = max(1, min(256, cp))
        show_g = bool(dpg.get_value("ts_sprite_editor_show_grid")) if dpg.does_item_exist(
            "ts_sprite_editor_show_grid"
        ) else False
        if show_g:
            gstep = parse_sprite_editor_grid_step()
            base = _apply_sprite_editor_grid_overlay(base, pw, ph, grid_step=gstep)
        if len(base) != pw * ph * 4:
            return
        _apply_sprite_edit_rgba(pw, ph, base)
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
        _refresh_sprite_edit_texture()

    def on_sprite_apply_size(_sender: object, _app_data: object) -> None:
        _resize_sprite_edit_matrix_for_widgets()
        _refresh_sprite_edit_texture()

    def on_sprite_editor_scale_change(_sender: object, _app_data: object) -> None:
        _refresh_sprite_edit_texture()

    def on_sprite_editor_grid_toggle(_sender: object, _app_data: object) -> None:
        _refresh_sprite_edit_texture()

    def parse_sprite_editor_grid_step() -> int:
        if not dpg.does_item_exist("ts_sprite_editor_grid_step"):
            return _SPRITE_EDITOR_GRID_STEP_DEFAULT
        return _normalize_sprite_grid_step(dpg.get_value("ts_sprite_editor_grid_step"))

    def on_sprite_editor_grid_step_change(_sender: object, _app_data: object) -> None:
        if not dpg.does_item_exist("ts_sprite_editor_grid_step"):
            return
        norm = parse_sprite_editor_grid_step()
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

    def on_sprite_edit_canvas_click(_sender: object, _app_data: object) -> None:
        _sprite_edit_paint_at_mouse()

    def on_sprite_edit_paint_drag(_sender: object, _app_data: object) -> None:
        if state.get("sprite_ui_silent"):
            return
        if not dpg.does_item_exist(_SPRITE_EDITOR_IMG_TAG):
            return
        try:
            if not dpg.is_item_hovered(_SPRITE_EDITOR_IMG_TAG):
                return
        except SystemError:
            return
        _sprite_edit_paint_at_mouse()

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
            cp = int(data.get("cell_px", 8))
        except (TypeError, ValueError):
            cp = 8
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
        if sprite_is_indexed_pixels(data):
            parsed = parse_palette_rows_image(data)
            if parsed:
                state["sprite_pixel_rows"] = [list(r) for r in parsed]
            else:
                state["sprite_pixel_rows"] = solid_fill_indices(pw, ph, pi)
        else:
            state["sprite_pixel_rows"] = solid_fill_indices(pw, ph, pi)
        state["sprite_ui_silent"] = True
        try:
            dpg.set_value("ts_sprite_blocks_w", bw)
            dpg.set_value("ts_sprite_blocks_h", bh)
        finally:
            state["sprite_ui_silent"] = False
        _set_sprite_brush_index(pi)
        _sprite_palette_reload_core(append_log=False, preferred_palette_index=pi)
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
            rows = state.get("sprite_pixel_rows")
            if not isinstance(rows, list) or not rows:
                raise ValueError("matriz de pixeles vacia; recarga el sprite o la paleta.")
            n = max(1, _palette_len_sprite())
            rows2: list[list[int]] = [
                [max(0, min(n - 1, int(c))) for c in (r if isinstance(r, list) else [])]
                for r in rows
            ]
            path = save_indexed_pixels_sprite_json(
                root,
                sid,
                palette_rel=pal_raw,
                blocks_w=bw,
                blocks_h=bh,
                rows=rows2,
                cell_px=int(state.get("sprite_edit_cell_px") or 8),
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
        dpg.set_value(
            "ts_log",
            (dpg.get_value("ts_log") or "") + f"Objetos: cargado {stem}.json\n",
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
        try:
            path = write_object_json(root, oid, name=name, sprite_id=sp)
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
        try:
            path = save_object_json(root, oid, name=name, sprite_id=sp)
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
        dpg.set_value("ts_transparent_idx", DEFAULT_TRANSPARENT_INDEX)
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
                        dpg.add_input_int(
                            tag="ts_transparent_idx",
                            label="Indice transparente (chroma)",
                            width=_LEFT_FORM_WIDTH,
                            default_value=DEFAULT_TRANSPARENT_INDEX,
                            min_value=0,
                            max_value=31,
                            min_clamped=True,
                            max_clamped=True,
                            enabled=False,
                            use_internal_label=False,
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
                            "Con zoom alto, desplazate dentro del marco de la vista previa "
                            "(barras horizontal y vertical).",
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
                                "preview_texture",
                                tag="ts_canvas_image",
                                width=_FB_W * _DEFAULT_CANVAS_SCALE,
                                height=_FB_H * _DEFAULT_CANVAS_SCALE,
                            )
                            with dpg.item_handler_registry(tag="ts_canvas_click_reg"):
                                dpg.add_item_clicked_handler(callback=on_canvas_preview_click)
                            dpg.bind_item_handler_registry("ts_canvas_image", "ts_canvas_click_reg")
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
                    "Tamano en celdas de 8×8 px (ej. 2×2 = 16×16 px). Tras cambiar W/H: Enter, "
                    "clic fuera o «Aplicar tamano».",
                    wrap=520,
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
                        min_clamped=True,
                        max_clamped=True,
                        enabled=False,
                        callback=on_sprite_editor_grid_step_change,
                    )
                dpg.bind_item_handler_registry(
                    "ts_sprite_editor_grid_step", "ts_sprite_blocks_dim_handlers"
                )
                dpg.add_button(
                    tag="ts_btn_sprite_fill_canvas",
                    label="Rellenar lienzo con indice actual",
                    width=280,
                    callback=on_sprite_fill_canvas,
                    enabled=False,
                )
                dpg.add_text(
                    tag="ts_sprite_edit_size_label",
                    default_value="Vista: (carga paleta y ajusta celdas)",
                    wrap=520,
                )
                dpg.add_text(
                    "Pincel = color elegido en la paleta de arriba. Clic o arrastrar en el lienzo. "
                    "«Guardar sprite» guarda los pixeles pintados (no un bloque de un solo color).",
                    wrap=520,
                )
                with dpg.item_handler_registry(tag="ts_sprite_edit_click_reg"):
                    dpg.add_item_clicked_handler(callback=on_sprite_edit_canvas_click)
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
                        width=8 * _SPRITE_EDITOR_SCALE_DEFAULT,
                        height=8 * _SPRITE_EDITOR_SCALE_DEFAULT,
                        uv_min=(0.0, 0.0),
                        uv_max=_sprite_editor_uv_max(
                            8 * _SPRITE_EDITOR_SCALE_DEFAULT,
                            8 * _SPRITE_EDITOR_SCALE_DEFAULT,
                        ),
                    )
                dpg.bind_item_handler_registry(
                    _SPRITE_EDITOR_IMG_TAG, "ts_sprite_edit_click_reg"
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
                    label="Sprite asociado (objects/Sprites/)",
                    width=400,
                    items=["(abre un proyecto)"],
                    default_value="(abre un proyecto)",
                    enabled=False,
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
