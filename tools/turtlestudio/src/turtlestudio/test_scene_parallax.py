"""Pruebas de bandas de parallax horizontal (spec/scene-v0.md)."""

from __future__ import annotations

import unittest

from turtlestudio.scene_parallax import (
    MAX_PARALLAX_BANDS,
    SceneParallaxBand,
    apply_scene_parallax_bands_to_row,
    clamp_parallax_band,
    find_parallax_band,
    parse_scene_parallax_bands_from_row,
    scene_parallax_bands_to_json,
)


class SceneParallaxBandTests(unittest.TestCase):
    def test_empty_row_has_no_bands(self) -> None:
        self.assertEqual(parse_scene_parallax_bands_from_row({}, world_h=396), [])

    def test_parse_clamps_and_swaps(self) -> None:
        row = {
            "parallax_bands": [
                {"y0": 150, "y1": 10, "parallax_x": 9.0, "repeat_x": True},
            ]
        }
        bands = parse_scene_parallax_bands_from_row(row, world_h=198)
        self.assertEqual(len(bands), 1)
        b = bands[0]
        self.assertEqual((b.y0, b.y1), (10, 150))
        self.assertEqual(b.parallax_x, 2.0)  # clamped to MAX_PARALLAX_X
        self.assertTrue(b.repeat_x)

    def test_y_range_clamped_to_world_height(self) -> None:
        band = SceneParallaxBand(y0=-5, y1=1000, parallax_x=0.5)
        clamped = clamp_parallax_band(band, world_h=198)
        self.assertEqual((clamped.y0, clamped.y1), (0, 197))

    def test_more_than_max_bands_truncated(self) -> None:
        row = {"parallax_bands": [{"y0": i, "y1": i} for i in range(MAX_PARALLAX_BANDS + 5)]}
        bands = parse_scene_parallax_bands_from_row(row, world_h=396)
        self.assertEqual(len(bands), MAX_PARALLAX_BANDS)

    def test_find_parallax_band_matches_range(self) -> None:
        bands = [
            SceneParallaxBand(y0=0, y1=69, parallax_x=0.2),
            SceneParallaxBand(y0=70, y1=197, parallax_x=1.0),
        ]
        found = find_parallax_band(100, bands)
        self.assertIsNotNone(found)
        self.assertEqual(found.parallax_x, 1.0)
        self.assertIsNone(find_parallax_band(-1, bands))

    def test_apply_empty_list_clears_field(self) -> None:
        row: dict = {"parallax_bands": [{"y0": 0, "y1": 10, "parallax_x": 0.5}]}
        apply_scene_parallax_bands_to_row(row, [])
        self.assertNotIn("parallax_bands", row)

    def test_round_trip_preserves_bands(self) -> None:
        bands = [
            SceneParallaxBand(y0=0, y1=69, parallax_x=0.15, repeat_x=True),
            SceneParallaxBand(y0=70, y1=139, parallax_x=0.5),
        ]
        row: dict = {}
        apply_scene_parallax_bands_to_row(row, bands)
        self.assertIn("parallax_bands", row)
        reparsed = parse_scene_parallax_bands_from_row(row, world_h=396)
        self.assertEqual(len(reparsed), 2)
        self.assertEqual(reparsed[0].parallax_x, 0.15)
        self.assertTrue(reparsed[0].repeat_x)

    def test_compact_json_omits_defaults(self) -> None:
        band = SceneParallaxBand(y0=0, y1=10, parallax_x=1.0)
        js = scene_parallax_bands_to_json([band])[0]
        self.assertNotIn("fixed", js)
        self.assertNotIn("repeat_x", js)


if __name__ == "__main__":
    unittest.main()
