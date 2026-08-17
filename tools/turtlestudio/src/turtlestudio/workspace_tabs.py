"""Tab bar under the menu — fixed workspace tabs, one per editor.

Mirrors Semi-FantasyConsole/tortustudio/workspace_tabs.py's pattern (a QTabBar
placed above the project-tree/editor splitter, switching center_stack), trimmed
to TurtleStudio's actual editor set.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QTabBar, QWidget

from turtlestudio.i18n import tr
from turtlestudio.project import TargetBoard


class TabKind(str, Enum):
    SCENE_EDITOR = "scene_editor"
    PLAY_MODE = "play_mode"
    SPRITE_EDITOR = "sprite_editor"
    TILESET_EDITOR = "tileset_editor"
    BACKGROUND_EDITOR = "background_editor"
    OBJECT_EDITOR = "object_editor"
    FONT_EDITOR = "font_editor"
    PALETTE_EDITOR = "palette_editor"
    EXPORT = "export"


# Board -> i18n label key, shared with new_project_dialog.py's board combo.
BOARD_ORDER: tuple[tuple[TargetBoard, str], ...] = (
    (TargetBoard.ESP32_S3_N16R8, "mainwindow.target_board_s3"),
    (TargetBoard.ESP32_P4, "mainwindow.target_board_p4"),
)


@dataclass
class TabRef:
    kind: TabKind


class WorkspaceTabs(QWidget):
    """Tab strip placed directly under the menu bar."""

    tab_selected = pyqtSignal(TabRef)

    _ORDER: tuple[tuple[TabKind, str], ...] = (
        (TabKind.SCENE_EDITOR, "mainwindow.tab_scene"),
        (TabKind.PLAY_MODE, "mainwindow.tab_play"),
        (TabKind.SPRITE_EDITOR, "mainwindow.tab_sprites"),
        (TabKind.TILESET_EDITOR, "mainwindow.tab_tiles"),
        (TabKind.BACKGROUND_EDITOR, "mainwindow.tab_backgrounds"),
        (TabKind.OBJECT_EDITOR, "mainwindow.tab_objects"),
        (TabKind.FONT_EDITOR, "mainwindow.tab_fonts"),
        (TabKind.PALETTE_EDITOR, "mainwindow.tab_palette"),
        (TabKind.EXPORT, "mainwindow.tab_export"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._refs: list[TabRef] = []

        self.tab_bar = QTabBar()
        self.tab_bar.setMovable(False)
        self.tab_bar.setTabsClosable(False)
        self.tab_bar.setExpanding(False)
        self.tab_bar.currentChanged.connect(self._on_current_changed)

        self._board_label_prefix = QLabel(tr("mainwindow.target_board_label"))
        self.board_label = QLabel()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 0)
        layout.addWidget(self.tab_bar)
        layout.addStretch(1)
        layout.addWidget(self._board_label_prefix)
        layout.addWidget(self.board_label)

        for kind, label_key in self._ORDER:
            self.tab_bar.addTab(tr(label_key))
            self._refs.append(TabRef(kind=kind))

    def set_target_board(self, board: TargetBoard | None) -> None:
        if board is None:
            self.board_label.clear()
            return
        label_key = dict(BOARD_ORDER)[board]
        self.board_label.setText(tr(label_key))

    def _index_of(self, kind: TabKind) -> int:
        for i, (k, _label_key) in enumerate(self._ORDER):
            if k == kind:
                return i
        raise ValueError(f"unknown TabKind: {kind}")

    def select(self, kind: TabKind) -> None:
        self.tab_bar.setCurrentIndex(self._index_of(kind))

    def _on_current_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._refs):
            return
        self.tab_selected.emit(self._refs[index])
