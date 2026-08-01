"""Sprite editor tab — paint `objects/Sprites/*.json` sprites, frame by frame."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
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

from turtlestudio.build import hex_line_to_rgb01, load_palette_lines
from turtlestudio.palette_editor import PaletteGridWidget
from turtlestudio.palette_policy import (
    PALETTE_SIZE,
    TRANSPARENT_PALETTE_INDEX,
    clamp_paint_palette_index,
)
from turtlestudio.project import DEFAULT_EXAMPLE_PALETTE_REL
from turtlestudio.sprites import (
    MAX_BLOCKS_PER_AXIS,
    MAX_SPRITE_FRAMES,
    DEFAULT_CELL_PX,
    list_sprite_json_stems,
    normalize_palette_rows,
    parse_sprite_all_frame_rows,
    read_sprite_file,
    save_indexed_pixels_sprite_json,
    sprite_pixel_dimensions,
    validate_sprite_id,
    write_empty_sprite_json,
)


class Tool(str, Enum):
    PENCIL = "pencil"
    ERASER = "eraser"
    EYEDROPPER = "eyedropper"


class SpriteCanvas(QWidget):
    """Zoomed pixel-index grid; paints with the palette color at `current_index`."""

    changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows: list[list[int]] = []
        self.palette: list[tuple[int, int, int]] = []
        self.cell_px = DEFAULT_CELL_PX
        self.zoom = 16
        self.tool = Tool.PENCIL
        self.current_index = 0
        self.origin_x = 0
        self.origin_y = 0
        self._drawing = False
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def pixel_size(self) -> tuple[int, int]:
        ph = len(self.rows)
        pw = len(self.rows[0]) if ph else 0
        return pw, ph

    def set_sprite(
        self,
        rows: list[list[int]],
        palette: list[tuple[int, int, int]],
        *,
        cell_px: int,
        origin_x: int,
        origin_y: int,
    ) -> None:
        self.rows = rows
        self.palette = palette
        self.cell_px = max(1, cell_px)
        self.origin_x = origin_x
        self.origin_y = origin_y
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

    def _update_minimum_size(self) -> None:
        pw, ph = self.pixel_size()
        self.setMinimumSize(max(1, pw) * self.zoom, max(1, ph) * self.zoom)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        pw, ph = self.pixel_size()
        z = self.zoom
        painter.fillRect(self.rect(), QColor(26, 26, 46))
        for y in range(ph):
            row = self.rows[y]
            for x in range(pw):
                idx = row[x] if x < len(row) else TRANSPARENT_PALETTE_INDEX
                if idx == TRANSPARENT_PALETTE_INDEX:
                    shade = 60 if (x // 4 + y // 4) % 2 == 0 else 45
                    painter.fillRect(x * z, y * z, z, z, QColor(shade, shade, shade))
                elif idx < len(self.palette):
                    r, g, b = self.palette[idx]
                    painter.fillRect(x * z, y * z, z, z, QColor(r, g, b))

        if z >= 8:
            pen = QPen(QColor(0, 0, 0, 60))
            painter.setPen(pen)
            for x in range(0, pw + 1, self.cell_px):
                painter.drawLine(x * z, 0, x * z, ph * z)
            for y in range(0, ph + 1, self.cell_px):
                painter.drawLine(0, y * z, pw * z, y * z)

        # origin marker (sprite-space, bottom-left convention flipped to top-left for drawing)
        oy_top = ph - 1 - self.origin_y
        pen = QPen(QColor(255, 230, 50, 230))
        pen.setWidth(2)
        painter.setPen(pen)
        cx, cy = self.origin_x * z + z // 2, oy_top * z + z // 2
        painter.drawLine(cx - 6, cy, cx + 6, cy)
        painter.drawLine(cx, cy - 6, cx, cy + 6)
        painter.end()

    def _paint_at(self, pos) -> None:
        pw, ph = self.pixel_size()
        if pw == 0 or ph == 0:
            return
        x = int(pos.x()) // self.zoom
        y = int(pos.y()) // self.zoom
        if not (0 <= x < pw and 0 <= y < ph):
            return
        if self.tool == Tool.EYEDROPPER:
            self.current_index = self.rows[y][x]
            return
        idx = TRANSPARENT_PALETTE_INDEX if self.tool == Tool.ERASER else self.current_index
        if self.rows[y][x] != idx:
            self.rows[y][x] = idx
            self.changed.emit()
            self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._drawing = True
        self._paint_at(event.position())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drawing:
            self._paint_at(event.position())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drawing = False


class SpriteEditorWidget(QWidget):
    saved = pyqtSignal(Path)

    def __init__(self, project_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project_root = project_root
        self.sprite_id: str = ""
        self.cell_px = DEFAULT_CELL_PX
        self.blocks_w = 1
        self.blocks_h = 1
        self.origin_x = 0
        self.origin_y = 0
        self.palette_rel = DEFAULT_EXAMPLE_PALETTE_REL
        self._frames: list[list[list[int]]] = []
        self._frame_index = 0
        self._dirty = False
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_project_root(self, root: Path) -> None:
        self.project_root = root
        self.refresh_sprite_list()

    def refresh_sprite_list(self) -> None:
        current = self.combo_sprite.currentText()
        self.combo_sprite.blockSignals(True)
        self.combo_sprite.clear()
        stems = list_sprite_json_stems(self.project_root)
        self.combo_sprite.addItems(stems)
        self.combo_sprite.blockSignals(False)
        if stems:
            target = current if current in stems else stems[0]
            idx = self.combo_sprite.findText(target)
            self.combo_sprite.setCurrentIndex(max(idx, 0))
            self.open_sprite(self.combo_sprite.currentText())

    def open_sprite(self, stem: str) -> None:
        if not stem:
            return
        idx = self.combo_sprite.findText(stem)
        if idx < 0:
            self.refresh_sprite_list()
            idx = self.combo_sprite.findText(stem)
        if idx >= 0:
            self.combo_sprite.setCurrentIndex(idx)
        self._load_sprite(stem)

    def has_unsaved_changes(self) -> bool:
        return self._dirty

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Sprite:"))
        self.combo_sprite = QComboBox()
        self.combo_sprite.setMinimumWidth(180)
        self.combo_sprite.currentTextChanged.connect(self._on_sprite_combo_changed)
        top_row.addWidget(self.combo_sprite)
        self.btn_new = QPushButton("Nuevo…")
        self.btn_new.clicked.connect(self._action_new_sprite)
        top_row.addWidget(self.btn_new)
        self.btn_save = QPushButton("Guardar")
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
        self.canvas = SpriteCanvas()
        self.canvas.changed.connect(self._mark_dirty)
        canvas_scroll = QScrollArea()
        canvas_scroll.setWidgetResizable(True)
        canvas_scroll.setWidget(self.canvas)
        canvas_col.addWidget(canvas_scroll, stretch=1)

        tools = QHBoxLayout()
        self.btn_pencil = QPushButton("Lapiz")
        self.btn_pencil.setCheckable(True)
        self.btn_pencil.setChecked(True)
        self.btn_pencil.clicked.connect(lambda: self._set_tool(Tool.PENCIL))
        tools.addWidget(self.btn_pencil)
        self.btn_eraser = QPushButton("Borrador")
        self.btn_eraser.setCheckable(True)
        self.btn_eraser.clicked.connect(lambda: self._set_tool(Tool.ERASER))
        tools.addWidget(self.btn_eraser)
        self.btn_dropper = QPushButton("Cuentagotas")
        self.btn_dropper.setCheckable(True)
        self.btn_dropper.clicked.connect(lambda: self._set_tool(Tool.EYEDROPPER))
        tools.addWidget(self.btn_dropper)
        tools.addWidget(QLabel("Zoom:"))
        self.zoom_spin = QSpinBox()
        self.zoom_spin.setRange(4, 48)
        self.zoom_spin.setValue(16)
        self.zoom_spin.valueChanged.connect(self.canvas.set_zoom)
        tools.addWidget(self.zoom_spin)
        tools.addStretch()
        canvas_col.addLayout(tools)

        frame_row = QHBoxLayout()
        frame_row.addWidget(QLabel("Fotograma:"))
        self.frame_spin = QSpinBox()
        self.frame_spin.setRange(1, MAX_SPRITE_FRAMES)
        self.frame_spin.valueChanged.connect(self._on_frame_spin_changed)
        frame_row.addWidget(self.frame_spin)
        self.lbl_frame_count = QLabel("/ 1")
        frame_row.addWidget(self.lbl_frame_count)
        self.btn_add_frame = QPushButton("+ Fotograma")
        self.btn_add_frame.clicked.connect(self._action_add_frame)
        frame_row.addWidget(self.btn_add_frame)
        self.btn_del_frame = QPushButton("- Fotograma")
        self.btn_del_frame.clicked.connect(self._action_remove_frame)
        frame_row.addWidget(self.btn_del_frame)
        frame_row.addStretch()
        canvas_col.addLayout(frame_row)

        root.addLayout(canvas_col, stretch=1)

        side = QVBoxLayout()
        form = QFormLayout()
        self.spin_blocks_w = QSpinBox()
        self.spin_blocks_w.setRange(1, MAX_BLOCKS_PER_AXIS)
        form.addRow("Bloques ancho:", self.spin_blocks_w)
        self.spin_blocks_h = QSpinBox()
        self.spin_blocks_h.setRange(1, MAX_BLOCKS_PER_AXIS)
        form.addRow("Bloques alto:", self.spin_blocks_h)
        self.spin_cell_px = QSpinBox()
        self.spin_cell_px.setRange(1, 64)
        self.spin_cell_px.setValue(DEFAULT_CELL_PX)
        form.addRow("Px por bloque:", self.spin_cell_px)
        self.btn_resize = QPushButton("Redimensionar")
        self.btn_resize.clicked.connect(self._action_resize)
        form.addRow(self.btn_resize)
        self.spin_origin_x = QSpinBox()
        self.spin_origin_x.setRange(0, MAX_BLOCKS_PER_AXIS * 64)
        self.spin_origin_x.valueChanged.connect(self._on_origin_changed)
        form.addRow("Origen X:", self.spin_origin_x)
        self.spin_origin_y = QSpinBox()
        self.spin_origin_y.setRange(0, MAX_BLOCKS_PER_AXIS * 64)
        self.spin_origin_y.valueChanged.connect(self._on_origin_changed)
        form.addRow("Origen Y:", self.spin_origin_y)
        side.addLayout(form)

        side.addWidget(QLabel("Paleta del sprite (0–30):"))
        self.grid = PaletteGridWidget()
        self.grid.slot_selected.connect(self._on_slot_selected)
        side.addWidget(self.grid)
        side.addStretch()
        root.addLayout(side)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _current_rows(self) -> list[list[int]]:
        return self._frames[self._frame_index]

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

    def _load_sprite(self, stem: str) -> None:
        try:
            data = read_sprite_file(self.project_root, stem)
        except ValueError as e:
            QMessageBox.warning(self, "Abrir sprite", str(e))
            return
        cell_px, pw, ph = sprite_pixel_dimensions(data)
        self.sprite_id = stem
        self.cell_px = cell_px
        self.blocks_w = max(1, pw // cell_px)
        self.blocks_h = max(1, ph // cell_px)
        self.origin_x = int(data.get("origin_x", 0) or 0)
        self.origin_y = int(data.get("origin_y", 0) or 0)
        self.palette_rel = str(data.get("palette") or DEFAULT_EXAMPLE_PALETTE_REL)
        self._frames = parse_sprite_all_frame_rows(data, fill_index=TRANSPARENT_PALETTE_INDEX)
        self._frame_index = 0
        self._dirty = False

        self.spin_blocks_w.blockSignals(True)
        self.spin_blocks_w.setValue(self.blocks_w)
        self.spin_blocks_w.blockSignals(False)
        self.spin_blocks_h.blockSignals(True)
        self.spin_blocks_h.setValue(self.blocks_h)
        self.spin_blocks_h.blockSignals(False)
        self.spin_cell_px.blockSignals(True)
        self.spin_cell_px.setValue(self.cell_px)
        self.spin_cell_px.blockSignals(False)
        self.spin_origin_x.blockSignals(True)
        self.spin_origin_x.setValue(self.origin_x)
        self.spin_origin_x.blockSignals(False)
        self.spin_origin_y.blockSignals(True)
        self.spin_origin_y.setValue(self.origin_y)
        self.spin_origin_y.blockSignals(False)

        self.frame_spin.blockSignals(True)
        self.frame_spin.setValue(1)
        self.frame_spin.blockSignals(False)
        self.lbl_frame_count.setText(f"/ {len(self._frames)}")

        self.grid.set_colors(self._load_palette_colors(self.palette_rel))
        self._refresh_canvas()
        self.lbl_status.setText("")

    def _refresh_canvas(self) -> None:
        self.canvas.set_sprite(
            self._current_rows(),
            self.grid.colors(),
            cell_px=self.cell_px,
            origin_x=self.origin_x,
            origin_y=self.origin_y,
        )

    def _mark_dirty(self) -> None:
        self._dirty = True
        self.lbl_status.setText("Cambios sin guardar")

    def _set_tool(self, tool: Tool) -> None:
        self.canvas.set_tool(tool)
        self.btn_pencil.setChecked(tool == Tool.PENCIL)
        self.btn_eraser.setChecked(tool == Tool.ERASER)
        self.btn_dropper.setChecked(tool == Tool.EYEDROPPER)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_sprite_combo_changed(self, stem: str) -> None:
        if stem:
            self._load_sprite(stem)

    def _on_slot_selected(self, index: int) -> None:
        if index == TRANSPARENT_PALETTE_INDEX:
            return
        self.canvas.set_color_index(index)

    def _on_origin_changed(self, _value: int) -> None:
        self.origin_x = self.spin_origin_x.value()
        self.origin_y = self.spin_origin_y.value()
        self.canvas.origin_x = self.origin_x
        self.canvas.origin_y = self.origin_y
        self.canvas.update()
        self._mark_dirty()

    def _on_frame_spin_changed(self, value: int) -> None:
        idx = value - 1
        if 0 <= idx < len(self._frames):
            self._frame_index = idx
            self._refresh_canvas()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _action_new_sprite(self) -> None:
        name, ok = QInputDialog.getText(self, "Nuevo sprite", "Id del sprite:")
        if not ok or not name.strip():
            return
        try:
            sid = validate_sprite_id(name.strip())
            write_empty_sprite_json(self.project_root, sid)
        except ValueError as e:
            QMessageBox.warning(self, "Nuevo sprite", str(e))
            return
        self.refresh_sprite_list()
        self.open_sprite(sid)

    def _action_resize(self) -> None:
        new_bw = self.spin_blocks_w.value()
        new_bh = self.spin_blocks_h.value()
        new_cp = self.spin_cell_px.value()
        pw, ph = new_bw * new_cp, new_bh * new_cp
        self._frames = [
            normalize_palette_rows(fr, pw, ph, fill_index=TRANSPARENT_PALETTE_INDEX)
            for fr in self._frames
        ]
        self.blocks_w, self.blocks_h, self.cell_px = new_bw, new_bh, new_cp
        self._mark_dirty()
        self._refresh_canvas()

    def _action_add_frame(self) -> None:
        if len(self._frames) >= MAX_SPRITE_FRAMES:
            return
        pw, ph = self.canvas.pixel_size()
        self._frames.insert(
            self._frame_index + 1,
            [[TRANSPARENT_PALETTE_INDEX] * pw for _ in range(ph)],
        )
        self._frame_index += 1
        self.frame_spin.setRange(1, len(self._frames))
        self.frame_spin.blockSignals(True)
        self.frame_spin.setValue(self._frame_index + 1)
        self.frame_spin.blockSignals(False)
        self.lbl_frame_count.setText(f"/ {len(self._frames)}")
        self._mark_dirty()
        self._refresh_canvas()

    def _action_remove_frame(self) -> None:
        if len(self._frames) <= 1:
            return
        del self._frames[self._frame_index]
        self._frame_index = max(0, self._frame_index - 1)
        self.frame_spin.setRange(1, len(self._frames))
        self.frame_spin.blockSignals(True)
        self.frame_spin.setValue(self._frame_index + 1)
        self.frame_spin.blockSignals(False)
        self.lbl_frame_count.setText(f"/ {len(self._frames)}")
        self._mark_dirty()
        self._refresh_canvas()

    def _action_save(self) -> None:
        if not self.sprite_id:
            return
        try:
            save_indexed_pixels_sprite_json(
                self.project_root,
                self.sprite_id,
                palette_rel=self.palette_rel,
                blocks_w=self.blocks_w,
                blocks_h=self.blocks_h,
                rows=self._frames[0],
                frame_rows=self._frames,
                cell_px=self.cell_px,
                origin_x=self.origin_x,
                origin_y=self.origin_y,
            )
        except ValueError as e:
            QMessageBox.warning(self, "Guardar sprite", str(e))
            return
        self._dirty = False
        self.lbl_status.setText("Guardado.")
        self.saved.emit(self.project_root)
