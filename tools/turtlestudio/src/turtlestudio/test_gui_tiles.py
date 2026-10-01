"""Capa de tiles de capas GUI (spec/gui-layer-v0.md "Capa de tiles").

Correr: PYTHONPATH=src python3 src/turtlestudio/test_gui_tiles.py
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from turtlestudio.guilayers import (
    GUI_TILE_MAX_COLS,
    GUI_TILE_MAX_ROWS,
    GuiLayer,
    GuiTileGrid,
    collect_gui_layer_tileset_ids,
    gui_layer_to_json,
    parse_gui_layer,
    parse_gui_tile_grid,
    resize_tile_grid,
    write_gui_layer_file,
)

# Tileset de prueba 8px: tile i relleno con el indice de paleta i (0..8), asi el preview
# permite verificar que tile cayo en cada pixel.
TILE_PX = 8


def _make_project(root: Path) -> None:
    from turtlestudio.tiles import save_tileset_json

    (root / "scripts").mkdir()
    (root / "palettes").mkdir()
    (root / "guilayers").mkdir()
    (root / "scripts" / "main.lua").write_text("cls(0)\n", encoding="utf-8")
    (root / "palettes" / "pal.txt").write_text(
        "\n".join([f"#{i:02x}{i:02x}{i:02x}" for i in range(32)]) + "\n",
        encoding="utf-8",
    )
    tiles = [[[i] * TILE_PX for _ in range(TILE_PX)] for i in range(9)]
    save_tileset_json(root, "ui", palette_rel="palettes/pal.txt", tile_px=TILE_PX,
                      tiles_rows=tiles)


class GuiTileGridParseTests(unittest.TestCase):
    def test_layer_without_tiles_has_none_and_no_json_key(self) -> None:
        ly = parse_gui_layer({"id": "d"})
        assert ly is not None
        self.assertIsNone(ly.tiles)
        self.assertNotIn("tiles", gui_layer_to_json(ly))

    def test_full_round_trip(self) -> None:
        grid = GuiTileGrid(tileset="ui", x=2, y=3, cols=3, rows=2, cells=(3, 1, 4, 5, -1, 6))
        ly = GuiLayer(id="dialog", x=4, y=84, w=156, h=36, tiles=grid)
        again = parse_gui_layer(gui_layer_to_json(ly))
        assert again is not None
        self.assertEqual(again.tiles, grid)

    def test_grid_without_tileset_is_dropped(self) -> None:
        self.assertIsNone(parse_gui_tile_grid({"cols": 2, "rows": 2}))

    def test_cells_padded_normalized_and_size_capped(self) -> None:
        grid = parse_gui_tile_grid({"tileset": "ui", "cols": 99, "rows": 2,
                                    "cells": [1, -7, "x", 999]})
        assert grid is not None
        self.assertEqual(grid.cols, GUI_TILE_MAX_COLS)
        self.assertEqual(len(grid.cells), GUI_TILE_MAX_COLS * 2)
        self.assertEqual(grid.cells[:5], (1, -1, -1, 255, -1))
        big = parse_gui_tile_grid({"tileset": "ui", "cols": 1, "rows": 99})
        assert big is not None
        self.assertEqual(big.rows, GUI_TILE_MAX_ROWS)

    def test_resize_keeps_cells_anchored_top_left(self) -> None:
        grid = GuiTileGrid(tileset="ui", cols=2, rows=2, cells=(1, 2, 3, 4))
        bigger = resize_tile_grid(grid, 3, 3)
        self.assertEqual(bigger.cells, (1, 2, -1, 3, 4, -1, -1, -1, -1))
        smaller = resize_tile_grid(bigger, 1, 2)
        self.assertEqual(smaller.cells, (1, 3))

    def test_collect_tileset_ids(self) -> None:
        self.assertEqual(collect_gui_layer_tileset_ids(GuiLayer(id="d")), set())
        ly = GuiLayer(id="d", tiles=GuiTileGrid(tileset="ui"))
        self.assertEqual(collect_gui_layer_tileset_ids(ly), {"ui"})


class GuiTileGridExportTests(unittest.TestCase):
    def test_tileset_exported_without_scene_reference(self) -> None:
        from turtlestudio.build import collect_studio_bundle_files

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            write_gui_layer_file(root, GuiLayer(id="dialog", tiles=GuiTileGrid(tileset="ui")))
            pkg = collect_studio_bundle_files(
                root, scenes=[], active_scene="", transparent_index=31,
                entry_relpath="scripts/main.lua",
            )
            rels = [rel for rel, _ in pkg.sidecar]
            self.assertIn("tiles/ui.tts", rels)


def _has_pyqt6() -> bool:
    try:
        import PyQt6  # noqa: F401

        return True
    except Exception:
        return False


@unittest.skipUnless(_has_pyqt6(), "requires PyQt6 for the editor widget")
class GuiTileGridEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def _editor(self, root: Path, layer: GuiLayer):
        from turtlestudio.gui_layer_editor import GuiLayerEditorWidget

        write_gui_layer_file(root, layer)
        w = GuiLayerEditorWidget(Path("."))
        w.set_project_root(root)
        w.combo_preview_palette.setCurrentText("palettes/pal.txt")
        return w

    @staticmethod
    def _index_at(w, x: int, y: int) -> int:
        img = w.preview.pixmap().toImage()
        z = 3  # PREVIEW_ZOOM; +1 evita las lineas de la rejilla dibujadas en el borde de celda
        return img.pixelColor(x * z + 1, y * z + 1).red()  # paleta gris: r == indice

    def test_preview_draws_cells_clipped_to_layer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            # Capa 20x12 en (10,20); rejilla 3x2 en (2,2): la tercera columna (x 18..25 de la
            # capa) queda cortada en x=20.
            w = self._editor(root, GuiLayer(
                id="dialog", x=10, y=20, w=20, h=12, transparent_bg=True,
                tiles=GuiTileGrid(tileset="ui", x=2, y=2, cols=3, rows=2,
                                  cells=(3, 1, 4, 5, -1, 6))))
            self.assertEqual(self._index_at(w, 13, 23), 3)   # celda (0,0)
            self.assertEqual(self._index_at(w, 21, 23), 1)   # celda (1,0)
            self.assertEqual(self._index_at(w, 28, 23), 4)   # celda (2,0), dentro de la capa
            self.assertEqual(self._index_at(w, 13, 30), 5)   # celda (0,1)

    def test_paint_and_erase_cells_on_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            w = self._editor(root, GuiLayer(
                id="dialog", x=10, y=20, w=40, h=24,
                tiles=GuiTileGrid(tileset="ui", cols=5, rows=3, cells=(-1,) * 15)))
            self.assertTrue(w.preview.paintable)
            self.assertEqual(w.tiles_picker.count(), 9)

            w.tiles_picker.setCurrentRow(3)            # como clic en la tira de tiles
            w._on_preview_cell_clicked(11, 21)         # celda (0,0)
            w.tiles_picker.setCurrentRow(1)
            for x in range(18, 40):                    # arrastre por la fila 0
                w._on_preview_cell_clicked(x, 22)
            w._on_preview_cell_clicked(5, 5)           # fuera de la capa: ignorado
            self.assertEqual(w._tile_grid.cells[:5], (3, 1, 1, 1, -1))
            self.assertTrue(w._dirty)

            w.chk_tiles_erase.setChecked(True)
            w._on_preview_cell_clicked(19, 21)         # borrador en (1,0)
            self.assertEqual(w._tile_grid.cell(1, 0), -1)

            # Sin capa de tiles activa el preview no pinta.
            w.chk_tiles.setChecked(False)
            self.assertFalse(w.preview.paintable)
            w._on_preview_cell_clicked(11, 21)
            self.assertIsNone(w._current_layer().tiles)

    def test_fill_layer_resize_and_save(self) -> None:
        from turtlestudio.guilayers import read_gui_layer_file

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            w = self._editor(root, GuiLayer(id="dialog", x=4, y=84, w=156, h=36))
            self.assertIsNone(w._current_layer().tiles)
            # Activar crea una rejilla vacia que ya cubre la capa: ceil(156/8) x ceil(36/8).
            w.chk_tiles.setChecked(True)
            grid = w._current_layer().tiles
            assert grid is not None
            self.assertEqual((grid.x, grid.y, grid.cols, grid.rows), (0, 0, 20, 5))

            w.tiles_picker.setCurrentRow(7)
            w._on_preview_cell_clicked(4, 84)          # celda (0,0)
            w.spin_tiles_cols.setValue(4)              # achicar conserva (0,0)
            w.spin_tiles_x.setValue(8)
            grid = w._current_layer().tiles
            assert grid is not None
            self.assertEqual((grid.x, grid.cols, grid.cell(0, 0)), (8, 4, 7))

            w._action_tiles_fill_layer()               # vuelve a cubrir la capa, conserva celdas
            grid = w._current_layer().tiles
            assert grid is not None
            self.assertEqual((grid.x, grid.y, grid.cols, grid.rows, grid.cell(0, 0)),
                             (0, 0, 20, 5, 7))
            self.assertEqual(w.spin_tiles_cols.value(), 20)

            w._action_save()
            self.assertEqual(read_gui_layer_file(root, "dialog").tiles, grid)

            w._action_tiles_clear()
            self.assertTrue(all(v == -1 for v in w._current_layer().tiles.cells))


    def test_undo_redo_tile_painting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            w = self._editor(root, GuiLayer(
                id="dialog", x=10, y=20, w=40, h=24,
                tiles=GuiTileGrid(tileset="ui", cols=5, rows=3, cells=(-1,) * 15)))
            empty = w._tile_grid.cells

            # Un trazo (presionar, arrastrar por 3 celdas, soltar) = un solo paso de undo.
            w.tiles_picker.setCurrentRow(1)
            w.preview.stroke_started.emit()
            for x in range(10, 34):
                w._on_preview_cell_clicked(x, 21)
            w.preview.stroke_finished.emit()
            after_stroke = w._tile_grid.cells
            self.assertEqual(after_stroke[:4], (1, 1, 1, -1))

            # Clic suelto con el borrador = otro paso.
            w.chk_tiles_erase.setChecked(True)
            w.preview.stroke_started.emit()
            w._on_preview_cell_clicked(11, 21)
            w.preview.stroke_finished.emit()
            self.assertEqual(w._tile_grid.cell(0, 0), -1)

            w.undo()
            self.assertEqual(w._tile_grid.cells, after_stroke)
            w.undo()
            self.assertEqual(w._tile_grid.cells, empty)
            w.undo()                                   # nada mas que deshacer: sin cambios
            self.assertEqual(w._tile_grid.cells, empty)
            w.redo()
            self.assertEqual(w._tile_grid.cells, after_stroke)
            self.assertTrue(w._dirty)

            # Cambiar el tamaño de la rejilla tambien se deshace (y vuelve el spinbox).
            w.spin_tiles_cols.setValue(2)
            self.assertEqual(w._tile_grid.cols, 2)
            w.undo()
            self.assertEqual(w._tile_grid.cols, 5)
            self.assertEqual(w.spin_tiles_cols.value(), 5)
            self.assertEqual(w._tile_grid.cells, after_stroke)

    def test_undo_does_not_cross_into_other_layer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            write_gui_layer_file(root, GuiLayer(id="other"))
            w = self._editor(root, GuiLayer(
                id="dialog", tiles=GuiTileGrid(tileset="ui", cols=2, rows=1, cells=(-1, -1))))
            w.open_layer("dialog")
            w.tiles_picker.setCurrentRow(2)
            w._on_preview_cell_clicked(1, 1)
            self.assertEqual(w._tile_grid.cell(0, 0), 2)
            w.open_layer("other")
            w.undo()
            self.assertEqual(w.layer_id, "other")
            self.assertIsNone(w._current_layer().tiles)
            self.assertFalse(w._dirty)

if __name__ == "__main__":
    unittest.main()
