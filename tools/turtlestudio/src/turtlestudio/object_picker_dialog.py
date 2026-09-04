"""Object picker dialog — thumbnail grid with search filter."""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from turtlestudio.i18n import tr
from turtlestudio.objects import list_object_json_stems, objects_dir
from turtlestudio.sprite_picker_dialog import _THUMB_SIZE, _build_thumbnail


def _object_sprite_id(project_root: Path, object_id: str) -> str:
    path = objects_dir(project_root) / f"{object_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data.get("sprite_id", ""))
    except (OSError, json.JSONDecodeError, ValueError):
        return ""


class ObjectPickerDialog(QDialog):
    """Grid of object thumbnails (rendered from their default sprite) with a search bar."""

    def __init__(self, project_root: Path, current_id: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("object.pick_object_title"))
        self.setMinimumSize(520, 440)
        self._project_root = project_root
        self._selected_id = current_id
        self._all_stems: list[str] = list_object_json_stems(project_root)
        self._thumbs: dict[str, QPixmap] = {}
        self._build_ui()
        self._populate(self._all_stems)
        self._select_current(current_id)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    @property
    def selected_object_id(self) -> str:
        return self._selected_id

    # ------------------------------------------------------------------
    # UI build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("object.pick_object_search"))
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

        self._lbl_empty = QLabel(tr("object.pick_object_empty"))
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

    def _get_thumb(self, object_id: str) -> QPixmap:
        if object_id not in self._thumbs:
            sprite_id = _object_sprite_id(self._project_root, object_id)
            px = _build_thumbnail(self._project_root, sprite_id) if sprite_id else None
            if px is None:
                px = QPixmap(_THUMB_SIZE, _THUMB_SIZE)
                px.fill(QColor(60, 60, 60))
            self._thumbs[object_id] = px
        return self._thumbs[object_id]

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

    def _select_current(self, object_id: str) -> None:
        for i in range(self._list.count()):
            if self._list.item(i).text() == object_id:
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
