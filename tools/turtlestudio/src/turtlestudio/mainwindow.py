"""Main TurtleStudio window layout."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from turtlestudio.palette_editor import PaletteEditorWidget
from turtlestudio.background_editor import BackgroundEditorWidget
from turtlestudio.build_dialog import BuildDialogWidget
from turtlestudio.font_editor import FontEditorWidget
from turtlestudio.i18n import tr
from turtlestudio.new_project_dialog import NewProjectDialog
from turtlestudio.object_editor import ObjectEditorWidget
from turtlestudio.play_widget import PlayWidget
from turtlestudio.scene_editor import SceneEditorWidget
from turtlestudio.sprite_editor import SpriteEditorWidget
from turtlestudio.tileset_editor import TilesetEditorWidget
from turtlestudio.welcome_widget import WelcomeWidget
from turtlestudio.workspace_tabs import TabKind, TabRef, WorkspaceTabs
from turtlestudio.project import (
    MANIFEST_NAME,
    STANDARD_SUBDIRS,
    ProjectInfo,
    create_project,
    load_project,
    read_project_display_name,
)

# Section label (Spanish, matches the old tool) -> project-relative directory.
# Dispatch is by directory, not file suffix: every TurtleStudio asset is plain
# JSON, so ".json" alone can't tell a sprite from a tileset apart.
_ASSET_SECTIONS: tuple[tuple[str, str], ...] = (
    (tr("mainwindow.section_sprites"), "objects/Sprites"),
    (tr("mainwindow.section_objects"), "objects/Objects"),
    (tr("mainwindow.section_fonts"), "objects/Fonts"),
    (tr("mainwindow.section_backgrounds"), "backgrounds"),
    (tr("mainwindow.section_tiles"), "tiles"),
    (tr("mainwindow.section_scenes"), "scenes"),
    (tr("mainwindow.section_palettes"), "palettes"),
    (tr("mainwindow.section_scripts"), "scripts"),
)


class _CenterStack(QStackedWidget):
    """QStackedWidget whose size hints follow only the visible page.

    The default QStackedWidget sizes itself to fit the largest page among
    ALL stacked widgets, not just the current one, which pins the whole
    main window to the size of the most demanding editor tab regardless of
    which tab is showing or how the user tries to resize the window. See
    the equivalent fix in Semi-FantasyConsole/tortustudio/mainwindow.py.
    """

    def sizeHint(self):
        current = self.currentWidget()
        return current.sizeHint() if current is not None else super().sizeHint()

    def minimumSizeHint(self):
        current = self.currentWidget()
        return current.minimumSizeHint() if current is not None else super().minimumSizeHint()


class _PlaceholderPage(QWidget):
    """Shown until the corresponding editor tab has been ported."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #888; font-size: 14px;")
        layout.addWidget(label)


class MainWindow(QMainWindow):
    _RECENT_PROJECTS_KEY = "recent_projects"
    _MAX_RECENT_PROJECTS = 8

    def __init__(self, project_root: Path | None = None) -> None:
        super().__init__()
        self.project: ProjectInfo | None = None
        self.project_root: Path | None = None
        self._settings = QSettings("TurtleStudio", "TurtleStudio")

        self.setWindowTitle("TurtleStudio")
        self.resize(1280, 720)

        self._build_menu()
        self._build_ui()
        self._build_undo_shortcuts()

        if project_root is not None:
            self.open_project(project_root)

    # -- menu -----------------------------------------------------

    def _build_menu(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu(tr("mainwindow.menu_file"))

        open_action = QAction(tr("mainwindow.menu_open_project"), self)
        open_action.triggered.connect(self._action_open_project)
        file_menu.addAction(open_action)

        self.recent_menu = file_menu.addMenu(tr("mainwindow.menu_open_recent"))
        self._rebuild_recent_menu()

        new_action = QAction(tr("mainwindow.menu_new_project"), self)
        new_action.triggered.connect(self._action_new_project)
        file_menu.addAction(new_action)

        file_menu.addSeparator()

        export_action = QAction(tr("mainwindow.menu_export"), self)
        export_action.triggered.connect(self._action_show_export)
        file_menu.addAction(export_action)

    # -- ui ---------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.workspace_tabs = WorkspaceTabs()
        self.workspace_tabs.tab_selected.connect(self._on_workspace_tab_selected)
        outer_layout.addWidget(self.workspace_tabs)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer_layout.addWidget(splitter, stretch=1)

        self.project_tree = QTreeWidget()
        self.project_tree.setHeaderHidden(True)
        self.project_tree.itemDoubleClicked.connect(self._on_tree_double_click)
        splitter.addWidget(self.project_tree)

        self.center_stack = _CenterStack()
        self.center_stack.currentChanged.connect(lambda _i: self.center_stack.updateGeometry())
        self._empty_page = WelcomeWidget()
        self._empty_page.new_project_requested.connect(self._action_new_project)
        self._empty_page.open_project_requested.connect(self.open_project)
        self._empty_page.browse_requested.connect(self._action_open_project)
        self._empty_page.set_recent_projects(self._load_recent_projects())
        self.center_stack.addWidget(self._empty_page)

        self.palette_editor = PaletteEditorWidget(Path("."))
        self.center_stack.addWidget(self.palette_editor)

        self.sprite_editor = SpriteEditorWidget(Path("."))
        self.center_stack.addWidget(self.sprite_editor)

        self.scene_editor = SceneEditorWidget(Path("."))
        self.center_stack.addWidget(self.scene_editor)

        self.play_widget = PlayWidget(Path("."))
        self.center_stack.addWidget(self.play_widget)

        self.tileset_editor = TilesetEditorWidget(Path("."))
        self.center_stack.addWidget(self.tileset_editor)

        self.background_editor = BackgroundEditorWidget(Path("."))
        self.center_stack.addWidget(self.background_editor)

        self.object_editor = ObjectEditorWidget(Path("."))
        self.center_stack.addWidget(self.object_editor)

        self.font_editor = FontEditorWidget(Path("."))
        self.center_stack.addWidget(self.font_editor)

        self.build_dialog = BuildDialogWidget(Path("."))
        self.center_stack.addWidget(self.build_dialog)

        self._tab_widgets: dict[TabKind, QWidget] = {
            TabKind.SCENE_EDITOR: self.scene_editor,
            TabKind.PLAY_MODE: self.play_widget,
            TabKind.SPRITE_EDITOR: self.sprite_editor,
            TabKind.TILESET_EDITOR: self.tileset_editor,
            TabKind.BACKGROUND_EDITOR: self.background_editor,
            TabKind.OBJECT_EDITOR: self.object_editor,
            TabKind.FONT_EDITOR: self.font_editor,
            TabKind.PALETTE_EDITOR: self.palette_editor,
            TabKind.EXPORT: self.build_dialog,
        }

        splitter.addWidget(self.center_stack)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        self.setCentralWidget(outer)

    # -- undo/redo ---------------------------------------------------------

    def _build_undo_shortcuts(self) -> None:
        """Ctrl+Z/Ctrl+Shift+Z (and Ctrl+Y) dispatch to whichever editor tab is
        currently visible; each editor owns its own SnapshotHistory scoped to the
        item it has open (see edit_history.py), so this is just routing -- tabs
        without undo()/redo() (Play, Export) are silently ignored."""
        undo_sc = QShortcut(QKeySequence.StandardKey.Undo, self)
        undo_sc.activated.connect(self._action_undo)
        redo_sc = QShortcut(QKeySequence.StandardKey.Redo, self)
        redo_sc.activated.connect(self._action_redo)
        # StandardKey.Redo is Ctrl+Shift+Z on some platforms/styles and Ctrl+Y on
        # others; bind both explicitly so Ctrl+Y always works regardless of platform.
        redo_sc_y = QShortcut(QKeySequence("Ctrl+Y"), self)
        redo_sc_y.activated.connect(self._action_redo)

    def _action_undo(self) -> None:
        widget = self.center_stack.currentWidget()
        undo = getattr(widget, "undo", None)
        if callable(undo):
            undo()

    def _action_redo(self) -> None:
        widget = self.center_stack.currentWidget()
        redo = getattr(widget, "redo", None)
        if callable(redo):
            redo()

    # -- project actions ---------------------------------------------------------

    def _action_open_project(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr("mainwindow.open_project_title"))
        if path:
            self.open_project(Path(path))

    def _action_open_recent(self, path: Path) -> None:
        if not path.is_dir():
            QMessageBox.critical(
                self,
                tr("mainwindow.open_project_error_title"),
                tr("mainwindow.open_recent_missing", path=str(path)),
            )
            self._forget_recent_project(path)
            return
        self.open_project(path)

    def _action_clear_recent_projects(self) -> None:
        self._settings.remove(self._RECENT_PROJECTS_KEY)
        self._on_recent_projects_changed()

    def _load_recent_projects(self) -> list[Path]:
        raw = self._settings.value(self._RECENT_PROJECTS_KEY, [])
        if isinstance(raw, str):
            raw = [raw]
        return [Path(item) for item in raw or []]

    def _remember_recent_project(self, path: Path) -> None:
        recents = [p for p in self._load_recent_projects() if p != path]
        recents.insert(0, path)
        del recents[self._MAX_RECENT_PROJECTS :]
        self._settings.setValue(self._RECENT_PROJECTS_KEY, [str(p) for p in recents])
        self._on_recent_projects_changed()

    def _forget_recent_project(self, path: Path) -> None:
        recents = [p for p in self._load_recent_projects() if p != path]
        self._settings.setValue(self._RECENT_PROJECTS_KEY, [str(p) for p in recents])
        self._on_recent_projects_changed()

    def _on_recent_projects_changed(self) -> None:
        self._rebuild_recent_menu()
        empty_page = getattr(self, "_empty_page", None)
        if empty_page is not None:
            empty_page.set_recent_projects(self._load_recent_projects())

    def _rebuild_recent_menu(self) -> None:
        self.recent_menu.clear()
        recents = self._load_recent_projects()
        if not recents:
            empty_action = QAction(tr("mainwindow.menu_open_recent_empty"), self)
            empty_action.setEnabled(False)
            self.recent_menu.addAction(empty_action)
            return
        for path in recents:
            label = read_project_display_name(path) if path.is_dir() else str(path)
            action = QAction(label, self)
            action.setToolTip(str(path))
            action.triggered.connect(lambda _checked=False, p=path: self._action_open_recent(p))
            self.recent_menu.addAction(action)
        self.recent_menu.addSeparator()
        clear_action = QAction(tr("mainwindow.menu_open_recent_clear"), self)
        clear_action.triggered.connect(self._action_clear_recent_projects)
        self.recent_menu.addAction(clear_action)

    def _action_show_export(self) -> None:
        self.workspace_tabs.select(TabKind.EXPORT)

    def _on_workspace_tab_selected(self, ref: TabRef) -> None:
        if ref.kind == TabKind.PLAY_MODE:
            # Play always starts stopped (leaving the tab always stops it, below),
            # so a fresh re-read of the manifest here can't clobber a running
            # session -- it just picks up scene edits saved from other tabs.
            if self.project is not None:
                self.play_widget.refresh()
        else:
            self.play_widget.stop_on_tab_away()
            if ref.kind == TabKind.SCENE_EDITOR and self.project is not None:
                # Cheap catalog-only refresh (not a full self.scene_editor.refresh())
                # so objects created/removed in the Object Editor tab show up in the
                # "add object" combo without discarding unsaved scene edits/undo history.
                self.scene_editor.refresh_object_catalog()
        widget = self._tab_widgets.get(ref.kind)
        if widget is not None:
            self.center_stack.setCurrentWidget(widget)

    def _action_new_project(self) -> None:
        dialog = NewProjectDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        path = dialog.folder_path()
        try:
            create_project(
                Path(path),
                display_name=dialog.project_name() or None,
                board=dialog.selected_board(),
            )
        except (ValueError, OSError) as e:
            QMessageBox.critical(self, tr("common.error"), str(e))
            return
        self.open_project(Path(path))

    def open_project(self, project_root: Path) -> None:
        root = project_root.expanduser().resolve()
        try:
            info = load_project(root)
        except ValueError as e:
            QMessageBox.critical(self, tr("mainwindow.open_project_error_title"), str(e))
            return
        self.project = info
        self.project_root = root
        self._remember_recent_project(root)
        self.setWindowTitle(f"TurtleStudio — {info.name}")
        self.workspace_tabs.set_target_board(info.target_board)
        self.palette_editor.set_project_root(root)
        self.sprite_editor.set_project_root(root)
        self.scene_editor.set_project_root(root)
        self.play_widget.set_project_root(root)
        self.tileset_editor.set_project_root(root)
        self.background_editor.set_project_root(root)
        self.object_editor.set_project_root(root)
        self.font_editor.set_project_root(root)
        self.build_dialog.set_project_root(root)
        self._refresh_project_tree()
        # WorkspaceTabs auto-selects its first tab (Scene) during construction, before
        # tab_selected got connected here, so center_stack never followed it — sync once
        # explicitly rather than relying on a signal that already fired.
        self.center_stack.setCurrentWidget(self.scene_editor)

    # -- project tree ---------------------------------------------------------

    def _refresh_project_tree(self) -> None:
        self.project_tree.clear()
        if self.project_root is None:
            return
        for label, rel in _ASSET_SECTIONS:
            section_dir = self.project_root / rel
            section_item = QTreeWidgetItem([label])
            section_item.setData(0, Qt.ItemDataRole.UserRole, None)
            self.project_tree.addTopLevelItem(section_item)
            if not section_dir.is_dir():
                continue
            for p in sorted(section_dir.glob("*")):
                if not p.is_file():
                    continue
                child = QTreeWidgetItem([p.name])
                child.setData(0, Qt.ItemDataRole.UserRole, str(p))
                section_item.addChild(child)
            section_item.setExpanded(True)

    def _on_tree_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        raw = item.data(0, Qt.ItemDataRole.UserRole)
        if raw is None:
            return
        self._open_asset_path(Path(raw))

    def _open_asset_path(self, path: Path) -> None:
        """Dispatch a double-clicked asset to its editor, by parent directory.

        Every TurtleStudio asset is plain JSON, so unlike TortoiseStudio's
        per-type file extensions, dispatch has to key off which directory
        the file lives in rather than its suffix. Editors are wired in here
        as each one is built (see the port plan); until then this shows a
        placeholder so navigation is still testable end-to-end.
        """
        if self.project_root is None:
            return
        try:
            rel = path.relative_to(self.project_root).as_posix()
        except ValueError:
            return

        if rel.startswith("palettes/"):
            self.palette_editor.open_palette_relpath(rel)
            self.workspace_tabs.select(TabKind.PALETTE_EDITOR)
            return

        if rel.startswith("objects/Sprites/"):
            self.sprite_editor.open_sprite(path.stem)
            self.workspace_tabs.select(TabKind.SPRITE_EDITOR)
            return

        if rel.startswith("scenes/"):
            self.scene_editor.open_scene(path.stem)
            self.workspace_tabs.select(TabKind.SCENE_EDITOR)
            return

        if rel.startswith("tiles/"):
            self.tileset_editor.open_tileset(path.stem)
            self.workspace_tabs.select(TabKind.TILESET_EDITOR)
            return

        if rel.startswith("backgrounds/"):
            self.background_editor.open_background(path.stem)
            self.workspace_tabs.select(TabKind.BACKGROUND_EDITOR)
            return

        if rel.startswith("objects/Objects/"):
            self.object_editor.open_object(path.stem)
            self.workspace_tabs.select(TabKind.OBJECT_EDITOR)
            return

        if rel.startswith("objects/Fonts/"):
            self.font_editor.open_font(path.stem)
            self.workspace_tabs.select(TabKind.FONT_EDITOR)
            return

        placeholder = _PlaceholderPage(tr("mainwindow.placeholder_not_ported", rel=rel))
        self.center_stack.addWidget(placeholder)
        self.center_stack.setCurrentWidget(placeholder)


def run_studio(project_path: Path | None = None) -> int:
    app = QApplication(sys.argv)
    window = MainWindow(project_path)
    window.show()
    return app.exec()
