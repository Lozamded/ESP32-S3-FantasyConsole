"""Font editor tab — paint `objects/Fonts/*.json` glyphs and preview rendered text."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import QSize, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
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
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from turtlestudio.backgrounds import list_palette_relpaths
from turtlestudio.build import hex_line_to_rgb01, load_palette_lines, load_palette_rgb01_for_preview
from turtlestudio.edit_history import SnapshotHistory
from turtlestudio.fonts import (
    DEFAULT_GLYPH_PX,
    GLYPH_PX_STEP,
    LATIN_CHARSET,
    MAX_GLYPH_PX,
    MIN_GLYPH_PX,
    empty_glyph_rows,
    font_char_label,
    font_charset_from_data,
    font_file_glyph_px,
    font_metrics_from_data,
    list_font_json_stems,
    normalize_glyph_px,
    parse_font_glyphs,
    read_font_file,
    render_font_preview_rgba,
    save_font_json,
    validate_font_id,
    write_font_json,
)
from turtlestudio.i18n import tr
from turtlestudio.palette_editor import PaletteGridWidget
from turtlestudio.palette_policy import PALETTE_SIZE, TRANSPARENT_PALETTE_INDEX
from turtlestudio.project import DEFAULT_EXAMPLE_PALETTE_REL
from turtlestudio.scene_editor import SceneCanvas, _rgba_floats_to_qimage, _tile_icon, _tool_icon
from turtlestudio.sprite_editor import SpriteCanvas, Tool
from turtlestudio.sprites import normalize_palette_rows


class GlyphPickerWidget(QListWidget):
    """Grid of glyph thumbnails for the font's charset; emits glyph_selected(char)."""

    glyph_selected = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setIconSize(QSize(28, 28))
        self.setFixedHeight(200)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._chars: list[str] = []
        self.currentRowChanged.connect(self._on_row_changed)

    def set_glyphs(
        self,
        charset: str,
        glyphs: dict[str, list[list[int]]],
        rgbs: list[tuple[float, float, float]],
    ) -> None:
        self.blockSignals(True)
        self.clear()
        self._chars = list(charset)
        for ch in self._chars:
            rows = glyphs.get(ch) or []
            item = QListWidgetItem(_tile_icon(rows, rgbs, size=28), font_char_label(ch))
            self.addItem(item)
        self.blockSignals(False)

    def select_char(self, ch: str) -> None:
        if ch in self._chars:
            self.blockSignals(True)
            self.setCurrentRow(self._chars.index(ch))
            self.blockSignals(False)

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(self._chars):
            self.glyph_selected.emit(self._chars[row])


class FontEditorWidget(QWidget):
    def __init__(self, project_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project_root = project_root
        self.font_id = ""
        self.glyph_px = DEFAULT_GLYPH_PX
        self.line_height = DEFAULT_GLYPH_PX
        self.baseline = DEFAULT_GLYPH_PX
        self.palette_rel = DEFAULT_EXAMPLE_PALETTE_REL
        self.charset = LATIN_CHARSET
        self.glyphs: dict[str, list[list[int]]] = {}
        self.current_char = " "
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
        self.refresh_font_list()

    def refresh_font_list(self) -> None:
        current = self.combo_font.currentText()
        self.combo_font.blockSignals(True)
        self.combo_font.clear()
        stems = list_font_json_stems(self.project_root)
        self.combo_font.addItems(stems)
        self.combo_font.blockSignals(False)
        if stems:
            target = current if current in stems else stems[0]
            idx = self.combo_font.findText(target)
            self.combo_font.setCurrentIndex(max(idx, 0))
            self.open_font(self.combo_font.currentText())

    def open_font(self, stem: str) -> None:
        if not stem:
            return
        idx = self.combo_font.findText(stem)
        if idx < 0:
            self.refresh_font_list()
            idx = self.combo_font.findText(stem)
        if idx >= 0:
            self.combo_font.setCurrentIndex(idx)
        self._load_font(stem)

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel(tr("font.label")))
        self.combo_font = QComboBox()
        self.combo_font.setMinimumWidth(180)
        self.combo_font.currentTextChanged.connect(self._on_font_combo_changed)
        top_row.addWidget(self.combo_font)
        self.btn_new = QPushButton(tr("common.new"))
        self.btn_new.clicked.connect(self._action_new_font)
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
        self.canvas.changed.connect(self._on_canvas_changed)
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
        self.zoom_spin.setRange(4, 48)
        self.zoom_spin.setValue(20)
        self.zoom_spin.valueChanged.connect(self.canvas.set_zoom)
        tools.addWidget(self.zoom_spin)
        tools.addStretch()
        canvas_col.addLayout(tools)

        canvas_col.addWidget(QLabel(tr("font.charset_label")))
        self.glyph_picker = GlyphPickerWidget()
        self.glyph_picker.glyph_selected.connect(self._on_glyph_selected)
        canvas_col.addWidget(self.glyph_picker)

        root.addLayout(canvas_col, stretch=1)

        side = QVBoxLayout()
        form = QFormLayout()
        self.spin_glyph_px = QSpinBox()
        self.spin_glyph_px.setRange(MIN_GLYPH_PX, MAX_GLYPH_PX)
        self.spin_glyph_px.setSingleStep(GLYPH_PX_STEP)
        self.spin_glyph_px.setValue(DEFAULT_GLYPH_PX)
        form.addRow(tr("font.glyph_px_label"), self.spin_glyph_px)
        self.btn_resize = QPushButton(tr("common.resize"))
        self.btn_resize.clicked.connect(self._action_resize)
        form.addRow(self.btn_resize)
        self.spin_line_height = QSpinBox()
        self.spin_line_height.setRange(1, 64)
        self.spin_line_height.valueChanged.connect(self._on_metrics_changed)
        form.addRow(tr("font.line_height_label"), self.spin_line_height)
        self.spin_baseline = QSpinBox()
        self.spin_baseline.setRange(0, 64)
        self.spin_baseline.valueChanged.connect(self._on_metrics_changed)
        form.addRow(tr("font.baseline_label"), self.spin_baseline)
        self.lbl_palette = QLabel("—")
        form.addRow(tr("font.palette_label"), self.lbl_palette)
        side.addLayout(form)

        side.addWidget(QLabel(tr("font.palette_hint")))
        self.grid = PaletteGridWidget()
        self.grid.slot_selected.connect(self._on_slot_selected)
        side.addWidget(self.grid)

        preview_box = QGroupBox(tr("font.preview_group"))
        preview_layout = QVBoxLayout(preview_box)
        self.edit_preview_text = QLineEdit("Hello 123!")
        self.edit_preview_text.textChanged.connect(self._refresh_preview)
        preview_layout.addWidget(self.edit_preview_text)
        self.preview_canvas = SceneCanvas()
        self.preview_canvas.set_zoom(4)
        preview_scroll = QScrollArea()
        preview_scroll.setWidgetResizable(True)
        preview_scroll.setFixedHeight(90)
        preview_scroll.setWidget(self.preview_canvas)
        preview_layout.addWidget(preview_scroll)
        side.addWidget(preview_box)
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

    def _glyph_rgbs01(self) -> list[tuple[float, float, float]]:
        colors = self.grid.colors()
        return [(r / 255.0, g / 255.0, b / 255.0) for r, g, b in colors]

    def _load_font(self, stem: str) -> None:
        try:
            data = read_font_file(self.project_root, stem)
        except ValueError as e:
            QMessageBox.warning(self, tr("font.open_error_title"), str(e))
            return
        self.font_id = stem
        self.glyph_px = font_file_glyph_px(data)
        self.palette_rel = str(data.get("palette") or DEFAULT_EXAMPLE_PALETTE_REL)
        self.charset = font_charset_from_data(data)
        self.glyph_px, self.line_height, self.baseline = font_metrics_from_data(data)
        self.glyphs = parse_font_glyphs(data, fill_index=TRANSPARENT_PALETTE_INDEX)
        self.current_char = self.charset[0] if self.charset else " "
        self._dirty = False

        self._suspend = True
        self.spin_glyph_px.setValue(self.glyph_px)
        self.spin_line_height.setValue(self.line_height)
        self.spin_baseline.setValue(self.baseline)
        self._suspend = False
        self.lbl_palette.setText(self.palette_rel)

        self.grid.set_colors(self._load_palette_colors(self.palette_rel))
        self.glyph_picker.set_glyphs(self.charset, self.glyphs, self._glyph_rgbs01())
        self.glyph_picker.select_char(self.current_char)
        self._refresh_canvas()
        self._refresh_preview()
        self.lbl_status.setText("")
        self._history.reset(self._snapshot())

    def _refresh_canvas(self) -> None:
        rows = self.glyphs.get(self.current_char) or empty_glyph_rows(self.glyph_px, fill_index=TRANSPARENT_PALETTE_INDEX)
        self.canvas.set_sprite(rows, self.grid.colors(), cell_px=self.glyph_px, origin_x=0, origin_y=0)

    def _refresh_glyph_thumb(self) -> None:
        self.glyph_picker.set_glyphs(self.charset, self.glyphs, self._glyph_rgbs01())
        self.glyph_picker.select_char(self.current_char)

    def _refresh_preview(self) -> None:
        pal_path = (self.project_root / self.palette_rel).resolve() if self.palette_rel else None
        rgbs, _ = load_palette_rgb01_for_preview(pal_path if pal_path and pal_path.is_file() else None)
        rgba, w, h = render_font_preview_rgba(
            self.edit_preview_text.text(),
            glyphs=self.glyphs,
            palette_rgb=rgbs,
            glyph_px=self.glyph_px,
            line_height=self.line_height,
        )
        img = _rgba_floats_to_qimage(rgba, w, h)
        self.preview_canvas.set_frame(img, w, h)

    def _mark_dirty(self) -> None:
        self._dirty = True
        self.lbl_status.setText(tr("common.unsaved_changes"))

    # ------------------------------------------------------------------
    # Undo/redo
    # ------------------------------------------------------------------

    def _snapshot(self) -> dict[str, Any]:
        return {
            "glyphs": self.glyphs,
            "current_char": self.current_char,
            "glyph_px": self.glyph_px,
            "line_height": self.line_height,
            "baseline": self.baseline,
        }

    def _commit_history(self) -> None:
        if self._restoring:
            return
        self._history.commit(self._snapshot())

    def _restore(self, state: dict[str, Any]) -> None:
        self._restoring = True
        try:
            self.glyphs = state["glyphs"]
            self.current_char = state["current_char"]
            self.glyph_px = int(state["glyph_px"])
            self.line_height = int(state["line_height"])
            self.baseline = int(state["baseline"])

            self._suspend = True
            self.spin_glyph_px.setValue(self.glyph_px)
            self.spin_line_height.setValue(self.line_height)
            self.spin_baseline.setValue(self.baseline)
            self._suspend = False

            self._refresh_canvas()
            self._refresh_glyph_thumb()
            self._refresh_preview()
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

    def _on_font_combo_changed(self, stem: str) -> None:
        if stem:
            self._load_font(stem)

    def _on_glyph_selected(self, ch: str) -> None:
        if self._suspend:
            return
        self.current_char = ch
        self._refresh_canvas()

    def _on_canvas_changed(self) -> None:
        self.glyphs[self.current_char] = self.canvas.rows
        self._mark_dirty()
        self._refresh_glyph_thumb()
        self._refresh_preview()

    def _on_slot_selected(self, index: int) -> None:
        if index == TRANSPARENT_PALETTE_INDEX:
            return
        self.canvas.set_color_index(index)

    def _on_metrics_changed(self, _value: int) -> None:
        if self._suspend:
            return
        self.line_height = self.spin_line_height.value()
        self.baseline = self.spin_baseline.value()
        self._mark_dirty()
        self._refresh_preview()
        self._commit_history()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _action_resize(self) -> None:
        new_px = normalize_glyph_px(self.spin_glyph_px.value())
        self.glyphs = {
            ch: normalize_palette_rows(rows, new_px, new_px, fill_index=TRANSPARENT_PALETTE_INDEX)
            for ch, rows in self.glyphs.items()
        }
        self.glyph_px = new_px
        self.spin_glyph_px.blockSignals(True)
        self.spin_glyph_px.setValue(new_px)
        self.spin_glyph_px.blockSignals(False)
        self._mark_dirty()
        self._refresh_canvas()
        self._refresh_glyph_thumb()
        self._refresh_preview()
        self._commit_history()

    def _action_new_font(self) -> None:
        name, ok = QInputDialog.getText(self, tr("font.new_title"), tr("font.new_id_label"))
        if not ok or not name.strip():
            return
        rels = list_palette_relpaths(self.project_root)
        if not rels:
            QMessageBox.warning(self, tr("font.new_title"), tr("common.no_palettes"))
            return
        pal, ok = QInputDialog.getItem(self, tr("font.new_title"), tr("font.palette_label"), rels, 0, False)
        if not ok:
            return
        try:
            fid = validate_font_id(name.strip())
            write_font_json(self.project_root, fid, palette_rel=pal, glyph_px=DEFAULT_GLYPH_PX, glyphs={})
        except ValueError as e:
            QMessageBox.warning(self, tr("font.new_title"), str(e))
            return
        self.refresh_font_list()
        self.open_font(fid)

    def _action_save(self) -> None:
        if not self.font_id:
            return
        try:
            save_font_json(
                self.project_root,
                self.font_id,
                palette_rel=self.palette_rel,
                glyph_px=self.glyph_px,
                glyphs=self.glyphs,
                charset=self.charset,
                fill_index=TRANSPARENT_PALETTE_INDEX,
                line_height=self.line_height,
                baseline=self.baseline,
            )
        except ValueError as e:
            QMessageBox.warning(self, tr("font.save_error_title"), str(e))
            return
        self._dirty = False
        self.lbl_status.setText(tr("common.saved"))
