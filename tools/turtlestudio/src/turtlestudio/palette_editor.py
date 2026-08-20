"""Palette editor tab — create, edit, and import colors for `palettes/*.txt` files."""

from __future__ import annotations

import math
from collections import Counter
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
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
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from turtlestudio.backgrounds import list_palette_relpaths
from turtlestudio.build import (
    DEFAULT_CONSOLE_PALETTE_HEX,
    hex_line_to_rgb01,
    load_palette_lines,
    save_palette_lines,
)
from turtlestudio.edit_history import SnapshotHistory
from turtlestudio.i18n import tr
from turtlestudio.palette_policy import PALETTE_SIZE, TRANSPARENT_PALETTE_INDEX

SLOT_SIZE = 34
SLOT_GAP = 2
COLS = 8
MAX_IMPORT_COLORS = 48


def _default_palette_colors() -> list[tuple[int, int, int]]:
    return [_hex_to_rgb255(h) for h in DEFAULT_CONSOLE_PALETTE_HEX]


def _hex_to_rgb255(h: str) -> tuple[int, int, int]:
    r, g, b = hex_line_to_rgb01(h)
    return (round(r * 255), round(g * 255), round(b * 255))


def _rgb255_to_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"#{r:02X}{g:02X}{b:02X}"


def _extract_image_colors(path: Path) -> list[tuple[int, int, int]]:
    """Return up to MAX_IMPORT_COLORS unique RGB colors sorted by pixel frequency."""
    img = QImage(str(path))
    if img.isNull():
        return []
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    counts: Counter[tuple[int, int, int]] = Counter()
    for y in range(h):
        line = img.constScanLine(y)
        line.setsize(w * 4)
        row = bytes(line)
        for x in range(w):
            i = x * 4
            if row[i + 3] <= 64:
                continue
            counts[(row[i], row[i + 1], row[i + 2])] += 1
    return [rgb for rgb, _ in counts.most_common(MAX_IMPORT_COLORS)]


def _color_swatch_icon(r: int, g: int, b: int, size: int = 20) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(QColor(r, g, b))
    return QIcon(pix)


class PaletteGridWidget(QWidget):
    """Grid showing all PALETTE_SIZE (32) slots; emits slot_selected on click.

    Shared by every editor's swatch picker (sprite/tileset/background/...) so
    swatch-picking logic and transparent-index rendering live in exactly one
    place instead of being duplicated per editor.
    """

    slot_selected = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colors: list[tuple[int, int, int]] = _default_palette_colors()
        self._selected: int = 0
        w = COLS * (SLOT_SIZE + SLOT_GAP) - SLOT_GAP
        rows = math.ceil(PALETTE_SIZE / COLS)
        h = rows * (SLOT_SIZE + SLOT_GAP) - SLOT_GAP
        self.setFixedSize(w, h)

    def colors(self) -> list[tuple[int, int, int]]:
        return list(self._colors)

    def selected(self) -> int:
        return self._selected

    def set_colors(self, colors: list[tuple[int, int, int]]) -> None:
        self._colors = list(colors)
        self.update()

    def set_selected(self, index: int) -> None:
        self._selected = index
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        rows = math.ceil(PALETTE_SIZE / COLS)
        for row in range(rows):
            for col in range(COLS):
                idx = row * COLS + col
                if idx >= PALETTE_SIZE:
                    continue
                x = col * (SLOT_SIZE + SLOT_GAP)
                y = row * (SLOT_SIZE + SLOT_GAP)

                if idx == TRANSPARENT_PALETTE_INDEX:
                    painter.fillRect(x, y, SLOT_SIZE, SLOT_SIZE, QColor(200, 200, 200))
                    half = SLOT_SIZE // 2
                    painter.fillRect(x, y, half, half, QColor(140, 140, 140))
                    painter.fillRect(x + half, y + half, half, half, QColor(140, 140, 140))
                elif idx < len(self._colors):
                    r, g, b = self._colors[idx]
                    painter.fillRect(x, y, SLOT_SIZE, SLOT_SIZE, QColor(r, g, b))

                painter.setPen(QColor(0, 0, 0, 140))
                painter.drawText(x + 3, y + 13, str(idx))
                painter.setPen(QColor(255, 255, 255, 200))
                painter.drawText(x + 2, y + 12, str(idx))

                if idx == self._selected:
                    pen = QPen(QColor(255, 255, 255))
                    pen.setWidth(2)
                    painter.setPen(pen)
                    painter.drawRect(x + 1, y + 1, SLOT_SIZE - 3, SLOT_SIZE - 3)
                    pen2 = QPen(QColor(0, 0, 0))
                    pen2.setWidth(1)
                    painter.setPen(pen2)
                    painter.drawRect(x, y, SLOT_SIZE - 1, SLOT_SIZE - 1)

        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        col = int(event.position().x()) // (SLOT_SIZE + SLOT_GAP)
        row = int(event.position().y()) // (SLOT_SIZE + SLOT_GAP)
        if 0 <= col < COLS:
            idx = row * COLS + col
            if 0 <= idx < PALETTE_SIZE:
                self._selected = idx
                self.update()
                self.slot_selected.emit(idx)


class PaletteEditorWidget(QWidget):
    """Palette editor: browse, edit, create `palettes/*.txt` files and import colors from images."""

    saved = pyqtSignal(Path)

    def __init__(self, project_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project_root = project_root
        self._colors: list[tuple[int, int, int]] = _default_palette_colors()
        self._palette_rel: str = ""
        self._dirty: bool = False
        self._image_colors: list[tuple[int, int, int]] = []
        self._selected_image_color: tuple[int, int, int] | None = None
        self._history = SnapshotHistory()
        self._restoring = False
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_project_root(self, root: Path) -> None:
        self.project_root = root
        self.refresh()

    def open_palette_relpath(self, rel: str) -> None:
        idx = self.combo_palette.findText(rel)
        if idx >= 0:
            self.combo_palette.setCurrentIndex(idx)
        else:
            self.refresh()
            idx = self.combo_palette.findText(rel)
            if idx >= 0:
                self.combo_palette.setCurrentIndex(idx)

    def refresh(self) -> None:
        current = self.combo_palette.currentText()
        self.combo_palette.blockSignals(True)
        self.combo_palette.clear()
        rels = list_palette_relpaths(self.project_root)
        for rel in rels:
            self.combo_palette.addItem(rel)
        self.combo_palette.blockSignals(False)

        if rels:
            target = current if current in rels else rels[0]
            idx = self.combo_palette.findText(target)
            self.combo_palette.setCurrentIndex(max(idx, 0))
            self._load_palette(self.combo_palette.currentText())
        else:
            self._colors = _default_palette_colors()
            self._palette_rel = ""
            self.grid.set_colors(self._colors)

    def has_unsaved_changes(self) -> bool:
        return self._dirty

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(6, 6, 6, 6)
        root_layout.setSpacing(6)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel(tr("palette.label")))
        self.combo_palette = QComboBox()
        self.combo_palette.setMinimumWidth(200)
        self.combo_palette.currentIndexChanged.connect(self._on_palette_combo_changed)
        toolbar.addWidget(self.combo_palette)
        self.btn_new = QPushButton(tr("palette.new"))
        self.btn_new.setFixedWidth(70)
        self.btn_new.clicked.connect(self._action_new_palette)
        toolbar.addWidget(self.btn_new)
        self.btn_save = QPushButton(tr("common.save"))
        self.btn_save.setFixedWidth(70)
        self.btn_save.clicked.connect(self._action_save)
        toolbar.addWidget(self.btn_save)
        toolbar.addStretch()
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #888;")
        toolbar.addWidget(self.lbl_status)
        root_layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ---- Left: palette grid ----
        left = QWidget()
        left_vbox = QVBoxLayout(left)
        left_vbox.setContentsMargins(0, 0, 4, 0)

        self.grid = PaletteGridWidget()
        self.grid.slot_selected.connect(self._on_slot_selected)
        scroll = QScrollArea()
        scroll.setWidget(self.grid)
        scroll.setWidgetResizable(False)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        left_vbox.addWidget(scroll)

        self.lbl_slot = QLabel(tr("palette.slot_hint", index=0, ti=TRANSPARENT_PALETTE_INDEX))
        self.lbl_slot.setStyleSheet("color: #aaa; font-size: 11px;")
        self.lbl_slot.setWordWrap(True)
        left_vbox.addWidget(self.lbl_slot)
        left_vbox.addStretch()
        splitter.addWidget(left)

        # ---- Right: editor + importer ----
        right = QWidget()
        right_vbox = QVBoxLayout(right)
        right_vbox.setContentsMargins(4, 0, 0, 0)
        right_vbox.setSpacing(8)

        slot_group = QGroupBox(tr("palette.edit_slot_group"))
        slot_form = QFormLayout(slot_group)
        slot_form.setSpacing(4)

        swatch_row = QHBoxLayout()
        self.swatch = QLabel()
        self.swatch.setFixedSize(52, 52)
        self.swatch.setFrameShape(QLabel.Shape.Box)
        swatch_row.addWidget(self.swatch)
        self.lbl_hex = QLineEdit("#000000")
        self.lbl_hex.setFixedWidth(90)
        self.lbl_hex.setMaxLength(7)
        self.lbl_hex.setStyleSheet("font-family: monospace; font-size: 14px;")
        self.lbl_hex.setPlaceholderText("#rrggbb")
        self.lbl_hex.editingFinished.connect(self._on_hex_edited)
        swatch_row.addWidget(self.lbl_hex)
        swatch_row.addStretch()
        slot_form.addRow(swatch_row)

        self.spin_r = QSpinBox()
        self.spin_r.setRange(0, 255)
        self.spin_r.setPrefix("R  ")
        slot_form.addRow(self.spin_r)

        self.spin_g = QSpinBox()
        self.spin_g.setRange(0, 255)
        self.spin_g.setPrefix("G  ")
        slot_form.addRow(self.spin_g)

        self.spin_b = QSpinBox()
        self.spin_b.setRange(0, 255)
        self.spin_b.setPrefix("B  ")
        slot_form.addRow(self.spin_b)

        self.spin_r.valueChanged.connect(self._on_rgb_spinbox_changed)
        self.spin_g.valueChanged.connect(self._on_rgb_spinbox_changed)
        self.spin_b.valueChanged.connect(self._on_rgb_spinbox_changed)

        self.btn_apply = QPushButton(tr("palette.apply_color"))
        self.btn_apply.clicked.connect(self._action_apply_color)
        slot_form.addRow(self.btn_apply)
        right_vbox.addWidget(slot_group)

        import_group = QGroupBox(tr("palette.import_group"))
        import_vbox = QVBoxLayout(import_group)
        import_vbox.setSpacing(4)

        browse_row = QHBoxLayout()
        self.btn_browse = QPushButton(tr("palette.browse_image"))
        self.btn_browse.clicked.connect(self._action_browse_image)
        browse_row.addWidget(self.btn_browse)
        self.lbl_image_name = QLabel(tr("palette.no_image"))
        self.lbl_image_name.setStyleSheet("color: #888; font-size: 11px;")
        browse_row.addWidget(self.lbl_image_name, 1)
        import_vbox.addLayout(browse_row)

        img_row = QHBoxLayout()
        self.image_preview = QLabel()
        self.image_preview.setFixedSize(64, 64)
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview.setFrameShape(QLabel.Shape.Box)
        self.image_preview.setStyleSheet("background: #1a1a2e;")
        img_row.addWidget(self.image_preview)

        img_hint = QLabel(tr("palette.image_hint"))
        img_hint.setStyleSheet("color: #888; font-size: 11px;")
        img_hint.setWordWrap(True)
        img_row.addWidget(img_hint, 1)
        import_vbox.addLayout(img_row)

        import_vbox.addWidget(QLabel(tr("palette.colors_found")))
        self.color_list = QListWidget()
        self.color_list.setIconSize(QSize(20, 20))
        self.color_list.setMaximumHeight(180)
        self.color_list.itemClicked.connect(self._on_image_color_clicked)
        self.color_list.itemDoubleClicked.connect(self._on_image_color_double_clicked)
        import_vbox.addWidget(self.color_list)

        self.btn_use_color = QPushButton(tr("palette.use_color"))
        self.btn_use_color.setEnabled(False)
        self.btn_use_color.clicked.connect(self._action_use_image_color)
        import_vbox.addWidget(self.btn_use_color)

        right_vbox.addWidget(import_group)
        right_vbox.addStretch()
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        root_layout.addWidget(splitter, 1)

        self._refresh_swatch()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _palette_path(self, rel: str) -> Path:
        return self.project_root / rel

    def _load_palette(self, rel: str) -> None:
        if not rel:
            return
        path = self._palette_path(rel)
        try:
            hexes = load_palette_lines(path)
            self._colors = [_hex_to_rgb255(h) for h in hexes] if hexes else _default_palette_colors()
        except Exception as exc:
            QMessageBox.warning(self, tr("palette.load_error_title"), str(exc))
            self._colors = _default_palette_colors()
        # pad/truncate to PALETTE_SIZE so the grid always has a color per slot
        if len(self._colors) < PALETTE_SIZE:
            self._colors += _default_palette_colors()[len(self._colors) :]
        self._colors = self._colors[:PALETTE_SIZE]
        self._palette_rel = rel
        self._dirty = False
        self.grid.set_colors(self._colors)
        self._on_slot_selected(self.grid.selected())
        self.lbl_status.setText("")
        self._history.reset(self._snapshot())

    def _refresh_swatch(self) -> None:
        r = self.spin_r.value()
        g = self.spin_g.value()
        b = self.spin_b.value()
        pix = QPixmap(52, 52)
        pix.fill(QColor(r, g, b))
        self.swatch.setPixmap(pix)
        self.lbl_hex.blockSignals(True)
        self.lbl_hex.setText(f"#{r:02x}{g:02x}{b:02x}")
        self.lbl_hex.blockSignals(False)

    def _set_rgb_spinboxes(self, r: int, g: int, b: int) -> None:
        for spin, val in ((self.spin_r, r), (self.spin_g, g), (self.spin_b, b)):
            spin.blockSignals(True)
            spin.setValue(val)
            spin.blockSignals(False)
        self._refresh_swatch()

    # ------------------------------------------------------------------
    # Undo/redo
    # ------------------------------------------------------------------

    def _snapshot(self) -> dict[str, Any]:
        return {"colors": self._colors, "selected": self.grid.selected()}

    def _commit_history(self) -> None:
        if self._restoring:
            return
        self._history.commit(self._snapshot())

    def _restore(self, state: dict[str, Any]) -> None:
        self._restoring = True
        try:
            self._colors = state["colors"]
            self.grid.set_colors(self._colors)
            self.grid.set_selected(int(state["selected"]))
            self._on_slot_selected(self.grid.selected())
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
    # Slots
    # ------------------------------------------------------------------

    def _on_palette_combo_changed(self, _index: int) -> None:
        rel = self.combo_palette.currentText()
        if rel:
            self._load_palette(rel)

    def _on_slot_selected(self, index: int) -> None:
        self.lbl_slot.setText(tr("palette.slot_hint", index=index, ti=TRANSPARENT_PALETTE_INDEX))
        if index == TRANSPARENT_PALETTE_INDEX or index >= len(self._colors):
            return
        r, g, b = self._colors[index]
        self._set_rgb_spinboxes(r, g, b)

    def _on_rgb_spinbox_changed(self) -> None:
        self._refresh_swatch()

    def _on_hex_edited(self) -> None:
        text = self.lbl_hex.text().strip().lstrip("#")
        if len(text) == 6:
            try:
                r = int(text[0:2], 16)
                g = int(text[2:4], 16)
                b = int(text[4:6], 16)
                self._set_rgb_spinboxes(r, g, b)
            except ValueError:
                pass
        self._refresh_swatch()

    def _on_image_color_clicked(self, item: QListWidgetItem) -> None:
        rgb = item.data(Qt.ItemDataRole.UserRole)
        if rgb:
            self._selected_image_color = rgb
            self._set_rgb_spinboxes(*rgb)
            self.btn_use_color.setEnabled(True)

    def _on_image_color_double_clicked(self, item: QListWidgetItem) -> None:
        self._on_image_color_clicked(item)
        self._action_use_image_color()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _action_apply_color(self) -> None:
        idx = self.grid.selected()
        if idx == TRANSPARENT_PALETTE_INDEX:
            return
        r, g, b = self.spin_r.value(), self.spin_g.value(), self.spin_b.value()
        self._colors[idx] = (r, g, b)
        self.grid.set_colors(self._colors)
        self._dirty = True
        self.lbl_status.setText(tr("common.unsaved_changes"))
        self._commit_history()

    def _action_use_image_color(self) -> None:
        if self._selected_image_color is None:
            return
        idx = self.grid.selected()
        if idx == TRANSPARENT_PALETTE_INDEX:
            QMessageBox.information(
                self,
                tr("palette.set_color_title"),
                tr("palette.set_color_transparent_msg", ti=TRANSPARENT_PALETTE_INDEX),
            )
            return
        r, g, b = self._selected_image_color
        self._colors[idx] = (r, g, b)
        self._set_rgb_spinboxes(r, g, b)
        self.grid.set_colors(self._colors)
        self._dirty = True
        self.lbl_status.setText(tr("common.unsaved_changes"))
        self._commit_history()

    def _action_save(self) -> None:
        rel = self.combo_palette.currentText().strip()
        if not rel:
            QMessageBox.warning(self, tr("palette.save_error_title"), tr("palette.save_no_selection"))
            return
        path = self._palette_path(rel)
        try:
            save_palette_lines(path, [_rgb255_to_hex(c) for c in self._colors])
        except Exception as exc:
            QMessageBox.warning(self, tr("palette.save_error_title"), str(exc))
            return
        self._palette_rel = rel
        self._dirty = False
        self.lbl_status.setText(tr("common.saved"))
        self.saved.emit(path)

    def _action_new_palette(self) -> None:
        name, ok = QInputDialog.getText(self, tr("palette.new_title"), tr("palette.new_name_label"))
        if not ok or not name.strip():
            return
        stem = name.strip().replace(" ", "_")
        rel = f"palettes/{stem}.txt"
        path = self._palette_path(rel)
        if path.exists():
            QMessageBox.warning(self, tr("palette.new_title"), tr("palette.new_exists", rel=rel))
            return
        try:
            save_palette_lines(path, list(DEFAULT_CONSOLE_PALETTE_HEX))
        except Exception as exc:
            QMessageBox.warning(self, tr("palette.new_title"), str(exc))
            return
        self.refresh()
        idx = self.combo_palette.findText(rel)
        if idx >= 0:
            self.combo_palette.setCurrentIndex(idx)

    def _action_browse_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("palette.open_image_title"),
            "",
            tr("palette.image_filter"),
        )
        if not path:
            return
        image_path = Path(path)
        self.lbl_image_name.setText(image_path.name)

        pix = QPixmap(str(image_path))
        if not pix.isNull():
            self.image_preview.setPixmap(
                pix.scaled(
                    64,
                    64,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

        try:
            self._image_colors = _extract_image_colors(image_path)
        except Exception as exc:
            QMessageBox.warning(self, tr("palette.import_error_title"), tr("palette.import_error_msg", exc=exc))
            return

        self._populate_image_color_list()

    def _populate_image_color_list(self) -> None:
        self.color_list.clear()
        self._selected_image_color = None
        self.btn_use_color.setEnabled(False)
        for r, g, b in self._image_colors:
            item = QListWidgetItem(
                _color_swatch_icon(r, g, b), f"#{r:02x}{g:02x}{b:02x}   ({r}, {g}, {b})"
            )
            item.setData(Qt.ItemDataRole.UserRole, (r, g, b))
            self.color_list.addItem(item)
