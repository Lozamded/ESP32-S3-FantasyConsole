"""Main TurtleStudio window layout."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
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
from turtlestudio.sprite_editor import SpriteEditorWidget
from turtlestudio.project import (
    MANIFEST_NAME,
    STANDARD_SUBDIRS,
    ProjectInfo,
    create_project,
    load_project,
)

# Section label (Spanish, matches the old tool) -> project-relative directory.
# Dispatch is by directory, not file suffix: every TurtleStudio asset is plain
# JSON, so ".json" alone can't tell a sprite from a tileset apart.
_ASSET_SECTIONS: tuple[tuple[str, str], ...] = (
    ("Sprites", "objects/Sprites"),
    ("Objetos", "objects/Objects"),
    ("Fuentes", "objects/Fonts"),
    ("Fondos", "backgrounds"),
    ("Tiles", "tiles"),
    ("Escenas", "scenes"),
    ("Paletas", "palettes"),
    ("Scripts", "scripts"),
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
    def __init__(self, project_root: Path | None = None) -> None:
        super().__init__()
        self.project: ProjectInfo | None = None
        self.project_root: Path | None = None

        self.setWindowTitle("TurtleStudio")
        self.resize(1280, 720)

        self._build_menu()
        self._build_ui()

        if project_root is not None:
            self.open_project(project_root)

    # -- menu -----------------------------------------------------

    def _build_menu(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu("&Archivo")

        open_action = QAction("&Abrir proyecto…", self)
        open_action.triggered.connect(self._action_open_project)
        file_menu.addAction(open_action)

        new_action = QAction("&Nuevo proyecto…", self)
        new_action.triggered.connect(self._action_new_project)
        file_menu.addAction(new_action)

    # -- ui ---------------------------------------------------------

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.project_tree = QTreeWidget()
        self.project_tree.setHeaderHidden(True)
        self.project_tree.itemDoubleClicked.connect(self._on_tree_double_click)
        splitter.addWidget(self.project_tree)

        self.center_stack = _CenterStack()
        self.center_stack.currentChanged.connect(lambda _i: self.center_stack.updateGeometry())
        self._empty_page = _PlaceholderPage("Abre o crea un proyecto TurtleStudio.")
        self.center_stack.addWidget(self._empty_page)

        self.palette_editor = PaletteEditorWidget(Path("."))
        self.center_stack.addWidget(self.palette_editor)

        self.sprite_editor = SpriteEditorWidget(Path("."))
        self.center_stack.addWidget(self.sprite_editor)

        splitter.addWidget(self.center_stack)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        self.setCentralWidget(splitter)

    # -- project actions ---------------------------------------------------------

    def _action_open_project(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Abrir proyecto TurtleStudio")
        if path:
            self.open_project(Path(path))

    def _action_new_project(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Carpeta para el nuevo proyecto")
        if not path:
            return
        name, ok = QInputDialog.getText(self, "Nuevo proyecto", "Nombre del proyecto:")
        if not ok:
            return
        try:
            create_project(Path(path), display_name=name or None)
        except (ValueError, OSError) as e:
            QMessageBox.critical(self, "Error", str(e))
            return
        self.open_project(Path(path))

    def open_project(self, project_root: Path) -> None:
        root = project_root.expanduser().resolve()
        try:
            info = load_project(root)
        except ValueError as e:
            QMessageBox.critical(self, "Error al abrir proyecto", str(e))
            return
        self.project = info
        self.project_root = root
        self.setWindowTitle(f"TurtleStudio — {info.name}")
        self.palette_editor.set_project_root(root)
        self.sprite_editor.set_project_root(root)
        self._refresh_project_tree()

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
            self.center_stack.setCurrentWidget(self.palette_editor)
            return

        if rel.startswith("objects/Sprites/"):
            self.sprite_editor.open_sprite(path.stem)
            self.center_stack.setCurrentWidget(self.sprite_editor)
            return

        placeholder = _PlaceholderPage(f"Editor pendiente de portar para:\n{rel}")
        self.center_stack.addWidget(placeholder)
        self.center_stack.setCurrentWidget(placeholder)


def run_studio(project_path: Path | None = None) -> int:
    app = QApplication(sys.argv)
    window = MainWindow(project_path)
    window.show()
    return app.exec()
