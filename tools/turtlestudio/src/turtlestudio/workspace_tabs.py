"""Tab bar under the menu — fixed workspace tabs, one per editor.

Mirrors Semi-FantasyConsole/tortustudio/workspace_tabs.py's pattern (a QTabBar
placed above the project-tree/editor splitter, switching center_stack), trimmed
to TurtleStudio's actual editor set.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QTabBar, QWidget

from turtlestudio.i18n import tr


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

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 0)
        layout.addWidget(self.tab_bar)

        for kind, label_key in self._ORDER:
            self.tab_bar.addTab(tr(label_key))
            self._refs.append(TabRef(kind=kind))

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
