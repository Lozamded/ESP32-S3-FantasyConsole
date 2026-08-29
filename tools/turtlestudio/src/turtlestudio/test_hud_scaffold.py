"""Pruebas del scaffold "Crear capa HUD" del editor de escenas.

Geometria por lado y idempotencia (dos clicks NO crean dos archivos)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from turtlestudio.guilayers import SCENE_PIXEL_H, SCENE_PIXEL_W
from turtlestudio.scene_editor import compute_hud_layer_rect, hud_layer_stem


class ComputeHudLayerRectTests(unittest.TestCase):
    def test_top_spans_full_width(self) -> None:
        self.assertEqual(
            compute_hud_layer_rect("top", hud_top=16, hud_bottom=0, hud_left=0, hud_right=0),
            (0, 0, SCENE_PIXEL_W, 16),
        )

    def test_bottom_is_anchored_to_bottom_edge(self) -> None:
        x, y, w, h = compute_hud_layer_rect(
            "bottom", hud_top=0, hud_bottom=12, hud_left=0, hud_right=0
        )
        self.assertEqual((x, w, h), (0, SCENE_PIXEL_W, 12))
        self.assertEqual(y + h, SCENE_PIXEL_H)

    def test_left_excludes_top_and_bottom_strips(self) -> None:
        x, y, w, h = compute_hud_layer_rect(
            "left", hud_top=16, hud_bottom=8, hud_left=4, hud_right=0
        )
        self.assertEqual((x, w), (0, 4))
        self.assertEqual(y, 16)
        self.assertEqual(y + h, SCENE_PIXEL_H - 8)

    def test_right_is_anchored_to_right_edge_and_excludes_hstrips(self) -> None:
        x, y, w, h = compute_hud_layer_rect(
            "right", hud_top=0, hud_bottom=0, hud_left=0, hud_right=6
        )
        self.assertEqual(x + w, SCENE_PIXEL_W)
        self.assertEqual(w, 6)
        self.assertEqual((y, h), (0, SCENE_PIXEL_H))

    def test_unknown_side_rejected(self) -> None:
        with self.assertRaises(ValueError):
            compute_hud_layer_rect("middle", 0, 0, 0, 0)

    def test_returns_at_least_one_px_dimension(self) -> None:
        # Zero-size input clamped a 1: la escena editor decide si mostrar warning; la
        # funcion nunca devuelve rect degenerado.
        _x, _y, w, h = compute_hud_layer_rect("top", 0, 0, 0, 0)
        self.assertGreaterEqual(w, 1)
        self.assertGreaterEqual(h, 1)


class HudLayerStemTests(unittest.TestCase):
    def test_derives_from_scene_id_and_side(self) -> None:
        self.assertEqual(hud_layer_stem("level_1", "top"), "level_1_hud_top")
        self.assertEqual(hud_layer_stem("intro", "bottom"), "intro_hud_bottom")

    def test_falls_back_when_scene_id_invalid_for_stem(self) -> None:
        # id vacio, o con caracteres invalidos (empieza con digito) -> fallback a "scene".
        self.assertEqual(hud_layer_stem("", "top"), "scene_hud_top")
        self.assertEqual(hud_layer_stem("1bad", "top"), "scene_hud_top")


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
class HudScaffoldActionTests(unittest.TestCase):
    def _make_widget(self, root: Path):
        _ensure_qapp()
        from turtlestudio.scene_editor import SceneEditorWidget

        w = SceneEditorWidget(Path("."))
        w.project_root = root
        w._scenes = [{"id": "level_1", "gui_layers_autoshow": []}]
        w._current_index = 0
        w.spin_hud_top.setValue(16)
        return w

    def test_scaffold_creates_layer_and_registers_autoshow(self) -> None:
        from turtlestudio.guilayers import read_gui_layer_file

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            w = self._make_widget(root)
            emitted: list[str] = []
            w.request_open_gui_layer.connect(emitted.append)
            w._action_scaffold_hud_layer("top")
            # Archivo creado
            self.assertTrue((root / "guilayers" / "level_1_hud_top.json").is_file())
            layer = read_gui_layer_file(root, "level_1_hud_top")
            self.assertEqual((layer.x, layer.y, layer.w, layer.h), (0, 0, SCENE_PIXEL_W, 16))
            # Registrado en autoshow de la escena
            self.assertIn("level_1_hud_top", w._scenes[0]["gui_layers_autoshow"])
            # Emite la senal para saltar de tab
            self.assertEqual(emitted, ["level_1_hud_top"])

    def test_scaffold_is_idempotent(self) -> None:
        from turtlestudio.guilayers import GuiLayer, read_gui_layer_file, write_gui_layer_file

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Pre-existente con un color de fondo NO-default: si el scaffold sobreescribe,
            # este test falla (regresion protection).
            existing = GuiLayer(id="level_1_hud_top", x=0, y=0, w=SCENE_PIXEL_W, h=16, bg_color_index=9)
            write_gui_layer_file(root, existing)
            w = self._make_widget(root)
            w._action_scaffold_hud_layer("top")
            layer = read_gui_layer_file(root, "level_1_hud_top")
            self.assertEqual(layer.bg_color_index, 9)  # no fue sobreescrito
            # Autoshow sigue conteniendo un unico entry (no duplicado por segundo click).
            w._action_scaffold_hud_layer("top")
            self.assertEqual(
                w._scenes[0]["gui_layers_autoshow"].count("level_1_hud_top"),
                1,
            )

    def test_zero_border_shows_warning_and_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            w = self._make_widget(root)
            w.spin_hud_bottom.setValue(0)
            emitted: list[str] = []
            w.request_open_gui_layer.connect(emitted.append)
            # QMessageBox se abre modalmente; en offscreen la llamada retorna sin bloquear.
            # Basta con verificar que no se creo archivo ni emitio signal ni cambio la escena.
            from unittest.mock import patch

            with patch("turtlestudio.scene_editor.QMessageBox.information"):
                w._action_scaffold_hud_layer("bottom")
            self.assertFalse((root / "guilayers" / "level_1_hud_bottom.json").exists())
            self.assertEqual(emitted, [])
            self.assertEqual(w._scenes[0]["gui_layers_autoshow"], [])


if __name__ == "__main__":
    unittest.main()
