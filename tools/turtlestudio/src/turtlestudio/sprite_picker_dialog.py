"""Sprite picker dialog — thumbnail grid with search filter."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from turtlestudio.build import hex_line_to_rgb01, load_palette_lines
from turtlestudio.i18n import tr
from turtlestudio.palette_policy import PALETTE_SIZE, TRANSPARENT_PALETTE_INDEX
from turtlestudio.project import DEFAULT_EXAMPLE_PALETTE_REL
from turtlestudio.sprites import (
    list_sprite_json_stems,
    parse_palette_rows_image,
    parse_sprite_origin,
    read_sprite_file,
    sprite_pixel_dimensions,
)

_THUMB_SIZE = 64
_CHECKER_A = QColor(80, 80, 80)
_CHECKER_B = QColor(50, 50, 50)
_CELL = 4  # checker square size in pixels


def _load_palette(project_root: Path, palette_rel: str) -> list[tuple[int, int, int]]:
    path = project_root / palette_rel
    try:
        hexes = load_palette_lines(path)
    except OSError:
        hexes = []
    rgbs = [(round(r * 255), round(g * 255), round(b * 255)) for r, g, b in (hex_line_to_rgb01(h) for h in hexes)]
    if len(rgbs) < PALETTE_SIZE:
        rgbs += [(0, 0, 0)] * (PALETTE_SIZE - len(rgbs))
    return rgbs[:PALETTE_SIZE]


def _build_thumbnail(project_root: Path, sprite_id: str) -> QPixmap | None:
    try:
        sd = read_sprite_file(project_root, sprite_id)
    except (ValueError, OSError):
        return None
    _, pw, ph = sprite_pixel_dimensions(sd)
    if pw <= 0 or ph <= 0:
        return None
    pal_rel = str(sd.get("palette") or DEFAULT_EXAMPLE_PALETTE_REL)
    colors = _load_palette(project_root, pal_rel)
    rows = parse_palette_rows_image(sd) or [[TRANSPARENT_PALETTE_INDEX] * pw for _ in range(ph)]

    img = QImage(pw, ph, QImage.Format.Format_ARGB32)
    for y in range(ph):
        row = rows[y] if y < len(rows) else []
        for x in range(pw):
            idx = row[x] if x < len(row) else TRANSPARENT_PALETTE_INDEX
            if idx == TRANSPARENT_PALETTE_INDEX:
                shade = _CHECKER_A if (x // _CELL + y // _CELL) % 2 == 0 else _CHECKER_B
                img.setPixelColor(x, y, shade)
            elif idx < len(colors):
                r, g, b = colors[idx]
                img.setPixelColor(x, y, QColor(r, g, b))

    px = QPixmap.fromImage(img)
    return px.scaled(_THUMB_SIZE, _THUMB_SIZE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)


class SpritePickerDialog(QDialog):
    """Grid of sprite thumbnails with a search bar; returns the chosen sprite id."""

    def __init__(self, project_root: Path, current_id: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("object.pick_sprite_title"))
        self.setMinimumSize(520, 440)
        self._project_root = project_root
        self._selected_id = current_id
        self._all_stems: list[str] = list_sprite_json_stems(project_root)
        self._thumbs: dict[str, QPixmap] = {}
        self._build_ui()
        self._populate(self._all_stems)
        self._select_current(current_id)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    @property
    def selected_sprite_id(self) -> str:
        return self._selected_id

    # ------------------------------------------------------------------
    # UI build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("object.pick_sprite_search"))
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search)
        layout.addWidget(self._search)

        self._list = QListWidget()
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setIconSize(QSize(_THUMB_SIZE, _THUMB_SIZE))
        self._list.setGridSize(QSize(_THUMB_SIZE + 24, _THUMB_SIZE + 28))
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setMovement(QListWidget.Movement.Static)
        self._list.setUniformItemSizes(True)
        self._list.setSpacing(4)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        self._list.currentItemChanged.connect(self._on_selection_changed)
        layout.addWidget(self._list, stretch=1)

        self._lbl_empty = QLabel(tr("object.pick_sprite_empty"))
        self._lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_empty.setStyleSheet("color: #888;")
        self._lbl_empty.setVisible(False)
        layout.addWidget(self._lbl_empty)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    # Populate / filter
    # ------------------------------------------------------------------

    def _get_thumb(self, stem: str) -> QPixmap:
        if stem not in self._thumbs:
            px = _build_thumbnail(self._project_root, stem)
            if px is None:
                px = QPixmap(_THUMB_SIZE, _THUMB_SIZE)
                px.fill(QColor(60, 60, 60))
            self._thumbs[stem] = px
        return self._thumbs[stem]

    def _populate(self, stems: list[str]) -> None:
        self._list.clear()
        for stem in stems:
            item = QListWidgetItem(QIcon(self._get_thumb(stem)), stem)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
            item.setToolTip(stem)
            self._list.addItem(item)
        empty = len(stems) == 0
        self._list.setVisible(not empty)
        self._lbl_empty.setVisible(empty)

    def _select_current(self, sprite_id: str) -> None:
        for i in range(self._list.count()):
            if self._list.item(i).text() == sprite_id:
                self._list.setCurrentRow(i)
                self._list.scrollToItem(self._list.item(i))
                return

    def _on_search(self, text: str) -> None:
        q = text.strip().lower()
        filtered = [s for s in self._all_stems if q in s.lower()] if q else self._all_stems
        self._populate(filtered)
        self._select_current(self._selected_id)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_selection_changed(self, current: QListWidgetItem | None, _prev) -> None:
        if current is not None:
            self._selected_id = current.text()

    def _on_double_click(self, item: QListWidgetItem) -> None:
        self._selected_id = item.text()
        self.accept()

    def _on_ok(self) -> None:
        cur = self._list.currentItem()
        if cur is not None:
            self._selected_id = cur.text()
        self.accept()
