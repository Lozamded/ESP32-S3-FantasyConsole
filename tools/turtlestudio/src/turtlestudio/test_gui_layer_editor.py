"""Pruebas smoke del editor de capas GUI (spec/gui-layer-v0.md).

Requiere PyQt6. Se saltea con `skipUnless` si no esta disponible (por ejemplo entornos
sin display server), matching el patron de test_hud_border.py.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


def _has_pyqt6() -> bool:
    try:
        import PyQt6  # noqa: F401

        return True
    except Exception:
        return False


# QApplication no puede instanciarse dos veces por proceso; se reusa el mismo entre tests.
_app = None


def _ensure_qapp():
    global _app
    if _app is not None:
        return _app
    from PyQt6.QtWidgets import QApplication

    # offscreen para CI sin display server -- no requiere Xvfb.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])
    return _app


@unittest.skipUnless(_has_pyqt6(), "requires PyQt6 for the editor widget")
class GuiLayerEditorSmokeTests(unittest.TestCase):
    def test_widget_instantiates_without_project(self) -> None:
        _ensure_qapp()
        from turtlestudio.gui_layer_editor import GuiLayerEditorWidget

        w = GuiLayerEditorWidget(Path("."))
        self.assertEqual(w.layer_id, "")
        self.assertEqual(w.rects, [])
        self.assertEqual(w.labels, [])

    def test_set_project_root_discovers_existing_layer(self) -> None:
        _ensure_qapp()
        from turtlestudio.gui_layer_editor import GuiLayerEditorWidget
        from turtlestudio.guilayers import GuiLayer, GuiRect, write_gui_layer_file

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_gui_layer_file(
                root,
                GuiLayer(
                    id="pause",
                    bg_color_index=3,
                    pauses_scene=True,
                    rects=(GuiRect(x=10, y=10, w=40, h=20, color_index=5),),
                ),
            )
            w = GuiLayerEditorWidget(Path("."))
            w.set_project_root(root)
            self.assertEqual(w.layer_id, "pause")
            self.assertEqual(w.spin_bg.value(), 3)
            self.assertTrue(w.chk_pauses.isChecked())
            self.assertEqual(len(w.rects), 1)
            self.assertEqual(w.rects[0].w, 40)

    def test_current_layer_reconstructs_dataclass_from_ui_state(self) -> None:
        _ensure_qapp()
        from turtlestudio.gui_layer_editor import GuiLayerEditorWidget
        from turtlestudio.guilayers import GuiRect, GuiTextLabel

        w = GuiLayerEditorWidget(Path("."))
        w.layer_id = "menu"
        w.spin_x.setValue(4)
        w.spin_y.setValue(4)
        w.spin_w.setValue(100)
        w.spin_h.setValue(60)
        w.spin_bg.setValue(7)
        w.chk_transparent.setChecked(True)
        w.chk_pauses.setChecked(True)
        w.chk_captures.setChecked(True)
        w.spin_z.setValue(50)
        w.rects = [GuiRect(x=1, y=2, w=3, h=4, color_index=5)]
        w.labels = [GuiTextLabel(id="title", font="font_main", text="HI", x=1, y=2)]
        ly = w._current_layer()
        self.assertEqual(ly.id, "menu")
        self.assertEqual((ly.x, ly.y, ly.w, ly.h), (4, 4, 100, 60))
        self.assertEqual(ly.bg_color_index, 7)
        self.assertTrue(ly.transparent_bg)
        self.assertTrue(ly.pauses_scene)
        self.assertTrue(ly.captures_input)
        self.assertEqual(ly.z, 50)
        self.assertEqual(len(ly.rects), 1)
        self.assertEqual(ly.rects[0].color_index, 5)
        self.assertEqual(ly.text_labels[0].text, "HI")

    def test_add_and_remove_rect_row_updates_model(self) -> None:
        _ensure_qapp()
        from turtlestudio.gui_layer_editor import GuiLayerEditorWidget

        w = GuiLayerEditorWidget(Path("."))
        w.layer_id = "menu"
        self.assertEqual(len(w.rects), 0)
        w._action_add_rect()
        self.assertEqual(len(w.rects), 1)
        self.assertEqual(w.rects_table.rowCount(), 1)
        w.rects_table.setCurrentCell(0, 0)
        w._action_remove_rect()
        self.assertEqual(len(w.rects), 0)
        self.assertEqual(w.rects_table.rowCount(), 0)

    def test_add_and_remove_label_row_updates_model(self) -> None:
        _ensure_qapp()
        from turtlestudio.gui_layer_editor import GuiLayerEditorWidget

        w = GuiLayerEditorWidget(Path("."))
        w.layer_id = "menu"
        w._action_add_label()
        self.assertEqual(len(w.labels), 1)
        self.assertEqual(w.labels_table.rowCount(), 1)
        w.labels_table.setCurrentCell(0, 0)
        w._action_remove_label()
        self.assertEqual(len(w.labels), 0)

    def test_save_writes_current_layer_to_disk(self) -> None:
        _ensure_qapp()
        from turtlestudio.gui_layer_editor import GuiLayerEditorWidget
        from turtlestudio.guilayers import GuiLayer, read_gui_layer_file, write_gui_layer_file

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_gui_layer_file(root, GuiLayer(id="pause"))
            w = GuiLayerEditorWidget(Path("."))
            w.set_project_root(root)
            self.assertEqual(w.layer_id, "pause")
            w.spin_bg.setValue(9)  # marca dirty
            self.assertTrue(w._dirty)
            w._action_save()
            self.assertFalse(w._dirty)
            reread = read_gui_layer_file(root, "pause")
            self.assertEqual(reread.bg_color_index, 9)


if __name__ == "__main__":
    unittest.main()
