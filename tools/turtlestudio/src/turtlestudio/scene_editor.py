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

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QImage, QMouseEvent, QPainter, QPixmap
from PyQt6.QtWidgets import (
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
    background_layers_to_json_list,
    clamp_world_steps,
    manifest_path,
    parse_background_layers,
    parse_scene_objects_raw,
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
from turtlestudio.scene_tiles import (
    TILE_LAYER_COUNT,
    draw_scene_step_bounds_on_rgba,
    draw_scene_tile_grid_on_rgba,
    empty_tile_cells,
    list_tileset_stems_for_palette,
    paint_tile_layers_on_rgba,
    parse_tile_layers,
    scene_coords_to_cell,
    scene_tile_grid_dimensions,
    set_cell_index,
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
    paint_layer_index: int | None = None,
    hover_cell: tuple[int, int] | None = None,
) -> tuple[list[float], int, int]:
    wsx = clamp_world_steps(row.get("world_steps_x", 1))
    wsy = clamp_world_steps(row.get("world_steps_y", 1))
    fw, fh = scene_world_pixel_size(wsx, wsy)
    rgba = [0.0] * (fw * fh * 4)
    for i in range(3, len(rgba), 4):
        rgba[i] = 1.0

    palette_rel = str(row.get("palette", "")).strip()
    pal_path = (project_root / palette_rel).resolve() if palette_rel else None
    rgbs, _ = load_palette_rgb01_for_preview(pal_path if pal_path and pal_path.is_file() else None)

    for ld in row.get("background_layers") or []:
        if not isinstance(ld, dict) or not ld.get("enabled"):
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

    bg_stem = str(row.get("background", "") or "").strip()
    if bg_stem:
        _paint_background_stem(rgba, fw, fh, project_root, bg_stem, palette_rel, rgbs)

    layers = parse_tile_layers(row.get("tile_layers"), tile_px=tile_px, world_w=fw, world_h=fh)
    paint_tile_layers_on_rgba(rgba, fw, fh, layers, project_root, rgbs, tile_px=tile_px)

    placements = row.get("objects") or []
    _paint_scene_objects(rgba, fw, fh, project_root, placements)

    if paint_layer_index is not None:
        draw_scene_tile_grid_on_rgba(rgba, fw, fh, tile_px, hover_cell=hover_cell, full_grid=True)

    if fw > SCENE_PIXEL_W or fh > SCENE_PIXEL_H:
        draw_scene_step_bounds_on_rgba(rgba, fw, fh)
        cam = parse_scene_camera_from_row(row)
        cam_x, cam_y = resolve_scene_camera_viewport(cam, world_w=fw, world_h=fh, objects=list(placements))
        draw_scene_camera_viewport_on_rgba(rgba, fw, fh, cam_x, cam_y)

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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image: QImage | None = None
        self._fw = 0
        self._fh = 0
        self.zoom = 2
        self.paintable = False
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
        if not self.paintable or event.button() != Qt.MouseButton.LeftButton:
            return
        xy = self._scene_xy_at(event.position())
        if xy is not None:
            self.cell_clicked.emit(*xy)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.paintable and (event.buttons() & Qt.MouseButton.LeftButton):
            xy = self._scene_xy_at(event.position())
            if xy is not None:
                self.cell_clicked.emit(*xy)


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
        "background": "",
        "script": sid,
        "objects": [],
        "tile_layers": tile_layers_to_json_list(parse_tile_layers(None, tile_px=tile_px)),
        "world_steps_x": 1,
        "world_steps_y": 1,
        "camera": _default_camera_dict(),
    }


def _normalize_row(row: dict[str, Any], tile_px: int) -> dict[str, Any]:
    """Round-trip a raw manifest scene row through the parse/serialize helpers."""
    r = dict(row)
    wsx = clamp_world_steps(r.get("world_steps_x", 1))
    wsy = clamp_world_steps(r.get("world_steps_y", 1))
    ww, wh = scene_world_pixel_size(wsx, wsy)
    r["world_steps_x"] = wsx
    r["world_steps_y"] = wsy
    layers = parse_background_layers(
        r.get("background_layers"), legacy_flat_index=int(r.get("background_index", 1) or 1), n_colors=PALETTE_SIZE
    )
    r["background_layers"] = background_layers_to_json_list(layers)
    tile_layers = parse_tile_layers(r.get("tile_layers"), tile_px=tile_px, world_w=ww, world_h=wh)
    r["tile_layers"] = tile_layers_to_json_list(tile_layers)
    placements = parse_scene_objects_raw(r.get("objects"), world_w=ww, world_h=wh)
    r["objects"] = [{"id": p.id, "x": p.x, "y": p.y} for p in placements]
    cam = parse_scene_camera_from_row(r)
    r["camera"] = scene_camera_to_json(cam)
    r["background"] = str(r.get("background", "") or "")
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
        self._dirty = False
        self._paint_layer: int | None = None
        self._paint_tile_index = 0
        self._hover_cell: tuple[int, int] | None = None
        self._suspend = False
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
        raw_scenes = data.get("scenes") if isinstance(data.get("scenes"), list) else []
        self._scenes = [_normalize_row(s, self._tile_px) for s in raw_scenes if isinstance(s, dict) and s.get("id")]
        self._active_id = str(data.get("active_scene", "")).strip()
        if not self._scenes:
            self._current_index = -1
        else:
            ids = [s["id"] for s in self._scenes]
            self._current_index = ids.index(self._active_id) if self._active_id in ids else 0
        self._dirty = False
        self._refresh_scene_combo()
        self._load_current_into_form()

    def open_scene(self, scene_id: str) -> None:
        ids = [s["id"] for s in self._scenes]
        if scene_id in ids:
            self._current_index = ids.index(scene_id)
            self._load_current_into_form()

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
        canvas_tools.addWidget(QLabel(tr("scene.paint_layer_label")))
        self.combo_paint_layer = QComboBox()
        self.combo_paint_layer.addItem(tr("scene.paint_layer_none"), None)
        for i in range(TILE_LAYER_COUNT):
            self.combo_paint_layer.addItem(tr("scene.layer_n", n=i + 1), i)
        self.combo_paint_layer.currentIndexChanged.connect(self._on_paint_layer_combo_changed)
        canvas_tools.addWidget(self.combo_paint_layer)
        self.chk_erase = QCheckBox(tr("common.eraser"))
        canvas_tools.addWidget(self.chk_erase)
        canvas_tools.addStretch()
        right_layout.addLayout(canvas_tools)

        self.tile_picker = TilePickerWidget()
        self.tile_picker.tile_selected.connect(self._on_tile_picker_selected)
        right_layout.addWidget(self.tile_picker)

        self.canvas = SceneCanvas()
        self.canvas.cell_clicked.connect(self._on_canvas_cell_clicked)
        self.spin_zoom.valueChanged.connect(self.canvas.set_zoom)
        canvas_scroll = QScrollArea()
        canvas_scroll.setWidgetResizable(True)
        canvas_scroll.setWidget(self.canvas)
        right_layout.addWidget(canvas_scroll, stretch=1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

    def _build_properties_group(self) -> QGroupBox:
        box = QGroupBox(tr("scene.properties_group"))
        form = QFormLayout(box)
        self.lbl_scene_id = QLabel("—")
        form.addRow(tr("scene.id_label"), self.lbl_scene_id)
        self.combo_palette = QComboBox()
        self.combo_palette.currentTextChanged.connect(self._on_palette_changed)
        form.addRow(tr("scene.palette_label"), self.combo_palette)
        self.edit_script = QLineEdit()
        self.edit_script.editingFinished.connect(self._on_script_edited)
        form.addRow(tr("scene.script_label"), self.edit_script)
        self.spin_world_x = QSpinBox()
        self.spin_world_x.setRange(1, 2)
        self.spin_world_x.valueChanged.connect(self._on_world_steps_changed)
        form.addRow(tr("scene.world_steps_x"), self.spin_world_x)
        self.spin_world_y = QSpinBox()
        self.spin_world_y.setRange(1, 2)
        self.spin_world_y.valueChanged.connect(self._on_world_steps_changed)
        form.addRow(tr("scene.world_steps_y"), self.spin_world_y)
        return box

    def _build_background_group(self) -> QGroupBox:
        box = QGroupBox(tr("scene.background_group"))
        layout = QVBoxLayout(box)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("scene.background_asset_label")))
        self.combo_background = QComboBox()
        self.combo_background.currentTextChanged.connect(self._on_background_stem_changed)
        row.addWidget(self.combo_background)
        layout.addLayout(row)

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
            self.bg_layer_rows.append({"enabled": chk, "color": spin_color, "opacity": spin_op})
        return box

    def _build_tile_layers_group(self) -> QGroupBox:
        box = QGroupBox(tr("scene.tile_layers_group"))
        layout = QVBoxLayout(box)
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
            self.tile_layer_rows.append({"enabled": chk, "tileset": combo})
        hint = QLabel(tr("scene.tile_layer_hint"))
        hint.setStyleSheet("color: #888;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return box

    def _build_objects_group(self) -> QGroupBox:
        box = QGroupBox(tr("scene.objects_group"))
        layout = QVBoxLayout(box)
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
        self.spin_obj_x.setRange(0, SCENE_PIXEL_W * 2)
        self.spin_obj_x.valueChanged.connect(self._on_object_xy_changed)
        pos_row.addWidget(self.spin_obj_x)
        pos_row.addWidget(QLabel(tr("scene.y_label")))
        self.spin_obj_y = QSpinBox()
        self.spin_obj_y.setRange(0, SCENE_PIXEL_H * 2)
        self.spin_obj_y.valueChanged.connect(self._on_object_xy_changed)
        pos_row.addWidget(self.spin_obj_y)
        layout.addLayout(pos_row)
        return box

    def _build_camera_group(self) -> QGroupBox:
        box = QGroupBox(tr("scene.camera_group"))
        form = QFormLayout(box)
        self.combo_camera_mode = QComboBox()
        self.combo_camera_mode.addItems([CAMERA_MODE_FOLLOW, CAMERA_MODE_FIXED])
        self.combo_camera_mode.currentTextChanged.connect(self._on_camera_changed)
        form.addRow(tr("scene.mode_label"), self.combo_camera_mode)
        self.spin_cam_x = QSpinBox()
        self.spin_cam_x.setRange(0, SCENE_PIXEL_W * 2)
        self.spin_cam_x.valueChanged.connect(self._on_camera_changed)
        form.addRow(tr("scene.x_label"), self.spin_cam_x)
        self.spin_cam_y = QSpinBox()
        self.spin_cam_y.setRange(0, SCENE_PIXEL_H * 2)
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
            self._refresh_background_combo(palette_rel, str(row.get("background", "")))
            self._load_bg_layers(row)
            self._refresh_tileset_combos(palette_rel)
            self._load_tile_layers(row)
            self._refresh_object_combo(palette_rel)
            self._load_objects(row)
            self._load_camera(row)
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

    def _refresh_background_combo(self, palette_rel: str, current: str) -> None:
        self.combo_background.blockSignals(True)
        self.combo_background.clear()
        self.combo_background.addItem(tr("scene.no_background"), "")
        for stem in list_background_stems_for_palette(self.project_root, palette_rel):
            self.combo_background.addItem(stem, stem)
        idx = self.combo_background.findData(current)
        self.combo_background.setCurrentIndex(max(0, idx))
        self.combo_background.blockSignals(False)

    def _load_bg_layers(self, row: dict[str, Any]) -> None:
        layers = row.get("background_layers") or []
        for i, widgets in enumerate(self.bg_layer_rows):
            d = layers[i] if i < len(layers) and isinstance(layers[i], dict) else {}
            widgets["enabled"].blockSignals(True)
            widgets["color"].blockSignals(True)
            widgets["opacity"].blockSignals(True)
            widgets["enabled"].setChecked(bool(d.get("enabled")))
            widgets["color"].setValue(int(d.get("color_index", 1)))
            widgets["opacity"].setValue(int(d.get("opacity", 255)))
            widgets["enabled"].blockSignals(False)
            widgets["color"].blockSignals(False)
            widgets["opacity"].blockSignals(False)

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

    def _refresh_canvas(self) -> None:
        row = self._current_row()
        if row is None:
            self.canvas.set_frame(QImage(), 0, 0)
            return
        rgba, fw, fh = render_scene_rgba(
            self.project_root, row, self._tile_px, paint_layer_index=self._paint_layer, hover_cell=self._hover_cell
        )
        img = _rgba_floats_to_qimage(rgba, fw, fh)
        self.canvas.set_frame(img, fw, fh)
        self.canvas.paintable = self._paint_layer is not None

    def _mark_dirty(self) -> None:
        self._dirty = True
        self.lbl_status.setText(tr("common.unsaved_changes"))

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
        self._refresh_background_combo(text, str(row.get("background", "")))
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
        ww, wh = scene_world_pixel_size(row["world_steps_x"], row["world_steps_y"])
        layers = parse_tile_layers(row.get("tile_layers"), tile_px=self._tile_px, world_w=ww, world_h=wh)
        row["tile_layers"] = tile_layers_to_json_list(layers)
        self._mark_dirty()
        self._refresh_canvas()

    # ------------------------------------------------------------------
    # Slots — background
    # ------------------------------------------------------------------

    def _on_background_stem_changed(self, _text: str) -> None:
        if self._suspend:
            return
        row = self._current_row()
        if row is None:
            return
        row["background"] = self.combo_background.currentData() or ""
        self._mark_dirty()
        self._refresh_canvas()

    def _on_bg_layer_changed(self, _index: int) -> None:
        if self._suspend:
            return
        row = self._current_row()
        if row is None:
            return
        layers = []
        for widgets in self.bg_layer_rows:
            layers.append(
                {
                    "enabled": widgets["enabled"].isChecked(),
                    "color_index": widgets["color"].value(),
                    "opacity": widgets["opacity"].value(),
                }
            )
        row["background_layers"] = layers
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
            if i >= len(layers):
                continue
            layers[i]["enabled"] = widgets["enabled"].isChecked()
            layers[i]["tileset"] = widgets["tileset"].currentText()
        self._mark_dirty()
        if self._paint_layer is not None:
            self._refresh_tile_picker()
        self._refresh_canvas()

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
        ww, wh = scene_world_pixel_size(ws_x, ws_y)
        cell = scene_coords_to_cell(sx, sy, tile_px=self._tile_px, world_w=ww, world_h=wh)
        if cell is None:
            return
        gx, gy = cell
        tile_index = TRANSPARENT_PALETTE_INDEX if self.chk_erase.isChecked() else self._paint_tile_index
        cells = layer.get("cells")
        if not isinstance(cells, list):
            return
        set_cell_index(cells, gx, gy, tile_index)
        self._mark_dirty()
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
        objs.append({"id": oid, "x": SCENE_PIXEL_W // 2, "y": SCENE_PIXEL_H // 2})
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
        if row is None or index < 0:
            return
        objs = row.get("objects") or []
        if not (0 <= index < len(objs)):
            return
        p = objs[index]
        self.spin_obj_x.blockSignals(True)
        self.spin_obj_y.blockSignals(True)
        self.spin_obj_x.setValue(int(p.get("x", 0)))
        self.spin_obj_y.setValue(int(p.get("y", 0)))
        self.spin_obj_x.blockSignals(False)
        self.spin_obj_y.blockSignals(False)

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
