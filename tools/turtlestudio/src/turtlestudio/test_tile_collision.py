"""Pruebas de collision en tilesets."""

from __future__ import annotations

import unittest

from turtlestudio.tile_collision import (
    TILE_COLLISION_NONE,
    TILE_COLLISION_SHAPE,
    TILE_COLLISION_SOLID,
    TILE_ONEWAY_UP,
    aabb_from_tile_pixels,
    apply_oneway_to_collision_entry,
    collision_meta_to_json_field,
    parse_tile_collision_from_entry,
    parse_tileset_collision_meta,
)
from turtlestudio.tiles import serialize_tileset_tiles


class TileCollisionTests(unittest.TestCase):
    def test_parse_none_and_shape(self) -> None:
        none_e = parse_tile_collision_from_entry({"collision": "none"})
        self.assertEqual(none_e["kind"], TILE_COLLISION_NONE)
        shape_e = parse_tile_collision_from_entry(
            {
                "collision": {
                    "mode": "aabb",
                    "x0": 1,
                    "y0": 2,
                    "x1": 3,
                    "y1": 4,
                }
            }
        )
        self.assertEqual(shape_e["kind"], TILE_COLLISION_SHAPE)
        self.assertEqual(shape_e["shape"]["x1"], 3)

    def test_serialize_omits_solid(self) -> None:
        rows = [[0] * 4 for _ in range(4)]
        meta = [{"kind": TILE_COLLISION_SOLID}, {"kind": TILE_COLLISION_NONE}]
        out = serialize_tileset_tiles(rows * 2, pw=4, ph=4, collision_meta=meta)
        self.assertNotIn("collision", out[0])
        self.assertEqual(out[1]["collision"], "none")

    def test_aabb_from_pixels(self) -> None:
        rows = [
            [31, 31, 31, 31],
            [31, 5, 5, 31],
            [31, 5, 5, 31],
            [31, 31, 31, 31],
        ]
        box = aabb_from_tile_pixels(rows, tile_px=4, transparent_index=31)
        self.assertEqual(box["x0"], 1)
        self.assertEqual(box["x1"], 2)
        self.assertEqual(box["y0"], 1)
        self.assertEqual(box["y1"], 2)

    def test_parse_tileset_meta_list(self) -> None:
        data = {
            "tiles": [
                {"image": {"format": "palette_rows", "rows": [[0]]}},
                {"collision": "none", "image": {"format": "palette_rows", "rows": [[1]]}},
            ]
        }
        meta = parse_tileset_collision_meta(data)
        self.assertEqual(len(meta), 2)
        self.assertEqual(meta[1]["kind"], TILE_COLLISION_NONE)

    def test_collision_field_shape_json(self) -> None:
        field = collision_meta_to_json_field(
            {
                "kind": TILE_COLLISION_SHAPE,
                "shape": {
                    "mode": "aabb",
                    "x0": 0,
                    "y0": 0,
                    "x1": 15,
                    "y1": 15,
                },
            }
        )
        self.assertIsInstance(field, dict)
        self.assertEqual(field["x1"], 15)

    def test_oneway_solid_entry_level(self) -> None:
        rows = [[0] * 4 for _ in range(4)]
        meta = [
            {
                "kind": TILE_COLLISION_SOLID,
                "oneway": True,
                "oneway_direction": TILE_ONEWAY_UP,
            }
        ]
        out = serialize_tileset_tiles(rows, pw=4, ph=4, collision_meta=meta)
        self.assertTrue(out[0]["oneway"])
        self.assertEqual(out[0]["oneway_direction"], "up")

    def test_oneway_inside_shape_collision(self) -> None:
        rows = [[0] * 4 for _ in range(4)]
        meta = [
            {
                "kind": TILE_COLLISION_SHAPE,
                "oneway": True,
                "oneway_direction": "left",
                "shape": {
                    "mode": "aabb",
                    "x0": 0,
                    "y0": 0,
                    "x1": 3,
                    "y1": 3,
                },
            }
        ]
        out = serialize_tileset_tiles(rows, pw=4, ph=4, collision_meta=meta)
        coll = out[0]["collision"]
        self.assertIsInstance(coll, dict)
        self.assertTrue(coll["oneway"])
        self.assertEqual(coll["oneway_direction"], "left")

    def test_parse_oneway_roundtrip(self) -> None:
        entry = {
            "oneway": True,
            "oneway_direction": "down",
            "collision": {
                "mode": "aabb",
                "x0": 0,
                "y0": 0,
                "x1": 1,
                "y1": 1,
            },
        }
        meta = parse_tile_collision_from_entry(entry)
        self.assertTrue(meta["oneway"])
        self.assertEqual(meta["oneway_direction"], "down")


if __name__ == "__main__":
    unittest.main()
