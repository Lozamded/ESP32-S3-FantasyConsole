"""Startup screen shown in the center stack while no project is open: recent
projects (see MainWindow._remember_recent_project) plus New/Open buttons."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from turtlestudio.i18n import tr
from turtlestudio.project import read_project_display_name


class WelcomeWidget(QWidget):
    new_project_requested = pyqtSignal()
    open_project_requested = pyqtSignal(Path)
    browse_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(12)
        outer.addStretch()

        title = QLabel(tr("welcome.title"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        outer.addWidget(title)

        self._recent_label = QLabel(tr("welcome.recent_label"))
        self._recent_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self._recent_label)

        list_row = QHBoxLayout()
        list_row.addStretch()
        self.list_recent = QListWidget()
        self.list_recent.setMaximumWidth(480)
        self.list_recent.setMinimumHeight(160)
        self.list_recent.itemDoubleClicked.connect(self._on_item_double_clicked)
        list_row.addWidget(self.list_recent, stretch=1)
        list_row.addStretch()
        outer.addLayout(list_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_open = QPushButton(tr("welcome.open_button"))
        self.btn_open.clicked.connect(self.browse_requested.emit)
        btn_row.addWidget(self.btn_open)
        self.btn_new = QPushButton(tr("welcome.new_button"))
        self.btn_new.clicked.connect(self.new_project_requested.emit)
        btn_row.addWidget(self.btn_new)
        btn_row.addStretch()
        outer.addLayout(btn_row)

        outer.addStretch()

    def set_recent_projects(self, paths: list[Path]) -> None:
        self.list_recent.clear()
        self._recent_label.setVisible(bool(paths))
        self.list_recent.setVisible(bool(paths))
        for path in paths:
            label = read_project_display_name(path) if path.is_dir() else str(path)
            item = QListWidgetItem(label)
            item.setToolTip(str(path))
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.list_recent.addItem(item)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(path, Path):
            self.open_project_requested.emit(path)
