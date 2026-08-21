"""Scene editor tab — scenes live in the project manifest, not per-file.

Composites background layers + an optional background asset + up to four
tile layers + object placements + the camera viewport into one preview,
reusing the pure-Python RGBA compositing helpers from scene_tiles.py /
scene_camera.py (no live gameplay simulation exists on PC for TurtleStudio,
unlike TortoiseStudio's pygame-embedded viewport — see project.py's
SceneEntry for the full field set this editor edits).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QImage, QMouseEvent, QPainter, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from turtlestudio.backgrounds import (
    background_is_indexed_pixels,
    background_scene_preview_data,
    list_background_stems_for_palette,
    list_palette_relpaths,
    parse_background_palette_rows,
    parse_background_solid_palette_index,
)
from turtlestudio.build import load_palette_rgb01_for_preview
from turtlestudio.collapsible import CollapsibleSection
from turtlestudio.edit_history import SnapshotHistory
from turtlestudio.i18n import tr
from turtlestudio.objects import list_object_ids_for_scene_palette, read_object_file
from turtlestudio.palette_policy import (
    PALETTE_SIZE,
    TRANSPARENT_PALETTE_INDEX,
    is_transparent_palette_index,
    resolve_palette_color,
)
from turtlestudio.project import (
    DEFAULT_INITIAL_SCENE_ID,
    MANIFEST_NAME,
    SCENE_PIXEL_H,
    SCENE_PIXEL_W,
    WORLD_STEPS_MAX,
    WORLD_STEPS_MIN,
    background_layers_to_json_list,
    clamp_world_steps,
    manifest_path,
    parse_background_layers,
    parse_scene_objects_raw,
    parse_viewport_from_manifest,
    save_project,
    scene_world_pixel_size,
)
from turtlestudio.scene_camera import (
    CAMERA_MODE_FIXED,
    CAMERA_MODE_FOLLOW,
    VIEWPORT_PIXEL_H,
    VIEWPORT_PIXEL_W,
    draw_scene_camera_viewport_on_rgba,
    parse_scene_camera_from_row,
    resolve_scene_camera_viewport,
    scene_camera_to_json,
)
from turtlestudio.scene_parallax import (
    MAX_PARALLAX_BANDS,
    SceneParallaxBand,
    clamp_parallax_band,
    draw_scene_parallax_bands_on_rgba,
    parse_scene_parallax_bands_from_row,
    scene_parallax_band_to_json,
    scene_parallax_bands_to_json,
)
from turtlestudio.scene_tiles import (
    TILE_LAYER_COUNT,
    draw_scene_step_bounds_on_rgba,
    draw_scene_tile_grid_on_rgba,
    empty_tile_cells,
    flood_fill_cell_index,
    get_cell_index,
    list_tileset_stems_for_palette,
    normalize_collision_tile_layer,
    paint_tile_layers_on_rgba_blocked,
    parse_tile_layers,
    scene_coords_to_cell,
    scene_tile_grid_dimensions,
    set_cell_index,
    tile_block_key,
    tile_layers_to_json_list,
)
from turtlestudio.sprites import (
    normalize_palette_rel,
    parse_palette_rows_image,
    parse_sprite_origin,
    read_sprite_file,
    sprite_blit_bottom_left,
    sprite_is_indexed_pixels,
    sprite_pixel_dimensions,
)
from turtlestudio.tiles import (
    list_tileset_json_stems,
    parse_tile_px_from_manifest,
    parse_tileset_all_tiles,
    read_tileset_file,
    tileset_file_pixel_dimensions,
)

_ORIGIN_CROSS_RGB = (1.0, 0.9, 0.2)
_SELECTION_FRAME_RGB = (0.2, 0.9, 1.0)


# ----------------------------------------------------------------------
# Pure-data compositing (no Qt) — mirrors old gui.py's scene-preview path
# ----------------------------------------------------------------------


def _fill_rect_rgba(rgba: list[float], fw: int, fh: int, r: float, g: float, b: float, alpha: float) -> None:
    if alpha >= 0.999:
        row = [r, g, b, 1.0] * fw
        for y in range(fh):
            base = y * fw * 4
            rgba[base : base + fw * 4] = row
        return
    from turtlestudio.scene_tiles import _blend_rgba_pixel_inplace

    for i in range(0, len(rgba), 4):
        _blend_rgba_pixel_inplace(rgba, i, r, g, b, alpha)


def _fill_rect_rgba_region(
    rgba: list[float], fw: int, fh: int, sx0: int, sy0: int, w: int, h: int, r: float, g: float, b: float
) -> None:
    for sy in range(max(0, sy0), min(fh, sy0 + h)):
        ty = (fh - 1) - sy
        if ty < 0 or ty >= fh:
            continue
        base = ty * fw * 4
        for sx in range(max(0, sx0), min(fw, sx0 + w)):
            i = base + sx * 4
            rgba[i] = r
            rgba[i + 1] = g
            rgba[i + 2] = b
            rgba[i + 3] = 1.0


def _blit_indexed_rows_scene(
    rgba: list[float],
    fw: int,
    fh: int,
    sx0: int,
    sy_bottom: int,
    rows: list[list[int]],
    rgbs: list[tuple[float, float, float]],
) -> None:
    """(sx0, sy_bottom) = bottom-left corner of the bbox, in scene space."""
    ph = len(rows)
    pw = len(rows[0]) if rows else 0
    for py in range(ph):
        scene_y = sy_bottom + (ph - 1 - py)
        row = rows[py] if py < len(rows) else []
        for lx in range(pw):
            scene_x = sx0 + lx
            if scene_x < 0 or scene_x >= fw or scene_y < 0 or scene_y >= fh:
                continue
            try:
                idx = int(row[lx]) if lx < len(row) else TRANSPARENT_PALETTE_INDEX
            except (TypeError, ValueError):
                continue
            if is_transparent_palette_index(idx):
                continue
            col = resolve_palette_color(idx, rgbs)
            if col is None:
                continue
            r, g, b = col
            ty = (fh - 1) - scene_y
            i = (ty * fw + scene_x) * 4
            rgba[i] = r
            rgba[i + 1] = g
            rgba[i + 2] = b
            rgba[i + 3] = 1.0


def _draw_cross_on_rgba(rgba: list[float], fw: int, fh: int, sx: int, sy: int) -> None:
    ty = (fh - 1) - sy
    r, g, b = _ORIGIN_CROSS_RGB
    for dx, dy in ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1), (-2, 0), (2, 0), (0, -2), (0, 2)):
        x, y = sx + dx, ty + dy
        if 0 <= x < fw and 0 <= y < fh:
            i = (y * fw + x) * 4
            rgba[i] = r
            rgba[i + 1] = g
            rgba[i + 2] = b
            rgba[i + 3] = 1.0


def _draw_rect_outline_on_rgba(
    rgba: list[float], fw: int, fh: int, sx0: int, sy0: int, w: int, h: int, r: float, g: float, b: float
) -> None:
    """1px border around the scene-space bbox (sx0, sy0)=bottom-left, w x h, expanded
    1px outward so it frames the sprite instead of overlapping its edge pixels."""
    x0, y0 = sx0 - 1, sy0 - 1
    x1, y1 = sx0 + w, sy0 + h

    def set_px(sx: int, sy: int) -> None:
        if sx < 0 or sx >= fw or sy < 0 or sy >= fh:
            return
        ty = (fh - 1) - sy
        i = (ty * fw + sx) * 4
        rgba[i] = r
        rgba[i + 1] = g
        rgba[i + 2] = b
        rgba[i + 3] = 1.0

    for sx in range(x0, x1 + 1):
        set_px(sx, y0)
        set_px(sx, y1)
    for sy in range(y0, y1 + 1):
        set_px(x0, sy)
        set_px(x1, sy)


def _paint_background_stem(
    rgba: list[float],
    fw: int,
    fh: int,
    project_root: Path,
    stem: str,
    scene_palette_rel: str,
    rgbs: list[tuple[float, float, float]],
) -> None:
    if not stem:
        return
    got = background_scene_preview_data(project_root, stem, scene_palette_rel=scene_palette_rel)
    if got is None:
        return
    pw, ph, data = got
    if background_is_indexed_pixels(data):
        rows = parse_background_palette_rows(data)
        if rows:
            _blit_indexed_rows_scene(rgba, fw, fh, 0, 0, rows, rgbs)
        return
    pi = parse_background_solid_palette_index(data)
    col = resolve_palette_color(pi, rgbs)
    if col is not None:
        r, g, b = col
        _fill_rect_rgba_region(rgba, fw, fh, 0, 0, pw, ph, r, g, b)


def _resolve_object_sprite_preview(project_root: Path, object_id: str) -> dict[str, Any]:
    fb: dict[str, Any] = {
        "mode": "solid",
        "pw": 8,
        "ph": 8,
        "rgb": (0.42, 0.42, 0.48),
        "origin_x": 0,
        "origin_y": 0,
    }
    oid = object_id.strip()
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
            return {"mode": "indexed", "pw": pw, "ph": ph, "rows": rows, "rgbs": rgbs, "origin_x": ox, "origin_y": oy}
    pi = 0
    render = sd.get("render")
    if isinstance(render, dict):
        try:
            pi = int(render.get("palette_index", 0))
        except (TypeError, ValueError):
            pi = 0
    pi = max(0, min(len(rgbs) - 1, pi))
    r, g, b = rgbs[pi]
    return {"mode": "solid", "pw": pw, "ph": ph, "rgb": (r, g, b), "origin_x": ox, "origin_y": oy}


def _paint_scene_objects(
    rgba: list[float], fw: int, fh: int, project_root: Path, placements: list[dict[str, Any]]
) -> None:
    for p in placements:
        if not isinstance(p, dict):
            continue
        oid = str(p.get("id", "")).strip()
        if not oid:
            continue
        try:
            sx = int(p.get("x", 0))
            sy = int(p.get("y", 0))
        except (TypeError, ValueError):
            continue
        sx = max(0, min(fw - 1, sx))
        sy = max(0, min(fh - 1, sy))
        info = _resolve_object_sprite_preview(project_root, oid)
        bx, by = sprite_blit_bottom_left(sx, sy, int(info["origin_x"]), int(info["origin_y"]))
        if info["mode"] == "indexed":
            _blit_indexed_rows_scene(rgba, fw, fh, bx, by, info["rows"], info["rgbs"])
        else:
            r, g, b = info["rgb"]
            _fill_rect_rgba_region(rgba, fw, fh, bx, by, int(info["pw"]), int(info["ph"]), r, g, b)
        _draw_cross_on_rgba(rgba, fw, fh, sx, sy)


def render_scene_rgba(
    project_root: Path,
    row: dict[str, Any],
    tile_px: int,
    *,
    viewport_w: int = SCENE_PIXEL_W,
    viewport_h: int = SCENE_PIXEL_H,
    paint_layer_index: int | None = None,
    hover_cell: tuple[int, int] | None = None,
    selected_parallax_band_index: int | None = None,
    selected_object_index: int | None = None,
    tile_block_cache: dict[tuple[int, int], tuple[list[float], int, int]] | None = None,
) -> tuple[list[float], int, int]:
    wsx = clamp_world_steps(row.get("world_steps_x", 1))
    wsy = clamp_world_steps(row.get("world_steps_y", 1))
    fw, fh = scene_world_pixel_size(wsx, wsy, base_w=viewport_w, base_h=viewport_h)
    rgba = [0.0] * (fw * fh * 4)
    for i in range(3, len(rgba), 4):
        rgba[i] = 1.0

    palette_rel = str(row.get("palette", "")).strip()
    pal_path = (project_root / palette_rel).resolve() if palette_rel else None
    rgbs, _ = load_palette_rgb01_for_preview(pal_path if pal_path and pal_path.is_file() else None)

    # spec/scene-v0.md "Capas de fondo con imagen": capa 1 (indice 0) es la capa base -- se
    # hornea junto a los tiles en el mundo estatico del firmware y es la unica elegible para
    # `parallax_bands` -- las capas 2-4 son independientes. La vista previa no distingue el
    # costo de render de cada una; solo importa el orden (0 abajo, 3 arriba).
    for ld in row.get("background_layers") or []:
        if not isinstance(ld, dict) or not ld.get("enabled"):
            continue
        layer_stem = str(ld.get("background", "") or "").strip()
        if layer_stem:
            # Ancla abajo-izquierda (igual que paint_bg_image_layers/paint_cached_world_background
            # en firmware); sin mezcla alfa -- opacity solo aplica al color plano de respaldo
            # de abajo, no a la imagen.
            _paint_background_stem(rgba, fw, fh, project_root, layer_stem, palette_rel, rgbs)
            continue
        try:
            ci = int(ld.get("color_index", 1))
            op = max(0, min(255, int(ld.get("opacity", 255)))) / 255.0
        except (TypeError, ValueError):
            continue
        if op <= 0.0:
            continue
        col = resolve_palette_color(ci, rgbs)
        if col is None:
            continue
        r, g, b = col
        _fill_rect_rgba(rgba, fw, fh, r, g, b, op)

    layers = parse_tile_layers(row.get("tile_layers"), tile_px=tile_px, world_w=fw, world_h=fh)
    paint_tile_layers_on_rgba_blocked(
        rgba, fw, fh, layers, project_root, rgbs, tile_px=tile_px, block_cache=tile_block_cache
    )

    placements = row.get("objects") or []
    _paint_scene_objects(rgba, fw, fh, project_root, placements)

    if paint_layer_index is not None:
        draw_scene_tile_grid_on_rgba(rgba, fw, fh, tile_px, hover_cell=hover_cell, full_grid=True)

    # Las bandas solo afectan la Capa 1 (ver comentario arriba); si esa capa esta
    # desactivada no tienen efecto, asi que no se dibuja la superposicion (igual que el
    # grupo "Bandas de parallax" del panel, que tambien se oculta con la capa apagada).
    bg_layers_raw = row.get("background_layers") or []
    layer0_enabled = bool(bg_layers_raw[0].get("enabled")) if bg_layers_raw and isinstance(bg_layers_raw[0], dict) else False
    if layer0_enabled:
        parallax_bands = parse_scene_parallax_bands_from_row(row, world_h=fh)
        if parallax_bands:
            draw_scene_parallax_bands_on_rgba(
                rgba, fw, fh, parallax_bands, selected_index=selected_parallax_band_index
            )

    if fw > viewport_w or fh > viewport_h:
        draw_scene_step_bounds_on_rgba(rgba, fw, fh, step_w=viewport_w, step_h=viewport_h)
        cam = parse_scene_camera_from_row(row)
        cam_x, cam_y = resolve_scene_camera_viewport(
            cam, world_w=fw, world_h=fh, objects=list(placements), viewport_w=viewport_w, viewport_h=viewport_h
        )
        draw_scene_camera_viewport_on_rgba(rgba, fw, fh, cam_x, cam_y, viewport_w=viewport_w, viewport_h=viewport_h)

    # Se dibuja al final, encima de todo (tiles, capas, limites de mundo, viewport de
    # camara), para que el marco de seleccion siempre sea visible sin importar que
    # otras superposiciones esten activas.
    if selected_object_index is not None and 0 <= selected_object_index < len(placements):
        sel = placements[selected_object_index]
        if isinstance(sel, dict):
            sel_oid = str(sel.get("id", "")).strip()
            if sel_oid:
                try:
                    sel_sx = int(sel.get("x", 0))
                    sel_sy = int(sel.get("y", 0))
                except (TypeError, ValueError):
                    sel_sx = sel_sy = None
                if sel_sx is not None:
                    sel_info = _resolve_object_sprite_preview(project_root, sel_oid)
                    sbx, sby = sprite_blit_bottom_left(sel_sx, sel_sy, int(sel_info["origin_x"]), int(sel_info["origin_y"]))
                    _draw_rect_outline_on_rgba(
                        rgba, fw, fh, sbx, sby, int(sel_info["pw"]), int(sel_info["ph"]), *_SELECTION_FRAME_RGB
                    )

    return rgba, fw, fh


def _rgba_floats_to_qimage(rgba: list[float], w: int, h: int) -> QImage:
    buf = bytes(min(255, max(0, int(v * 255.0))) for v in rgba)
    img = QImage(buf, w, h, w * 4, QImage.Format.Format_RGBA8888)
    return img.copy()


def _tile_icon(rows: list[list[int]], rgbs: list[tuple[float, float, float]], *, size: int = 32) -> QIcon:
    ph = len(rows)
    pw = len(rows[0]) if rows else 0
    pw = max(1, pw)
    ph = max(1, ph)
    tile_rgba = [0.0] * (pw * ph * 4)
    for y in range(ph):
        row = rows[y] if y < len(rows) else []
        for x in range(pw):
            idx = row[x] if x < len(row) else TRANSPARENT_PALETTE_INDEX
            col = resolve_palette_color(idx, rgbs)
            i = (y * pw + x) * 4
            if col is None:
                shade = 0.28 if (x // 2 + y // 2) % 2 == 0 else 0.2
                tile_rgba[i] = tile_rgba[i + 1] = tile_rgba[i + 2] = shade
                tile_rgba[i + 3] = 1.0
            else:
                r, g, b = col
                tile_rgba[i] = r
                tile_rgba[i + 1] = g
                tile_rgba[i + 2] = b
                tile_rgba[i + 3] = 1.0
    img = _rgba_floats_to_qimage(tile_rgba, pw, ph)
    pix = QPixmap.fromImage(img).scaled(
        size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation
    )
    return QIcon(pix)


# ----------------------------------------------------------------------
# Pixel-editor tool icons (procedural, no image assets -- same house convention
# as _tile_icon above). Each _draw_*_icon function paints into a fixed 20x20
# coordinate space; _tool_icon scales that space to the requested pixel size.
# Shared by every Pencil/Eraser/Eyedropper/Bucket toolbar in the app (scene
# tile-paint, sprite, background, font glyph, tileset editors) -- imported from
# here the same way font_editor.py already imports _tile_icon from this module.
# ----------------------------------------------------------------------


def _draw_brush_tool_icon(p: QPainter) -> None:
    pen = QPen(QColor(214, 176, 110))
    pen.setWidthF(4.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(4, 16), QPointF(12, 8))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(50, 50, 50))
    p.drawPolygon(QPolygonF([QPointF(11, 9), QPointF(16, 4), QPointF(14, 7)]))
    p.setBrush(QColor(232, 120, 130))
    p.drawEllipse(QPointF(4, 16), 2.0, 2.0)


def _draw_eraser_tool_icon(p: QPainter) -> None:
    p.save()
    p.translate(10, 11)
    p.rotate(-35)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(235, 120, 150))
    p.drawRoundedRect(QRectF(-7, -4, 14, 8), 2, 2)
    p.setBrush(QColor(250, 250, 250))
    p.drawRect(QRectF(-7, -4, 5, 8))
    p.restore()


def _draw_eyedropper_tool_icon(p: QPainter) -> None:
    pen = QPen(QColor(150, 150, 160))
    pen.setWidthF(3.2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(6, 16), QPointF(14, 6))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(120, 190, 230))
    p.drawEllipse(QPointF(15, 5), 3.2, 3.2)
    p.setBrush(QColor(90, 170, 220))
    p.drawEllipse(QPointF(5, 17), 1.6, 1.6)


def _draw_bucket_tool_icon(p: QPainter) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(170, 170, 178))
    p.drawPolygon(QPolygonF([QPointF(4, 8), QPointF(16, 8), QPointF(13, 17), QPointF(7, 17)]))
    pen = QPen(QColor(90, 90, 95))
    pen.setWidthF(1.6)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(5, 2, 10, 10), 0, 180 * 16)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(90, 190, 235))
    p.drawPolygon(QPolygonF([QPointF(15, 15), QPointF(18, 15), QPointF(16.5, 19)]))


_TOOL_ICON_DRAWERS = {
    "brush": _draw_brush_tool_icon,
    "pencil": _draw_brush_tool_icon,  # sprite/background/font/tileset editors call the same tool "pencil"
    "eraser": _draw_eraser_tool_icon,
    "eyedropper": _draw_eyedropper_tool_icon,
    "bucket": _draw_bucket_tool_icon,
}


def _tool_icon(tool: str, *, size: int = 20) -> QIcon:
    draw = _TOOL_ICON_DRAWERS.get(tool)
    if draw is None:
        return QIcon()
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.scale(size / 20.0, size / 20.0)
    draw(p)
    p.end()
    return QIcon(pm)


# ----------------------------------------------------------------------
# Widgets
# ----------------------------------------------------------------------


class TilePickerWidget(QListWidget):
    """Thumbnail strip of a tileset's tiles; emits tile_selected(index)."""

    tile_selected = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(False)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setIconSize(QSize(32, 32))
        self.setFixedHeight(56)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.currentRowChanged.connect(self._on_row_changed)

    def set_tiles(self, tiles: list[list[list[int]]], rgbs: list[tuple[float, float, float]]) -> None:
        self.blockSignals(True)
        self.clear()
        for i, rows in enumerate(tiles):
            item = QListWidgetItem(_tile_icon(rows, rgbs), str(i))
            self.addItem(item)
        self.blockSignals(False)

    def _on_row_changed(self, row: int) -> None:
        if row >= 0:
            self.tile_selected.emit(row)

    def select_index(self, index: int) -> None:
        self.blockSignals(True)
        self.setCurrentRow(index)
        self.blockSignals(False)


class SceneCanvas(QWidget):
    """Displays the composited scene RGBA and reports clicks in scene space."""

    cell_clicked = pyqtSignal(int, int)
    stroke_finished = pyqtSignal()
    object_drag_started = pyqtSignal(int, int)
    object_drag_moved = pyqtSignal(int, int)
    object_drag_finished = pyqtSignal()
    tool_context_menu_requested = pyqtSignal(object)  # QPoint (global), avoids importing QPoint just for the hint

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image: QImage | None = None
        self._fw = 0
        self._fh = 0
        self.zoom = 2
        self.paintable = False
        # Modo Editor (no pintando tiles): clic+arrastre sobre un objeto lo selecciona
        # y lo mueve, en vez de pintar celdas -- ver object_drag_* mas arriba.
        self.object_mode = False
        self._drawing = False
        self.setMouseTracking(True)

    def set_frame(self, image: QImage, fw: int, fh: int) -> None:
        self._image = image
        self._fw = fw
        self._fh = fh
        self.setMinimumSize(max(1, fw) * self.zoom, max(1, fh) * self.zoom)
        self.update()

    def set_zoom(self, zoom: int) -> None:
        self.zoom = max(1, min(6, zoom))
        self.setMinimumSize(max(1, self._fw) * self.zoom, max(1, self._fh) * self.zoom)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if self._image is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            target = self._image.scaled(
                self._fw * self.zoom,
                self._fh * self.zoom,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            painter.drawImage(0, 0, target)
        painter.end()

    def _scene_xy_at(self, pos) -> tuple[int, int] | None:
        if self._fw <= 0 or self._fh <= 0:
            return None
        x_img = int(pos.x()) // self.zoom
        y_img = int(pos.y()) // self.zoom
        if not (0 <= x_img < self._fw and 0 <= y_img < self._fh):
            return None
        return x_img, (self._fh - 1) - y_img

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not self.paintable and not self.object_mode:
            return
        xy = self._scene_xy_at(event.position())
        if xy is None:
            return
        self._drawing = True
        if self.paintable:
            self.cell_clicked.emit(*xy)
        else:
            self.object_drag_started.emit(*xy)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        xy = self._scene_xy_at(event.position())
        if xy is None:
            return
        if self.paintable:
            self.cell_clicked.emit(*xy)
        elif self.object_mode and self._drawing:
            self.object_drag_moved.emit(*xy)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        was_drawing = self._drawing
        self._drawing = False
        if not was_drawing:
            return
        if self.paintable:
            # Un solo checkpoint de historial por trazo de pintura de tiles, no uno
            # por celda (cell_clicked se emite por cada celda tocada al arrastrar).
            self.stroke_finished.emit()
        elif self.object_mode:
            self.object_drag_finished.emit()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        if not self.paintable:
            return
        self.tool_context_menu_requested.emit(event.globalPos())
        event.accept()


# ----------------------------------------------------------------------
# Main editor widget
# ----------------------------------------------------------------------


def _default_camera_dict() -> dict[str, Any]:
    return {"mode": CAMERA_MODE_FOLLOW, "x": 0, "y": 0, "target": "", "margin_x": 64, "margin_y": 48}


def _new_scene_row(sid: str, palette_rel: str, tile_px: int) -> dict[str, Any]:
    return {
        "id": sid,
        "palette": palette_rel,
        "background_index": 1,
        "background_layers": background_layers_to_json_list(parse_background_layers(None, legacy_flat_index=1, n_colors=PALETTE_SIZE)),
        "script": sid,
        "objects": [],
        "tile_layers": tile_layers_to_json_list(parse_tile_layers(None, tile_px=tile_px)),
        "world_steps_x": 1,
        "world_steps_y": 1,
        "camera": _default_camera_dict(),
    }


def _normalize_row(
    row: dict[str, Any],
    tile_px: int,
    *,
    viewport_w: int = SCENE_PIXEL_W,
    viewport_h: int = SCENE_PIXEL_H,
) -> dict[str, Any]:
    """Round-trip a raw manifest scene row through the parse/serialize helpers."""
    r = dict(row)
    wsx = clamp_world_steps(r.get("world_steps_x", 1))
    wsy = clamp_world_steps(r.get("world_steps_y", 1))
    ww, wh = scene_world_pixel_size(wsx, wsy, base_w=viewport_w, base_h=viewport_h)
    r["world_steps_x"] = wsx
    r["world_steps_y"] = wsy
    layers = parse_background_layers(
        r.get("background_layers"), legacy_flat_index=int(r.get("background_index", 1) or 1), n_colors=PALETTE_SIZE
    )
    # Migracion: fondo suelto pre-unificacion -> background_layers[0].background (capa base).
    # Validacion real de que el stem exista pasa despues, al poblar los combos de la capa.
    legacy_bg = str(r.get("background", "") or "").strip()
    if legacy_bg and not layers[0].background:
        from dataclasses import replace as _replace

        layers = (_replace(layers[0], background=legacy_bg, enabled=True),) + layers[1:]
    r["background_layers"] = background_layers_to_json_list(layers)
    r.pop("background", None)
    tile_layers = parse_tile_layers(r.get("tile_layers"), tile_px=tile_px, world_w=ww, world_h=wh)
    r["tile_layers"] = tile_layers_to_json_list(tile_layers)
    placements = parse_scene_objects_raw(r.get("objects"), world_w=ww, world_h=wh)
    r["objects"] = [{"id": p.id, "x": p.x, "y": p.y} for p in placements]
    cam = parse_scene_camera_from_row(r)
    r["camera"] = scene_camera_to_json(cam)
    r["script"] = str(r.get("script", r.get("id", DEFAULT_INITIAL_SCENE_ID)) or r.get("id", DEFAULT_INITIAL_SCENE_ID))
    return r


class SceneEditorWidget(QWidget):
    saved = pyqtSignal(Path)

    def __init__(self, project_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project_root = project_root
        self._scenes: list[dict[str, Any]] = []
        self._active_id = ""
        self._current_index = -1
        self._tile_px = 16
        self._viewport_w = SCENE_PIXEL_W
        self._viewport_h = SCENE_PIXEL_H
        self._dirty = False
        self._paint_layer: int | None = None
        self._paint_tile_index = 0
        self._paint_tool = "brush"  # "brush" | "eyedropper" | "bucket"
        self._hover_cell: tuple[int, int] | None = None
        self._dragging_object_index: int | None = None
        self._drag_offset: tuple[int, int] | None = None
        self._suspend = False
        # Cache de render de tiles por bloque (perf editor con world_steps grandes, no
        # firmware): dropeado entero cuando cambia algo estructural (ver _tile_cache_
        # signature); invalidado bloque-a-bloque al pintar una sola celda (ver
        # _on_canvas_cell_clicked).
        self._tile_block_cache: dict[tuple[int, int], tuple[list[float], int, int]] = {}
        self._tile_cache_signature_value: tuple[Any, ...] | None = None
        self._history = SnapshotHistory()
        self._restoring = False
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_project_root(self, root: Path) -> None:
        self.project_root = root
        self.refresh()

    def refresh(self) -> None:
        try:
            data = json.loads(manifest_path(self.project_root).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            QMessageBox.warning(self, tr("scene.read_error_title"), tr("scene.read_error_msg", manifest=MANIFEST_NAME, e=e))
            return
        self._tile_px = parse_tile_px_from_manifest(data)
        self._viewport_w, self._viewport_h = parse_viewport_from_manifest(data)
        raw_scenes = data.get("scenes") if isinstance(data.get("scenes"), list) else []
        self._scenes = [
            _normalize_row(s, self._tile_px, viewport_w=self._viewport_w, viewport_h=self._viewport_h)
            for s in raw_scenes
            if isinstance(s, dict) and s.get("id")
        ]
        self._active_id = str(data.get("active_scene", "")).strip()
        if not self._scenes:
            self._current_index = -1
        else:
            ids = [s["id"] for s in self._scenes]
            self._current_index = ids.index(self._active_id) if self._active_id in ids else 0
        self._dirty = False
        self._refresh_scene_combo()
        self._load_current_into_form()
        self._history.reset(self._snapshot())

    def open_scene(self, scene_id: str) -> None:
        ids = [s["id"] for s in self._scenes]
        if scene_id in ids:
            self._current_index = ids.index(scene_id)
            self._load_current_into_form()
            self._history.reset(self._snapshot())

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel(tr("scene.label")))
        self.combo_scene = QComboBox()
        self.combo_scene.setMinimumWidth(160)
        self.combo_scene.currentIndexChanged.connect(self._on_scene_combo_changed)
        top_row.addWidget(self.combo_scene)
        self.btn_new_scene = QPushButton(tr("scene.new_scene_button"))
        self.btn_new_scene.clicked.connect(self._action_new_scene)
        top_row.addWidget(self.btn_new_scene)
        self.btn_del_scene = QPushButton(tr("scene.delete_button"))
        self.btn_del_scene.clicked.connect(self._action_delete_scene)
        top_row.addWidget(self.btn_del_scene)
        self.btn_set_active = QPushButton(tr("scene.activate_button"))
        self.btn_set_active.clicked.connect(self._action_set_active)
        top_row.addWidget(self.btn_set_active)
        self.btn_save = QPushButton(tr("common.save"))
        self.btn_save.clicked.connect(self._action_save)
        top_row.addWidget(self.btn_save)
        top_row.addStretch()
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #888;")
        top_row.addWidget(self.lbl_status)
        outer.addLayout(top_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, stretch=1)

        # ---- left: form panels, scrollable ----
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_inner = QWidget()
        left_layout = QVBoxLayout(left_inner)
        left_layout.setContentsMargins(4, 4, 4, 4)

        left_layout.addWidget(self._build_properties_group())
        left_layout.addWidget(self._build_background_group())
        left_layout.addWidget(self._build_tile_layers_group())
        left_layout.addWidget(self._build_objects_group())
        left_layout.addWidget(self._build_camera_group())
        left_layout.addStretch()

        left_scroll.setWidget(left_inner)
        left_scroll.setMinimumWidth(360)
        splitter.addWidget(left_scroll)

        # ---- right: composite canvas ----
        right = QWidget()
        right_layout = QVBoxLayout(right)
        canvas_tools = QHBoxLayout()
        canvas_tools.addWidget(QLabel(tr("common.zoom")))
        self.spin_zoom = QSpinBox()
        self.spin_zoom.setRange(1, 6)
        self.spin_zoom.setValue(2)
        canvas_tools.addWidget(self.spin_zoom)
        canvas_tools.addSpacing(12)
        self.btn_mode_editor = QPushButton(tr("scene.mode_editor"))
        self.btn_mode_editor.setCheckable(True)
        self.btn_mode_editor.setChecked(True)
        self.btn_mode_draw = QPushButton(tr("scene.mode_draw"))
        self.btn_mode_draw.setCheckable(True)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self.btn_mode_editor)
        self._mode_group.addButton(self.btn_mode_draw)
        self.btn_mode_draw.toggled.connect(self._on_mode_toggled)
        canvas_tools.addWidget(self.btn_mode_editor)
        canvas_tools.addWidget(self.btn_mode_draw)
        canvas_tools.addStretch()
        right_layout.addLayout(canvas_tools)

        draw_tools = QHBoxLayout()
        draw_tools.addWidget(QLabel(tr("scene.paint_layer_label")))
        self.combo_paint_layer = QComboBox()
        self.combo_paint_layer.addItem(tr("scene.paint_layer_none"), None)
        for i in range(TILE_LAYER_COUNT):
            self.combo_paint_layer.addItem(tr("scene.layer_n", n=i + 1), i)
        self.combo_paint_layer.currentIndexChanged.connect(self._on_paint_layer_combo_changed)
        draw_tools.addWidget(self.combo_paint_layer)
        draw_tools.addSpacing(12)
        self.btn_tool_brush = QPushButton(tr("scene.tool_brush"))
        self.btn_tool_brush.setCheckable(True)
        self.btn_tool_brush.setChecked(True)
        self.btn_tool_eyedropper = QPushButton(tr("scene.tool_eyedropper"))
        self.btn_tool_eyedropper.setCheckable(True)
        self.btn_tool_bucket = QPushButton(tr("scene.tool_bucket"))
        self.btn_tool_bucket.setCheckable(True)
        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        for btn, tool in (
            (self.btn_tool_brush, "brush"),
            (self.btn_tool_eyedropper, "eyedropper"),
            (self.btn_tool_bucket, "bucket"),
        ):
            btn.setIcon(_tool_icon(tool))
            btn.setIconSize(QSize(18, 18))
            self._tool_group.addButton(btn)
            draw_tools.addWidget(btn)
            btn.toggled.connect(lambda checked, t=tool: checked and self._on_paint_tool_changed(t))
        self.chk_erase = QCheckBox(tr("common.eraser"))
        draw_tools.addWidget(self.chk_erase)
        draw_tools.addSpacing(12)
        draw_tools.addWidget(QLabel(tr("scene.current_tool_label")))
        self.lbl_current_tool_icon = QLabel()
        self.lbl_current_tool_icon.setFixedSize(26, 26)
        draw_tools.addWidget(self.lbl_current_tool_icon)
        draw_tools.addStretch()
        self._update_current_tool_icon()
        self.draw_tools_row = QWidget()
        self.draw_tools_row.setLayout(draw_tools)
        right_layout.addWidget(self.draw_tools_row)

        self.tile_picker = TilePickerWidget()
        self.tile_picker.tile_selected.connect(self._on_tile_picker_selected)
        right_layout.addWidget(self.tile_picker)

        # Modo Editor por defecto: el area de pintura de tiles solo aparece en modo Dibujar.
        self.draw_tools_row.setVisible(False)
        self.tile_picker.setVisible(False)

        self.canvas = SceneCanvas()
        self.canvas.cell_clicked.connect(self._on_canvas_cell_clicked)
        self.canvas.stroke_finished.connect(self._commit_history)
        self.canvas.object_drag_started.connect(self._on_object_drag_started)
        self.canvas.object_drag_moved.connect(self._on_object_drag_moved)
        self.canvas.object_drag_finished.connect(self._on_object_drag_finished)
        self.canvas.tool_context_menu_requested.connect(self._on_canvas_context_menu)
        self.spin_zoom.valueChanged.connect(self.canvas.set_zoom)
        canvas_scroll = QScrollArea()
        canvas_scroll.setWidgetResizable(True)
        canvas_scroll.setWidget(self.canvas)
        right_layout.addWidget(canvas_scroll, stretch=1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

    def _build_properties_group(self) -> CollapsibleSection:
        section = CollapsibleSection(tr("scene.properties_group"))
        form = QFormLayout()
        section.content_layout().addLayout(form)
        self.lbl_scene_id = QLabel("—")
        form.addRow(tr("scene.id_label"), self.lbl_scene_id)
        self.combo_palette = QComboBox()
        self.combo_palette.currentTextChanged.connect(self._on_palette_changed)
        form.addRow(tr("scene.palette_label"), self.combo_palette)
        self.edit_script = QLineEdit()
        self.edit_script.editingFinished.connect(self._on_script_edited)
        form.addRow(tr("scene.script_label"), self.edit_script)
        self.spin_world_x = QSpinBox()
        self.spin_world_x.setRange(WORLD_STEPS_MIN, WORLD_STEPS_MAX)
        self.spin_world_x.valueChanged.connect(self._on_world_steps_changed)
        form.addRow(tr("scene.world_steps_x"), self.spin_world_x)
        self.spin_world_y = QSpinBox()
        self.spin_world_y.setRange(WORLD_STEPS_MIN, WORLD_STEPS_MAX)
        self.spin_world_y.valueChanged.connect(self._on_world_steps_changed)
        form.addRow(tr("scene.world_steps_y"), self.spin_world_y)
        return section

    def _build_background_group(self) -> CollapsibleSection:
        section = CollapsibleSection(tr("scene.background_group"))
        layout = section.content_layout()

        hint = QLabel(tr("scene.bg_layer_image_hint"))
        hint.setStyleSheet("color: #888;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.bg_layer_rows: list[dict[str, Any]] = []
        for i in range(4):
            lrow = QHBoxLayout()
            chk = QCheckBox(tr("scene.layer_n", n=i + 1))
            chk.toggled.connect(lambda v, idx=i: self._on_bg_layer_changed(idx))
            lrow.addWidget(chk)
            lrow.addWidget(QLabel(tr("scene.color_label")))
            spin_color = QSpinBox()
            spin_color.setRange(0, PALETTE_SIZE - 2)
            spin_color.valueChanged.connect(lambda v, idx=i: self._on_bg_layer_changed(idx))
            lrow.addWidget(spin_color)
            lrow.addWidget(QLabel(tr("scene.opacity_label")))
            spin_op = QSpinBox()
            spin_op.setRange(0, 255)
            spin_op.valueChanged.connect(lambda v, idx=i: self._on_bg_layer_changed(idx))
            lrow.addWidget(spin_op)
            layout.addLayout(lrow)

            img_row = QHBoxLayout()
            img_row.addWidget(QLabel(tr("scene.background_asset_label")))
            combo_bg = QComboBox()
            combo_bg.currentIndexChanged.connect(lambda v, idx=i: self._on_bg_layer_changed(idx))
            img_row.addWidget(combo_bg, stretch=1)
            img_row.addWidget(QLabel(tr("scene.parallax_x_label")))
            spin_px = QDoubleSpinBox()
            spin_px.setRange(0.0, 2.0)
            spin_px.setSingleStep(0.05)
            spin_px.setDecimals(2)
            spin_px.valueChanged.connect(lambda v, idx=i: self._on_bg_layer_changed(idx))
            img_row.addWidget(spin_px)
            chk_fixed = QCheckBox(tr("scene.parallax_fixed_label"))
            chk_fixed.toggled.connect(lambda v, idx=i: self._on_bg_layer_changed(idx))
            img_row.addWidget(chk_fixed)
            chk_repeat = QCheckBox(tr("scene.parallax_repeat_x_label"))
            chk_repeat.toggled.connect(lambda v, idx=i: self._on_bg_layer_changed(idx))
            img_row.addWidget(chk_repeat)
            layout.addLayout(img_row)

            row_widgets: dict[str, Any] = {
                "enabled": chk,
                "color": spin_color,
                "opacity": spin_op,
                "background": combo_bg,
                "parallax_x": spin_px,
                "fixed": chk_fixed,
                "repeat_x": chk_repeat,
            }

            if i == 0:
                # Capa base: se hornea en el mundo estatico del firmware y usa el grupo de
                # escena "Bandas de parallax" en vez de un Parallax X por capa (spec/scene-v0.md).
                disabled_hint = tr("scene.bg_layer1_parallax_disabled_hint")
                for w in (spin_px, chk_fixed, chk_repeat):
                    w.setEnabled(False)
                    w.setToolTip(disabled_hint)

                # Anidado bajo la Capa 1 (a la que aplica) y visible solo si esa capa esta
                # activada, para que sea obvio a que capa afecta (antes vivia suelto al final
                # del panel, separado de la fila que realmente controla).
                nested_row = QHBoxLayout()
                nested_row.addSpacing(20)
                self.parallax_bands_box = self._build_parallax_bands_group()
                self.parallax_bands_box.setVisible(chk.isChecked())
                chk.toggled.connect(self.parallax_bands_box.setVisible)
                nested_row.addWidget(self.parallax_bands_box, stretch=1)
                layout.addLayout(nested_row)
            else:
                # spec/scene-v1.md "Bandas propias por capas 2-4": misma idea que el grupo de
                # Capa 1 de arriba, pero anidada en esta entrada de background_layers y con su
                # propio "parallax_bands" (anula Parallax X/Fija/Repetir X de esta capa).
                nested_row = QHBoxLayout()
                nested_row.addSpacing(20)
                bands_box, bands_widgets = self._build_layer_parallax_bands_group(i)
                bands_box.setVisible(chk.isChecked())
                chk.toggled.connect(bands_box.setVisible)
                nested_row.addWidget(bands_box, stretch=1)
                layout.addLayout(nested_row)
                row_widgets["bands"] = bands_widgets

            self.bg_layer_rows.append(row_widgets)
        return section

    def _build_layer_parallax_bands_group(self, layer_idx: int) -> tuple[QGroupBox, dict[str, Any]]:
        """Grupo de bandas anidado bajo background_layers[layer_idx] (capas 2-4). Misma
        estructura que _build_parallax_bands_group (Capa 1), parametrizada por indice de
        capa; los widgets viven en `self.bg_layer_rows[layer_idx]["bands"]`, no como
        atributos sueltos, para no repetir `self.list_parallax_bands` etc. tres veces."""
        box = QGroupBox(tr("scene.parallax_group_layer_n", n=layer_idx + 1))
        layout = QVBoxLayout(box)
        hint = QLabel(tr("scene.parallax_hint_layer"))
        hint.setStyleSheet("color: #888;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        chk_enabled = QCheckBox(tr("scene.parallax_enabled_label"))
        chk_enabled.toggled.connect(lambda v, idx=layer_idx: self._on_layer_bands_enabled_toggled(idx, v))
        layout.addWidget(chk_enabled)

        list_bands = QListWidget()
        list_bands.currentRowChanged.connect(lambda v, idx=layer_idx: self._on_layer_band_selected(idx, v))
        layout.addWidget(list_bands)

        band_btn_row = QHBoxLayout()
        btn_add = QPushButton(tr("scene.parallax_add_band"))
        btn_add.clicked.connect(lambda _v, idx=layer_idx: self._action_add_layer_band(idx))
        band_btn_row.addWidget(btn_add)
        btn_remove = QPushButton(tr("scene.parallax_remove_band"))
        btn_remove.clicked.connect(lambda _v, idx=layer_idx: self._action_remove_layer_band(idx))
        band_btn_row.addWidget(btn_remove)
        layout.addLayout(band_btn_row)

        edit_form = QFormLayout()
        max_y = SCENE_PIXEL_H * WORLD_STEPS_MAX - 1
        spin_y0 = QSpinBox()
        spin_y0.setRange(0, max_y)
        spin_y0.valueChanged.connect(lambda _v, idx=layer_idx: self._on_layer_band_edited(idx))
        edit_form.addRow(tr("scene.parallax_y0_label"), spin_y0)
        spin_y1 = QSpinBox()
        spin_y1.setRange(0, max_y)
        spin_y1.valueChanged.connect(lambda _v, idx=layer_idx: self._on_layer_band_edited(idx))
        edit_form.addRow(tr("scene.parallax_y1_label"), spin_y1)
        spin_x = QDoubleSpinBox()
        spin_x.setRange(0.0, 2.0)
        spin_x.setSingleStep(0.05)
        spin_x.setDecimals(2)
        spin_x.valueChanged.connect(lambda _v, idx=layer_idx: self._on_layer_band_edited(idx))
        edit_form.addRow(tr("scene.parallax_x_label"), spin_x)
        layout.addLayout(edit_form)
        flags_row = QHBoxLayout()
        chk_fixed = QCheckBox(tr("scene.parallax_fixed_label"))
        chk_fixed.toggled.connect(lambda _v, idx=layer_idx: self._on_layer_band_edited(idx))
        flags_row.addWidget(chk_fixed)
        chk_repeat_x = QCheckBox(tr("scene.parallax_repeat_x_label"))
        chk_repeat_x.toggled.connect(lambda _v, idx=layer_idx: self._on_layer_band_edited(idx))
        flags_row.addWidget(chk_repeat_x)
        layout.addLayout(flags_row)

        widgets: dict[str, Any] = {
            "box": box,
            "enabled": chk_enabled,
            "list": list_bands,
            "add": btn_add,
            "remove": btn_remove,
            "y0": spin_y0,
            "y1": spin_y1,
            "x": spin_x,
            "fixed": chk_fixed,
            "repeat_x": chk_repeat_x,
        }
        widgets["editor_widgets"] = [list_bands, btn_add, btn_remove, spin_y0, spin_y1, spin_x, chk_fixed, chk_repeat_x]
        return box, widgets

    def _build_tile_layers_group(self) -> CollapsibleSection:
        section = CollapsibleSection(tr("scene.tile_layers_group"))
        layout = section.content_layout()
        self.tile_layer_rows: list[dict[str, Any]] = []
        for i in range(TILE_LAYER_COUNT):
            lrow = QHBoxLayout()
            chk = QCheckBox(tr("scene.layer_n_active", n=i + 1))
            chk.toggled.connect(lambda v, idx=i: self._on_tile_layer_changed(idx))
            lrow.addWidget(chk)
            combo = QComboBox()
            combo.currentTextChanged.connect(lambda v, idx=i: self._on_tile_layer_changed(idx))
            lrow.addWidget(combo, stretch=1)
            layout.addLayout(lrow)
            warning = QLabel()
            warning.setStyleSheet("color: #e0a030;")
            warning.setWordWrap(True)
            warning.setVisible(False)
            layout.addWidget(warning)
            self.tile_layer_rows.append({"enabled": chk, "tileset": combo, "warning": warning})
        hint = QLabel(tr("scene.tile_layer_hint"))
        hint.setStyleSheet("color: #888;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        coll_row = QHBoxLayout()
        coll_row.addWidget(QLabel(tr("scene.collision_layer_label")))
        self.combo_collision_layer = QComboBox()
        for i in range(TILE_LAYER_COUNT):
            self.combo_collision_layer.addItem(tr("scene.layer_n", n=i + 1), i)
        self.combo_collision_layer.currentIndexChanged.connect(self._on_collision_tile_layer_changed)
        coll_row.addWidget(self.combo_collision_layer, stretch=1)
        layout.addLayout(coll_row)
        coll_hint = QLabel(tr("scene.collision_layer_hint"))
        coll_hint.setStyleSheet("color: #888;")
        coll_hint.setWordWrap(True)
        layout.addWidget(coll_hint)
        return section

    def _update_tile_layer_warning(self, idx: int) -> None:
        widgets = self.tile_layer_rows[idx]
        warning = widgets["warning"]
        stem = widgets["tileset"].currentText().strip()
        if not stem:
            warning.setVisible(False)
            return
        try:
            data = read_tileset_file(self.project_root, stem)
        except ValueError:
            warning.setVisible(False)
            return
        tileset_px = tileset_file_pixel_dimensions(data)
        if tileset_px == self._tile_px:
            warning.setVisible(False)
            return
        warning.setText(tr("scene.tile_layer_px_mismatch", tileset_px=tileset_px, project_px=self._tile_px))
        warning.setVisible(True)

    def _build_objects_group(self) -> CollapsibleSection:
        section = CollapsibleSection(tr("scene.objects_group"))
        layout = section.content_layout()
        self.list_objects = QListWidget()
        self.list_objects.currentRowChanged.connect(self._on_object_selected)
        layout.addWidget(self.list_objects)

        add_row = QHBoxLayout()
        self.combo_add_object = QComboBox()
        add_row.addWidget(self.combo_add_object, stretch=1)
        self.btn_add_object = QPushButton(tr("scene.add_object"))
        self.btn_add_object.clicked.connect(self._action_add_object)
        add_row.addWidget(self.btn_add_object)
        self.btn_remove_object = QPushButton(tr("scene.remove_object"))
        self.btn_remove_object.clicked.connect(self._action_remove_object)
        add_row.addWidget(self.btn_remove_object)
        layout.addLayout(add_row)

        pos_row = QHBoxLayout()
        pos_row.addWidget(QLabel(tr("scene.x_label")))
        self.spin_obj_x = QSpinBox()
        self.spin_obj_x.setRange(0, SCENE_PIXEL_W * WORLD_STEPS_MAX)
        self.spin_obj_x.valueChanged.connect(self._on_object_xy_changed)
        pos_row.addWidget(self.spin_obj_x)
        pos_row.addWidget(QLabel(tr("scene.y_label")))
        self.spin_obj_y = QSpinBox()
        self.spin_obj_y.setRange(0, SCENE_PIXEL_H * WORLD_STEPS_MAX)
        self.spin_obj_y.valueChanged.connect(self._on_object_xy_changed)
        pos_row.addWidget(self.spin_obj_y)
        layout.addLayout(pos_row)
        return section

    def _build_camera_group(self) -> CollapsibleSection:
        section = CollapsibleSection(tr("scene.camera_group"))
        form = QFormLayout()
        section.content_layout().addLayout(form)
        self.combo_camera_mode = QComboBox()
        self.combo_camera_mode.addItems([CAMERA_MODE_FOLLOW, CAMERA_MODE_FIXED])
        self.combo_camera_mode.currentTextChanged.connect(self._on_camera_changed)
        form.addRow(tr("scene.mode_label"), self.combo_camera_mode)
        self.spin_cam_x = QSpinBox()
        self.spin_cam_x.setRange(0, SCENE_PIXEL_W * WORLD_STEPS_MAX)
        self.spin_cam_x.valueChanged.connect(self._on_camera_changed)
        form.addRow(tr("scene.x_label"), self.spin_cam_x)
        self.spin_cam_y = QSpinBox()
        self.spin_cam_y.setRange(0, SCENE_PIXEL_H * WORLD_STEPS_MAX)
        self.spin_cam_y.valueChanged.connect(self._on_camera_changed)
        form.addRow(tr("scene.y_label"), self.spin_cam_y)
        self.edit_cam_target = QLineEdit()
        self.edit_cam_target.setPlaceholderText(tr("scene.camera_target_placeholder"))
        self.edit_cam_target.editingFinished.connect(self._on_camera_changed)
        form.addRow(tr("scene.camera_target_label"), self.edit_cam_target)
        self.spin_cam_margin_x = QSpinBox()
        self.spin_cam_margin_x.setRange(0, VIEWPORT_PIXEL_W)
        self.spin_cam_margin_x.valueChanged.connect(self._on_camera_changed)
        form.addRow(tr("scene.margin_x_label"), self.spin_cam_margin_x)
        self.spin_cam_margin_y = QSpinBox()
        self.spin_cam_margin_y.setRange(0, VIEWPORT_PIXEL_H)
        self.spin_cam_margin_y.valueChanged.connect(self._on_camera_changed)
        form.addRow(tr("scene.margin_y_label"), self.spin_cam_margin_y)
        return section

    def _build_parallax_bands_group(self) -> QGroupBox:
        box = QGroupBox(tr("scene.parallax_group"))
        layout = QVBoxLayout(box)
        hint = QLabel(tr("scene.parallax_hint"))
        hint.setStyleSheet("color: #888;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.chk_parallax_enabled = QCheckBox(tr("scene.parallax_enabled_label"))
        self.chk_parallax_enabled.toggled.connect(self._on_parallax_enabled_toggled)
        layout.addWidget(self.chk_parallax_enabled)

        self.list_parallax_bands = QListWidget()
        self.list_parallax_bands.currentRowChanged.connect(self._on_parallax_band_selected)
        layout.addWidget(self.list_parallax_bands)

        band_btn_row = QHBoxLayout()
        self.btn_add_parallax_band = QPushButton(tr("scene.parallax_add_band"))
        self.btn_add_parallax_band.clicked.connect(self._action_add_parallax_band)
        band_btn_row.addWidget(self.btn_add_parallax_band)
        self.btn_remove_parallax_band = QPushButton(tr("scene.parallax_remove_band"))
        self.btn_remove_parallax_band.clicked.connect(self._action_remove_parallax_band)
        band_btn_row.addWidget(self.btn_remove_parallax_band)
        layout.addLayout(band_btn_row)

        edit_form = QFormLayout()
        max_y = SCENE_PIXEL_H * WORLD_STEPS_MAX - 1
        self.spin_parallax_y0 = QSpinBox()
        self.spin_parallax_y0.setRange(0, max_y)
        self.spin_parallax_y0.valueChanged.connect(self._on_parallax_band_edited)
        edit_form.addRow(tr("scene.parallax_y0_label"), self.spin_parallax_y0)
        self.spin_parallax_y1 = QSpinBox()
        self.spin_parallax_y1.setRange(0, max_y)
        self.spin_parallax_y1.valueChanged.connect(self._on_parallax_band_edited)
        edit_form.addRow(tr("scene.parallax_y1_label"), self.spin_parallax_y1)
        self.spin_parallax_x = QDoubleSpinBox()
        self.spin_parallax_x.setRange(0.0, 2.0)
        self.spin_parallax_x.setSingleStep(0.05)
        self.spin_parallax_x.setDecimals(2)
        self.spin_parallax_x.valueChanged.connect(self._on_parallax_band_edited)
        edit_form.addRow(tr("scene.parallax_x_label"), self.spin_parallax_x)
        layout.addLayout(edit_form)
        flags_row = QHBoxLayout()
        self.chk_parallax_fixed = QCheckBox(tr("scene.parallax_fixed_label"))
        self.chk_parallax_fixed.toggled.connect(self._on_parallax_band_edited)
        flags_row.addWidget(self.chk_parallax_fixed)
        self.chk_parallax_repeat_x = QCheckBox(tr("scene.parallax_repeat_x_label"))
        self.chk_parallax_repeat_x.toggled.connect(self._on_parallax_band_edited)
        flags_row.addWidget(self.chk_parallax_repeat_x)
        layout.addLayout(flags_row)

        self._parallax_editor_widgets: list[Any] = [
            self.list_parallax_bands,
            self.btn_add_parallax_band,
            self.btn_remove_parallax_band,
            self.spin_parallax_y0,
            self.spin_parallax_y1,
            self.spin_parallax_x,
            self.chk_parallax_fixed,
            self.chk_parallax_repeat_x,
        ]
        return box

    # ------------------------------------------------------------------
    # Loading state into the form
    # ------------------------------------------------------------------

    def _current_row(self) -> dict[str, Any] | None:
        if 0 <= self._current_index < len(self._scenes):
            return self._scenes[self._current_index]
        return None

    def _refresh_scene_combo(self) -> None:
        self.combo_scene.blockSignals(True)
        self.combo_scene.clear()
        for s in self._scenes:
            label = s["id"] + (tr("scene.active_suffix") if s["id"] == self._active_id else "")
            self.combo_scene.addItem(label, s["id"])
        if 0 <= self._current_index < len(self._scenes):
            self.combo_scene.setCurrentIndex(self._current_index)
        self.combo_scene.blockSignals(False)

    def _load_current_into_form(self) -> None:
        row = self._current_row()
        self._suspend = True
        try:
            self._refresh_palette_combo(row)
            if row is None:
                self.lbl_scene_id.setText("—")
                self.list_objects.clear()
                self.canvas.set_frame(QImage(), 0, 0)
                return
            self.lbl_scene_id.setText(row["id"])
            self.edit_script.setText(str(row.get("script", "")))
            self.spin_world_x.setValue(int(row.get("world_steps_x", 1)))
            self.spin_world_y.setValue(int(row.get("world_steps_y", 1)))

            palette_rel = str(row.get("palette", ""))
            self._load_bg_layers(row, palette_rel=palette_rel)
            self._refresh_tileset_combos(palette_rel)
            self._load_tile_layers(row)
            self._refresh_object_combo(palette_rel)
            self._load_objects(row)
            self._load_camera(row)
            self._load_parallax_bands(row)
        finally:
            self._suspend = False
        self._refresh_tile_picker()
        self._refresh_canvas()

    def _refresh_palette_combo(self, row: dict[str, Any] | None) -> None:
        self.combo_palette.blockSignals(True)
        self.combo_palette.clear()
        rels = list_palette_relpaths(self.project_root)
        self.combo_palette.addItems(rels)
        if row is not None:
            pal = str(row.get("palette", ""))
            idx = self.combo_palette.findText(pal)
            if idx < 0 and pal:
                self.combo_palette.addItem(pal)
                idx = self.combo_palette.findText(pal)
            self.combo_palette.setCurrentIndex(max(0, idx))
        self.combo_palette.blockSignals(False)

    def _refresh_bg_layer_combos(self, palette_rel: str) -> None:
        stems = list_background_stems_for_palette(self.project_root, palette_rel)
        for widgets in self.bg_layer_rows:
            combo = widgets["background"]
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(tr("scene.no_background"), "")
            for stem in stems:
                combo.addItem(stem, stem)
            idx = combo.findData(current)
            combo.setCurrentIndex(max(0, idx))
            combo.blockSignals(False)

    def _load_bg_layers(self, row: dict[str, Any], *, palette_rel: str) -> None:
        self._refresh_bg_layer_combos(palette_rel)
        layers = row.get("background_layers") or []
        for i, widgets in enumerate(self.bg_layer_rows):
            d = layers[i] if i < len(layers) and isinstance(layers[i], dict) else {}
            uniform_widgets = [w for k, w in widgets.items() if k != "bands"]
            for w in uniform_widgets:
                w.blockSignals(True)
            widgets["enabled"].setChecked(bool(d.get("enabled")))
            widgets["color"].setValue(int(d.get("color_index", 1)))
            widgets["opacity"].setValue(int(d.get("opacity", 255)))
            idx = widgets["background"].findData(str(d.get("background", "")))
            widgets["background"].setCurrentIndex(max(0, idx))
            widgets["parallax_x"].setValue(float(d.get("parallax_x", 1.0)))
            widgets["fixed"].setChecked(bool(d.get("fixed", False)))
            widgets["repeat_x"].setChecked(bool(d.get("repeat_x", False)))
            for w in uniform_widgets:
                w.blockSignals(False)
            if i == 0:
                self.parallax_bands_box.setVisible(widgets["enabled"].isChecked())
            else:
                self._load_layer_bands(i, d)
                widgets["bands"]["box"].setVisible(widgets["enabled"].isChecked())

    def _refresh_tileset_combos(self, palette_rel: str) -> None:
        stems = list_tileset_stems_for_palette(self.project_root, palette_rel)
        for widgets in self.tile_layer_rows:
            combo = widgets["tileset"]
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("", "")
            combo.addItems(stems)
            idx = combo.findText(current)
            combo.setCurrentIndex(max(0, idx))
            combo.blockSignals(False)

    def _load_tile_layers(self, row: dict[str, Any]) -> None:
        layers = row.get("tile_layers") or []
        for i, widgets in enumerate(self.tile_layer_rows):
            d = layers[i] if i < len(layers) and isinstance(layers[i], dict) else {}
            widgets["enabled"].blockSignals(True)
            widgets["enabled"].setChecked(bool(d.get("enabled")))
            widgets["enabled"].blockSignals(False)
            combo = widgets["tileset"]
            combo.blockSignals(True)
            ts = str(d.get("tileset", ""))
            idx = combo.findText(ts)
            if idx < 0 and ts:
                combo.addItem(ts)
                idx = combo.findText(ts)
            combo.setCurrentIndex(max(0, idx))
            combo.blockSignals(False)
            self._update_tile_layer_warning(i)
        self._load_collision_layer(row)

    def _load_collision_layer(self, row: dict[str, Any]) -> None:
        layer = normalize_collision_tile_layer(row.get("collision_tile_layer", 0))
        self.combo_collision_layer.blockSignals(True)
        idx = self.combo_collision_layer.findData(layer)
        self.combo_collision_layer.setCurrentIndex(max(0, idx))
        self.combo_collision_layer.blockSignals(False)

    def _refresh_object_combo(self, palette_rel: str) -> None:
        self.combo_add_object.blockSignals(True)
        self.combo_add_object.clear()
        self.combo_add_object.addItems(list_object_ids_for_scene_palette(self.project_root, palette_rel))
        self.combo_add_object.blockSignals(False)

    def _load_objects(self, row: dict[str, Any]) -> None:
        self.list_objects.blockSignals(True)
        self.list_objects.clear()
        for p in row.get("objects") or []:
            if not isinstance(p, dict):
                continue
            self.list_objects.addItem(f"{p.get('id', '')}  ({p.get('x', 0)}, {p.get('y', 0)})")
        self.list_objects.blockSignals(False)

    def _load_camera(self, row: dict[str, Any]) -> None:
        cam = row.get("camera") or {}
        self.combo_camera_mode.blockSignals(True)
        self.spin_cam_x.blockSignals(True)
        self.spin_cam_y.blockSignals(True)
        self.edit_cam_target.blockSignals(True)
        self.spin_cam_margin_x.blockSignals(True)
        self.spin_cam_margin_y.blockSignals(True)
        idx = self.combo_camera_mode.findText(str(cam.get("mode", CAMERA_MODE_FOLLOW)))
        self.combo_camera_mode.setCurrentIndex(max(0, idx))
        self.spin_cam_x.setValue(int(cam.get("x", 0)))
        self.spin_cam_y.setValue(int(cam.get("y", 0)))
        self.edit_cam_target.setText(str(cam.get("target", "")))
        self.spin_cam_margin_x.setValue(int(cam.get("margin_x", 64)))
        self.spin_cam_margin_y.setValue(int(cam.get("margin_y", 48)))
        self.combo_camera_mode.blockSignals(False)
        self.spin_cam_x.blockSignals(False)
        self.spin_cam_y.blockSignals(False)
        self.edit_cam_target.blockSignals(False)
        self.spin_cam_margin_x.blockSignals(False)
        self.spin_cam_margin_y.blockSignals(False)

    @staticmethod
    def _parallax_band_summary(d: dict[str, Any]) -> str:
        y0 = int(d.get("y0", 0))
        y1 = int(d.get("y1", 0))
        px = float(d.get("parallax_x", 1.0))
        extra = []
        if d.get("fixed"):
            extra.append(tr("scene.parallax_fixed_label"))
        if d.get("repeat_x"):
            extra.append(tr("scene.parallax_repeat_x_label"))
        suffix = f"  ({', '.join(extra)})" if extra else ""
        return f"Y {y0}-{y1}  x{px:.2f}{suffix}"

    def _set_parallax_controls_enabled(self, enabled: bool) -> None:
        for w in self._parallax_editor_widgets:
            w.setEnabled(enabled)
        if not enabled:
            self._load_parallax_band_editor(None)

    def _load_parallax_band_editor(self, d: dict[str, Any] | None) -> None:
        """Rellena el sub-panel de edicion con la banda `d` seleccionada, o lo limpia/
        deshabilita si `d` es None (nada seleccionado en la lista)."""
        widgets = (
            self.spin_parallax_y0,
            self.spin_parallax_y1,
            self.spin_parallax_x,
            self.chk_parallax_fixed,
            self.chk_parallax_repeat_x,
        )
        for w in widgets:
            w.blockSignals(True)
        vals = d or {}
        self.spin_parallax_y0.setValue(int(vals.get("y0", 0)))
        self.spin_parallax_y1.setValue(int(vals.get("y1", 0)))
        self.spin_parallax_x.setValue(float(vals.get("parallax_x", 1.0)))
        self.chk_parallax_fixed.setChecked(bool(vals.get("fixed", False)))
        self.chk_parallax_repeat_x.setChecked(bool(vals.get("repeat_x", False)))
        for w in widgets:
            w.blockSignals(False)
            w.setEnabled(d is not None and self.chk_parallax_enabled.isChecked())

    def _load_parallax_bands(self, row: dict[str, Any]) -> None:
        bands = row.get("parallax_bands")
        has_bands = isinstance(bands, list)
        self.chk_parallax_enabled.blockSignals(True)
        self.chk_parallax_enabled.setChecked(has_bands)
        self.chk_parallax_enabled.blockSignals(False)
        self.list_parallax_bands.blockSignals(True)
        self.list_parallax_bands.clear()
        if has_bands:
            for d in bands:
                if isinstance(d, dict):
                    self.list_parallax_bands.addItem(self._parallax_band_summary(d))
        self.list_parallax_bands.blockSignals(False)
        self._set_parallax_controls_enabled(has_bands)
        self._load_parallax_band_editor(None)

    def _refresh_tile_picker(self) -> None:
        row = self._current_row()
        if row is None or self._paint_layer is None:
            self.tile_picker.clear()
            return
        layers = row.get("tile_layers") or []
        if self._paint_layer >= len(layers):
            self.tile_picker.clear()
            return
        stem = str(layers[self._paint_layer].get("tileset", "")).strip()
        if not stem:
            self.tile_picker.clear()
            return
        try:
            data = read_tileset_file(self.project_root, stem)
        except ValueError:
            self.tile_picker.clear()
            return
        tiles = parse_tileset_all_tiles(data, fill_index=1)
        palette_rel = str(row.get("palette", ""))
        pal_path = (self.project_root / palette_rel).resolve() if palette_rel else None
        rgbs, _ = load_palette_rgb01_for_preview(pal_path if pal_path and pal_path.is_file() else None)
        self.tile_picker.set_tiles(tiles, rgbs)
        self.tile_picker.select_index(min(self._paint_tile_index, len(tiles) - 1) if tiles else 0)

    def _tile_cache_signature(self, row: dict[str, Any]) -> tuple[Any, ...]:
        """Firma barata de todo lo que invalida el cache de render de tiles por bloque
        entero (a diferencia de una sola celda pintada, que se invalida quirurgicamente
        en _on_canvas_cell_clicked): tamano de mundo, tile_px, y por capa enabled+tileset
        (el contenido de celdas NO entra aca a proposito -- eso es justo lo que el cache
        por bloque existe para no tener que invalidar entero)."""
        layers = row.get("tile_layers") or []
        layer_sig = tuple(
            (bool(ly.get("enabled")), str(ly.get("tileset", ""))) if isinstance(ly, dict) else (False, "")
            for ly in layers
        )
        return (
            int(row.get("world_steps_x", 1)),
            int(row.get("world_steps_y", 1)),
            self._tile_px,
            layer_sig,
        )

    def _refresh_canvas(self) -> None:
        row = self._current_row()
        if row is None:
            self.canvas.set_frame(QImage(), 0, 0)
            self.canvas.paintable = False
            self.canvas.object_mode = False
            return
        sig = self._tile_cache_signature(row)
        if sig != self._tile_cache_signature_value:
            self._tile_block_cache.clear()
            self._tile_cache_signature_value = sig
        selected_band = self.list_parallax_bands.currentRow()
        selected_object = self.list_objects.currentRow()
        rgba, fw, fh = render_scene_rgba(
            self.project_root,
            row,
            self._tile_px,
            viewport_w=self._viewport_w,
            viewport_h=self._viewport_h,
            paint_layer_index=self._paint_layer,
            hover_cell=self._hover_cell,
            selected_parallax_band_index=selected_band if selected_band >= 0 else None,
            selected_object_index=selected_object if selected_object >= 0 else None,
            tile_block_cache=self._tile_block_cache,
        )
        img = _rgba_floats_to_qimage(rgba, fw, fh)
        self.canvas.set_frame(img, fw, fh)
        self.canvas.paintable = self._paint_layer is not None
        self.canvas.object_mode = self._paint_layer is None

    def _mark_dirty(self) -> None:
        self._dirty = True
        self.lbl_status.setText(tr("common.unsaved_changes"))
        # Un checkpoint por mark_dirty basta en toda la escena EXCEPTO el pincel de
        # tiles al arrastrar (_on_canvas_cell_clicked evita llamar a _mark_dirty por
        # celda y usa SceneCanvas.stroke_finished en su lugar -- ver mas abajo).
        self._commit_history()

    # ------------------------------------------------------------------
    # Undo/redo
    # ------------------------------------------------------------------

    def _snapshot(self) -> dict[str, Any] | None:
        return self._current_row()

    def _commit_history(self) -> None:
        if self._restoring:
            return
        row = self._current_row()
        if row is not None:
            self._history.commit(row)

    def _restore(self, state: dict[str, Any]) -> None:
        self._restoring = True
        try:
            self._scenes[self._current_index] = state
            self._load_current_into_form()
        finally:
            self._restoring = False
        self._dirty = True
        self.lbl_status.setText(tr("common.unsaved_changes"))

    def undo(self) -> None:
        state = self._history.undo()
        if state is not None:
            self._restore(state)

    def redo(self) -> None:
        state = self._history.redo()
        if state is not None:
            self._restore(state)

    # ------------------------------------------------------------------
    # Slots — scene management
    # ------------------------------------------------------------------

    def _on_scene_combo_changed(self, index: int) -> None:
        if self._suspend or index < 0:
            return
        self._current_index = index
        self._paint_layer = None
        self.combo_paint_layer.blockSignals(True)
        self.combo_paint_layer.setCurrentIndex(0)
        self.combo_paint_layer.blockSignals(False)
        self._load_current_into_form()
        self._history.reset(self._snapshot())

    def _action_new_scene(self) -> None:
        sid, ok = QInputDialog.getText(self, tr("scene.new_scene_title"), tr("scene.new_scene_id_label"))
        if not ok or not sid.strip():
            return
        sid = sid.strip()
        if any(s["id"] == sid for s in self._scenes):
            QMessageBox.warning(self, tr("scene.new_scene_title"), tr("scene.new_scene_exists", sid=repr(sid)))
            return
        rels = list_palette_relpaths(self.project_root)
        if not rels:
            QMessageBox.warning(self, tr("scene.new_scene_title"), tr("common.no_palettes"))
            return
        pal, ok = QInputDialog.getItem(self, tr("scene.new_scene_title"), tr("scene.palette_label"), rels, 0, False)
        if not ok:
            return
        self._scenes.append(_new_scene_row(sid, pal, self._tile_px))
        self._current_index = len(self._scenes) - 1
        self._mark_dirty()
        self._refresh_scene_combo()
        self._load_current_into_form()
        self._history.reset(self._snapshot())

    def _action_delete_scene(self) -> None:
        row = self._current_row()
        if row is None:
            return
        if len(self._scenes) <= 1:
            QMessageBox.warning(self, tr("scene.delete_confirm_title"), tr("scene.delete_min_scenes"))
            return
        if (
            QMessageBox.question(self, tr("scene.delete_confirm_title"), tr("scene.delete_confirm_msg", sid=repr(row["id"])))
            != QMessageBox.StandardButton.Yes
        ):
            return
        del self._scenes[self._current_index]
        if self._active_id == row["id"]:
            self._active_id = self._scenes[0]["id"]
        self._current_index = min(self._current_index, len(self._scenes) - 1)
        self._mark_dirty()
        self._refresh_scene_combo()
        self._load_current_into_form()
        self._history.reset(self._snapshot())

    def _action_set_active(self) -> None:
        row = self._current_row()
        if row is None:
            return
        self._active_id = row["id"]
        self._mark_dirty()
        self._refresh_scene_combo()

    # ------------------------------------------------------------------
    # Slots — properties
    # ------------------------------------------------------------------

    def _on_palette_changed(self, text: str) -> None:
        if self._suspend:
            return
        row = self._current_row()
        if row is None or not text:
            return
        row["palette"] = text
        self._mark_dirty()
        self._refresh_bg_layer_combos(text)
        self._refresh_tileset_combos(text)
        self._refresh_object_combo(text)
        self._refresh_tile_picker()
        self._refresh_canvas()

    def _on_script_edited(self) -> None:
        row = self._current_row()
        if row is None:
            return
        row["script"] = self.edit_script.text().strip() or row["id"]
        self._mark_dirty()

    def _on_world_steps_changed(self, _value: int) -> None:
        if self._suspend:
            return
        row = self._current_row()
        if row is None:
            return
        row["world_steps_x"] = self.spin_world_x.value()
        row["world_steps_y"] = self.spin_world_y.value()
        ww, wh = scene_world_pixel_size(
            row["world_steps_x"], row["world_steps_y"], base_w=self._viewport_w, base_h=self._viewport_h
        )
        layers = parse_tile_layers(row.get("tile_layers"), tile_px=self._tile_px, world_w=ww, world_h=wh)
        row["tile_layers"] = tile_layers_to_json_list(layers)
        if isinstance(row.get("parallax_bands"), list):
            # Reacota y0/y1 al nuevo alto de mundo; no usar apply_scene_parallax_bands_to_row
            # aqui porque una lista vacia (bandas activas pero sin ninguna aun) borraria el
            # campo entero y desactivaria sin querer el checkbox del grupo.
            bands = parse_scene_parallax_bands_from_row(row, world_h=wh)
            row["parallax_bands"] = scene_parallax_bands_to_json(bands)
        self._load_parallax_bands(row)
        self._mark_dirty()
        self._refresh_canvas()

    # ------------------------------------------------------------------
    # Slots — background
    # ------------------------------------------------------------------

    def _on_bg_layer_changed(self, _index: int) -> None:
        if self._suspend:
            return
        row = self._current_row()
        if row is None:
            return
        # Este handler reconstruye las 4 entradas enteras a partir de los widgets uniformes
        # cada vez que cualquiera de ellos cambia -- "parallax_bands" (capas 2-4) no tiene
        # widget uniforme propio, asi que hay que preservarlo de la entrada existente o se
        # perderia con la primera edicion de color/opacidad/etc. de esa capa.
        existing = row.get("background_layers") or []
        layers = []
        for i, widgets in enumerate(self.bg_layer_rows):
            d: dict[str, Any] = {
                "enabled": widgets["enabled"].isChecked(),
                "color_index": widgets["color"].value(),
                "opacity": widgets["opacity"].value(),
                "background": widgets["background"].currentData() or "",
                "parallax_x": widgets["parallax_x"].value(),
                "fixed": widgets["fixed"].isChecked(),
                "repeat_x": widgets["repeat_x"].isChecked(),
            }
            if i < len(existing) and isinstance(existing[i], dict):
                prev_bands = existing[i].get("parallax_bands")
                if isinstance(prev_bands, list):
                    d["parallax_bands"] = prev_bands
            layers.append(d)
        row["background_layers"] = layers
        self._mark_dirty()
        self._refresh_canvas()

    def _layer_band_widgets(self, layer_idx: int) -> dict[str, Any]:
        return self.bg_layer_rows[layer_idx]["bands"]

    def _load_layer_bands(self, layer_idx: int, d: dict[str, Any]) -> None:
        w = self._layer_band_widgets(layer_idx)
        bands = d.get("parallax_bands")
        has_bands = isinstance(bands, list)
        w["enabled"].blockSignals(True)
        w["enabled"].setChecked(has_bands)
        w["enabled"].blockSignals(False)
        w["list"].blockSignals(True)
        w["list"].clear()
        if has_bands:
            for b in bands:
                if isinstance(b, dict):
                    w["list"].addItem(self._parallax_band_summary(b))
        w["list"].blockSignals(False)
        self._set_layer_band_controls_enabled(layer_idx, has_bands)
        self._load_layer_band_editor(layer_idx, None)

    def _set_layer_band_controls_enabled(self, layer_idx: int, enabled: bool) -> None:
        w = self._layer_band_widgets(layer_idx)
        for widget in w["editor_widgets"]:
            widget.setEnabled(enabled)
        if not enabled:
            self._load_layer_band_editor(layer_idx, None)

    def _load_layer_band_editor(self, layer_idx: int, d: dict[str, Any] | None) -> None:
        w = self._layer_band_widgets(layer_idx)
        fields = (w["y0"], w["y1"], w["x"], w["fixed"], w["repeat_x"])
        for widget in fields:
            widget.blockSignals(True)
        vals = d or {}
        w["y0"].setValue(int(vals.get("y0", 0)))
        w["y1"].setValue(int(vals.get("y1", 0)))
        w["x"].setValue(float(vals.get("parallax_x", 1.0)))
        w["fixed"].setChecked(bool(vals.get("fixed", False)))
        w["repeat_x"].setChecked(bool(vals.get("repeat_x", False)))
        for widget in fields:
            widget.blockSignals(False)
            widget.setEnabled(d is not None and w["enabled"].isChecked())

    def _bands_enabled_layer_count(self, row: dict[str, Any]) -> int:
        """Capas (0-4) con bandas de parallax activas -- capa 1 via row["parallax_bands"],
        capas 2-4 via su propio background_layers[i]["parallax_bands"] (spec/scene-v1.md)."""
        count = 1 if isinstance(row.get("parallax_bands"), list) else 0
        layers = row.get("background_layers")
        if isinstance(layers, list):
            for i, ly in enumerate(layers):
                if i == 0 or not isinstance(ly, dict):
                    continue
                if isinstance(ly.get("parallax_bands"), list):
                    count += 1
        return count

    def _warn_if_multiple_bands_layers(self) -> None:
        row = self._current_row()
        if row is None:
            return
        if self._bands_enabled_layer_count(row) > 1:
            QMessageBox.warning(
                self, tr("scene.parallax_group"), tr("scene.parallax_multi_layer_perf_warning")
            )

    def _on_layer_bands_enabled_toggled(self, layer_idx: int, checked: bool) -> None:
        if self._suspend:
            return
        row = self._current_row()
        if row is None:
            return
        layers = row.get("background_layers")
        if not isinstance(layers, list) or layer_idx >= len(layers):
            return
        d = layers[layer_idx]
        if not isinstance(d, dict):
            return
        if checked:
            if not isinstance(d.get("parallax_bands"), list):
                d["parallax_bands"] = []
        else:
            d.pop("parallax_bands", None)
        self._mark_dirty()
        self._load_layer_bands(layer_idx, d)
        self._refresh_canvas()
        if checked:
            self._warn_if_multiple_bands_layers()

    def _action_add_layer_band(self, layer_idx: int) -> None:
        row = self._current_row()
        if row is None:
            return
        layers = row.get("background_layers")
        if not isinstance(layers, list) or layer_idx >= len(layers):
            return
        d = layers[layer_idx]
        bands = d.get("parallax_bands") if isinstance(d, dict) else None
        if not isinstance(bands, list):
            return
        if len(bands) >= MAX_PARALLAX_BANDS:
            QMessageBox.warning(
                self, tr("scene.parallax_group"), tr("scene.parallax_max_bands", n=MAX_PARALLAX_BANDS)
            )
            return
        wh = self._parallax_world_h(row)
        bands.append(scene_parallax_band_to_json(clamp_parallax_band(SceneParallaxBand(), world_h=wh)))
        self._mark_dirty()
        self._load_layer_bands(layer_idx, d)
        self._layer_band_widgets(layer_idx)["list"].setCurrentRow(len(bands) - 1)
        self._refresh_canvas()

    def _action_remove_layer_band(self, layer_idx: int) -> None:
        row = self._current_row()
        if row is None:
            return
        layers = row.get("background_layers")
        if not isinstance(layers, list) or layer_idx >= len(layers):
            return
        d = layers[layer_idx]
        bands = d.get("parallax_bands") if isinstance(d, dict) else None
        if not isinstance(bands, list):
            return
        idx = self._layer_band_widgets(layer_idx)["list"].currentRow()
        if 0 <= idx < len(bands):
            del bands[idx]
            self._mark_dirty()
            self._load_layer_bands(layer_idx, d)
            self._refresh_canvas()

    def _on_layer_band_selected(self, layer_idx: int, index: int) -> None:
        row = self._current_row()
        if row is None:
            return
        layers = row.get("background_layers")
        d = layers[layer_idx] if isinstance(layers, list) and layer_idx < len(layers) else None
        bands = d.get("parallax_bands") if isinstance(d, dict) else None
        band = bands[index] if isinstance(bands, list) and 0 <= index < len(bands) else None
        self._load_layer_band_editor(layer_idx, band)

    def _on_layer_band_edited(self, layer_idx: int, *_args: Any) -> None:
        row = self._current_row()
        if row is None:
            return
        layers = row.get("background_layers")
        if not isinstance(layers, list) or layer_idx >= len(layers):
            return
        d = layers[layer_idx]
        bands = d.get("parallax_bands") if isinstance(d, dict) else None
        w = self._layer_band_widgets(layer_idx)
        idx = w["list"].currentRow()
        if not isinstance(bands, list) or not (0 <= idx < len(bands)):
            return
        wh = self._parallax_world_h(row)
        raw = SceneParallaxBand(
            y0=w["y0"].value(),
            y1=w["y1"].value(),
            parallax_x=w["x"].value(),
            fixed=w["fixed"].isChecked(),
            repeat_x=w["repeat_x"].isChecked(),
        )
        bands[idx] = scene_parallax_band_to_json(clamp_parallax_band(raw, world_h=wh))
        w["list"].blockSignals(True)
        w["list"].item(idx).setText(self._parallax_band_summary(bands[idx]))
        w["list"].blockSignals(False)
        self._mark_dirty()
        self._refresh_canvas()

    # ------------------------------------------------------------------
    # Slots — tile layers / painting
    # ------------------------------------------------------------------

    def _on_tile_layer_changed(self, _index: int) -> None:
        if self._suspend:
            return
        row = self._current_row()
        if row is None:
            return
        layers = row.get("tile_layers") or []
        for i, widgets in enumerate(self.tile_layer_rows):
            self._update_tile_layer_warning(i)
            if i >= len(layers):
                continue
            layers[i]["enabled"] = widgets["enabled"].isChecked()
            layers[i]["tileset"] = widgets["tileset"].currentText()
        self._mark_dirty()
        if self._paint_layer is not None:
            self._refresh_tile_picker()
        self._refresh_canvas()

    def _on_collision_tile_layer_changed(self, _index: int) -> None:
        if self._suspend:
            return
        row = self._current_row()
        if row is None:
            return
        row["collision_tile_layer"] = normalize_collision_tile_layer(
            self.combo_collision_layer.currentData()
        )
        self._mark_dirty()

    def _on_mode_toggled(self, draw_checked: bool) -> None:
        self.draw_tools_row.setVisible(draw_checked)
        self.tile_picker.setVisible(draw_checked)
        if draw_checked:
            if self.combo_paint_layer.currentData() is None:
                # Sin esto la combo se queda en "Ninguna (solo vista)" y ninguna
                # herramienta (pincel incluido) pinta hasta elegir capa a mano --
                # entrar en modo Dibujar debe dejar el pincel listo de inmediato.
                self.combo_paint_layer.setCurrentIndex(self._first_paintable_layer_combo_index())
            return
        # Volver a modo Editor: se sale de pintura de tiles, sin importar la capa elegida.
        self.combo_paint_layer.blockSignals(True)
        self.combo_paint_layer.setCurrentIndex(0)
        self.combo_paint_layer.blockSignals(False)
        self._paint_layer = None
        self._hover_cell = None
        self._refresh_tile_picker()
        self._refresh_canvas()

    def _first_paintable_layer_combo_index(self) -> int:
        """combo_paint_layer index for the first tile layer with a tileset assigned,
        falling back to Layer 1 (index 1) if none has one yet."""
        row = self._current_row()
        layers = row.get("tile_layers") if row else None
        if isinstance(layers, list):
            for i, ld in enumerate(layers):
                if isinstance(ld, dict) and str(ld.get("tileset", "")).strip():
                    return i + 1
        return 1 if self.combo_paint_layer.count() > 1 else 0

    def _on_paint_tool_changed(self, tool: str) -> None:
        self._paint_tool = tool
        # El borrador solo tiene sentido pintando (pincel/cubo); el cuentagotas solo lee.
        self.chk_erase.setEnabled(tool != "eyedropper")
        self._update_current_tool_icon()

    def _update_current_tool_icon(self) -> None:
        self.lbl_current_tool_icon.setPixmap(_tool_icon(self._paint_tool, size=24).pixmap(QSize(24, 24)))

    def _tool_menu_specs(self) -> tuple[tuple[str, str, QPushButton], ...]:
        return (
            ("brush", "scene.tool_brush", self.btn_tool_brush),
            ("eyedropper", "scene.tool_eyedropper", self.btn_tool_eyedropper),
            ("bucket", "scene.tool_bucket", self.btn_tool_bucket),
        )

    def _build_tool_menu(self) -> tuple[QMenu, dict[Any, QPushButton]]:
        menu = QMenu(self)
        action_to_button: dict[Any, QPushButton] = {}
        for tool, label_key, btn in self._tool_menu_specs():
            act = menu.addAction(_tool_icon(tool), tr(label_key))
            act.setCheckable(True)
            act.setChecked(self._paint_tool == tool)
            action_to_button[act] = btn
        return menu, action_to_button

    def _on_canvas_context_menu(self, global_pos: Any) -> None:
        # Solo tiene sentido en modo Dibujar pintando una capa -- coincide con
        # self.canvas.paintable, que ya filtra el evento antes de emitir la senal.
        menu, action_to_button = self._build_tool_menu()
        chosen = menu.exec(global_pos)
        if chosen is not None and chosen in action_to_button:
            action_to_button[chosen].setChecked(True)

    def _on_paint_layer_combo_changed(self, _index: int) -> None:
        self._paint_layer = self.combo_paint_layer.currentData()
        self._hover_cell = None
        self._refresh_tile_picker()
        self._refresh_canvas()

    def _on_tile_picker_selected(self, index: int) -> None:
        self._paint_tile_index = index

    def _on_canvas_cell_clicked(self, sx: int, sy: int) -> None:
        row = self._current_row()
        if row is None or self._paint_layer is None:
            return
        layers = row.get("tile_layers") or []
        if self._paint_layer >= len(layers):
            return
        layer = layers[self._paint_layer]
        ws_x = int(row.get("world_steps_x", 1))
        ws_y = int(row.get("world_steps_y", 1))
        ww, wh = scene_world_pixel_size(ws_x, ws_y, base_w=self._viewport_w, base_h=self._viewport_h)
        cell = scene_coords_to_cell(sx, sy, tile_px=self._tile_px, world_w=ww, world_h=wh)
        if cell is None:
            return
        gx, gy = cell
        cells = layer.get("cells")
        if not isinstance(cells, list):
            return

        if self._paint_tool == "eyedropper":
            picked = get_cell_index(cells, gx, gy)
            if picked is not None and not is_transparent_palette_index(picked):
                self._paint_tile_index = picked
                self.tile_picker.select_index(picked)
            return

        tile_index = TRANSPARENT_PALETTE_INDEX if self.chk_erase.isChecked() else self._paint_tile_index
        if self._paint_tool == "bucket":
            flood_fill_cell_index(cells, gx, gy, tile_index)
            # El balde puede tocar celdas repartidas por varios bloques del cache; no
            # vale la pena rastrear cuales -- es un solo click, no el arrastre repetido
            # que el cache por bloque esta pensado para acelerar.
            self._tile_block_cache.clear()
        else:
            set_cell_index(cells, gx, gy, tile_index)
            # Pincel/borrador: se dispara un cell_clicked por celda tocada al arrastrar
            # -- invalidar solo el bloque de esa celda (no todo el cache) es lo que hace
            # que un trazo largo en un mundo de 8x8 pasos no re-camine los otros ~63
            # bloques en cada evento.
            self._tile_block_cache.pop(tile_block_key(gx, gy), None)
        # No _mark_dirty() aqui a proposito: se emite un cell_clicked por celda
        # tocada al arrastrar, y un checkpoint de historial por celda haria falta un
        # Ctrl+Z por celda para deshacer un solo trazo. SceneCanvas.stroke_finished
        # (mouseReleaseEvent) hace el commit una sola vez al soltar el boton.
        self._dirty = True
        self.lbl_status.setText(tr("common.unsaved_changes"))
        self._refresh_canvas()

    # ------------------------------------------------------------------
    # Slots — objects
    # ------------------------------------------------------------------

    def _action_add_object(self) -> None:
        row = self._current_row()
        if row is None:
            return
        oid = self.combo_add_object.currentText().strip()
        if not oid:
            return
        objs = row.get("objects")
        if not isinstance(objs, list):
            objs = []
            row["objects"] = objs
        objs.append({"id": oid, "x": self._viewport_w // 2, "y": self._viewport_h // 2})
        self._mark_dirty()
        self._load_objects(row)
        self._refresh_canvas()

    def _action_remove_object(self) -> None:
        row = self._current_row()
        if row is None:
            return
        idx = self.list_objects.currentRow()
        objs = row.get("objects") or []
        if 0 <= idx < len(objs):
            del objs[idx]
            self._mark_dirty()
            self._load_objects(row)
            self._refresh_canvas()

    def _on_object_selected(self, index: int) -> None:
        row = self._current_row()
        if row is None:
            return
        objs = row.get("objects") or []
        if 0 <= index < len(objs):
            p = objs[index]
            self.spin_obj_x.blockSignals(True)
            self.spin_obj_y.blockSignals(True)
            self.spin_obj_x.setValue(int(p.get("x", 0)))
            self.spin_obj_y.setValue(int(p.get("y", 0)))
            self.spin_obj_x.blockSignals(False)
            self.spin_obj_y.blockSignals(False)
        self._refresh_canvas()

    def _on_object_xy_changed(self, _value: int) -> None:
        row = self._current_row()
        if row is None:
            return
        idx = self.list_objects.currentRow()
        objs = row.get("objects") or []
        if not (0 <= idx < len(objs)):
            return
        objs[idx]["x"] = self.spin_obj_x.value()
        objs[idx]["y"] = self.spin_obj_y.value()
        self.list_objects.blockSignals(True)
        self.list_objects.item(idx).setText(f"{objs[idx]['id']}  ({objs[idx]['x']}, {objs[idx]['y']})")
        self.list_objects.blockSignals(False)
        self._mark_dirty()
        self._refresh_canvas()

    def _object_at_scene_xy(self, row: dict[str, Any], sx: int, sy: int) -> int | None:
        """Topmost placed object whose sprite bbox contains (sx, sy), or None.
        Iterates back-to-front since later entries in "objects" draw on top
        (see _paint_scene_objects) -- a click should hit whatever is visible."""
        placements = row.get("objects") or []
        for idx in range(len(placements) - 1, -1, -1):
            p = placements[idx]
            if not isinstance(p, dict):
                continue
            oid = str(p.get("id", "")).strip()
            if not oid:
                continue
            try:
                ox = int(p.get("x", 0))
                oy = int(p.get("y", 0))
            except (TypeError, ValueError):
                continue
            info = _resolve_object_sprite_preview(self.project_root, oid)
            bx, by = sprite_blit_bottom_left(ox, oy, int(info["origin_x"]), int(info["origin_y"]))
            pw, ph = int(info["pw"]), int(info["ph"])
            if bx <= sx < bx + pw and by <= sy < by + ph:
                return idx
        return None

    def _on_object_drag_started(self, sx: int, sy: int) -> None:
        row = self._current_row()
        self._dragging_object_index = None
        self._drag_offset = None
        if row is None:
            return
        idx = self._object_at_scene_xy(row, sx, sy)
        if idx is None:
            return
        objs = row.get("objects") or []
        p = objs[idx]
        self._dragging_object_index = idx
        self._drag_offset = (sx - int(p.get("x", 0)), sy - int(p.get("y", 0)))
        self.list_objects.blockSignals(True)
        self.list_objects.setCurrentRow(idx)
        self.list_objects.blockSignals(False)
        self._on_object_selected(idx)

    def _on_object_drag_moved(self, sx: int, sy: int) -> None:
        if self._dragging_object_index is None or self._drag_offset is None:
            return
        row = self._current_row()
        if row is None:
            return
        objs = row.get("objects") or []
        idx = self._dragging_object_index
        if not (0 <= idx < len(objs)):
            return
        ws_x = int(row.get("world_steps_x", 1))
        ws_y = int(row.get("world_steps_y", 1))
        ww, wh = scene_world_pixel_size(ws_x, ws_y, base_w=self._viewport_w, base_h=self._viewport_h)
        dx, dy = self._drag_offset
        nx = max(0, min(ww - 1, sx - dx))
        ny = max(0, min(wh - 1, sy - dy))
        objs[idx]["x"] = nx
        objs[idx]["y"] = ny
        self.spin_obj_x.blockSignals(True)
        self.spin_obj_y.blockSignals(True)
        self.spin_obj_x.setValue(nx)
        self.spin_obj_y.setValue(ny)
        self.spin_obj_x.blockSignals(False)
        self.spin_obj_y.blockSignals(False)
        self.list_objects.blockSignals(True)
        self.list_objects.item(idx).setText(f"{objs[idx]['id']}  ({nx}, {ny})")
        self.list_objects.blockSignals(False)
        self._dirty = True
        self.lbl_status.setText(tr("common.unsaved_changes"))
        self._refresh_canvas()

    def _on_object_drag_finished(self) -> None:
        # Un solo checkpoint de historial por arrastre, igual que stroke_finished
        # para pintura de tiles -- commit() equality-dedupe evita un checkpoint
        # vacio si fue un clic sin movimiento.
        if self._dragging_object_index is not None:
            self._commit_history()
        self._dragging_object_index = None
        self._drag_offset = None

    # ------------------------------------------------------------------
    # Slots — camera
    # ------------------------------------------------------------------

    def _on_camera_changed(self, *_args: Any) -> None:
        if self._suspend:
            return
        row = self._current_row()
        if row is None:
            return
        row["camera"] = {
            "mode": self.combo_camera_mode.currentText(),
            "x": self.spin_cam_x.value(),
            "y": self.spin_cam_y.value(),
            "target": self.edit_cam_target.text().strip(),
            "margin_x": self.spin_cam_margin_x.value(),
            "margin_y": self.spin_cam_margin_y.value(),
        }
        self._mark_dirty()
        self._refresh_canvas()

    def _parallax_world_h(self, row: dict[str, Any]) -> int:
        ws_x = int(row.get("world_steps_x", 1))
        ws_y = int(row.get("world_steps_y", 1))
        _ww, wh = scene_world_pixel_size(ws_x, ws_y, base_w=self._viewport_w, base_h=self._viewport_h)
        return wh

    def _on_parallax_enabled_toggled(self, checked: bool) -> None:
        if self._suspend:
            return
        row = self._current_row()
        if row is None:
            return
        if checked:
            if not isinstance(row.get("parallax_bands"), list):
                row["parallax_bands"] = []
        else:
            row.pop("parallax_bands", None)
        self._mark_dirty()
        self._load_parallax_bands(row)
        self._refresh_canvas()
        if checked:
            self._warn_if_multiple_bands_layers()

    def _action_add_parallax_band(self) -> None:
        row = self._current_row()
        if row is None:
            return
        bands = row.get("parallax_bands")
        if not isinstance(bands, list):
            return
        if len(bands) >= MAX_PARALLAX_BANDS:
            QMessageBox.warning(
                self, tr("scene.parallax_group"), tr("scene.parallax_max_bands", n=MAX_PARALLAX_BANDS)
            )
            return
        wh = self._parallax_world_h(row)
        bands.append(scene_parallax_band_to_json(clamp_parallax_band(SceneParallaxBand(), world_h=wh)))
        self._mark_dirty()
        self._load_parallax_bands(row)
        self.list_parallax_bands.setCurrentRow(len(bands) - 1)
        self._refresh_canvas()

    def _action_remove_parallax_band(self) -> None:
        row = self._current_row()
        if row is None:
            return
        bands = row.get("parallax_bands")
        if not isinstance(bands, list):
            return
        idx = self.list_parallax_bands.currentRow()
        if 0 <= idx < len(bands):
            del bands[idx]
            self._mark_dirty()
            self._load_parallax_bands(row)
            self._refresh_canvas()

    def _on_parallax_band_selected(self, index: int) -> None:
        row = self._current_row()
        if row is None:
            return
        bands = row.get("parallax_bands")
        d = bands[index] if isinstance(bands, list) and 0 <= index < len(bands) else None
        self._load_parallax_band_editor(d)
        self._refresh_canvas()

    def _on_parallax_band_edited(self, *_args: Any) -> None:
        row = self._current_row()
        if row is None:
            return
        bands = row.get("parallax_bands")
        idx = self.list_parallax_bands.currentRow()
        if not isinstance(bands, list) or not (0 <= idx < len(bands)):
            return
        wh = self._parallax_world_h(row)
        raw = SceneParallaxBand(
            y0=self.spin_parallax_y0.value(),
            y1=self.spin_parallax_y1.value(),
            parallax_x=self.spin_parallax_x.value(),
            fixed=self.chk_parallax_fixed.isChecked(),
            repeat_x=self.chk_parallax_repeat_x.isChecked(),
        )
        bands[idx] = scene_parallax_band_to_json(clamp_parallax_band(raw, world_h=wh))
        self.list_parallax_bands.blockSignals(True)
        self.list_parallax_bands.item(idx).setText(self._parallax_band_summary(bands[idx]))
        self.list_parallax_bands.blockSignals(False)
        self._mark_dirty()
        self._refresh_canvas()

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _action_save(self) -> None:
        if not self._scenes:
            return
        try:
            data = json.loads(manifest_path(self.project_root).read_text(encoding="utf-8"))
            entry_rel = str(data.get("entry", "scripts/global.lua"))
            entry_path = self.project_root / entry_rel
            entry_text = entry_path.read_text(encoding="utf-8") if entry_path.is_file() else ""
            save_project(
                self.project_root,
                lua_files={entry_rel: entry_text},
                scenes=copy.deepcopy(self._scenes),
                active_scene=self._active_id or self._scenes[0]["id"],
            )
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, tr("scene.save_error_title"), str(e))
            return
        self._dirty = False
        self.lbl_status.setText(tr("common.saved"))
        self.saved.emit(self.project_root)
        self.refresh()
