"""Object editor tab — edit `objects/Objects/*.json` (sprite ref, animations, collision)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from turtlestudio.sprite_picker_dialog import SpritePickerDialog

from turtlestudio.build import hex_line_to_rgb01, load_palette_lines
from turtlestudio.edit_history import SnapshotHistory
from turtlestudio.i18n import tr
from turtlestudio.objects import (
    OBJECT_COLLISION_MODE_AABB,
    OBJECT_COLLISION_MODES,
    default_collision_from_sprite,
    list_object_json_stems,
    read_object_file,
    save_object_json,
    validate_object_id,
    write_object_json,
)
from turtlestudio.palette_policy import PALETTE_SIZE, TRANSPARENT_PALETTE_INDEX
from turtlestudio.project import DEFAULT_EXAMPLE_PALETTE_REL
from turtlestudio.sprites import (
    list_sprite_json_stems,
    parse_palette_rows_image,
    parse_sprite_origin,
    read_sprite_file,
    sprite_pixel_dimensions,
)

MAX_COORD = 256


def _load_palette_colors(project_root: Path, palette_rel: str) -> list[tuple[int, int, int]]:
    path = project_root / palette_rel
    try:
        hexes = load_palette_lines(path)
    except OSError:
        hexes = []
    rgbs01 = [hex_line_to_rgb01(h) for h in hexes] if hexes else []
    colors = [(round(r * 255), round(g * 255), round(b * 255)) for r, g, b in rgbs01]
    if len(colors) < PALETTE_SIZE:
        colors += [(0, 0, 0)] * (PALETTE_SIZE - len(colors))
    return colors[:PALETTE_SIZE]


def _load_sprite_preview(project_root: Path, sprite_id: str) -> dict[str, Any] | None:
    try:
        sd = read_sprite_file(project_root, sprite_id)
    except ValueError:
        return None
    _, pw, ph = sprite_pixel_dimensions(sd)
    ox, oy = parse_sprite_origin(sd, pw=pw, ph=ph)
    pal_rel = str(sd.get("palette") or DEFAULT_EXAMPLE_PALETTE_REL)
    colors = _load_palette_colors(project_root, pal_rel)
    rows = parse_palette_rows_image(sd) or [[TRANSPARENT_PALETTE_INDEX] * pw for _ in range(ph)]
    return {"rows": rows, "colors": colors, "pw": pw, "ph": ph, "origin_x": ox, "origin_y": oy}


class ObjectPreviewCanvas(QWidget):
    """Sprite preview with an origin marker and a draggable AABB collision overlay."""

    collision_dragged = pyqtSignal(int, int, int, int)  # x0, y0, x1, y1 (origin-relative)
    collision_drag_finished = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows: list[list[int]] = []
        self.palette: list[tuple[int, int, int]] = []
        self.pw = 0
        self.ph = 0
        self.origin_x = 0
        self.origin_y = 0
        self.zoom = 12
        self.collision: dict[str, Any] | None = None
        self._collision_selected = False
        self._dragging_resize: str | None = None
        self._dragging_move = False
        self._drag_start_screen: tuple[float, float] | None = None
        self._drag_start_collision: tuple[int, int, int, int] | None = None
        self.setMouseTracking(True)
        self.setToolTip(tr("object.collision_drag_hint"))

    def set_sprite(self, info: dict[str, Any]) -> None:
        self.rows = info["rows"]
        self.palette = info["colors"]
        self.pw = info["pw"]
        self.ph = info["ph"]
        self.origin_x = info["origin_x"]
        self.origin_y = info["origin_y"]
        self._update_minimum_size()
        self.update()

    def set_zoom(self, zoom: int) -> None:
        self.zoom = max(2, min(48, zoom))
        self._update_minimum_size()
        self.update()

    def set_collision(self, collision: dict[str, Any] | None) -> None:
        self.collision = collision
        self._collision_selected = False
        self._dragging_resize = None
        self._dragging_move = False
        self._drag_start_screen = None
        self._drag_start_collision = None
        self.update()

    def _update_minimum_size(self) -> None:
        self.setMinimumSize(max(1, self.pw) * self.zoom, max(1, self.ph) * self.zoom)

    def _to_canvas_row(self, y: int) -> int:
        """Origin-relative sprite-space y (up) -> pixel row from the top."""
        return (self.ph - 1) - (self.origin_y + y)

    # ------------------------------------------------------------------
    # Border-drag geometry (click/drag the AABB collider like the
    # Semi-FantasyConsole object editor does)
    # ------------------------------------------------------------------

    def _aabb_box(self) -> tuple[int, int, int, int] | None:
        if self.collision is None or self.collision.get("mode") != OBJECT_COLLISION_MODE_AABB:
            return None
        return (
            int(self.collision["x0"]),
            int(self.collision["y0"]),
            int(self.collision["x1"]),
            int(self.collision["y1"]),
        )

    def _aabb_screen_rect(self) -> tuple[float, float, float, float] | None:
        """Screen-space (left, top, right, bottom) for the current AABB collider."""
        box = self._aabb_box()
        if box is None:
            return None
        x0, y0, x1, y1 = box
        z = self.zoom
        left = (self.origin_x + x0) * z
        top = self._to_canvas_row(y1) * z
        right = left + max(0, x1 - x0 + 1) * z
        bottom = top + max(0, y1 - y0 + 1) * z
        return left, top, right, bottom

    def _edge_positions(self) -> dict[str, tuple[float, float]]:
        rect = self._aabb_screen_rect()
        if rect is None:
            return {}
        left, top, right, bottom = rect
        mx, my = (left + right) / 2, (top + bottom) / 2
        return {"top": (mx, top), "bottom": (mx, bottom), "left": (left, my), "right": (right, my)}

    def _edge_hit(self, mx: float, my: float, radius: int = 7) -> str | None:
        if not self._collision_selected:
            return None
        for edge, (ex, ey) in self._edge_positions().items():
            if (mx - ex) ** 2 + (my - ey) ** 2 <= radius * radius:
                return edge
        return None

    def _center_hit(self, mx: float, my: float, radius: int = 10) -> bool:
        rect = self._aabb_screen_rect()
        if rect is None:
            return False
        left, top, right, bottom = rect
        cx, cy = (left + right) / 2, (top + bottom) / 2
        return (mx - cx) ** 2 + (my - cy) ** 2 <= radius * radius

    def _is_near_border(self, mx: float, my: float, threshold: int = 6) -> bool:
        rect = self._aabb_screen_rect()
        if rect is None:
            return False
        left, top, right, bottom = rect
        in_outer = left - threshold <= mx <= right + threshold and top - threshold <= my <= bottom + threshold
        in_inner = left + threshold < mx < right - threshold and top + threshold < my < bottom - threshold
        return in_outer and not in_inner

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        mx, my = event.position().x(), event.position().y()

        if self._collision_selected:
            edge = self._edge_hit(mx, my)
            if edge is not None:
                self._dragging_resize = edge
                self._drag_start_screen = (mx, my)
                self._drag_start_collision = self._aabb_box()
                return
            if self._center_hit(mx, my):
                self._dragging_move = True
                self._drag_start_screen = (mx, my)
                self._drag_start_collision = self._aabb_box()
                return

        if self._is_near_border(mx, my):
            if not self._collision_selected:
                self._collision_selected = True
                self.update()
            return

        if self._collision_selected:
            self._collision_selected = False
            self.update()

    def _apply_resize_drag(self, mx: float, my: float) -> None:
        if self._drag_start_screen is None or self._drag_start_collision is None:
            return
        z = self.zoom
        dx_px = int((mx - self._drag_start_screen[0]) / z)
        dy_px = int((my - self._drag_start_screen[1]) / z)
        x0, y0, x1, y1 = self._drag_start_collision
        nx0, ny0, nx1, ny1 = x0, y0, x1, y1
        if self._dragging_resize == "top":
            ny1 = max(y0, min(MAX_COORD, y1 - dy_px))
        elif self._dragging_resize == "bottom":
            ny0 = min(y1, max(-MAX_COORD, y0 - dy_px))
        elif self._dragging_resize == "left":
            nx0 = min(x1, max(-MAX_COORD, x0 + dx_px))
        elif self._dragging_resize == "right":
            nx1 = max(x0, min(MAX_COORD, x1 + dx_px))
        if (nx0, ny0, nx1, ny1) != self._aabb_box():
            self.collision["x0"], self.collision["y0"] = nx0, ny0
            self.collision["x1"], self.collision["y1"] = nx1, ny1
            self.collision_dragged.emit(nx0, ny0, nx1, ny1)
            self.update()

    def _apply_move_drag(self, mx: float, my: float) -> None:
        if self._drag_start_screen is None or self._drag_start_collision is None:
            return
        z = self.zoom
        x0, y0, x1, y1 = self._drag_start_collision
        dx_px = int((mx - self._drag_start_screen[0]) / z)
        dy_px = int((my - self._drag_start_screen[1]) / z)
        dx_px = max(-MAX_COORD - x0, min(MAX_COORD - x1, dx_px))
        dy_px = max(y1 - MAX_COORD, min(MAX_COORD + y0, dy_px))
        nx0, nx1 = x0 + dx_px, x1 + dx_px
        ny0, ny1 = y0 - dy_px, y1 - dy_px
        if (nx0, ny0, nx1, ny1) != self._aabb_box():
            self.collision["x0"], self.collision["y0"] = nx0, ny0
            self.collision["x1"], self.collision["y1"] = nx1, ny1
            self.collision_dragged.emit(nx0, ny0, nx1, ny1)
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        mx, my = event.position().x(), event.position().y()

        if self._dragging_resize is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._apply_resize_drag(mx, my)
            return

        if self._dragging_move and event.buttons() & Qt.MouseButton.LeftButton:
            self._apply_move_drag(mx, my)
            return

        if self._collision_selected:
            edge = self._edge_hit(mx, my)
            if edge in ("top", "bottom"):
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif edge in ("left", "right"):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif self._center_hit(mx, my) or self._is_near_border(mx, my):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        elif self._is_near_border(mx, my):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            was_dragging = self._dragging_resize is not None or self._dragging_move
            self._dragging_resize = None
            self._dragging_move = False
            self._drag_start_screen = None
            self._drag_start_collision = None
            if was_dragging:
                self.collision_drag_finished.emit()

    def _draw_collision_handles(self, painter: QPainter, sx0: float, sy0: float, sx1: float, sy1: float) -> None:
        mx, my = (sx0 + sx1) / 2, (sy0 + sy1) / 2
        pen = QPen(QColor(255, 255, 255, 230))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(QColor(255, 90, 90, 220))
        r = 4
        for ex, ey in ((mx, sy0), (mx, sy1), (sx0, my), (sx1, my)):
            painter.drawEllipse(int(ex - r), int(ey - r), r * 2, r * 2)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        arm = 8
        painter.drawLine(int(mx - arm), int(my), int(mx + arm), int(my))
        painter.drawLine(int(mx), int(my - arm), int(mx), int(my + arm))

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        z = self.zoom
        painter.fillRect(self.rect(), QColor(26, 26, 46))
        for y in range(self.ph):
            row = self.rows[y] if y < len(self.rows) else []
            for x in range(self.pw):
                idx = row[x] if x < len(row) else TRANSPARENT_PALETTE_INDEX
                if idx == TRANSPARENT_PALETTE_INDEX:
                    shade = 60 if (x // 4 + y // 4) % 2 == 0 else 45
                    painter.fillRect(x * z, y * z, z, z, QColor(shade, shade, shade))
                elif idx < len(self.palette):
                    r, g, b = self.palette[idx]
                    painter.fillRect(x * z, y * z, z, z, QColor(r, g, b))

        oy_top = self.ph - 1 - self.origin_y
        pen = QPen(QColor(255, 230, 50, 230))
        pen.setWidth(2)
        painter.setPen(pen)
        cx, cy = self.origin_x * z + z // 2, oy_top * z + z // 2
        painter.drawLine(cx - 6, cy, cx + 6, cy)
        painter.drawLine(cx, cy - 6, cx, cy + 6)

        if self.collision is not None:
            pen = QPen(QColor(255, 90, 90, 220))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            mode = self.collision.get("mode")
            if mode == OBJECT_COLLISION_MODE_AABB:
                x0, y0, x1, y1 = (
                    int(self.collision["x0"]),
                    int(self.collision["y0"]),
                    int(self.collision["x1"]),
                    int(self.collision["y1"]),
                )
                left = self.origin_x + x0
                top = self._to_canvas_row(y1)
                w = max(0, x1 - x0 + 1)
                h = max(0, y1 - y0 + 1)
                painter.drawRect(left * z, top * z, w * z, h * z)
                if self._collision_selected or self._dragging_resize or self._dragging_move:
                    self._draw_collision_handles(painter, left * z, top * z, (left + w) * z, (top + h) * z)
            else:
                pts = self.collision.get("points") or []
                poly = [
                    (
                        (self.origin_x + int(px)) * z + z // 2,
                        self._to_canvas_row(int(py)) * z + z // 2,
                    )
                    for px, py in pts
                ]
                for i in range(len(poly)):
                    x1, y1 = poly[i]
                    x2, y2 = poly[(i + 1) % len(poly)]
                    painter.drawLine(x1, y1, x2, y2)
        painter.end()


class ObjectEditorWidget(QWidget):
    def __init__(self, project_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project_root = project_root
        self.object_id = ""
        self.sprite_id = ""
        self.animations: list[dict[str, str]] = []
        self.collision: dict[str, Any] | None = None
        self.script: str | None = None
        self._dirty = False
        self._suspend = False
        self._history = SnapshotHistory()
        self._restoring = False
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_project_root(self, root: Path) -> None:
        self.project_root = root
        self.refresh_object_list()

    def refresh_object_list(self) -> None:
        current = self.combo_object.currentText()
        self.combo_object.blockSignals(True)
        self.combo_object.clear()
        stems = list_object_json_stems(self.project_root)
        self.combo_object.addItems(stems)
        self.combo_object.blockSignals(False)
        if stems:
            target = current if current in stems else stems[0]
            idx = self.combo_object.findText(target)
            self.combo_object.setCurrentIndex(max(idx, 0))
            self.open_object(self.combo_object.currentText())

    def open_object(self, stem: str) -> None:
        if not stem:
            return
        idx = self.combo_object.findText(stem)
        if idx < 0:
            self.refresh_object_list()
            idx = self.combo_object.findText(stem)
        if idx >= 0:
            self.combo_object.setCurrentIndex(idx)
        self._load_object(stem)

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel(tr("object.label")))
        self.combo_object = QComboBox()
        self.combo_object.setMinimumWidth(180)
        self.combo_object.currentTextChanged.connect(self._on_object_combo_changed)
        top_row.addWidget(self.combo_object)
        self.btn_new = QPushButton(tr("common.new"))
        self.btn_new.clicked.connect(self._action_new_object)
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
        self.canvas = ObjectPreviewCanvas()
        self.canvas.collision_dragged.connect(self._on_preview_collision_dragged)
        self.canvas.collision_drag_finished.connect(self._on_preview_collision_drag_finished)
        canvas_scroll = QScrollArea()
        canvas_scroll.setWidgetResizable(True)
        canvas_scroll.setWidget(self.canvas)
        canvas_col.addWidget(canvas_scroll, stretch=1)

        tools = QHBoxLayout()
        tools.addWidget(QLabel(tr("common.zoom")))
        self.zoom_spin = QSpinBox()
        self.zoom_spin.setRange(2, 48)
        self.zoom_spin.setValue(12)
        self.zoom_spin.valueChanged.connect(self.canvas.set_zoom)
        tools.addWidget(self.zoom_spin)
        tools.addStretch()
        canvas_col.addLayout(tools)
        root.addLayout(canvas_col, stretch=1)

        side = QVBoxLayout()
        form = QFormLayout()
        self.lbl_object_id = QLabel("—")
        form.addRow(tr("object.id_label"), self.lbl_object_id)
        self.edit_name = QLineEdit()
        self.edit_name.editingFinished.connect(self._on_name_edited)
        form.addRow(tr("object.name_label"), self.edit_name)
        sprite_row = QHBoxLayout()
        self.lbl_sprite_id = QLabel("—")
        self.lbl_sprite_id.setStyleSheet("font-family: monospace;")
        sprite_row.addWidget(self.lbl_sprite_id, stretch=1)
        self.btn_pick_sprite = QPushButton(tr("object.pick_sprite"))
        self.btn_pick_sprite.clicked.connect(self._action_pick_sprite)
        sprite_row.addWidget(self.btn_pick_sprite)
        form.addRow(tr("object.sprite_label"), sprite_row)
        self.edit_script = QLineEdit()
        self.edit_script.editingFinished.connect(self._on_script_edited)
        form.addRow(tr("object.script_label"), self.edit_script)
        side.addLayout(form)

        anim_box = QGroupBox(tr("object.animations_group"))
        anim_layout = QVBoxLayout(anim_box)
        self.list_animations = QListWidget()
        self.list_animations.currentRowChanged.connect(self._on_animation_selected)
        anim_layout.addWidget(self.list_animations)
        anim_btn_row = QHBoxLayout()
        self.btn_add_animation = QPushButton(tr("object.add_animation"))
        self.btn_add_animation.clicked.connect(self._action_add_animation)
        anim_btn_row.addWidget(self.btn_add_animation)
        self.btn_remove_animation = QPushButton(tr("object.remove_animation"))
        self.btn_remove_animation.clicked.connect(self._action_remove_animation)
        anim_btn_row.addWidget(self.btn_remove_animation)
        anim_layout.addLayout(anim_btn_row)
        side.addWidget(anim_box)

        coll_box = QGroupBox(tr("object.collision_group"))
        coll_layout = QVBoxLayout(coll_box)
        self.chk_has_collision = QCheckBox(tr("object.has_collision"))
        self.chk_has_collision.toggled.connect(self._on_has_collision_toggled)
        coll_layout.addWidget(self.chk_has_collision)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(tr("object.collision_mode_label")))
        self.combo_coll_mode = QComboBox()
        self.combo_coll_mode.addItems(list(OBJECT_COLLISION_MODES))
        self.combo_coll_mode.currentTextChanged.connect(self._on_collision_mode_changed)
        mode_row.addWidget(self.combo_coll_mode)
        coll_layout.addLayout(mode_row)

        self.spin_x0 = QSpinBox()
        self.spin_y0 = QSpinBox()
        self.spin_x1 = QSpinBox()
        self.spin_y1 = QSpinBox()
        for s in (self.spin_x0, self.spin_y0, self.spin_x1, self.spin_y1):
            s.setRange(-MAX_COORD, MAX_COORD)
            s.valueChanged.connect(self._on_aabb_spin_changed)
        aabb_row1 = QHBoxLayout()
        aabb_row1.addWidget(QLabel("x0:"))
        aabb_row1.addWidget(self.spin_x0)
        aabb_row1.addWidget(QLabel("y0:"))
        aabb_row1.addWidget(self.spin_y0)
        coll_layout.addLayout(aabb_row1)
        aabb_row2 = QHBoxLayout()
        aabb_row2.addWidget(QLabel("x1:"))
        aabb_row2.addWidget(self.spin_x1)
        aabb_row2.addWidget(QLabel("y1:"))
        aabb_row2.addWidget(self.spin_y1)
        coll_layout.addLayout(aabb_row2)

        self.lbl_points = QLabel("")
        self.lbl_points.setWordWrap(True)
        self.lbl_points.setStyleSheet("color: #888; font-size: 11px;")
        coll_layout.addWidget(self.lbl_points)

        self.btn_auto_shape = QPushButton(tr("object.auto_shape"))
        self.btn_auto_shape.clicked.connect(self._action_auto_shape)
        coll_layout.addWidget(self.btn_auto_shape)

        side.addWidget(coll_box)
        side.addStretch()
        root.addLayout(side)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refresh_sprite_label(self) -> None:
        self.lbl_sprite_id.setText(self.sprite_id or "—")

    def _refresh_animation_list(self) -> None:
        self.list_animations.blockSignals(True)
        self.list_animations.clear()
        for a in self.animations:
            self.list_animations.addItem(f"{a['name']} → {a['sprite_id']}")
        self.list_animations.blockSignals(False)

    def _refresh_preview_sprite(self, sprite_id: str) -> None:
        info = _load_sprite_preview(self.project_root, sprite_id)
        if info is not None:
            self.canvas.set_sprite(info)

    def _refresh_collision_form(self) -> None:
        self._suspend = True
        has = self.collision is not None
        self.chk_has_collision.setChecked(has)
        mode = str(self.collision.get("mode", OBJECT_COLLISION_MODE_AABB)) if has else OBJECT_COLLISION_MODE_AABB
        idx = self.combo_coll_mode.findText(mode)
        self.combo_coll_mode.setCurrentIndex(max(0, idx))
        is_aabb = has and mode == OBJECT_COLLISION_MODE_AABB
        if is_aabb:
            self.spin_x0.setValue(int(self.collision.get("x0", 0)))
            self.spin_y0.setValue(int(self.collision.get("y0", 0)))
            self.spin_x1.setValue(int(self.collision.get("x1", 0)))
            self.spin_y1.setValue(int(self.collision.get("y1", 0)))
        for s in (self.spin_x0, self.spin_y0, self.spin_x1, self.spin_y1):
            s.setEnabled(is_aabb)
        self.combo_coll_mode.setEnabled(has)
        self.btn_auto_shape.setEnabled(has)
        if has and mode != OBJECT_COLLISION_MODE_AABB:
            pts = self.collision.get("points") or []
            self.lbl_points.setText(tr("object.points_label") + " " + ", ".join(f"({p[0]},{p[1]})" for p in pts))
        else:
            self.lbl_points.setText("")
        self._suspend = False
        self.canvas.set_collision(self.collision)

    def _mark_dirty(self) -> None:
        self._dirty = True
        self.lbl_status.setText(tr("common.unsaved_changes"))

    def _load_object(self, stem: str) -> None:
        try:
            data = read_object_file(self.project_root, stem)
        except ValueError as e:
            QMessageBox.warning(self, tr("object.open_error_title"), str(e))
            return
        self.object_id = stem
        self.sprite_id = str(data.get("sprite_id", "")).strip()
        self.script = data.get("script") if isinstance(data.get("script"), str) else None
        raw_anims = data.get("animations")
        self.animations = (
            [{"name": str(a.get("name", "")), "sprite_id": str(a.get("sprite_id", ""))} for a in raw_anims]
            if isinstance(raw_anims, list)
            else []
        )
        raw_coll = data.get("collision")
        self.collision = dict(raw_coll) if isinstance(raw_coll, dict) else None
        self._dirty = False

        self._suspend = True
        self.lbl_object_id.setText(self.object_id)
        self.edit_name.setText(str(data.get("name", self.object_id)))
        self.edit_script.setText(self.script or "")
        self._refresh_sprite_label()
        self._suspend = False
        self._refresh_animation_list()
        self._refresh_preview_sprite(self.sprite_id)
        self._refresh_collision_form()
        self.lbl_status.setText("")
        self._history.reset(self._snapshot())

    # ------------------------------------------------------------------
    # Undo/redo
    # ------------------------------------------------------------------

    def _snapshot(self) -> dict[str, Any]:
        return {
            "name": self.edit_name.text(),
            "sprite_id": self.sprite_id,
            "script": self.script,
            "animations": self.animations,
            "collision": self.collision,
        }

    def _commit_history(self) -> None:
        if self._restoring:
            return
        self._history.commit(self._snapshot())

    def _restore(self, state: dict[str, Any]) -> None:
        self._restoring = True
        try:
            self.sprite_id = state["sprite_id"]
            self.script = state["script"]
            self.animations = state["animations"]
            self.collision = state["collision"]

            self._suspend = True
            self.edit_name.setText(state["name"])
            self.edit_script.setText(self.script or "")
            self._refresh_sprite_label()
            self._suspend = False

            self._refresh_animation_list()
            self._refresh_preview_sprite(self.sprite_id)
            self._refresh_collision_form()
        finally:
            self._restoring = False
        self._mark_dirty()

    def undo(self) -> None:
        state = self._history.undo()
        if state is not None:
            self._restore(state)

    def redo(self) -> None:
        state = self._history.redo()
        if state is not None:
            self._restore(state)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_object_combo_changed(self, stem: str) -> None:
        if stem:
            self._load_object(stem)

    def _on_name_edited(self) -> None:
        self._mark_dirty()
        self._commit_history()

    def _on_sprite_changed(self, text: str) -> None:
        if self._suspend or not text:
            return
        self.sprite_id = text
        self._refresh_sprite_label()
        self._refresh_preview_sprite(self.sprite_id)
        self._mark_dirty()
        self._commit_history()

    def _action_pick_sprite(self) -> None:
        dlg = SpritePickerDialog(self.project_root, self.sprite_id, parent=self)
        if dlg.exec() and dlg.selected_sprite_id:
            self._on_sprite_changed(dlg.selected_sprite_id)

    def _on_script_edited(self) -> None:
        text = self.edit_script.text().strip()
        self.script = text or None
        self._mark_dirty()
        self._commit_history()

    def _on_animation_selected(self, index: int) -> None:
        if 0 <= index < len(self.animations):
            self._refresh_preview_sprite(self.animations[index]["sprite_id"])
        else:
            self._refresh_preview_sprite(self.sprite_id)

    def _on_has_collision_toggled(self, checked: bool) -> None:
        if self._suspend:
            return
        if not checked:
            self.collision = None
            self._mark_dirty()
            self._refresh_collision_form()
            self._commit_history()
            return
        try:
            sprite_data = read_sprite_file(self.project_root, self.sprite_id)
        except ValueError as e:
            self.chk_has_collision.setChecked(False)
            QMessageBox.warning(self, tr("object.collision_group"), str(e))
            return
        self.collision = default_collision_from_sprite(sprite_data, mode=self.combo_coll_mode.currentText())
        self._mark_dirty()
        self._refresh_collision_form()
        self._commit_history()

    def _on_collision_mode_changed(self, mode: str) -> None:
        if self._suspend or self.collision is None:
            return
        self._regenerate_shape(mode)

    def _on_aabb_spin_changed(self, _value: int) -> None:
        if self._suspend or self.collision is None:
            return
        self.collision = {
            "mode": OBJECT_COLLISION_MODE_AABB,
            "x0": self.spin_x0.value(),
            "y0": self.spin_y0.value(),
            "x1": max(self.spin_x0.value(), self.spin_x1.value()),
            "y1": max(self.spin_y0.value(), self.spin_y1.value()),
        }
        self._mark_dirty()
        self.canvas.set_collision(self.collision)
        self._commit_history()

    def _on_preview_collision_dragged(self, x0: int, y0: int, x1: int, y1: int) -> None:
        if self.collision is None:
            return
        self.collision["x0"], self.collision["y0"] = x0, y0
        self.collision["x1"], self.collision["y1"] = x1, y1
        self._suspend = True
        self.spin_x0.setValue(x0)
        self.spin_y0.setValue(y0)
        self.spin_x1.setValue(x1)
        self.spin_y1.setValue(y1)
        self._suspend = False
        self._mark_dirty()

    def _on_preview_collision_drag_finished(self) -> None:
        self._commit_history()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _regenerate_shape(self, mode: str) -> None:
        try:
            sprite_data = read_sprite_file(self.project_root, self.sprite_id)
        except ValueError:
            return
        self.collision = default_collision_from_sprite(sprite_data, mode=mode)
        self._mark_dirty()
        self._refresh_collision_form()
        self._commit_history()

    def _action_auto_shape(self) -> None:
        self._regenerate_shape(self.combo_coll_mode.currentText())

    def _action_add_animation(self) -> None:
        if not list_sprite_json_stems(self.project_root):
            QMessageBox.warning(self, tr("object.new_animation_title"), tr("object.no_sprites"))
            return
        name, ok = QInputDialog.getText(self, tr("object.new_animation_title"), tr("object.new_animation_name_label"))
        if not ok or not name.strip():
            return
        dlg = SpritePickerDialog(self.project_root, self.sprite_id, parent=self)
        dlg.setWindowTitle(tr("object.new_animation_title"))
        if not dlg.exec() or not dlg.selected_sprite_id:
            return
        if len(self.animations) >= 32:
            return
        self.animations.append({"name": name.strip(), "sprite_id": dlg.selected_sprite_id})
        self._refresh_animation_list()
        self._mark_dirty()
        self._commit_history()

    def _action_remove_animation(self) -> None:
        idx = self.list_animations.currentRow()
        if 0 <= idx < len(self.animations):
            del self.animations[idx]
            self._refresh_animation_list()
            self._mark_dirty()
            self._commit_history()

    def _action_new_object(self) -> None:
        name, ok = QInputDialog.getText(self, tr("object.new_title"), tr("object.new_id_label"))
        if not ok or not name.strip():
            return
        sprites = list_sprite_json_stems(self.project_root)
        if not sprites:
            QMessageBox.warning(self, tr("object.new_title"), tr("object.no_sprites"))
            return
        sprite_id, ok = QInputDialog.getItem(self, tr("object.new_title"), tr("object.new_sprite_label"), sprites, 0, False)
        if not ok:
            return
        try:
            oid = validate_object_id(name.strip())
            write_object_json(self.project_root, oid, name=oid, sprite_id=sprite_id)
        except ValueError as e:
            QMessageBox.warning(self, tr("object.new_title"), str(e))
            return
        self.refresh_object_list()
        self.open_object(oid)

    def _action_save(self) -> None:
        if not self.object_id:
            return
        try:
            save_object_json(
                self.project_root,
                self.object_id,
                name=self.edit_name.text().strip() or self.object_id,
                sprite_id=self.sprite_id,
                animations=self.animations,
                collision=self.collision,
                script=self.script,
            )
        except ValueError as e:
            QMessageBox.warning(self, tr("object.save_error_title"), str(e))
            return
        self._dirty = False
        self.lbl_status.setText(tr("common.saved"))
