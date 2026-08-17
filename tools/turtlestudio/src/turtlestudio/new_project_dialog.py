"""New Project dialog: folder, name, and target board, chosen once at creation."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from turtlestudio.i18n import tr
from turtlestudio.project import TargetBoard
from turtlestudio.workspace_tabs import BOARD_ORDER


class NewProjectDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("mainwindow.new_project_title"))

        self._folder_edit = QLineEdit()
        self._folder_edit.setReadOnly(True)
        browse_button = QPushButton(tr("mainwindow.new_project_browse_button"))
        browse_button.clicked.connect(self._pick_folder)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self._folder_edit, stretch=1)
        folder_row.addWidget(browse_button)

        self._name_edit = QLineEdit()

        self._board_combo = QComboBox()
        for board, label_key in BOARD_ORDER:
            self._board_combo.addItem(tr(label_key), board)

        form = QFormLayout()
        form.addRow(tr("mainwindow.new_project_folder_label"), folder_row)
        form.addRow(tr("mainwindow.new_project_name_label"), self._name_edit)
        form.addRow(tr("mainwindow.target_board_label"), self._board_combo)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._buttons)

    def _pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr("mainwindow.new_project_folder_title"))
        if path:
            self._folder_edit.setText(path)
            self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    def folder_path(self) -> str:
        return self._folder_edit.text()

    def project_name(self) -> str:
        return self._name_edit.text().strip()

    def selected_board(self) -> TargetBoard:
        return self._board_combo.currentData()
