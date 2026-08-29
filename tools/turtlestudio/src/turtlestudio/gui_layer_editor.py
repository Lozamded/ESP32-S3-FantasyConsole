"""GUI-layer editor tab -- edita `guilayers/*.json` (spec/gui-layer-v0.md).

Las capas son globales al proyecto (no viven bajo una escena) porque los actor VMs y el
ENTRY VM las muestran/ocultan por id en tiempo de ejecucion sin importar la escena activa
-- por eso este editor es una pestaña propia, no un panel dentro de scene_editor.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from turtlestudio.build import hex_line_to_rgb01, load_palette_lines
from turtlestudio.fonts import (
    blit_text_scene,
    font_metrics_from_data,
    list_font_json_stems,
    parse_font_advances,
    parse_font_glyphs,
    read_font_file,
)
from turtlestudio.guilayers import (
    BAR_DIRECTIONS,
    FILL_MODES,
    GUI_LAYER_TEXT_MAX_CHARS,
    MAX_GUI_BAR_RANGES,
    MAX_GUI_LAYER_LABELS,
    MAX_GUI_LAYER_PIP_BARS,
    MAX_GUI_LAYER_PROGRESS_BARS,
    MAX_GUI_LAYER_RECTS,
    MAX_PIP_COUNT,
    PIP_DIRECTIONS,
    SCENE_PIXEL_H,
    SCENE_PIXEL_W,
    GuiBarRange,
    GuiLayer,
    GuiPipBar,
    GuiProgressBar,
    GuiRect,
    GuiTextLabel,
    is_valid_gui_layer_id,
    list_gui_layer_stems,
    read_gui_layer_file,
    write_gui_layer_file,
)
from turtlestudio.backgrounds import list_palette_relpaths
from turtlestudio.sprites import (
    list_sprite_json_stems,
    parse_sprite_all_frame_rows,
    read_sprite_file,
)
from turtlestudio.i18n import tr
from turtlestudio.palette_policy import PALETTE_SIZE

# Escala del preview (canvas 164x124 * PREVIEW_ZOOM).
PREVIEW_ZOOM = 3


class GuiLayerEditorWidget(QWidget):
    def __init__(self, project_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project_root = project_root
        self.layer_id = ""
        self.layer_x = 0
        self.layer_y = 0
        self.layer_w = SCENE_PIXEL_W
        self.layer_h = SCENE_PIXEL_H
        self.bg_color_index = 0
        self.transparent_bg = False
        self.pauses_scene = False
        self.captures_input = False
        self.z = 0
        self.rects: list[GuiRect] = []
        self.labels: list[GuiTextLabel] = []
        self.progress_bars: list[GuiProgressBar] = []
        self.pip_bars: list[GuiPipBar] = []
        self._dirty = False
        self._loading = False  # evita marcar dirty al reconstruir la UI desde disco
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API (used by mainwindow)
    # ------------------------------------------------------------------

    def set_project_root(self, root: Path) -> None:
        self.project_root = root
        self._refresh_font_combo_choices()
        self._refresh_palette_combo()
        self.refresh_layer_list()

    def refresh_layer_list(self) -> None:
        current = self.combo_layer.currentText()
        self.combo_layer.blockSignals(True)
        self.combo_layer.clear()
        stems = list_gui_layer_stems(self.project_root)
        self.combo_layer.addItems(stems)
        self.combo_layer.blockSignals(False)
        if stems:
            target = current if current in stems else stems[0]
            idx = self.combo_layer.findText(target)
            self.combo_layer.setCurrentIndex(max(idx, 0))
            self.open_layer(self.combo_layer.currentText())
        else:
            self._clear_editor_state()

    def open_layer(self, stem: str) -> None:
        if not stem:
            return
        idx = self.combo_layer.findText(stem)
        if idx < 0:
            self.refresh_layer_list()
            idx = self.combo_layer.findText(stem)
        if idx >= 0:
            self.combo_layer.setCurrentIndex(idx)
        self._load_layer(stem)

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel(tr("guilayer.label")))
        self.combo_layer = QComboBox()
        self.combo_layer.setMinimumWidth(180)
        self.combo_layer.currentTextChanged.connect(self._on_layer_combo_changed)
        top_row.addWidget(self.combo_layer)
        self.btn_new = QPushButton(tr("common.new"))
        self.btn_new.clicked.connect(self._action_new_layer)
        top_row.addWidget(self.btn_new)
        self.btn_save = QPushButton(tr("common.save"))
        self.btn_save.clicked.connect(self._action_save)
        top_row.addWidget(self.btn_save)
        self.btn_delete = QPushButton(tr("guilayer.delete_button"))
        self.btn_delete.clicked.connect(self._action_delete)
        top_row.addWidget(self.btn_delete)
        top_row.addSpacing(12)
        top_row.addWidget(QLabel(tr("guilayer.preview_palette_label")))
        self.combo_preview_palette = QComboBox()
        self.combo_preview_palette.setMinimumWidth(160)
        self.combo_preview_palette.currentTextChanged.connect(lambda _t: self._refresh_preview())
        top_row.addWidget(self.combo_preview_palette)
        top_row.addStretch()
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #888;")
        top_row.addWidget(self.lbl_status)
        outer.addLayout(top_row)

        body = QHBoxLayout()
        outer.addLayout(body, stretch=1)

        # ------------- LEFT: form + tables -------------
        form_col = QVBoxLayout()
        body.addLayout(form_col, stretch=1)

        meta_form = QFormLayout()
        self.spin_x = QSpinBox()
        self.spin_x.setRange(0, SCENE_PIXEL_W - 1)
        self.spin_x.valueChanged.connect(self._on_meta_changed)
        meta_form.addRow(tr("guilayer.x_label"), self.spin_x)
        self.spin_y = QSpinBox()
        self.spin_y.setRange(0, SCENE_PIXEL_H - 1)
        self.spin_y.valueChanged.connect(self._on_meta_changed)
        meta_form.addRow(tr("guilayer.y_label"), self.spin_y)
        self.spin_w = QSpinBox()
        self.spin_w.setRange(1, SCENE_PIXEL_W)
        self.spin_w.setValue(SCENE_PIXEL_W)
        self.spin_w.valueChanged.connect(self._on_meta_changed)
        meta_form.addRow(tr("guilayer.w_label"), self.spin_w)
        self.spin_h = QSpinBox()
        self.spin_h.setRange(1, SCENE_PIXEL_H)
        self.spin_h.setValue(SCENE_PIXEL_H)
        self.spin_h.valueChanged.connect(self._on_meta_changed)
        meta_form.addRow(tr("guilayer.h_label"), self.spin_h)
        self.spin_bg = QSpinBox()
        self.spin_bg.setRange(0, PALETTE_SIZE - 1)
        self.spin_bg.valueChanged.connect(self._on_meta_changed)
        meta_form.addRow(tr("guilayer.bg_color_label"), self.spin_bg)
        self.chk_transparent = QCheckBox()
        self.chk_transparent.stateChanged.connect(self._on_meta_changed)
        meta_form.addRow(tr("guilayer.transparent_bg_label"), self.chk_transparent)
        self.chk_pauses = QCheckBox()
        self.chk_pauses.stateChanged.connect(self._on_meta_changed)
        meta_form.addRow(tr("guilayer.pauses_scene_label"), self.chk_pauses)
        self.chk_captures = QCheckBox()
        self.chk_captures.stateChanged.connect(self._on_meta_changed)
        meta_form.addRow(tr("guilayer.captures_input_label"), self.chk_captures)
        self.spin_z = QSpinBox()
        self.spin_z.setRange(-1000, 1000)
        self.spin_z.valueChanged.connect(self._on_meta_changed)
        meta_form.addRow(tr("guilayer.z_label"), self.spin_z)
        form_col.addLayout(meta_form)

        # Rects table
        form_col.addWidget(QLabel(tr("guilayer.rects_title")))
        self.rects_table = QTableWidget(0, 5)
        self.rects_table.setHorizontalHeaderLabels(
            [
                tr("guilayer.col_x"),
                tr("guilayer.col_y"),
                tr("guilayer.col_w"),
                tr("guilayer.col_h"),
                tr("guilayer.col_color"),
            ]
        )
        self.rects_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.rects_table.verticalHeader().setDefaultSectionSize(22)
        self.rects_table.itemChanged.connect(self._on_rects_item_changed)
        form_col.addWidget(self.rects_table, stretch=1)
        rects_btns = QHBoxLayout()
        self.btn_rect_add = QPushButton(tr("guilayer.add_rect"))
        self.btn_rect_add.clicked.connect(self._action_add_rect)
        rects_btns.addWidget(self.btn_rect_add)
        self.btn_rect_remove = QPushButton(tr("guilayer.remove_rect"))
        self.btn_rect_remove.clicked.connect(self._action_remove_rect)
        rects_btns.addWidget(self.btn_rect_remove)
        rects_btns.addStretch()
        form_col.addLayout(rects_btns)

        # Labels table
        form_col.addWidget(QLabel(tr("guilayer.labels_title")))
        self.labels_table = QTableWidget(0, 6)
        self.labels_table.setHorizontalHeaderLabels(
            [
                tr("guilayer.col_id"),
                tr("guilayer.col_x"),
                tr("guilayer.col_y"),
                tr("guilayer.col_font"),
                tr("guilayer.col_text"),
                tr("guilayer.col_color"),
            ]
        )
        self.labels_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.labels_table.verticalHeader().setDefaultSectionSize(22)
        self.labels_table.itemChanged.connect(self._on_labels_item_changed)
        form_col.addWidget(self.labels_table, stretch=1)
        labels_btns = QHBoxLayout()
        self.btn_label_add = QPushButton(tr("guilayer.add_label"))
        self.btn_label_add.clicked.connect(self._action_add_label)
        labels_btns.addWidget(self.btn_label_add)
        self.btn_label_remove = QPushButton(tr("guilayer.remove_label"))
        self.btn_label_remove.clicked.connect(self._action_remove_label)
        labels_btns.addWidget(self.btn_label_remove)
        labels_btns.addStretch()
        form_col.addLayout(labels_btns)

        # Progress bars table (spec/gui-layer-v0.md "Barras de progreso").
        form_col.addWidget(QLabel(tr("guilayer.progress_bars_title")))
        # Columnas: id, x, y, w, h, direction, fill_mode, fill_color, fill_sprite, bg_color,
        # border_color, value_num, value_den, ranges (leido: cantidad).
        self.progress_table = QTableWidget(0, 14)
        self.progress_table.setHorizontalHeaderLabels(
            [
                tr("guilayer.col_id"),
                tr("guilayer.col_x"),
                tr("guilayer.col_y"),
                tr("guilayer.col_w"),
                tr("guilayer.col_h"),
                tr("guilayer.col_direction"),
                tr("guilayer.col_fill_mode"),
                tr("guilayer.col_fill_color"),
                tr("guilayer.col_fill_sprite"),
                tr("guilayer.col_bg_color"),
                tr("guilayer.col_border_color"),
                tr("guilayer.col_value_num"),
                tr("guilayer.col_value_den"),
                tr("guilayer.col_ranges"),
            ]
        )
        self.progress_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.progress_table.verticalHeader().setDefaultSectionSize(24)
        self.progress_table.itemChanged.connect(self._on_progress_item_changed)
        form_col.addWidget(self.progress_table, stretch=1)
        prog_btns = QHBoxLayout()
        self.btn_progress_add = QPushButton(tr("guilayer.add_progress_bar"))
        self.btn_progress_add.clicked.connect(self._action_add_progress_bar)
        prog_btns.addWidget(self.btn_progress_add)
        self.btn_progress_remove = QPushButton(tr("guilayer.remove_progress_bar"))
        self.btn_progress_remove.clicked.connect(self._action_remove_progress_bar)
        prog_btns.addWidget(self.btn_progress_remove)
        self.btn_progress_ranges = QPushButton(tr("guilayer.edit_ranges"))
        self.btn_progress_ranges.clicked.connect(self._action_edit_progress_ranges)
        prog_btns.addWidget(self.btn_progress_ranges)
        prog_btns.addStretch()
        form_col.addLayout(prog_btns)

        # Pip bars table (spec/gui-layer-v0.md "Barras de pips").
        form_col.addWidget(QLabel(tr("guilayer.pip_bars_title")))
        # Columnas: id, x, y, sprite_full, direction, gap_px, value, max_value, ranges.
        self.pip_table = QTableWidget(0, 9)
        self.pip_table.setHorizontalHeaderLabels(
            [
                tr("guilayer.col_id"),
                tr("guilayer.col_x"),
                tr("guilayer.col_y"),
                tr("guilayer.col_sprite_full"),
                tr("guilayer.col_direction"),
                tr("guilayer.col_gap_px"),
                tr("guilayer.col_value"),
                tr("guilayer.col_max_value"),
                tr("guilayer.col_ranges"),
            ]
        )
        self.pip_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.pip_table.verticalHeader().setDefaultSectionSize(24)
        self.pip_table.itemChanged.connect(self._on_pip_item_changed)
        form_col.addWidget(self.pip_table, stretch=1)
        pip_btns = QHBoxLayout()
        self.btn_pip_add = QPushButton(tr("guilayer.add_pip_bar"))
        self.btn_pip_add.clicked.connect(self._action_add_pip_bar)
        pip_btns.addWidget(self.btn_pip_add)
        self.btn_pip_remove = QPushButton(tr("guilayer.remove_pip_bar"))
        self.btn_pip_remove.clicked.connect(self._action_remove_pip_bar)
        pip_btns.addWidget(self.btn_pip_remove)
        self.btn_pip_ranges = QPushButton(tr("guilayer.edit_ranges"))
        self.btn_pip_ranges.clicked.connect(self._action_edit_pip_ranges)
        pip_btns.addWidget(self.btn_pip_ranges)
        pip_btns.addStretch()
        form_col.addLayout(pip_btns)

        # ------------- RIGHT: preview -------------
        preview_col = QVBoxLayout()
        body.addLayout(preview_col)
        preview_col.addWidget(QLabel(tr("guilayer.preview_title")))
        self.preview = QLabel()
        self.preview.setFixedSize(SCENE_PIXEL_W * PREVIEW_ZOOM, SCENE_PIXEL_H * PREVIEW_ZOOM)
        self.preview.setStyleSheet("border: 1px solid #444; background: #222;")
        self.preview.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        preview_col.addWidget(self.preview)
        self.lbl_preview_hint = QLabel(tr("guilayer.preview_hint"))
        self.lbl_preview_hint.setStyleSheet("color: #888;")
        self.lbl_preview_hint.setWordWrap(True)
        self.lbl_preview_hint.setMaximumWidth(SCENE_PIXEL_W * PREVIEW_ZOOM)
        preview_col.addWidget(self.lbl_preview_hint)
        preview_col.addStretch()

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _clear_editor_state(self) -> None:
        self.layer_id = ""
        self.rects = []
        self.labels = []
        self.progress_bars = []
        self.pip_bars = []
        self._loading = True
        try:
            self.spin_x.setValue(0)
            self.spin_y.setValue(0)
            self.spin_w.setValue(SCENE_PIXEL_W)
            self.spin_h.setValue(SCENE_PIXEL_H)
            self.spin_bg.setValue(0)
            self.chk_transparent.setChecked(False)
            self.chk_pauses.setChecked(False)
            self.chk_captures.setChecked(False)
            self.spin_z.setValue(0)
            self.rects_table.setRowCount(0)
            self.labels_table.setRowCount(0)
            self.progress_table.setRowCount(0)
            self.pip_table.setRowCount(0)
        finally:
            self._loading = False
        self._dirty = False
        self.lbl_status.setText(tr("guilayer.no_layer_open"))
        self._refresh_preview()

    def _load_layer(self, stem: str) -> None:
        try:
            layer = read_gui_layer_file(self.project_root, stem)
        except ValueError as e:
            QMessageBox.warning(self, tr("guilayer.open_error_title"), str(e))
            return
        self._loading = True
        try:
            self.layer_id = layer.id
            self.spin_x.setValue(layer.x)
            self.spin_y.setValue(layer.y)
            self.spin_w.setValue(layer.w)
            self.spin_h.setValue(layer.h)
            self.spin_bg.setValue(layer.bg_color_index)
            self.chk_transparent.setChecked(layer.transparent_bg)
            self.chk_pauses.setChecked(layer.pauses_scene)
            self.chk_captures.setChecked(layer.captures_input)
            self.spin_z.setValue(layer.z)
            self.rects = list(layer.rects)
            self.labels = list(layer.text_labels)
            self.progress_bars = list(layer.progress_bars)
            self.pip_bars = list(layer.pip_bars)
            self._rebuild_rects_table()
            self._rebuild_labels_table()
            self._rebuild_progress_table()
            self._rebuild_pip_table()
        finally:
            self._loading = False
        self._dirty = False
        self.lbl_status.setText("")
        self._refresh_preview()

    def _current_layer(self) -> GuiLayer:
        return GuiLayer(
            id=self.layer_id or "unnamed",
            x=self.spin_x.value(),
            y=self.spin_y.value(),
            w=self.spin_w.value(),
            h=self.spin_h.value(),
            bg_color_index=self.spin_bg.value(),
            transparent_bg=self.chk_transparent.isChecked(),
            pauses_scene=self.chk_pauses.isChecked(),
            captures_input=self.chk_captures.isChecked(),
            z=self.spin_z.value(),
            rects=tuple(self.rects),
            text_labels=tuple(self.labels),
            progress_bars=tuple(self.progress_bars),
            pip_bars=tuple(self.pip_bars),
        )

    def _mark_dirty(self) -> None:
        if self._loading:
            return
        self._dirty = True
        self.lbl_status.setText(tr("common.unsaved_changes"))

    # ------------------------------------------------------------------
    # Rects/labels tables
    # ------------------------------------------------------------------

    def _rebuild_rects_table(self) -> None:
        self.rects_table.blockSignals(True)
        try:
            self.rects_table.setRowCount(len(self.rects))
            for i, r in enumerate(self.rects):
                self._set_int_cell(self.rects_table, i, 0, r.x)
                self._set_int_cell(self.rects_table, i, 1, r.y)
                self._set_int_cell(self.rects_table, i, 2, r.w)
                self._set_int_cell(self.rects_table, i, 3, r.h)
                self._set_int_cell(self.rects_table, i, 4, r.color_index)
        finally:
            self.rects_table.blockSignals(False)

    def _rebuild_labels_table(self) -> None:
        self.labels_table.blockSignals(True)
        try:
            self.labels_table.setRowCount(len(self.labels))
            for i, lbl in enumerate(self.labels):
                self.labels_table.setItem(i, 0, QTableWidgetItem(lbl.id))
                self._set_int_cell(self.labels_table, i, 1, lbl.x)
                self._set_int_cell(self.labels_table, i, 2, lbl.y)
                combo = self._new_font_combo(lbl.font)
                self.labels_table.setCellWidget(i, 3, combo)
                self.labels_table.setItem(i, 4, QTableWidgetItem(lbl.text))
                self._set_int_cell(self.labels_table, i, 5, lbl.color_index)
        finally:
            self.labels_table.blockSignals(False)

    def _set_int_cell(self, table: QTableWidget, row: int, col: int, value: int) -> None:
        item = QTableWidgetItem(str(int(value)))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        table.setItem(row, col, item)

    def _new_font_combo(self, current_font: str) -> QComboBox:
        combo = QComboBox()
        stems = list_font_json_stems(self.project_root)
        combo.addItem("")  # dejar vacio explicito
        combo.addItems(stems)
        if current_font and current_font not in stems:
            # Fuente referida por la capa pero no presente: mostrarla igual para no perderla.
            combo.addItem(current_font)
        idx = combo.findText(current_font) if current_font else 0
        combo.setCurrentIndex(max(idx, 0))
        combo.currentTextChanged.connect(self._on_label_font_changed)
        return combo

    def _refresh_font_combo_choices(self) -> None:
        # Reconstruye las combos de la tabla de labels tras cambiar el proyecto.
        for i in range(self.labels_table.rowCount()):
            widget = self.labels_table.cellWidget(i, 3)
            if isinstance(widget, QComboBox):
                current = widget.currentText()
                widget.blockSignals(True)
                widget.clear()
                widget.addItem("")
                widget.addItems(list_font_json_stems(self.project_root))
                if current and widget.findText(current) < 0:
                    widget.addItem(current)
                idx = widget.findText(current) if current else 0
                widget.setCurrentIndex(max(idx, 0))
                widget.blockSignals(False)

    def _refresh_palette_combo(self) -> None:
        current = self.combo_preview_palette.currentText()
        self.combo_preview_palette.blockSignals(True)
        self.combo_preview_palette.clear()
        rels = list_palette_relpaths(self.project_root)
        self.combo_preview_palette.addItems(rels)
        self.combo_preview_palette.blockSignals(False)
        if rels:
            target = current if current in rels else rels[0]
            idx = self.combo_preview_palette.findText(target)
            self.combo_preview_palette.setCurrentIndex(max(idx, 0))

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_layer_combo_changed(self, stem: str) -> None:
        if stem:
            self._load_layer(stem)

    def _on_meta_changed(self, *_args: Any) -> None:
        self._mark_dirty()
        self._refresh_preview()

    def _on_rects_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        row = item.row()
        if row < 0 or row >= len(self.rects):
            return
        try:
            v = int(item.text())
        except (TypeError, ValueError):
            v = 0
        r = self.rects[row]
        col = item.column()
        if col == 0:
            v = max(0, min(SCENE_PIXEL_W, v))
            self.rects[row] = replace(r, x=v)
        elif col == 1:
            v = max(0, min(SCENE_PIXEL_H, v))
            self.rects[row] = replace(r, y=v)
        elif col == 2:
            v = max(1, min(SCENE_PIXEL_W, v))
            self.rects[row] = replace(r, w=v)
        elif col == 3:
            v = max(1, min(SCENE_PIXEL_H, v))
            self.rects[row] = replace(r, h=v)
        elif col == 4:
            v = max(0, min(PALETTE_SIZE - 1, v))
            self.rects[row] = replace(r, color_index=v)
        # Restaurar el texto clampeado sin re-emitir itemChanged.
        self.rects_table.blockSignals(True)
        try:
            item.setText(str(v))
        finally:
            self.rects_table.blockSignals(False)
        self._mark_dirty()
        self._refresh_preview()

    def _on_labels_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        row = item.row()
        if row < 0 or row >= len(self.labels):
            return
        lbl = self.labels[row]
        col = item.column()
        text = item.text()
        if col == 0:
            new_id = text.strip()
            if new_id and not is_valid_gui_layer_id(new_id):
                QMessageBox.warning(
                    self, tr("guilayer.label_id_error_title"), tr("guilayer.label_id_error_msg")
                )
                self.labels_table.blockSignals(True)
                try:
                    item.setText(lbl.id)
                finally:
                    self.labels_table.blockSignals(False)
                return
            self.labels[row] = replace(lbl, id=new_id)
        elif col in (1, 2, 5):
            try:
                v = int(text)
            except (TypeError, ValueError):
                v = 0
            if col == 1:
                v = max(0, min(SCENE_PIXEL_W, v))
                self.labels[row] = replace(lbl, x=v)
            elif col == 2:
                v = max(0, min(SCENE_PIXEL_H, v))
                self.labels[row] = replace(lbl, y=v)
            else:  # 5 = color_index (-1..30)
                v = max(-1, min(PALETTE_SIZE - 2, v))  # -1..30, no 31 (transparente)
                self.labels[row] = replace(lbl, color_index=v)
            self.labels_table.blockSignals(True)
            try:
                item.setText(str(v))
            finally:
                self.labels_table.blockSignals(False)
        elif col == 4:
            if len(text) > GUI_LAYER_TEXT_MAX_CHARS:
                text = text[:GUI_LAYER_TEXT_MAX_CHARS]
                self.labels_table.blockSignals(True)
                try:
                    item.setText(text)
                finally:
                    self.labels_table.blockSignals(False)
            self.labels[row] = replace(lbl, text=text)
        self._mark_dirty()
        self._refresh_preview()

    def _on_label_font_changed(self, _text: str) -> None:
        if self._loading:
            return
        for i in range(self.labels_table.rowCount()):
            widget = self.labels_table.cellWidget(i, 3)
            if isinstance(widget, QComboBox) and i < len(self.labels):
                self.labels[i] = replace(self.labels[i], font=widget.currentText().strip())
        self._mark_dirty()
        self._refresh_preview()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _action_new_layer(self) -> None:
        name, ok = QInputDialog.getText(
            self, tr("guilayer.new_title"), tr("guilayer.new_id_label")
        )
        if not ok:
            return
        stem = name.strip()
        if not is_valid_gui_layer_id(stem):
            QMessageBox.warning(
                self, tr("guilayer.new_title"), tr("guilayer.new_id_invalid")
            )
            return
        existing = set(list_gui_layer_stems(self.project_root))
        if stem in existing:
            QMessageBox.warning(
                self, tr("guilayer.new_title"), tr("guilayer.new_id_exists", id=stem)
            )
            return
        layer = GuiLayer(id=stem)
        try:
            write_gui_layer_file(self.project_root, layer)
        except OSError as e:
            QMessageBox.warning(self, tr("guilayer.save_error_title"), str(e))
            return
        self.refresh_layer_list()
        self.open_layer(stem)

    def _action_save(self) -> None:
        if not self.layer_id:
            return
        # Reconciliar el nombre del archivo con el id actual (no se puede renombrar aca,
        # pero validar por si el estado se rompio de otra manera).
        try:
            write_gui_layer_file(self.project_root, self._current_layer())
        except OSError as e:
            QMessageBox.warning(self, tr("guilayer.save_error_title"), str(e))
            return
        self._dirty = False
        self.lbl_status.setText(tr("common.saved"))

    def _action_delete(self) -> None:
        if not self.layer_id:
            return
        reply = QMessageBox.question(
            self,
            tr("guilayer.delete_title"),
            tr("guilayer.delete_confirm", id=self.layer_id),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        path = self.project_root / "guilayers" / f"{self.layer_id}.json"
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            QMessageBox.warning(self, tr("guilayer.delete_title"), str(e))
            return
        self.refresh_layer_list()

    def _action_add_rect(self) -> None:
        if len(self.rects) >= MAX_GUI_LAYER_RECTS:
            QMessageBox.information(
                self,
                tr("guilayer.rects_title"),
                tr("guilayer.rect_cap_reached", cap=MAX_GUI_LAYER_RECTS),
            )
            return
        self.rects.append(GuiRect(x=0, y=0, w=8, h=8, color_index=0))
        self._rebuild_rects_table()
        self._mark_dirty()
        self._refresh_preview()

    def _action_remove_rect(self) -> None:
        row = self.rects_table.currentRow()
        if row < 0 or row >= len(self.rects):
            return
        del self.rects[row]
        self._rebuild_rects_table()
        self._mark_dirty()
        self._refresh_preview()

    def _action_add_label(self) -> None:
        if len(self.labels) >= MAX_GUI_LAYER_LABELS:
            QMessageBox.information(
                self,
                tr("guilayer.labels_title"),
                tr("guilayer.label_cap_reached", cap=MAX_GUI_LAYER_LABELS),
            )
            return
        self.labels.append(GuiTextLabel(id="label", font="", text="", x=0, y=0, color_index=-1))
        self._rebuild_labels_table()
        self._mark_dirty()
        self._refresh_preview()

    def _action_remove_label(self) -> None:
        row = self.labels_table.currentRow()
        if row < 0 or row >= len(self.labels):
            return
        del self.labels[row]
        self._rebuild_labels_table()
        self._mark_dirty()
        self._refresh_preview()

    # ------------------------------------------------------------------
    # Progress bars
    # ------------------------------------------------------------------

    def _rebuild_progress_table(self) -> None:
        self.progress_table.blockSignals(True)
        try:
            self.progress_table.setRowCount(len(self.progress_bars))
            for i, bar in enumerate(self.progress_bars):
                self.progress_table.setItem(i, 0, QTableWidgetItem(bar.id))
                self._set_int_cell(self.progress_table, i, 1, bar.x)
                self._set_int_cell(self.progress_table, i, 2, bar.y)
                self._set_int_cell(self.progress_table, i, 3, bar.w)
                self._set_int_cell(self.progress_table, i, 4, bar.h)
                combo_dir = self._new_direction_combo(BAR_DIRECTIONS, bar.direction,
                                                     lambda _t, row=i: self._on_progress_direction_changed(row))
                self.progress_table.setCellWidget(i, 5, combo_dir)
                combo_mode = self._new_direction_combo(FILL_MODES, bar.fill_mode,
                                                      lambda _t, row=i: self._on_progress_fill_mode_changed(row))
                self.progress_table.setCellWidget(i, 6, combo_mode)
                self._set_int_cell(self.progress_table, i, 7, bar.fill_color_index)
                combo_sprite = self._new_sprite_combo(bar.fill_sprite_id, allow_empty=True,
                                                     on_change=lambda _t, row=i: self._on_progress_sprite_changed(row))
                self.progress_table.setCellWidget(i, 8, combo_sprite)
                self._set_int_cell(self.progress_table, i, 9, bar.bg_color_index)
                self._set_int_cell(self.progress_table, i, 10, bar.border_color_index)
                self._set_int_cell(self.progress_table, i, 11, bar.value_num)
                self._set_int_cell(self.progress_table, i, 12, bar.value_den)
                # Ranges: solo mostrar cantidad (edicion via dialogo).
                self._set_int_cell(self.progress_table, i, 13, len(bar.ranges))
        finally:
            self.progress_table.blockSignals(False)

    def _on_progress_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        row = item.row()
        if row < 0 or row >= len(self.progress_bars):
            return
        bar = self.progress_bars[row]
        col = item.column()
        if col == 0:
            new_id = item.text().strip()
            if new_id and not is_valid_gui_layer_id(new_id):
                QMessageBox.warning(self, tr("guilayer.label_id_error_title"),
                                    tr("guilayer.label_id_error_msg"))
                self.progress_table.blockSignals(True)
                try:
                    item.setText(bar.id)
                finally:
                    self.progress_table.blockSignals(False)
                return
            self.progress_bars[row] = replace(bar, id=new_id)
            self._mark_dirty()
            self._refresh_preview()
            return
        if col == 13:
            # Ranges column is read-only from the table; ignore typed edits.
            self.progress_table.blockSignals(True)
            try:
                item.setText(str(len(bar.ranges)))
            finally:
                self.progress_table.blockSignals(False)
            return
        try:
            v = int(item.text())
        except (TypeError, ValueError):
            v = 0
        if col == 1:
            v = max(0, min(SCENE_PIXEL_W, v))
            self.progress_bars[row] = replace(bar, x=v)
        elif col == 2:
            v = max(0, min(SCENE_PIXEL_H, v))
            self.progress_bars[row] = replace(bar, y=v)
        elif col == 3:
            v = max(1, min(SCENE_PIXEL_W, v))
            self.progress_bars[row] = replace(bar, w=v)
        elif col == 4:
            v = max(1, min(SCENE_PIXEL_H, v))
            self.progress_bars[row] = replace(bar, h=v)
        elif col == 7:
            v = max(0, min(PALETTE_SIZE - 1, v))
            self.progress_bars[row] = replace(bar, fill_color_index=v)
        elif col == 9:
            v = max(0, min(PALETTE_SIZE - 1, v))
            self.progress_bars[row] = replace(bar, bg_color_index=v)
        elif col == 10:
            v = max(-1, min(PALETTE_SIZE - 2, v))
            self.progress_bars[row] = replace(bar, border_color_index=v)
        elif col == 11:
            v = max(-32768, min(32767, v))
            self.progress_bars[row] = replace(bar, value_num=v)
        elif col == 12:
            v = max(1, min(32767, v))
            self.progress_bars[row] = replace(bar, value_den=v)
        self.progress_table.blockSignals(True)
        try:
            item.setText(str(v))
        finally:
            self.progress_table.blockSignals(False)
        self._mark_dirty()
        self._refresh_preview()

    def _on_progress_direction_changed(self, row: int) -> None:
        if self._loading or row >= len(self.progress_bars):
            return
        widget = self.progress_table.cellWidget(row, 5)
        if isinstance(widget, QComboBox):
            self.progress_bars[row] = replace(self.progress_bars[row], direction=widget.currentText())
            self._mark_dirty()
            self._refresh_preview()

    def _on_progress_fill_mode_changed(self, row: int) -> None:
        if self._loading or row >= len(self.progress_bars):
            return
        widget = self.progress_table.cellWidget(row, 6)
        if isinstance(widget, QComboBox):
            self.progress_bars[row] = replace(self.progress_bars[row], fill_mode=widget.currentText())
            self._mark_dirty()
            self._refresh_preview()

    def _on_progress_sprite_changed(self, row: int) -> None:
        if self._loading or row >= len(self.progress_bars):
            return
        widget = self.progress_table.cellWidget(row, 8)
        if isinstance(widget, QComboBox):
            self.progress_bars[row] = replace(self.progress_bars[row], fill_sprite_id=widget.currentText().strip())
            self._mark_dirty()
            self._refresh_preview()

    def _action_add_progress_bar(self) -> None:
        if len(self.progress_bars) >= MAX_GUI_LAYER_PROGRESS_BARS:
            QMessageBox.information(self, tr("guilayer.progress_bars_title"),
                                    tr("guilayer.progress_cap_reached", cap=MAX_GUI_LAYER_PROGRESS_BARS))
            return
        existing_ids = {bar.id for bar in self.progress_bars}
        base = "bar"
        i = 1
        while f"{base}{i}" in existing_ids:
            i += 1
        self.progress_bars.append(GuiProgressBar(id=f"{base}{i}", x=2, y=2, w=40, h=6,
                                                 value_num=1, value_den=2))
        self._rebuild_progress_table()
        self._mark_dirty()
        self._refresh_preview()

    def _action_remove_progress_bar(self) -> None:
        row = self.progress_table.currentRow()
        if row < 0 or row >= len(self.progress_bars):
            return
        del self.progress_bars[row]
        self._rebuild_progress_table()
        self._mark_dirty()
        self._refresh_preview()

    def _action_edit_progress_ranges(self) -> None:
        row = self.progress_table.currentRow()
        if row < 0 or row >= len(self.progress_bars):
            QMessageBox.information(self, tr("guilayer.edit_ranges"), tr("guilayer.no_row_selected"))
            return
        bar = self.progress_bars[row]
        new_ranges = self._edit_ranges_dialog(bar.ranges, allow_alt_color=True, allow_alt_sprite=True)
        if new_ranges is None:
            return
        self.progress_bars[row] = replace(bar, ranges=tuple(new_ranges))
        self._rebuild_progress_table()
        self._mark_dirty()
        self._refresh_preview()

    # ------------------------------------------------------------------
    # Pip bars
    # ------------------------------------------------------------------

    def _rebuild_pip_table(self) -> None:
        self.pip_table.blockSignals(True)
        try:
            self.pip_table.setRowCount(len(self.pip_bars))
            for i, bar in enumerate(self.pip_bars):
                self.pip_table.setItem(i, 0, QTableWidgetItem(bar.id))
                self._set_int_cell(self.pip_table, i, 1, bar.x)
                self._set_int_cell(self.pip_table, i, 2, bar.y)
                combo_sprite = self._new_sprite_combo(bar.sprite_full_id, allow_empty=False,
                                                     on_change=lambda _t, row=i: self._on_pip_sprite_changed(row))
                self.pip_table.setCellWidget(i, 3, combo_sprite)
                combo_dir = self._new_direction_combo(PIP_DIRECTIONS, bar.direction,
                                                     lambda _t, row=i: self._on_pip_direction_changed(row))
                self.pip_table.setCellWidget(i, 4, combo_dir)
                self._set_int_cell(self.pip_table, i, 5, bar.gap_px)
                self._set_int_cell(self.pip_table, i, 6, bar.value)
                self._set_int_cell(self.pip_table, i, 7, bar.max_value)
                self._set_int_cell(self.pip_table, i, 8, len(bar.ranges))
        finally:
            self.pip_table.blockSignals(False)

    def _on_pip_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        row = item.row()
        if row < 0 or row >= len(self.pip_bars):
            return
        bar = self.pip_bars[row]
        col = item.column()
        if col == 0:
            new_id = item.text().strip()
            if new_id and not is_valid_gui_layer_id(new_id):
                QMessageBox.warning(self, tr("guilayer.label_id_error_title"),
                                    tr("guilayer.label_id_error_msg"))
                self.pip_table.blockSignals(True)
                try:
                    item.setText(bar.id)
                finally:
                    self.pip_table.blockSignals(False)
                return
            self.pip_bars[row] = replace(bar, id=new_id)
            self._mark_dirty()
            self._refresh_preview()
            return
        if col == 8:
            self.pip_table.blockSignals(True)
            try:
                item.setText(str(len(bar.ranges)))
            finally:
                self.pip_table.blockSignals(False)
            return
        try:
            v = int(item.text())
        except (TypeError, ValueError):
            v = 0
        if col == 1:
            v = max(0, min(SCENE_PIXEL_W, v))
            self.pip_bars[row] = replace(bar, x=v)
        elif col == 2:
            v = max(0, min(SCENE_PIXEL_H, v))
            self.pip_bars[row] = replace(bar, y=v)
        elif col == 5:
            v = max(0, min(32, v))
            self.pip_bars[row] = replace(bar, gap_px=v)
        elif col == 6:
            v = max(0, min(bar.max_value, v))
            self.pip_bars[row] = replace(bar, value=v)
        elif col == 7:
            v = max(1, min(MAX_PIP_COUNT, v))
            new_val = min(bar.value, v)
            self.pip_bars[row] = replace(bar, max_value=v, value=new_val)
        self.pip_table.blockSignals(True)
        try:
            item.setText(str(v))
            # Reflejar value clamped en su celda si cambio.
            if col == 7 and self.pip_bars[row].value != bar.value:
                self._set_int_cell(self.pip_table, row, 6, self.pip_bars[row].value)
        finally:
            self.pip_table.blockSignals(False)
        self._mark_dirty()
        self._refresh_preview()

    def _on_pip_direction_changed(self, row: int) -> None:
        if self._loading or row >= len(self.pip_bars):
            return
        widget = self.pip_table.cellWidget(row, 4)
        if isinstance(widget, QComboBox):
            self.pip_bars[row] = replace(self.pip_bars[row], direction=widget.currentText())
            self._mark_dirty()
            self._refresh_preview()

    def _on_pip_sprite_changed(self, row: int) -> None:
        if self._loading or row >= len(self.pip_bars):
            return
        widget = self.pip_table.cellWidget(row, 3)
        if isinstance(widget, QComboBox):
            self.pip_bars[row] = replace(self.pip_bars[row], sprite_full_id=widget.currentText().strip())
            self._mark_dirty()
            self._refresh_preview()

    def _action_add_pip_bar(self) -> None:
        if len(self.pip_bars) >= MAX_GUI_LAYER_PIP_BARS:
            QMessageBox.information(self, tr("guilayer.pip_bars_title"),
                                    tr("guilayer.pip_cap_reached", cap=MAX_GUI_LAYER_PIP_BARS))
            return
        existing_ids = {bar.id for bar in self.pip_bars}
        base = "pips"
        i = 1
        while f"{base}{i}" in existing_ids:
            i += 1
        # Preselect the first sprite so the new row is valid on save.
        sprites = list_sprite_json_stems(self.project_root)
        default_sprite = sprites[0] if sprites else ""
        if not default_sprite:
            QMessageBox.warning(self, tr("guilayer.pip_bars_title"),
                                tr("guilayer.pip_needs_sprite_msg"))
            return
        self.pip_bars.append(GuiPipBar(id=f"{base}{i}", x=2, y=2, sprite_full_id=default_sprite,
                                       value=1, max_value=3))
        self._rebuild_pip_table()
        self._mark_dirty()
        self._refresh_preview()

    def _action_remove_pip_bar(self) -> None:
        row = self.pip_table.currentRow()
        if row < 0 or row >= len(self.pip_bars):
            return
        del self.pip_bars[row]
        self._rebuild_pip_table()
        self._mark_dirty()
        self._refresh_preview()

    def _action_edit_pip_ranges(self) -> None:
        row = self.pip_table.currentRow()
        if row < 0 or row >= len(self.pip_bars):
            QMessageBox.information(self, tr("guilayer.edit_ranges"), tr("guilayer.no_row_selected"))
            return
        bar = self.pip_bars[row]
        # Pip bars: alt_color no aplica (el pip es sprite); alt_sprite si.
        new_ranges = self._edit_ranges_dialog(bar.ranges, allow_alt_color=False, allow_alt_sprite=True)
        if new_ranges is None:
            return
        self.pip_bars[row] = replace(bar, ranges=tuple(new_ranges))
        self._rebuild_pip_table()
        self._mark_dirty()
        self._refresh_preview()

    # ------------------------------------------------------------------
    # Bar helpers
    # ------------------------------------------------------------------

    def _new_direction_combo(self, choices: tuple[str, ...], current: str, on_change) -> QComboBox:
        combo = QComboBox()
        combo.addItems(list(choices))
        idx = combo.findText(current) if current in choices else 0
        combo.setCurrentIndex(max(idx, 0))
        combo.currentTextChanged.connect(on_change)
        return combo

    def _new_sprite_combo(self, current: str, *, allow_empty: bool, on_change) -> QComboBox:
        combo = QComboBox()
        if allow_empty:
            combo.addItem("")
        stems = list_sprite_json_stems(self.project_root)
        combo.addItems(stems)
        if current and current not in stems:
            combo.addItem(current)
        idx = combo.findText(current) if current else 0
        combo.setCurrentIndex(max(idx, 0))
        combo.currentTextChanged.connect(on_change)
        return combo

    def _edit_ranges_dialog(self, current: tuple[GuiBarRange, ...], *, allow_alt_color: bool,
                            allow_alt_sprite: bool) -> list[GuiBarRange] | None:
        """Dialogo minimo: entrada por texto en formato JSON de la lista. Suficiente para v0;
        una tabla dedicada agregaria mucha UI para una operacion poco frecuente."""
        payload = [
            {k: v for k, v in {
                "min_pct": r.min_pct,
                "max_pct": r.max_pct,
                "alt_color_index": r.alt_color_index if allow_alt_color and r.alt_color_index >= 0 else None,
                "alt_sprite_id": r.alt_sprite_id if allow_alt_sprite and r.alt_sprite_id else None,
            }.items() if v is not None}
            for r in current
        ]
        text, ok = QInputDialog.getMultiLineText(
            self, tr("guilayer.edit_ranges"), tr("guilayer.edit_ranges_hint"),
            json.dumps(payload, indent=2, ensure_ascii=False),
        )
        if not ok:
            return None
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as e:
            QMessageBox.warning(self, tr("guilayer.edit_ranges"), str(e))
            return None
        if not isinstance(raw, list):
            QMessageBox.warning(self, tr("guilayer.edit_ranges"),
                                tr("guilayer.edit_ranges_not_list"))
            return None
        out: list[GuiBarRange] = []
        from turtlestudio.guilayers import parse_gui_bar_range  # local import to avoid cycles
        for item in raw:
            if len(out) >= MAX_GUI_BAR_RANGES:
                break
            r = parse_gui_bar_range(item)
            if r is None:
                continue
            if not allow_alt_color and r.alt_color_index >= 0:
                r = replace(r, alt_color_index=-1)
            out.append(r)
        return out

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def _load_preview_palette(self) -> list[tuple[float, float, float]]:
        """RGBs 0..1 para pintar el preview. Fallback a grises si no hay paleta seleccionable."""
        rel = self.combo_preview_palette.currentText()
        colors: list[tuple[float, float, float]] = []
        if rel:
            try:
                hexes = load_palette_lines(self.project_root / rel)
            except OSError:
                hexes = []
            colors = [hex_line_to_rgb01(h) for h in hexes]
        # Rellenar hasta 32 con negros; el ultimo (31) queda como transparente.
        while len(colors) < PALETTE_SIZE:
            colors.append((0.0, 0.0, 0.0))
        return colors[:PALETTE_SIZE]

    def _refresh_preview(self) -> None:
        fw, fh = SCENE_PIXEL_W, SCENE_PIXEL_H
        rgba = [0.0] * (fw * fh * 4)
        # Fondo damero para distinguir zonas transparentes.
        for y in range(fh):
            for x in range(fw):
                shade = 0.22 if ((x // 8) + (y // 8)) % 2 == 0 else 0.16
                i = (y * fw + x) * 4
                rgba[i] = rgba[i + 1] = rgba[i + 2] = shade
                rgba[i + 3] = 1.0

        rgbs = self._load_preview_palette()
        lx = self.spin_x.value()
        ly = self.spin_y.value()
        lw = self.spin_w.value()
        lh = self.spin_h.value()
        # Recortar rect de la capa al framebuffer.
        lw = min(lw, fw - lx)
        lh = min(lh, fh - ly)

        def paint_rect_absolute(px: int, py: int, pw: int, ph: int, color_index: int) -> None:
            """Pinta un rect en coordenadas de framebuffer (origen top-left), ignorando la
            transparencia del color 31 -- para el preview usamos el color base literal."""
            if pw <= 0 or ph <= 0 or color_index < 0 or color_index >= len(rgbs):
                return
            r, g, b = rgbs[color_index]
            for yy in range(max(0, py), min(fh, py + ph)):
                for xx in range(max(0, px), min(fw, px + pw)):
                    i = (yy * fw + xx) * 4
                    rgba[i] = r
                    rgba[i + 1] = g
                    rgba[i + 2] = b
                    rgba[i + 3] = 1.0

        # Fondo de la capa (a menos que transparent_bg).
        if not self.chk_transparent.isChecked():
            paint_rect_absolute(lx, ly, lw, lh, self.spin_bg.value())

        # Rects internos (orden array, 0 primero, N-1 encima).
        for r in self.rects:
            rx = lx + r.x
            ry = ly + r.y
            rw = min(r.w, (lx + lw) - rx)
            rh = min(r.h, (ly + lh) - ry)
            paint_rect_absolute(rx, ry, rw, rh, r.color_index)

        # Progress bars y pip bars: mismo orden que firmware (rects -> progress -> pips -> labels).
        sprite_cache: dict[str, tuple[int, int, list[list[int]]]] = {}

        def load_sprite_pixels(stem: str) -> tuple[int, int, list[list[int]]] | None:
            if not stem:
                return None
            if stem in sprite_cache:
                return sprite_cache[stem]
            try:
                data = read_sprite_file(self.project_root, stem)
            except ValueError:
                return None
            from turtlestudio.sprites import sprite_pixel_dimensions
            _, pw, ph = sprite_pixel_dimensions(data)
            frames = parse_sprite_all_frame_rows(data)
            if not frames:
                return None
            frame0 = frames[0]
            sprite_cache[stem] = (pw, ph, frame0)
            return sprite_cache[stem]

        def blit_sprite_tiled(dx: int, dy: int, dw: int, dh: int, stem: str) -> None:
            info = load_sprite_pixels(stem)
            if info is None:
                # Fallback: rayado gris para senalizar sprite no resuelto.
                paint_rect_absolute(dx, dy, dw, dh, 3)
                return
            pw, ph, pixels = info
            for yy in range(dh):
                sy = yy % ph
                for xx in range(dw):
                    sx = xx % pw
                    px = pixels[sy][sx]
                    if px == PALETTE_SIZE - 1:
                        continue
                    paint_rect_absolute(dx + xx, dy + yy, 1, 1, px)

        def blit_sprite(dx: int, dy: int, stem: str) -> tuple[int, int]:
            info = load_sprite_pixels(stem)
            if info is None:
                paint_rect_absolute(dx, dy, 8, 8, 3)
                return 8, 8
            pw, ph, pixels = info
            for yy in range(ph):
                for xx in range(pw):
                    px = pixels[yy][xx]
                    if px == PALETTE_SIZE - 1:
                        continue
                    paint_rect_absolute(dx + xx, dy + yy, 1, 1, px)
            return pw, ph

        def active_range(frac_pct: int, ranges: tuple[GuiBarRange, ...]) -> GuiBarRange | None:
            for rng in ranges:
                hit = (frac_pct >= rng.min_pct) and (
                    frac_pct <= rng.max_pct if rng.max_pct >= 100 else frac_pct < rng.max_pct
                )
                if hit:
                    return rng
            return None

        for bar in self.progress_bars:
            bx = lx + bar.x
            by = ly + bar.y
            bw = min(bar.w, (lx + lw) - bx)
            bh = min(bar.h, (ly + lh) - by)
            if bw <= 0 or bh <= 0:
                continue
            # Fondo del bar (parte vacia). 31 = transparente, no pintar.
            if bar.bg_color_index != PALETTE_SIZE - 1:
                paint_rect_absolute(bx, by, bw, bh, bar.bg_color_index)
            num = max(0, min(bar.value_den, bar.value_num))
            den = max(1, bar.value_den)
            frac_pct = (num * 100) // den
            rng = active_range(frac_pct, bar.ranges)
            eff_color = bar.fill_color_index
            eff_sprite = bar.fill_sprite_id
            if rng is not None:
                if rng.alt_color_index >= 0:
                    eff_color = rng.alt_color_index
                if rng.alt_sprite_id:
                    eff_sprite = rng.alt_sprite_id
            # Sub-rect segun direction. OJO con no shadowear fw/fh (framebuffer w/h) del scope
            # exterior: se usan mas abajo para construir el QImage. Nombres locales explicitos.
            fill_x, fill_y, fill_w, fill_h = bx, by, bw, bh
            if bar.direction == "left_to_right":
                fill_w = (bw * num) // den
            elif bar.direction == "right_to_left":
                filled = (bw * num) // den
                fill_x = bx + (bw - filled)
                fill_w = filled
            elif bar.direction == "top_to_bottom":
                fill_h = (bh * num) // den
            elif bar.direction == "bottom_to_top":
                filled = (bh * num) // den
                fill_y = by + (bh - filled)
                fill_h = filled
            if fill_w > 0 and fill_h > 0:
                if bar.fill_mode == "color":
                    if eff_color != PALETTE_SIZE - 1:
                        paint_rect_absolute(fill_x, fill_y, fill_w, fill_h, eff_color)
                else:
                    blit_sprite_tiled(fill_x, fill_y, fill_w, fill_h, eff_sprite)
            # Marco 1 px por encima del relleno.
            if bar.border_color_index >= 0:
                paint_rect_absolute(bx, by, bw, 1, bar.border_color_index)
                paint_rect_absolute(bx, by + bh - 1, bw, 1, bar.border_color_index)
                paint_rect_absolute(bx, by, 1, bh, bar.border_color_index)
                paint_rect_absolute(bx + bw - 1, by, 1, bh, bar.border_color_index)

        for bar in self.pip_bars:
            val = max(0, min(bar.max_value, bar.value))
            if val == 0 or not bar.sprite_full_id:
                continue
            maxv = max(1, bar.max_value)
            frac_pct = (val * 100) // maxv
            rng = active_range(frac_pct, bar.ranges)
            eff_sprite = bar.sprite_full_id
            if rng is not None and rng.alt_sprite_id:
                eff_sprite = rng.alt_sprite_id
            info = load_sprite_pixels(eff_sprite)
            if info is None:
                # Fallback: caja gris por pip.
                for i in range(val):
                    dx = lx + bar.x + (i * (8 + bar.gap_px) if bar.direction == "horizontal" else 0)
                    dy = ly + bar.y + (i * (8 + bar.gap_px) if bar.direction == "vertical" else 0)
                    paint_rect_absolute(dx, dy, 8, 8, 3)
                continue
            sw, sh, _ = info
            step = (sw if bar.direction == "horizontal" else sh) + bar.gap_px
            for i in range(val):
                px = lx + bar.x + (i * step if bar.direction == "horizontal" else 0)
                py = ly + bar.y + (i * step if bar.direction == "vertical" else 0)
                if px + sw > lx + lw or py + sh > ly + lh:
                    break
                blit_sprite(px, py, eff_sprite)

        # Labels: usan blit_text_scene (mismo pipeline que scene_editor para paridad con firmware).
        for lbl in self.labels:
            if not lbl.text or not lbl.font:
                continue
            try:
                data = read_font_file(self.project_root, lbl.font)
            except ValueError:
                continue
            glyphs = parse_font_glyphs(data)
            advances = parse_font_advances(data)
            glyph_px, _lh, _bl = font_metrics_from_data(data)
            # blit_text_scene usa origen bottom-left, Y-up (convencion escena). El label da (x, y)
            # en coords de la capa; el offset (lx, ly) tambien esta en top-left. Para pasar a
            # escena Y-up debemos invertir sobre el framebuffer completo.
            scene_sx = lx + lbl.x
            scene_sy = (fh - 1) - (ly + lbl.y) - (glyph_px - 1)
            tint = lbl.color_index if lbl.color_index >= 0 else -1
            blit_text_scene(
                rgba,
                fw,
                fh,
                scene_sx,
                scene_sy,
                lbl.text,
                glyphs=glyphs,
                advances=advances,
                glyph_px=glyph_px,
                rgbs=rgbs,
                tint_index=tint,
            )

        buf = bytes(min(255, max(0, int(v * 255.0))) for v in rgba)
        img = QImage(buf, fw, fh, fw * 4, QImage.Format.Format_RGBA8888).copy()
        pix = QPixmap.fromImage(img).scaled(
            fw * PREVIEW_ZOOM,
            fh * PREVIEW_ZOOM,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.preview.setPixmap(pix)
