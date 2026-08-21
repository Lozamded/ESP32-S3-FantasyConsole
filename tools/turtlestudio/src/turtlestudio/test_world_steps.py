"""Pruebas de limites de world_steps_x/y (spec/scene-v0.md, tope 1..8)."""

from __future__ import annotations

import unittest

from turtlestudio.project import (
    WORLD_STEPS_MAX,
    WORLD_STEPS_MIN,
    clamp_world_steps,
    scene_world_pixel_size,
)


class WorldStepsClampTests(unittest.TestCase):
    def test_cap_is_eight(self) -> None:
        self.assertEqual(WORLD_STEPS_MAX, 8)
        self.assertEqual(WORLD_STEPS_MIN, 1)

    def test_within_range_unchanged(self) -> None:
        for v in range(WORLD_STEPS_MIN, WORLD_STEPS_MAX + 1):
            self.assertEqual(clamp_world_steps(v), v)

    def test_above_max_clamped(self) -> None:
        self.assertEqual(clamp_world_steps(WORLD_STEPS_MAX + 1), WORLD_STEPS_MAX)
        self.assertEqual(clamp_world_steps(100), WORLD_STEPS_MAX)

    def test_below_min_clamped(self) -> None:
        self.assertEqual(clamp_world_steps(0), WORLD_STEPS_MIN)
        self.assertEqual(clamp_world_steps(-5), WORLD_STEPS_MIN)

    def test_invalid_uses_default(self) -> None:
        self.assertEqual(clamp_world_steps(None), 1)
        self.assertEqual(clamp_world_steps("nope"), 1)

    def test_pixel_size_at_max(self) -> None:
        w, h = scene_world_pixel_size(WORLD_STEPS_MAX, WORLD_STEPS_MAX, base_w=164, base_h=124)
        self.assertEqual((w, h), (164 * 8, 124 * 8))

    def test_pixel_size_clamps_oversized_steps(self) -> None:
        w, h = scene_world_pixel_size(99, 99, base_w=164, base_h=124)
        self.assertEqual((w, h), (164 * 8, 124 * 8))


if __name__ == "__main__":
    unittest.main()
