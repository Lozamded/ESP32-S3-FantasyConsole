"""Pruebas de camera.hud_border (spec/hud-border-v0.md)."""

from __future__ import annotations

import unittest

from turtlestudio.scene_camera import (
    HUD_MIN_PLAYFIELD,
    VIEWPORT_PIXEL_H,
    VIEWPORT_PIXEL_W,
    HudBorder,
    SceneCameraConfig,
    clamp_hud_border,
    parse_hud_border,
    parse_scene_camera,
    parse_scene_camera_from_row,
    scene_camera_flat_row_fields,
    scene_camera_to_json,
)


class HudBorderParseTests(unittest.TestCase):
    def test_default_is_zeros(self) -> None:
        b = HudBorder()
        self.assertTrue(b.is_zero())
        self.assertEqual(
            b.playfield_size(VIEWPORT_PIXEL_W, VIEWPORT_PIXEL_H),
            (VIEWPORT_PIXEL_W, VIEWPORT_PIXEL_H),
        )

    def test_missing_raw_returns_zeros(self) -> None:
        self.assertEqual(parse_hud_border(None), HudBorder())
        self.assertEqual(parse_hud_border({}), HudBorder())
        self.assertEqual(parse_hud_border(42), HudBorder())

    def test_partial_fields_default_others_to_zero(self) -> None:
        b = parse_hud_border({"top": 16})
        self.assertEqual((b.top, b.bottom, b.left, b.right), (16, 0, 0, 0))

    def test_negative_values_clamp_to_zero(self) -> None:
        b = parse_hud_border({"top": -5, "bottom": -1, "left": -100, "right": -1})
        self.assertTrue(b.is_zero())

    def test_oversize_clamps_to_half_viewport(self) -> None:
        b = parse_hud_border({"top": 999, "bottom": 999, "left": 999, "right": 999})
        # top+bottom debe dejar al menos HUD_MIN_PLAYFIELD px de playfield.
        self.assertGreaterEqual(VIEWPORT_PIXEL_H - b.top - b.bottom, HUD_MIN_PLAYFIELD)
        self.assertGreaterEqual(VIEWPORT_PIXEL_W - b.left - b.right, HUD_MIN_PLAYFIELD)


class HudBorderClampTests(unittest.TestCase):
    def test_clamp_hud_border_respects_min_playfield_v(self) -> None:
        b = clamp_hud_border(top=60, bottom=60, left=0, right=0)
        self.assertGreaterEqual(VIEWPORT_PIXEL_H - b.top - b.bottom, HUD_MIN_PLAYFIELD)

    def test_clamp_hud_border_respects_min_playfield_h(self) -> None:
        b = clamp_hud_border(top=0, bottom=0, left=80, right=80)
        self.assertGreaterEqual(VIEWPORT_PIXEL_W - b.left - b.right, HUD_MIN_PLAYFIELD)


class SceneCameraRoundtripTests(unittest.TestCase):
    def test_absence_of_hud_border_is_zeros(self) -> None:
        cam = parse_scene_camera({"mode": "fixed", "x": 0, "y": 0})
        self.assertTrue(cam.hud_border.is_zero())

    def test_hud_border_survives_json_roundtrip(self) -> None:
        cam = SceneCameraConfig(hud_border=HudBorder(top=16, bottom=0, left=8, right=8))
        j = scene_camera_to_json(cam)
        self.assertIn("hud_border", j)
        cam2 = parse_scene_camera(j)
        self.assertEqual(cam2.hud_border, cam.hud_border)

    def test_zero_hud_border_is_omitted_from_json(self) -> None:
        cam = SceneCameraConfig()
        j = scene_camera_to_json(cam)
        self.assertNotIn("hud_border", j)

    def test_parse_scene_camera_from_row_reads_flat_fallback(self) -> None:
        row = {
            "camera_mode": "fixed",
            "camera_hud_border_top": 20,
            "camera_hud_border_bottom": 4,
        }
        cam = parse_scene_camera_from_row(row)
        self.assertEqual(cam.hud_border.top, 20)
        self.assertEqual(cam.hud_border.bottom, 4)
        self.assertEqual(cam.hud_border.left, 0)
        self.assertEqual(cam.hud_border.right, 0)

    def test_nested_camera_wins_over_flat(self) -> None:
        row = {
            "camera": {
                "mode": "follow",
                "hud_border": {"top": 12, "bottom": 0, "left": 0, "right": 0},
            },
            "camera_hud_border_top": 200,  # ignorado (nested tiene precedencia)
        }
        cam = parse_scene_camera_from_row(row)
        self.assertEqual(cam.hud_border.top, 12)

    def test_flat_row_fields_include_hud_border(self) -> None:
        cam = SceneCameraConfig(hud_border=HudBorder(top=8, left=4, right=4))
        flat = scene_camera_flat_row_fields(cam)
        self.assertEqual(flat["camera_hud_border_top"], 8)
        self.assertEqual(flat["camera_hud_border_bottom"], 0)
        self.assertEqual(flat["camera_hud_border_left"], 4)
        self.assertEqual(flat["camera_hud_border_right"], 4)


def _has_pyqt6() -> bool:
    try:
        import PyQt6  # noqa: F401

        return True
    except Exception:
        return False


@unittest.skipUnless(_has_pyqt6(), "requires PyQt6 (scene_editor pulls it via play_runtime)")
class PlayRuntimePlayfieldTests(unittest.TestCase):
    """Verifica que PlaySession.begin() derive playfield_w/h del hud_border."""

    def test_begin_reduces_playfield_for_hud_top(self) -> None:
        from pathlib import Path

        from turtlestudio.play_runtime import PlaySession

        sess = PlaySession(Path("."))
        row = {
            "id": "s0",
            "world_steps_x": 1,
            "world_steps_y": 1,
            "objects": [],
            "camera": {
                "mode": "fixed",
                "hud_border": {"top": 16, "bottom": 0, "left": 0, "right": 0},
            },
        }
        sess.begin(row, tile_px=16, project_target_fps=30, project_anim_fps=8)
        self.assertEqual(sess.playfield_w, VIEWPORT_PIXEL_W)
        self.assertEqual(sess.playfield_h, VIEWPORT_PIXEL_H - 16)
        self.assertEqual(sess.playfield_oy, 16)
        # spec/hud-border-v0.md: mundo efectivo = playfield × ws. Con ws=1 y hud_top=16,
        # queda 164×108 = playfield, sin scrolling: la escena renderiza fija con el piso
        # (scene y=0) anclado al borde inferior del playfield.
        self.assertEqual(sess.fw, VIEWPORT_PIXEL_W)
        self.assertEqual(sess.fh, VIEWPORT_PIXEL_H - 16)
        self.assertFalse(sess._scrolling())


class HudBorderBgColorTests(unittest.TestCase):
    """spec/hud-border-v0.md "bg_color_index": pintar la region HUD una vez al comenzar."""

    def test_missing_field_defaults_to_no_paint(self) -> None:
        b = parse_hud_border({"top": 16})
        self.assertEqual(b.bg_color_index, -1)

    def test_valid_color_parsed(self) -> None:
        b = parse_hud_border({"top": 16, "bg_color_index": 5})
        self.assertEqual(b.bg_color_index, 5)

    def test_transparent_31_collapses_to_no_paint(self) -> None:
        b = parse_hud_border({"top": 16, "bg_color_index": 31})
        self.assertEqual(b.bg_color_index, -1)

    def test_out_of_range_collapses_to_no_paint(self) -> None:
        for bad in (-2, 40, 999):
            b = parse_hud_border({"top": 16, "bg_color_index": bad})
            self.assertEqual(b.bg_color_index, -1, f"input {bad}")

    def test_is_zero_reflects_bg_field(self) -> None:
        # Sin bordes pero con bg color -> NO es zero (queremos emitir el bloque hud_border).
        b = HudBorder(bg_color_index=3)
        self.assertFalse(b.is_zero())
        # Con bordes y sin bg -> tampoco es zero (comportamiento pre-existente).
        b2 = HudBorder(top=16)
        self.assertFalse(b2.is_zero())
        # Sin nada -> zero.
        self.assertTrue(HudBorder().is_zero())

    def test_scene_json_round_trip_preserves_bg(self) -> None:
        cam = parse_scene_camera({
            "mode": "fixed",
            "hud_border": {"top": 16, "bottom": 0, "left": 0, "right": 0, "bg_color_index": 4},
        })
        out = scene_camera_to_json(cam)
        self.assertIn("hud_border", out)
        self.assertEqual(out["hud_border"].get("bg_color_index"), 4)
        cam2 = parse_scene_camera(out)
        self.assertEqual(cam2.hud_border.bg_color_index, 4)

    def test_scene_json_omits_bg_when_not_set(self) -> None:
        cam = parse_scene_camera({"mode": "fixed", "hud_border": {"top": 16}})
        out = scene_camera_to_json(cam)
        self.assertNotIn("bg_color_index", out.get("hud_border", {}))

    def test_flat_row_carries_bg_field(self) -> None:
        cam = parse_scene_camera({
            "hud_border": {"top": 16, "bg_color_index": 7},
        })
        flat = scene_camera_flat_row_fields(cam)
        self.assertEqual(flat["camera_hud_border_bg_color_index"], 7)
        cam2 = parse_scene_camera_from_row(flat)
        self.assertEqual(cam2.hud_border.bg_color_index, 7)


class HudBorderOverlayTests(unittest.TestCase):
    """spec/hud-border-v0.md "overlay": mundo mantiene tamano canonico, actor entra en HUD."""

    def test_default_is_false(self) -> None:
        self.assertFalse(HudBorder().overlay)
        self.assertFalse(parse_hud_border({"top": 16}).overlay)

    def test_true_parsed_and_preserved(self) -> None:
        b = parse_hud_border({"top": 16, "overlay": True})
        self.assertTrue(b.overlay)

    def test_is_zero_reflects_overlay(self) -> None:
        # Sin bordes, sin bg, pero con overlay -> NO es zero (mantener el bloque emitido).
        self.assertFalse(HudBorder(overlay=True).is_zero())
        self.assertTrue(HudBorder().is_zero())

    def test_scene_json_round_trip_preserves_overlay(self) -> None:
        cam = parse_scene_camera({
            "hud_border": {"top": 16, "overlay": True},
        })
        out = scene_camera_to_json(cam)
        self.assertTrue(out["hud_border"]["overlay"])
        cam2 = parse_scene_camera(out)
        self.assertTrue(cam2.hud_border.overlay)

    def test_scene_json_omits_overlay_when_false(self) -> None:
        cam = parse_scene_camera({"hud_border": {"top": 16}})
        out = scene_camera_to_json(cam)
        self.assertNotIn("overlay", out.get("hud_border", {}))

    def test_flat_row_carries_overlay(self) -> None:
        cam = parse_scene_camera({"hud_border": {"top": 16, "overlay": True}})
        flat = scene_camera_flat_row_fields(cam)
        self.assertTrue(flat["camera_hud_border_overlay"])
        cam2 = parse_scene_camera_from_row(flat)
        self.assertTrue(cam2.hud_border.overlay)


if __name__ == "__main__":
    unittest.main()
