"""Tileset editor tab — paint `tiles/*.json` tiles and per-tile collision shapes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from turtlestudio.backgrounds import list_palette_relpaths
from turtlestudio.build import hex_line_to_rgb01, load_palette_lines
from turtlestudio.i18n import tr
from turtlestudio.objects import OBJECT_COLLISION_MODE_AABB
from turtlestudio.palette_editor import PaletteGridWidget
from turtlestudio.palette_policy import PALETTE_SIZE, TRANSPARENT_PALETTE_INDEX
from turtlestudio.project import DEFAULT_EXAMPLE_PALETTE_REL
from turtlestudio.scene_editor import TilePickerWidget
from turtlestudio.sprite_editor import Tool
from turtlestudio.sprites import normalize_palette_rows
from turtlestudio.tileset_import_dialog import TilesetImportDialog
from turtlestudio.tile_collision import (
    TILE_COLLISION_KINDS,
    TILE_COLLISION_NONE,
    TILE_COLLISION_SHAPE,
    TILE_COLLISION_SOLID,
    TILE_ONEWAY_DIR_DEFAULT,
    TILE_ONEWAY_DIRECTIONS,
    default_shape_from_tile_pixels,
    default_tile_collision_meta,
    parse_tileset_collision_meta,
)
from turtlestudio.tiles import (
    DEFAULT_TILE_PX,
    MAX_TILE_PX,
    MAX_TILES_PER_TILESET,
    MIN_TILE_PX,
    TILE_PX_STEP,
    empty_tile_rows,
    list_tileset_json_stems,
    parse_tileset_all_tiles,
    read_tileset_file,
    save_tileset_json,
    tileset_file_pixel_dimensions,
    validate_tileset_id,
    write_tileset_json,
)


class TileCanvas(QWidget):
    """Zoomed pixel-index grid for a single square tile, plus a collision AABB overlay."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows: list[list[int]] = []
        self.palette: list[tuple[int, int, int]] = []
        self.tile_px = DEFAULT_TILE_PX
        self.zoom = 16
        self.tool = Tool.PENCIL
        self.current_index = 0
        self.collision_box: tuple[int, int, int, int] | None = None
        self._drawing = False
        self._on_paint: Any = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_on_paint(self, callback: Any) -> None:
        self._on_paint = callback

    def set_tile(self, rows: list[list[int]], palette: list[tuple[int, int, int]], *, tile_px: int) -> None:
        self.rows = rows
        self.palette = palette
        self.tile_px = max(1, tile_px)
        self._update_minimum_size()
        self.update()

    def set_zoom(self, zoom: int) -> None:
        self.zoom = max(4, min(48, zoom))
        self._update_minimum_size()
        self.update()

    def set_tool(self, tool: Tool) -> None:
        self.tool = tool

    def set_color_index(self, index: int) -> None:
        self.current_index = index

    def set_collision_box(self, box: tuple[int, int, int, int] | None) -> None:
        self.collision_box = box
        self.update()

    def _update_minimum_size(self) -> None:
        self.setMinimumSize(self.tile_px * self.zoom, self.tile_px * self.zoom)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        px = self.tile_px
        z = self.zoom
        painter.fillRect(self.rect(), QColor(26, 26, 46))
        for y in range(px):
            row = self.rows[y] if y < len(self.rows) else []
            for x in range(px):
                idx = row[x] if x < len(row) else TRANSPARENT_PALETTE_INDEX
                if idx == TRANSPARENT_PALETTE_INDEX:
                    shade = 60 if (x // 4 + y // 4) % 2 == 0 else 45
                    painter.fillRect(x * z, y * z, z, z, QColor(shade, shade, shade))
                elif idx < len(self.palette):
                    r, g, b = self.palette[idx]
                    painter.fillRect(x * z, y * z, z, z, QColor(r, g, b))

        if self.collision_box is not None:
            x0, y0, x1, y1 = self.collision_box
            top = px - 1 - y1
            left = x0
            w = max(0, x1 - x0 + 1)
            h = max(0, y1 - y0 + 1)
            pen = QPen(QColor(255, 90, 90, 220))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(left * z, top * z, w * z, h * z)
        painter.end()

    def _flood_fill(self, x0: int, y0: int) -> None:
        target = self.rows[y0][x0]
        if target == self.current_index:
            return
        px = self.tile_px
        stack = [(x0, y0)]
        seen: set[tuple[int, int]] = set()
        while stack:
            x, y = stack.pop()
            if (x, y) in seen or not (0 <= x < px and 0 <= y < px):
                continue
            if self.rows[y][x] != target:
                continue
            seen.add((x, y))
            self.rows[y][x] = self.current_index
            stack.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
        self.update()
        if self._on_paint is not None:
            self._on_paint()

    def _paint_at(self, pos) -> None:
        px = self.tile_px
        x = int(pos.x()) // self.zoom
        y = int(pos.y()) // self.zoom
        if not (0 <= x < px and 0 <= y < px):
            return
        if self.tool == Tool.EYEDROPPER:
            self.current_index = self.rows[y][x]
            return
        if self.tool == Tool.BUCKET:
            self._flood_fill(x, y)
            return
        idx = TRANSPARENT_PALETTE_INDEX if self.tool == Tool.ERASER else self.current_index
        if self.rows[y][x] != idx:
            self.rows[y][x] = idx
            self.update()
            if self._on_paint is not None:
                self._on_paint()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._drawing = True
        self._paint_at(event.position())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drawing and self.tool != Tool.BUCKET:
            self._paint_at(event.position())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drawing = False


class TilesetEditorWidget(QWidget):
    def __init__(self, project_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project_root = project_root
        self.tileset_id = ""
        self.tile_px = DEFAULT_TILE_PX
        self.palette_rel = DEFAULT_EXAMPLE_PALETTE_REL
        self._tiles: list[list[list[int]]] = []
        self._collision: list[dict[str, Any]] = []
        self._tile_index = 0
        self._dirty = False
        self._suspend = False
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_project_root(self, root: Path) -> None:
        self.project_root = root
        self.refresh_tileset_list()

    def refresh_tileset_list(self) -> None:
        current = self.combo_tileset.currentText()
        self.combo_tileset.blockSignals(True)
        self.combo_tileset.clear()
        stems = list_tileset_json_stems(self.project_root)
        self.combo_tileset.addItems(stems)
        self.combo_tileset.blockSignals(False)
        if stems:
            target = current if current in stems else stems[0]
            idx = self.combo_tileset.findText(target)
            self.combo_tileset.setCurrentIndex(max(idx, 0))
            self.open_tileset(self.combo_tileset.currentText())

    def open_tileset(self, stem: str) -> None:
        if not stem:
            return
        idx = self.combo_tileset.findText(stem)
        if idx < 0:
            self.refresh_tileset_list()
            idx = self.combo_tileset.findText(stem)
        if idx >= 0:
            self.combo_tileset.setCurrentIndex(idx)
        self._load_tileset(stem)

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel(tr("tileset.label")))
        self.combo_tileset = QComboBox()
        self.combo_tileset.setMinimumWidth(180)
        self.combo_tileset.currentTextChanged.connect(self._on_tileset_combo_changed)
        top_row.addWidget(self.combo_tileset)
        self.btn_new = QPushButton(tr("common.new"))
        self.btn_new.clicked.connect(self._action_new_tileset)
        top_row.addWidget(self.btn_new)
        self.btn_save = QPushButton(tr("common.save"))
        self.btn_save.clicked.connect(self._action_save)
        top_row.addWidget(self.btn_save)
        top_row.addStretch()
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #888;")
        top_row.addWidget(self.lbl_status)
        outer.addLayout(top_row)

        root = QHBoxLayout()
        outer.addLayout(root, stretch=1)

        canvas_col = QVBoxLayout()
        self.canvas = TileCanvas()
        self.canvas.set_on_paint(self._mark_dirty)
        canvas_scroll = QScrollArea()
        canvas_scroll.setWidgetResizable(True)
        canvas_scroll.setWidget(self.canvas)
        canvas_col.addWidget(canvas_scroll, stretch=1)

        tools = QHBoxLayout()
        self.btn_pencil = QPushButton(tr("common.pencil"))
        self.btn_pencil.setCheckable(True)
        self.btn_pencil.setChecked(True)
        self.btn_pencil.clicked.connect(lambda: self._set_tool(Tool.PENCIL))
        tools.addWidget(self.btn_pencil)
        self.btn_eraser = QPushButton(tr("common.eraser"))
        self.btn_eraser.setCheckable(True)
        self.btn_eraser.clicked.connect(lambda: self._set_tool(Tool.ERASER))
        tools.addWidget(self.btn_eraser)
        self.btn_dropper = QPushButton(tr("common.eyedropper"))
        self.btn_dropper.setCheckable(True)
        self.btn_dropper.clicked.connect(lambda: self._set_tool(Tool.EYEDROPPER))
        tools.addWidget(self.btn_dropper)
        self.btn_bucket = QPushButton(tr("common.bucket"))
        self.btn_bucket.setCheckable(True)
        self.btn_bucket.clicked.connect(lambda: self._set_tool(Tool.BUCKET))
        tools.addWidget(self.btn_bucket)
        tools.addWidget(QLabel(tr("common.zoom")))
        self.zoom_spin = QSpinBox()
        self.zoom_spin.setRange(4, 48)
        self.zoom_spin.setValue(16)
        self.zoom_spin.valueChanged.connect(self.canvas.set_zoom)
        tools.addWidget(self.zoom_spin)
        tools.addStretch()
        canvas_col.addLayout(tools)

        tile_row = QHBoxLayout()
        tile_row.addWidget(QLabel(tr("tileset.tiles_label")))
        self.btn_add_tile = QPushButton(tr("tileset.add_tile"))
        self.btn_add_tile.clicked.connect(self._action_add_tile)
        tile_row.addWidget(self.btn_add_tile)
        self.btn_del_tile = QPushButton(tr("tileset.remove_tile"))
        self.btn_del_tile.clicked.connect(self._action_remove_tile)
        tile_row.addWidget(self.btn_del_tile)
        tile_row.addStretch()
        canvas_col.addLayout(tile_row)

        self.tile_strip = TilePickerWidget()
        self.tile_strip.tile_selected.connect(self._on_tile_selected)
        canvas_col.addWidget(self.tile_strip)

        root.addLayout(canvas_col, stretch=1)

        side = QVBoxLayout()
        form = QFormLayout()
        self.spin_tile_px = QSpinBox()
        self.spin_tile_px.setRange(MIN_TILE_PX, MAX_TILE_PX)
        self.spin_tile_px.setSingleStep(TILE_PX_STEP)
        self.spin_tile_px.setValue(DEFAULT_TILE_PX)
        form.addRow(tr("tileset.px_per_tile"), self.spin_tile_px)
        self.btn_resize = QPushButton(tr("common.resize"))
        self.btn_resize.clicked.connect(self._action_resize)
        form.addRow(self.btn_resize)
        self.btn_import = QPushButton(tr("tileset.import_button"))
        self.btn_import.clicked.connect(self._action_import_image)
        form.addRow(self.btn_import)
        self.lbl_palette = QLabel("—")
        form.addRow(tr("tileset.palette_label"), self.lbl_palette)
        side.addLayout(form)

        side.addWidget(QLabel(tr("tileset.palette_hint")))
        self.grid = PaletteGridWidget()
        self.grid.slot_selected.connect(self._on_slot_selected)
        side.addWidget(self.grid)

        coll_box = QGroupBox(tr("tileset.collision_group"))
        coll_form = QFormLayout(coll_box)
        self.combo_coll_kind = QComboBox()
        self.combo_coll_kind.addItems(list(TILE_COLLISION_KINDS))
        self.combo_coll_kind.currentTextChanged.connect(self._on_collision_changed)
        coll_form.addRow(tr("tileset.collision_type"), self.combo_coll_kind)

        self.spin_x0 = QSpinBox()
        self.spin_y0 = QSpinBox()
        self.spin_x1 = QSpinBox()
        self.spin_y1 = QSpinBox()
        for s in (self.spin_x0, self.spin_y0, self.spin_x1, self.spin_y1):
            s.setRange(0, MAX_TILE_PX - 1)
            s.valueChanged.connect(self._on_collision_changed)
        aabb_row1 = QHBoxLayout()
        aabb_row1.addWidget(QLabel("x0:"))
        aabb_row1.addWidget(self.spin_x0)
        aabb_row1.addWidget(QLabel("y0:"))
        aabb_row1.addWidget(self.spin_y0)
        coll_form.addRow(aabb_row1)
        aabb_row2 = QHBoxLayout()
        aabb_row2.addWidget(QLabel("x1:"))
        aabb_row2.addWidget(self.spin_x1)
        aabb_row2.addWidget(QLabel("y1:"))
        aabb_row2.addWidget(self.spin_y1)
        coll_form.addRow(aabb_row2)
        self.btn_auto_shape = QPushButton(tr("tileset.auto_shape"))
        self.btn_auto_shape.clicked.connect(self._action_auto_shape)
        coll_form.addRow(self.btn_auto_shape)

        self.chk_oneway = QCheckBox(tr("tileset.oneway"))
        self.chk_oneway.toggled.connect(self._on_collision_changed)
        coll_form.addRow(self.chk_oneway)
        self.combo_oneway_dir = QComboBox()
        self.combo_oneway_dir.addItems(list(TILE_ONEWAY_DIRECTIONS))
        self.combo_oneway_dir.currentTextChanged.connect(self._on_collision_changed)
        coll_form.addRow(tr("tileset.direction"), self.combo_oneway_dir)

        side.addWidget(coll_box)
        side.addStretch()
        root.addLayout(side)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_palette_colors(self, palette_rel: str) -> list[tuple[int, int, int]]:
        path = self.project_root / palette_rel
        try:
            hexes = load_palette_lines(path)
        except OSError:
            hexes = []
        rgbs01 = [hex_line_to_rgb01(h) for h in hexes] if hexes else []
        colors = [(round(r * 255), round(g * 255), round(b * 255)) for r, g, b in rgbs01]
        if len(colors) < PALETTE_SIZE:
            colors += [(0, 0, 0)] * (PALETTE_SIZE - len(colors))
        return colors[:PALETTE_SIZE]

    def _load_tileset(self, stem: str) -> None:
        try:
            data = read_tileset_file(self.project_root, stem)
        except ValueError as e:
            QMessageBox.warning(self, tr("tileset.open_error_title"), str(e))
            return
        self.tileset_id = stem
        self.tile_px = tileset_file_pixel_dimensions(data)
        self.palette_rel = str(data.get("palette") or DEFAULT_EXAMPLE_PALETTE_REL)
        self._tiles = parse_tileset_all_tiles(data, fill_index=1)
        if not self._tiles:
            self._tiles = [empty_tile_rows(self.tile_px)]
        self._collision = parse_tileset_collision_meta(data)
        if len(self._collision) < len(self._tiles):
            self._collision += [default_tile_collision_meta() for _ in range(len(self._tiles) - len(self._collision))]
        self._tile_index = 0
        self._dirty = False

        self._suspend = True
        self.spin_tile_px.setValue(self.tile_px)
        self._suspend = False
        self.lbl_palette.setText(self.palette_rel)

        self.grid.set_colors(self._load_palette_colors(self.palette_rel))
        self.tile_strip.set_tiles(self._tiles, [self._grid_rgb01(c) for c in self.grid.colors()])
        self.tile_strip.select_index(0)
        self._refresh_canvas()
        self._refresh_collision_form()
        self.lbl_status.setText("")

    @staticmethod
    def _grid_rgb01(rgb255: tuple[int, int, int]) -> tuple[float, float, float]:
        r, g, b = rgb255
        return (r / 255.0, g / 255.0, b / 255.0)

    def _refresh_canvas(self) -> None:
        if not self._tiles:
            return
        self.canvas.set_tile(self._tiles[self._tile_index], self.grid.colors(), tile_px=self.tile_px)
        self._update_collision_overlay()

    def _refresh_tile_strip_icons(self) -> None:
        self.tile_strip.set_tiles(self._tiles, [self._grid_rgb01(c) for c in self.grid.colors()])
        self.tile_strip.select_index(self._tile_index)

    def _mark_dirty(self) -> None:
        self._dirty = True
        self.lbl_status.setText(tr("common.unsaved_changes"))

    def _set_tool(self, tool: Tool) -> None:
        self.canvas.set_tool(tool)
        self.btn_pencil.setChecked(tool == Tool.PENCIL)
        self.btn_eraser.setChecked(tool == Tool.ERASER)
        self.btn_dropper.setChecked(tool == Tool.EYEDROPPER)
        self.btn_bucket.setChecked(tool == Tool.BUCKET)

    def _current_collision(self) -> dict[str, Any]:
        if not self._collision:
            self._collision = [default_tile_collision_meta()]
        return self._collision[self._tile_index]

    def _refresh_collision_form(self) -> None:
        meta = self._current_collision()
        self._suspend = True
        kind = str(meta.get("kind", TILE_COLLISION_SOLID))
        idx = self.combo_coll_kind.findText(kind)
        self.combo_coll_kind.setCurrentIndex(max(0, idx))
        shape = meta.get("shape") if isinstance(meta.get("shape"), dict) else None
        if shape is not None and shape.get("mode") == OBJECT_COLLISION_MODE_AABB:
            self.spin_x0.setValue(int(shape.get("x0", 0)))
            self.spin_y0.setValue(int(shape.get("y0", 0)))
            self.spin_x1.setValue(int(shape.get("x1", 0)))
            self.spin_y1.setValue(int(shape.get("y1", 0)))
        self.chk_oneway.setChecked(bool(meta.get("oneway")))
        dir_idx = self.combo_oneway_dir.findText(str(meta.get("oneway_direction", TILE_ONEWAY_DIR_DEFAULT)))
        self.combo_oneway_dir.setCurrentIndex(max(0, dir_idx))
        self._suspend = False
        self._update_collision_overlay()

    def _update_collision_overlay(self) -> None:
        meta = self._current_collision()
        if meta.get("kind") == TILE_COLLISION_SHAPE:
            shape = meta.get("shape")
            if isinstance(shape, dict) and shape.get("mode") == OBJECT_COLLISION_MODE_AABB:
                self.canvas.set_collision_box((int(shape["x0"]), int(shape["y0"]), int(shape["x1"]), int(shape["y1"])))
                return
        self.canvas.set_collision_box(None)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_tileset_combo_changed(self, stem: str) -> None:
        if stem:
            self._load_tileset(stem)

    def _on_tile_selected(self, index: int) -> None:
        if 0 <= index < len(self._tiles):
            self._tile_index = index
            self._refresh_canvas()
            self._refresh_collision_form()

    def _on_slot_selected(self, index: int) -> None:
        if index == TRANSPARENT_PALETTE_INDEX:
            return
        self.canvas.set_color_index(index)

    def _on_collision_changed(self, *_args: Any) -> None:
        if self._suspend:
            return
        meta = self._current_collision()
        kind = self.combo_coll_kind.currentText()
        if kind not in TILE_COLLISION_KINDS:
            kind = TILE_COLLISION_SOLID
        meta["kind"] = kind
        if kind == TILE_COLLISION_SHAPE:
            meta["shape"] = {
                "mode": OBJECT_COLLISION_MODE_AABB,
                "x0": self.spin_x0.value(),
                "y0": self.spin_y0.value(),
                "x1": max(self.spin_x0.value(), self.spin_x1.value()),
                "y1": max(self.spin_y0.value(), self.spin_y1.value()),
            }
        meta["oneway"] = self.chk_oneway.isChecked() if kind != TILE_COLLISION_NONE else False
        meta["oneway_direction"] = self.combo_oneway_dir.currentText()
        self._mark_dirty()
        self._update_collision_overlay()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _action_new_tileset(self) -> None:
        name, ok = QInputDialog.getText(self, tr("tileset.new_title"), tr("tileset.new_id_label"))
        if not ok or not name.strip():
            return
        rels = list_palette_relpaths(self.project_root)
        if not rels:
            QMessageBox.warning(self, tr("tileset.new_title"), tr("common.no_palettes"))
            return
        pal, ok = QInputDialog.getItem(self, tr("tileset.new_title"), tr("tileset.palette_label"), rels, 0, False)
        if not ok:
            return
        try:
            tid = validate_tileset_id(name.strip())
            write_tileset_json(self.project_root, tid, palette_rel=pal, tile_px=DEFAULT_TILE_PX, fill_index=1)
        except ValueError as e:
            QMessageBox.warning(self, tr("tileset.new_title"), str(e))
            return
        self.refresh_tileset_list()
        self.open_tileset(tid)

    def _action_resize(self) -> None:
        new_px = self.spin_tile_px.value()
        self._tiles = [normalize_palette_rows(rows, new_px, new_px, fill_index=1) for rows in self._tiles]
        self.tile_px = new_px
        self._mark_dirty()
        self._refresh_canvas()
        self._refresh_tile_strip_icons()

    def _action_import_image(self) -> None:
        if not self.tileset_id:
            QMessageBox.warning(self, tr("tileset.import_button"), tr("tileset.import_no_tileset_open"))
            return
        rgbs01 = [self._grid_rgb01(c) for c in self.grid.colors()]
        dlg = TilesetImportDialog(
            self.project_root,
            self.tile_px,
            rgbs01,
            tile_index=self._tile_index,
            tile_count=len(self._tiles),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        rows = dlg.result_rows()
        if rows is None:
            return
        self._tiles[self._tile_index] = rows
        self._mark_dirty()
        self._refresh_canvas()
        self._refresh_tile_strip_icons()

    def _action_add_tile(self) -> None:
        if len(self._tiles) >= MAX_TILES_PER_TILESET:
            return
        self._tiles.insert(self._tile_index + 1, empty_tile_rows(self.tile_px))
        self._collision.insert(self._tile_index + 1, default_tile_collision_meta())
        self._tile_index += 1
        self._mark_dirty()
        self._refresh_tile_strip_icons()
        self._refresh_canvas()
        self._refresh_collision_form()

    def _action_remove_tile(self) -> None:
        if len(self._tiles) <= 1:
            return
        del self._tiles[self._tile_index]
        del self._collision[self._tile_index]
        self._tile_index = max(0, self._tile_index - 1)
        self._mark_dirty()
        self._refresh_tile_strip_icons()
        self._refresh_canvas()
        self._refresh_collision_form()

    def _action_auto_shape(self) -> None:
        box = default_shape_from_tile_pixels(
            self._tiles[self._tile_index], tile_px=self.tile_px, transparent_index=TRANSPARENT_PALETTE_INDEX
        )
        meta = self._current_collision()
        meta["kind"] = TILE_COLLISION_SHAPE
        meta["shape"] = box
        self._mark_dirty()
        self._refresh_collision_form()

    def _action_save(self) -> None:
        if not self.tileset_id:
            return
        try:
            save_tileset_json(
                self.project_root,
                self.tileset_id,
                palette_rel=self.palette_rel,
                tile_px=self.tile_px,
                tiles_rows=self._tiles,
                fill_index=1,
                collision_meta=self._collision,
            )
        except ValueError as e:
            QMessageBox.warning(self, tr("tileset.save_error_title"), str(e))
            return
        self._dirty = False
        self.lbl_status.setText(tr("common.saved"))
