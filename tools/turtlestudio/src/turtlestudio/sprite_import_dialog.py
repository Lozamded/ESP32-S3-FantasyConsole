"""Import-image dialog for the sprite editor: pick a PNG/JPG, preview it quantized to the
current sprite palette, replace the active frame with the result."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from turtlestudio.i18n import tr
from turtlestudio.scene_editor import _rgba_floats_to_qimage
from turtlestudio.sprite_ref_image import (
    aspect_ratio_note,
    composite_sprite_editor_preview,
    convert_ref_source_to_palette_rows,
    load_image_rgba_float01,
)

_PREVIEW_MAX = 240


class SpriteImportDialog(QDialog):
    def __init__(
        self,
        project_root: Path,
        pixel_w: int,
        pixel_h: int,
        rgbs01: list[tuple[float, float, float]],
        *,
        frame_index: int = 0,
        frame_count: int = 1,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.project_root = project_root
        self._pixel_w = pixel_w
        self._pixel_h = pixel_h
        self._rgbs01 = rgbs01
        self._ref_source: tuple[int, int, list[float]] | None = None
        self._rows: list[list[int]] | None = None

        self.setWindowTitle(tr("sprite.import_dialog_title"))

        self._file_edit = QLineEdit()
        self._file_edit.setReadOnly(True)
        browse_button = QPushButton(tr("sprite.import_browse_button"))
        browse_button.clicked.connect(self._pick_file)
        file_row = QHBoxLayout()
        file_row.addWidget(self._file_edit, stretch=1)
        file_row.addWidget(browse_button)

        self._alpha_spin = QSpinBox()
        self._alpha_spin.setRange(0, 100)
        self._alpha_spin.setValue(50)
        self._alpha_spin.valueChanged.connect(self._refresh_preview)

        form = QFormLayout()
        form.addRow(tr("sprite.import_file_label"), file_row)
        form.addRow(tr("sprite.import_alpha_cutoff_label"), self._alpha_spin)

        self._frame_label = QLabel(tr("sprite.import_frame_note", n=f"{frame_index + 1}/{frame_count}"))
        self._frame_label.setStyleSheet("color: #888;")

        self._note_label = QLabel("")
        self._note_label.setStyleSheet("color: #c0392b;")
        self._note_label.setWordWrap(True)
        self._note_label.setVisible(False)

        self._preview_label = QLabel("")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumSize(_PREVIEW_MAX, _PREVIEW_MAX)
        self._preview_label.setStyleSheet("border: 1px solid #555;")

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._frame_label)
        layout.addWidget(self._note_label)
        layout.addWidget(self._preview_label)
        layout.addWidget(self._buttons)

    def _pick_file(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            tr("sprite.import_dialog_title"),
            "",
            tr("sprite.import_file_filter"),
        )
        if not path:
            return
        self._file_edit.setText(path)
        try:
            self._ref_source = load_image_rgba_float01(path)
        except ValueError as e:
            self._ref_source = None
            self._rows = None
            self._note_label.setText(tr("sprite.import_load_error", e=e))
            self._note_label.setVisible(True)
            self._preview_label.setPixmap(QPixmap())
            self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            return
        self._note_label.setVisible(False)
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        if self._ref_source is None:
            return
        sw, sh, _rgba = self._ref_source
        cutoff = self._alpha_spin.value() / 100.0
        self._rows = convert_ref_source_to_palette_rows(
            self._ref_source, self._pixel_w, self._pixel_h, self._rgbs01, alpha_cutoff=cutoff
        )
        preview_rgba = composite_sprite_editor_preview(self._rows, self._rgbs01, None)
        image = _rgba_floats_to_qimage(preview_rgba, self._pixel_w, self._pixel_h)
        pixmap = QPixmap.fromImage(image).scaled(
            _PREVIEW_MAX,
            _PREVIEW_MAX,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self._preview_label.setPixmap(pixmap)

        note = aspect_ratio_note(sw, sh, self._pixel_w, self._pixel_h)
        self._note_label.setText(note or "")
        self._note_label.setVisible(bool(note))

        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    def result_rows(self) -> list[list[int]] | None:
        return self._rows
