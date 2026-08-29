"""Pruebas del campo `gui_layers_autoshow` por escena (spec/gui-layer-v0.md
"Auto-show por escena")."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from turtlestudio.project import parse_gui_layers_autoshow


class ParseGuiLayersAutoshowTests(unittest.TestCase):
    def test_empty_when_missing(self) -> None:
        self.assertEqual(parse_gui_layers_autoshow(None), ())

    def test_empty_when_not_list(self) -> None:
        self.assertEqual(parse_gui_layers_autoshow("hud"), ())
        self.assertEqual(parse_gui_layers_autoshow({"foo": 1}), ())
        self.assertEqual(parse_gui_layers_autoshow(42), ())

    def test_filters_non_strings(self) -> None:
        self.assertEqual(parse_gui_layers_autoshow(["hud", 3, None, "score"]), ("hud", "score"))

    def test_filters_invalid_stems(self) -> None:
        self.assertEqual(
            parse_gui_layers_autoshow(["1bad", "-menu", "menu with space", "menu/foo", "good"]),
            ("good",),
        )

    def test_dedupes_preserving_order(self) -> None:
        self.assertEqual(
            parse_gui_layers_autoshow(["hud", "score", "hud", "score"]),
            ("hud", "score"),
        )

    def test_strips_whitespace(self) -> None:
        self.assertEqual(parse_gui_layers_autoshow(["  hud ", "score"]), ("hud", "score"))


def _has_pyqt6() -> bool:
    try:
        import PyQt6  # noqa: F401

        return True
    except Exception:
        return False


_app = None


def _ensure_qapp():
    global _app
    if _app is not None:
        return _app
    from PyQt6.QtWidgets import QApplication

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])
    return _app


@unittest.skipUnless(_has_pyqt6(), "requires PyQt6 for the scene editor widget")
class SceneEditorAutoshowSmokeTests(unittest.TestCase):
    def _make_widget_with_project(self, root: Path):
        _ensure_qapp()
        from turtlestudio.scene_editor import SceneEditorWidget

        w = SceneEditorWidget(Path("."))
        w.project_root = root
        return w

    def test_checklist_lists_all_project_guilayers(self) -> None:
        from turtlestudio.guilayers import GuiLayer, write_gui_layer_file

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_gui_layer_file(root, GuiLayer(id="hud_score"))
            write_gui_layer_file(root, GuiLayer(id="hud_lives"))
            w = self._make_widget_with_project(root)
            row = {"id": "s0", "gui_layers_autoshow": ["hud_score"]}
            w._load_gui_layers_autoshow(row)
            from PyQt6.QtCore import Qt

            texts = []
            checked = []
            for i in range(w.list_gui_layers_autoshow.count()):
                item = w.list_gui_layers_autoshow.item(i)
                texts.append(item.text())
                if item.checkState() == Qt.CheckState.Checked:
                    checked.append(item.text())
            self.assertEqual(sorted(texts), ["hud_lives", "hud_score"])
            self.assertEqual(checked, ["hud_score"])

    def test_collect_reflects_ui_state(self) -> None:
        from PyQt6.QtCore import Qt
        from turtlestudio.guilayers import GuiLayer, write_gui_layer_file

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_gui_layer_file(root, GuiLayer(id="hud_score"))
            write_gui_layer_file(root, GuiLayer(id="hud_lives"))
            w = self._make_widget_with_project(root)
            w._load_gui_layers_autoshow({"id": "s0", "gui_layers_autoshow": []})
            for i in range(w.list_gui_layers_autoshow.count()):
                item = w.list_gui_layers_autoshow.item(i)
                if item.text() == "hud_lives":
                    item.setCheckState(Qt.CheckState.Checked)
            self.assertEqual(w._collect_gui_layers_autoshow(), ["hud_lives"])

    def test_missing_layer_preserved_and_marked(self) -> None:
        from PyQt6.QtCore import Qt

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "guilayers").mkdir()
            w = self._make_widget_with_project(root)
            w._load_gui_layers_autoshow({"id": "s0", "gui_layers_autoshow": ["ghost_hud"]})
            # No hay guilayers en disco pero el id existente en la escena debe seguir
            # visible en la lista (con marker) para no perderse al guardar.
            self.assertEqual(w.list_gui_layers_autoshow.count(), 1)
            item = w.list_gui_layers_autoshow.item(0)
            self.assertEqual(item.checkState(), Qt.CheckState.Checked)
            self.assertIn("ghost_hud", item.text())
            # Al colectar, debe salir el id original -- no el label con sufijo "(missing)".
            self.assertEqual(w._collect_gui_layers_autoshow(), ["ghost_hud"])


if __name__ == "__main__":
    unittest.main()
