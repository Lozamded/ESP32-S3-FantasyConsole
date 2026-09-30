"""Paneles 9-slice en capas GUI (spec/gui-layer-v0.md "Paneles").

Correr: PYTHONPATH=src python3 src/turtlestudio/test_gui_panels.py
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from turtlestudio.guilayers import (
    MAX_GUI_LAYER_PANELS,
    GuiLayer,
    GuiPanel,
    collect_gui_layer_tileset_ids,
    gui_layer_to_json,
    parse_gui_layer,
    parse_gui_panel,
    write_gui_layer_file,
)

# Tileset de prueba 8px: tile i relleno con el indice de paleta i (0..8), asi el preview
# permite verificar que slice cayo en cada pixel.
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


class GuiPanelParseTests(unittest.TestCase):
    def test_full_round_trip(self) -> None:
        pn = GuiPanel(id="box", tileset="ui", x=4, y=80, w=156, h=40,
                      slices=(3, 1, 4, 2, 0, 2, 5, 1, 6), fill_center=False)
        ly = GuiLayer(id="dialog", panels=(pn,))
        again = parse_gui_layer(gui_layer_to_json(ly))
        assert again is not None
        self.assertEqual(again.panels, (pn,))

    def test_missing_tileset_or_id_rejected(self) -> None:
        self.assertIsNone(parse_gui_panel({"id": "box"}))
        self.assertIsNone(parse_gui_panel({"tileset": "ui"}))

    def test_slices_padded_and_normalized(self) -> None:
        pn = parse_gui_panel({"id": "box", "tileset": "ui", "slices": [1, -7, "x", 999]})
        assert pn is not None
        self.assertEqual(pn.slices, (1, -1, -1, 255, -1, -1, -1, -1, -1))

    def test_fill_center_defaults_true_and_omitted_in_json(self) -> None:
        pn = parse_gui_panel({"id": "box", "tileset": "ui"})
        assert pn is not None
        self.assertTrue(pn.fill_center)
        ly = GuiLayer(id="d", panels=(pn,))
        self.assertNotIn("fill_center", gui_layer_to_json(ly)["panels"][0])

    def test_panels_capped(self) -> None:
        raw = {"id": "d", "panels": [{"id": f"p{i}", "tileset": "ui"} for i in range(10)]}
        ly = parse_gui_layer(raw)
        assert ly is not None
        self.assertEqual(len(ly.panels), MAX_GUI_LAYER_PANELS)

    def test_collect_tileset_ids(self) -> None:
        ly = GuiLayer(id="d", panels=(GuiPanel(id="a", tileset="ui"),
                                      GuiPanel(id="b", tileset="frames")))
        self.assertEqual(collect_gui_layer_tileset_ids(ly), {"ui", "frames"})


class GuiPanelExportTests(unittest.TestCase):
    def test_panel_tileset_exported_without_scene_reference(self) -> None:
        from turtlestudio.build import collect_studio_bundle_files

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            write_gui_layer_file(root, GuiLayer(
                id="dialog", panels=(GuiPanel(id="box", tileset="ui"),)))
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
class GuiPanelEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def test_preview_paints_nine_slice(self) -> None:
        from turtlestudio.gui_layer_editor import GuiLayerEditorWidget

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            # Panel 40x24 en (0,0): esquinas 8x8, bordes/centro repetidos. transparent_bg para
            # que solo el panel pinte.
            write_gui_layer_file(root, GuiLayer(
                id="dialog", w=40, h=24, transparent_bg=True,
                panels=(GuiPanel(id="box", tileset="ui", w=40, h=24,
                                 slices=tuple(range(9))),)))
            w = GuiLayerEditorWidget(Path("."))
            w.set_project_root(root)
            w.combo_preview_palette.setCurrentText("palettes/pal.txt")
            w._refresh_preview()
            img = w.preview.pixmap().toImage()
            z = 3  # PREVIEW_ZOOM

            def idx_at(x: int, y: int) -> int:
                return img.pixelColor(x * z + 1, y * z + 1).red()  # paleta gris: r == indice

            self.assertEqual(idx_at(0, 0), 0)     # TL
            self.assertEqual(idx_at(20, 0), 1)    # T
            self.assertEqual(idx_at(39, 0), 2)    # TR
            self.assertEqual(idx_at(0, 12), 3)    # L
            self.assertEqual(idx_at(20, 12), 4)   # C
            self.assertEqual(idx_at(39, 12), 5)   # R
            self.assertEqual(idx_at(0, 23), 6)    # BL
            self.assertEqual(idx_at(20, 23), 7)   # B
            self.assertEqual(idx_at(39, 23), 8)   # BR

    def test_add_panel_and_save(self) -> None:
        from turtlestudio.gui_layer_editor import GuiLayerEditorWidget
        from turtlestudio.guilayers import read_gui_layer_file

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            write_gui_layer_file(root, GuiLayer(id="dialog"))
            w = GuiLayerEditorWidget(Path("."))
            w.set_project_root(root)
            w._action_add_panel()
            self.assertEqual(len(w.panels), 1)
            self.assertEqual(w.panels[0].tileset, "ui")
            w._action_save()
            self.assertEqual(read_gui_layer_file(root, "dialog").panels, tuple(w.panels))

    def test_slice_picker_assigns_and_advances(self) -> None:
        from turtlestudio.gui_layer_editor import PanelSlicePickerDialog

        tiles = [[[i] * TILE_PX for _ in range(TILE_PX)] for i in range(9)]
        rgbs = [(i / 255, i / 255, i / 255) for i in range(32)]
        dlg = PanelSlicePickerDialog(tiles, rgbs, (-1,) * 9)
        dlg._assign_tile(3)
        dlg._assign_tile(1)
        self.assertEqual(dlg.slices[:2], [3, 1])
        self.assertEqual(dlg.active_slot, 2)
        dlg._select_slot(0)
        dlg._clear_active_slot()
        self.assertEqual(dlg.slices[0], -1)


if __name__ == "__main__":
    unittest.main()
