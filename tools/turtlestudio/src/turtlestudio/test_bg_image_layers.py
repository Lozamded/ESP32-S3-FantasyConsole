"""Pruebas de capas de fondo con imagen (spec/scene-v0.md, background_layers[i].background)."""

from __future__ import annotations

import unittest

from turtlestudio.project import (
    BackgroundLayer,
    background_layers_to_json_list,
    default_background_layers,
    parse_background_layers,
)


class BackgroundLayerImageFieldsTests(unittest.TestCase):
    def test_old_shape_still_parses_with_defaults(self) -> None:
        layers = parse_background_layers(
            [{"enabled": True, "color_index": 2, "opacity": 255}],
            legacy_flat_index=1,
            n_colors=32,
        )
        self.assertEqual(layers[0].background, "")
        self.assertEqual(layers[0].parallax_x, 1.0)
        self.assertFalse(layers[0].fixed)
        self.assertFalse(layers[0].repeat_x)

    def test_missing_array_uses_defaults(self) -> None:
        layers = parse_background_layers(None, legacy_flat_index=3, n_colors=32)
        self.assertEqual(layers, default_background_layers(3))
        for ly in layers:
            self.assertEqual(ly.background, "")

    def test_new_fields_round_trip(self) -> None:
        raw = [
            {
                "enabled": True,
                "color_index": 1,
                "opacity": 255,
                "background": "clouds",
                "parallax_x": 0.3,
                "repeat_x": True,
            }
        ]
        layers = parse_background_layers(raw, legacy_flat_index=1, n_colors=32)
        self.assertEqual(layers[0].background, "clouds")
        self.assertEqual(layers[0].parallax_x, 0.3)
        self.assertTrue(layers[0].repeat_x)
        self.assertFalse(layers[0].fixed)
        js = background_layers_to_json_list(layers)[0]
        self.assertEqual(js["background"], "clouds")
        self.assertEqual(js["parallax_x"], 0.3)
        self.assertTrue(js["repeat_x"])

    def test_parallax_x_clamped(self) -> None:
        layers = parse_background_layers(
            [{"enabled": True, "color_index": 1, "opacity": 255, "parallax_x": 99.0}],
            legacy_flat_index=1,
            n_colors=32,
        )
        self.assertEqual(layers[0].parallax_x, 2.0)
        layers2 = parse_background_layers(
            [{"enabled": True, "color_index": 1, "opacity": 255, "parallax_x": -5.0}],
            legacy_flat_index=1,
            n_colors=32,
        )
        self.assertEqual(layers2[0].parallax_x, 0.0)

    def test_positional_construction_still_works(self) -> None:
        # BackgroundLayer(enabled, color_index, opacity) without new fields must still work
        # (used by _DEFAULT_SCENE_BACKGROUND_LAYERS / default_background_layers()).
        ly = BackgroundLayer(True, 1, 255)
        self.assertEqual(ly.background, "")
        self.assertEqual(ly.parallax_x, 1.0)


if __name__ == "__main__":
    unittest.main()
