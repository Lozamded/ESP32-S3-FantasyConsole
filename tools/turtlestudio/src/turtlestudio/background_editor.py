"""Background editor tab — paint `backgrounds/*.json` (solid color or indexed pixels)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from turtlestudio.background_import_dialog import BackgroundImportDialog
from turtlestudio.backgrounds import (
    MAX_BACKGROUND_PIXEL_H,
    MAX_BACKGROUND_PIXEL_W,
    background_is_indexed_pixels,
    background_pixel_dimensions,
    list_background_json_stems,
    list_palette_relpaths,
    parse_background_palette_rows,
    parse_background_solid_palette_index,
    read_background_file,
    save_background_json,
    validate_background_id,
    write_solid_background_json,
)
from turtlestudio.build import hex_line_to_rgb01, load_palette_lines
from turtlestudio.edit_history import SnapshotHistory
from turtlestudio.i18n import tr
from turtlestudio.palette_editor import PaletteGridWidget
from turtlestudio.palette_policy import PALETTE_SIZE, TRANSPARENT_PALETTE_INDEX
from turtlestudio.project import (
    DEFAULT_EXAMPLE_PALETTE_REL,
    SCENE_PIXEL_H,
    SCENE_PIXEL_W,
    manifest_path,
    parse_viewport_from_manifest,
)
from turtlestudio.scene_editor import _tool_icon
from turtlestudio.sprite_editor import SpriteCanvas, Tool
from turtlestudio.sprites import normalize_palette_rows, solid_fill_indices

MODE_SOLID = "solid"
MODE_INDEXED = "indexed"


class BackgroundEditorWidget(QWidget):
    def __init__(self, project_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project_root = project_root
        self.background_id = ""
        self.pixel_w = SCENE_PIXEL_W
        self.pixel_h = SCENE_PIXEL_H
        self.palette_rel = DEFAULT_EXAMPLE_PALETTE_REL
        self.mode = MODE_SOLID
        self.rows: list[list[int]] = []
        self.solid_index = 0
        self._dirty = False
        self._history = SnapshotHistory()
        self._restoring = False
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_project_root(self, root: Path) -> None:
        self.project_root = root
        try:
            data = json.loads(manifest_path(root).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        self.pixel_w, self.pixel_h = parse_viewport_from_manifest(data)
        self.spin_pw.blockSignals(True)
        self.spin_pw.setValue(self.pixel_w)
        self.spin_pw.blockSignals(False)
        self.spin_ph.blockSignals(True)
        self.spin_ph.setValue(self.pixel_h)
        self.spin_ph.blockSignals(False)
        self.refresh_background_list()

    def refresh_background_list(self) -> None:
        current = self.combo_bg.currentText()
        self.combo_bg.blockSignals(True)
        self.combo_bg.clear()
        stems = list_background_json_stems(self.project_root)
        self.combo_bg.addItems(stems)
        self.combo_bg.blockSignals(False)
        if stems:
            target = current if current in stems else stems[0]
            idx = self.combo_bg.findText(target)
            self.combo_bg.setCurrentIndex(max(idx, 0))
            self.open_background(self.combo_bg.currentText())

    def open_background(self, stem: str) -> None:
        if not stem:
            return
        idx = self.combo_bg.findText(stem)
        if idx < 0:
            self.refresh_background_list()
            idx = self.combo_bg.findText(stem)
        if idx >= 0:
            self.combo_bg.setCurrentIndex(idx)
        self._load_background(stem)

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel(tr("background.label")))
        self.combo_bg = QComboBox()
        self.combo_bg.setMinimumWidth(180)
        self.combo_bg.currentTextChanged.connect(self._on_bg_combo_changed)
        top_row.addWidget(self.combo_bg)
        self.btn_new = QPushButton(tr("common.new"))
        self.btn_new.clicked.connect(self._action_new_background)
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
        self.canvas = SpriteCanvas()
        self.canvas.changed.connect(self._mark_dirty)
        self.canvas.stroke_finished.connect(self._commit_history)
        self.canvas.tool_context_menu_requested.connect(self._on_canvas_context_menu)
        canvas_scroll = QScrollArea()
        canvas_scroll.setWidgetResizable(True)
        canvas_scroll.setWidget(self.canvas)
        canvas_col.addWidget(canvas_scroll, stretch=1)

        tools = QHBoxLayout()
        self.btn_pencil = QPushButton(tr("common.pencil"))
        self.btn_pencil.setIcon(_tool_icon("pencil"))
        self.btn_pencil.setIconSize(QSize(18, 18))
        self.btn_pencil.setCheckable(True)
        self.btn_pencil.setChecked(True)
        self.btn_pencil.clicked.connect(lambda: self._set_tool(Tool.PENCIL))
        tools.addWidget(self.btn_pencil)
        self.btn_eraser = QPushButton(tr("common.eraser"))
        self.btn_eraser.setIcon(_tool_icon("eraser"))
        self.btn_eraser.setIconSize(QSize(18, 18))
        self.btn_eraser.setCheckable(True)
        self.btn_eraser.clicked.connect(lambda: self._set_tool(Tool.ERASER))
        tools.addWidget(self.btn_eraser)
        self.btn_dropper = QPushButton(tr("common.eyedropper"))
        self.btn_dropper.setIcon(_tool_icon("eyedropper"))
        self.btn_dropper.setIconSize(QSize(18, 18))
        self.btn_dropper.setCheckable(True)
        self.btn_dropper.clicked.connect(lambda: self._set_tool(Tool.EYEDROPPER))
        tools.addWidget(self.btn_dropper)
        self.btn_bucket = QPushButton(tr("common.bucket"))
        self.btn_bucket.setIcon(_tool_icon("bucket"))
        self.btn_bucket.setIconSize(QSize(18, 18))
        self.btn_bucket.setCheckable(True)
        self.btn_bucket.clicked.connect(lambda: self._set_tool(Tool.BUCKET))
        tools.addWidget(self.btn_bucket)
        tools.addSpacing(8)
        tools.addWidget(QLabel(tr("scene.current_tool_label")))
        self.lbl_current_tool_icon = QLabel()
        self.lbl_current_tool_icon.setFixedSize(26, 26)
        tools.addWidget(self.lbl_current_tool_icon)
        self._update_current_tool_icon()
        tools.addWidget(QLabel(tr("common.zoom")))
        self.zoom_spin = QSpinBox()
        self.zoom_spin.setRange(1, 16)
        self.zoom_spin.setValue(3)
        self.zoom_spin.valueChanged.connect(self.canvas.set_zoom)
        tools.addWidget(self.zoom_spin)
        tools.addStretch()
        canvas_col.addLayout(tools)

        root.addLayout(canvas_col, stretch=1)

        side = QVBoxLayout()
        form = QFormLayout()
        self.combo_mode = QComboBox()
        self.combo_mode.addItem(tr("background.mode_solid"), MODE_SOLID)
        self.combo_mode.addItem(tr("background.mode_indexed"), MODE_INDEXED)
        self.combo_mode.currentIndexChanged.connect(self._on_mode_combo_changed)
        form.addRow(tr("background.mode_label"), self.combo_mode)
        self.spin_pw = QSpinBox()
        self.spin_pw.setRange(1, MAX_BACKGROUND_PIXEL_W)
        self.spin_pw.setValue(SCENE_PIXEL_W)
        form.addRow(tr("background.width_px"), self.spin_pw)
        self.spin_ph = QSpinBox()
        self.spin_ph.setRange(1, MAX_BACKGROUND_PIXEL_H)
        self.spin_ph.setValue(SCENE_PIXEL_H)
        form.addRow(tr("background.height_px"), self.spin_ph)
        self.btn_resize = QPushButton(tr("common.resize"))
        self.btn_resize.clicked.connect(self._action_resize)
        form.addRow(self.btn_resize)
        self.btn_import = QPushButton(tr("background.import_button"))
        self.btn_import.clicked.connect(self._action_import_image)
        form.addRow(self.btn_import)
        self.lbl_solid_preview = QLabel("")
        self.lbl_solid_preview.setFixedSize(60, 24)
        self.lbl_solid_preview.setStyleSheet("border: 1px solid #555;")
        form.addRow(tr("background.solid_color_label"), self.lbl_solid_preview)
        side.addLayout(form)

        side.addWidget(QLabel(tr("background.palette_hint")))
        self.grid = PaletteGridWidget()
        self.grid.slot_selected.connect(self._on_slot_selected)
        side.addWidget(self.grid)
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

    def _load_background(self, stem: str) -> None:
        try:
            data = read_background_file(self.project_root, stem)
        except ValueError as e:
            QMessageBox.warning(self, tr("background.open_error_title"), str(e))
            return
        self.background_id = stem
        self.pixel_w, self.pixel_h = background_pixel_dimensions(data)
        self.palette_rel = str(data.get("palette") or DEFAULT_EXAMPLE_PALETTE_REL)
        if background_is_indexed_pixels(data):
            self.mode = MODE_INDEXED
            self.rows = parse_background_palette_rows(data) or solid_fill_indices(self.pixel_w, self.pixel_h, 0)
            self.solid_index = 0
        else:
            self.mode = MODE_SOLID
            self.solid_index = parse_background_solid_palette_index(data)
            self.rows = solid_fill_indices(self.pixel_w, self.pixel_h, self.solid_index)
        self._dirty = False

        self.spin_pw.blockSignals(True)
        self.spin_pw.setValue(self.pixel_w)
        self.spin_pw.blockSignals(False)
        self.spin_ph.blockSignals(True)
        self.spin_ph.setValue(self.pixel_h)
        self.spin_ph.blockSignals(False)
        self.combo_mode.blockSignals(True)
        self.combo_mode.setCurrentIndex(self.combo_mode.findData(self.mode))
        self.combo_mode.blockSignals(False)

        self.grid.set_colors(self._load_palette_colors(self.palette_rel))
        self._refresh_canvas()
        self._refresh_solid_preview()
        self.lbl_status.setText("")
        self._history.reset(self._snapshot())

    def _refresh_canvas(self) -> None:
        cell_px = max(self.pixel_w, self.pixel_h) + 1
        self.canvas.set_sprite(self.rows, self.grid.colors(), cell_px=cell_px, origin_x=0, origin_y=0)
        self.canvas.setEnabled(self.mode == MODE_INDEXED)

    def _refresh_solid_preview(self) -> None:
        colors = self.grid.colors()
        if 0 <= self.solid_index < len(colors):
            r, g, b = colors[self.solid_index]
            self.lbl_solid_preview.setStyleSheet(f"background-color: rgb({r},{g},{b}); border: 1px solid #555;")

    def _mark_dirty(self) -> None:
        self._dirty = True
        self.lbl_status.setText(tr("common.unsaved_changes"))

    # ------------------------------------------------------------------
    # Undo/redo
    # ------------------------------------------------------------------

    def _snapshot(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "rows": self.rows,
            "solid_index": self.solid_index,
            "pixel_w": self.pixel_w,
            "pixel_h": self.pixel_h,
        }

    def _commit_history(self) -> None:
        if self._restoring:
            return
        self._history.commit(self._snapshot())

    def _restore(self, state: dict[str, Any]) -> None:
        self._restoring = True
        try:
            self.mode = state["mode"]
            self.rows = state["rows"]
            self.solid_index = int(state["solid_index"])
            self.pixel_w = int(state["pixel_w"])
            self.pixel_h = int(state["pixel_h"])

            self.spin_pw.blockSignals(True)
            self.spin_pw.setValue(self.pixel_w)
            self.spin_pw.blockSignals(False)
            self.spin_ph.blockSignals(True)
            self.spin_ph.setValue(self.pixel_h)
            self.spin_ph.blockSignals(False)
            self.combo_mode.blockSignals(True)
            self.combo_mode.setCurrentIndex(self.combo_mode.findData(self.mode))
            self.combo_mode.blockSignals(False)

            self._refresh_canvas()
            self._refresh_solid_preview()
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

    def _set_tool(self, tool: Tool) -> None:
        self.canvas.set_tool(tool)
        self.btn_pencil.setChecked(tool == Tool.PENCIL)
        self.btn_eraser.setChecked(tool == Tool.ERASER)
        self.btn_dropper.setChecked(tool == Tool.EYEDROPPER)
        self.btn_bucket.setChecked(tool == Tool.BUCKET)
        self._update_current_tool_icon()

    def _update_current_tool_icon(self) -> None:
        self.lbl_current_tool_icon.setPixmap(_tool_icon(self.canvas.tool.value, size=24).pixmap(QSize(24, 24)))

    def _tool_menu_specs(self) -> tuple[tuple[Tool, str, QPushButton], ...]:
        return (
            (Tool.PENCIL, "common.pencil", self.btn_pencil),
            (Tool.ERASER, "common.eraser", self.btn_eraser),
            (Tool.EYEDROPPER, "common.eyedropper", self.btn_dropper),
            (Tool.BUCKET, "common.bucket", self.btn_bucket),
        )

    def _build_tool_menu(self) -> tuple[QMenu, dict[Any, QPushButton]]:
        menu = QMenu(self)
        action_to_button: dict[Any, QPushButton] = {}
        for tool, label_key, btn in self._tool_menu_specs():
            act = menu.addAction(_tool_icon(tool.value), tr(label_key))
            act.setCheckable(True)
            act.setChecked(self.canvas.tool == tool)
            action_to_button[act] = btn
        return menu, action_to_button

    def _on_canvas_context_menu(self, global_pos: Any) -> None:
        menu, action_to_button = self._build_tool_menu()
        chosen = menu.exec(global_pos)
        if chosen is not None and chosen in action_to_button:
            action_to_button[chosen].click()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_bg_combo_changed(self, stem: str) -> None:
        if stem:
            self._load_background(stem)

    def _on_mode_combo_changed(self, _index: int) -> None:
        self.mode = self.combo_mode.currentData()
        if self.mode == MODE_SOLID:
            self.rows = solid_fill_indices(self.pixel_w, self.pixel_h, self.solid_index)
        self._mark_dirty()
        self._refresh_canvas()
        self._commit_history()

    def _on_slot_selected(self, index: int) -> None:
        if index == TRANSPARENT_PALETTE_INDEX:
            return
        if self.mode == MODE_SOLID:
            self.solid_index = index
            self.rows = solid_fill_indices(self.pixel_w, self.pixel_h, self.solid_index)
            self._mark_dirty()
            self._refresh_canvas()
            self._refresh_solid_preview()
            self._commit_history()
        else:
            self.canvas.set_color_index(index)

    def _action_resize(self) -> None:
        new_pw = self.spin_pw.value()
        new_ph = self.spin_ph.value()
        if self.mode == MODE_SOLID:
            self.pixel_w, self.pixel_h = new_pw, new_ph
            self.rows = solid_fill_indices(self.pixel_w, self.pixel_h, self.solid_index)
        else:
            self.rows = normalize_palette_rows(self.rows, new_pw, new_ph, fill_index=TRANSPARENT_PALETTE_INDEX)
            self.pixel_w, self.pixel_h = new_pw, new_ph
        self._mark_dirty()
        self._refresh_canvas()
        self._commit_history()

    def _action_import_image(self) -> None:
        if not self.background_id:
            QMessageBox.warning(self, tr("background.import_button"), tr("background.import_no_background_open"))
            return
        rgbs01 = [(r / 255.0, g / 255.0, b / 255.0) for r, g, b in self.grid.colors()]
        dlg = BackgroundImportDialog(self.project_root, self.pixel_w, self.pixel_h, rgbs01, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        rows = dlg.result_rows()
        if rows is None:
            return
        self.mode = MODE_INDEXED
        self.rows = rows
        self.combo_mode.blockSignals(True)
        self.combo_mode.setCurrentIndex(self.combo_mode.findData(self.mode))
        self.combo_mode.blockSignals(False)
        self._mark_dirty()
        self._refresh_canvas()
        self._commit_history()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _action_new_background(self) -> None:
        name, ok = QInputDialog.getText(self, tr("background.new_title"), tr("background.new_id_label"))
        if not ok or not name.strip():
            return
        rels = list_palette_relpaths(self.project_root)
        if not rels:
            QMessageBox.warning(self, tr("background.new_title"), tr("common.no_palettes"))
            return
        pal, ok = QInputDialog.getItem(self, tr("background.new_title"), tr("background.new_palette_label"), rels, 0, False)
        if not ok:
            return
        try:
            bid = validate_background_id(name.strip())
            write_solid_background_json(
                self.project_root,
                bid,
                palette_rel=pal,
                palette_index=0,
                pixel_w=self.pixel_w,
                pixel_h=self.pixel_h,
            )
        except ValueError as e:
            QMessageBox.warning(self, tr("background.new_title"), str(e))
            return
        self.refresh_background_list()
        self.open_background(bid)

    def _action_save(self) -> None:
        if not self.background_id:
            return
        try:
            save_background_json(
                self.project_root,
                self.background_id,
                palette_rel=self.palette_rel,
                pixel_w=self.pixel_w,
                pixel_h=self.pixel_h,
                palette_index=self.solid_index,
                rows=self.rows if self.mode == MODE_INDEXED else None,
            )
        except ValueError as e:
            QMessageBox.warning(self, tr("background.save_error_title"), str(e))
            return
        self._dirty = False
        self.lbl_status.setText(tr("common.saved"))
