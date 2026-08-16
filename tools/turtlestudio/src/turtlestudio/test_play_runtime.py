"""Pruebas de play_runtime.py sin Qt ni lupa: move_actor / colision de tiles contra
rejillas sinteticas (solid, none, one-way, aabb sub-tile). No requiere el build de lupa
-- ver test_play_lua_bridge.py para las pruebas que si lo requieren."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from turtlestudio import play_runtime as pr
from turtlestudio.palette_policy import TRANSPARENT_PALETTE_INDEX
from turtlestudio.scene_tiles import SceneTileLayer, scene_tile_grid_dimensions
from turtlestudio.tiles import TILESET_JSON_KIND

TILE_PX = 16
WORLD_W = 264
WORLD_H = 198


def _actor(x: int, y: int, *, col: tuple[int, int, int, int] = (0, 0, 7, 7)) -> pr.ActorRuntimeState:
    x0, y0, x1, y1 = col
    return pr.ActorRuntimeState(
        id="a",
        x=x,
        y=y,
        pw=8,
        ph=8,
        origin_x=0,
        origin_y=0,
        col_x0=x0,
        col_y0=y0,
        col_x1=x1,
        col_y1=y1,
        sprite_id="s",
        frame_count=1,
    )


def _empty_grid() -> list[list[int]]:
    cols, rows = scene_tile_grid_dimensions(TILE_PX, world_w=WORLD_W, world_h=WORLD_H)
    return [[TRANSPARENT_PALETTE_INDEX for _ in range(cols)] for _ in range(rows)]


def _write_tileset(root: Path, stem: str, tiles: list[dict]) -> None:
    d = root / "tiles"
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "format_version": 1,
        "kind": TILESET_JSON_KIND,
        "id": stem,
        "palette": "palettes/palette.txt",
        "tile_px": TILE_PX,
        "tiles": tiles,
    }
    (d / f"{stem}.json").write_text(json.dumps(payload), encoding="utf-8")


def _build_index(root: Path, grid: list[list[int]], tiles: list[dict]) -> pr.TileCollisionIndex:
    _write_tileset(root, "floor", tiles)
    layer = SceneTileLayer(enabled=True, tileset="floor", cells=tuple(tuple(r) for r in grid))
    return pr.TileCollisionIndex(root, (layer,), tile_px=TILE_PX, world_w=WORLD_W, world_h=WORLD_H)


class MoveActorSolidTests(unittest.TestCase):
    def test_falls_and_lands_on_solid_tile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            grid = _empty_grid()
            # gy=10 cubre y en escena [16,31]; gx=2 cubre x en [32,47].
            grid[10][2] = 0
            tiles = [{"collision": "solid"}]
            idx = _build_index(root, grid, tiles)

            a = _actor(40, 100)
            self.assertFalse(a.grounded)
            dx, dy = pr.move_actor(a, 0, -200, idx, WORLD_W, WORLD_H)
            self.assertTrue(a.grounded)
            self.assertEqual(a.y, 32)
            self.assertEqual(dy, 32 - 100)

    def test_horizontal_blocked_by_solid_wall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            grid = _empty_grid()
            # gy=11 (fila inferior, y en [0,15]); gx=5 cubre x en [80,95].
            grid[11][5] = 0
            tiles = [{"collision": "solid"}]
            idx = _build_index(root, grid, tiles)

            a = _actor(60, 0, col=(0, 0, 7, 15))
            dx, dy = pr.move_actor(a, 100, 0, idx, WORLD_W, WORLD_H)
            # el borde derecho (x+7) no debe pasar de 79 (justo antes del muro en x=80)
            self.assertEqual(a.x + a.col_x1, 79)
            self.assertLess(dx, 100)


class MoveActorNoneTests(unittest.TestCase):
    def test_none_tile_does_not_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            grid = _empty_grid()
            grid[10][2] = 0
            tiles = [{"collision": "none"}]
            idx = _build_index(root, grid, tiles)

            a = _actor(40, 100)
            pr.move_actor(a, 0, -200, idx, WORLD_W, WORLD_H)
            # sin tile solido debajo, cae hasta el piso del mundo (clamp), no se queda en 32
            self.assertEqual(a.y, -a.col_y0)
            self.assertTrue(a.grounded)


class MoveActorOnewayTests(unittest.TestCase):
    def _tiles_oneway_up(self) -> list[dict]:
        return [{"collision": "solid", "oneway": True, "oneway_direction": "up"}]

    def test_oneway_up_blocks_falling_actor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            grid = _empty_grid()
            grid[10][2] = 0
            idx = _build_index(root, grid, self._tiles_oneway_up())

            a = _actor(40, 100)
            pr.move_actor(a, 0, -200, idx, WORLD_W, WORLD_H)
            self.assertTrue(a.grounded)
            self.assertEqual(a.y, 32)

    def test_oneway_up_lets_actor_pass_moving_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            grid = _empty_grid()
            grid[10][2] = 0
            idx = _build_index(root, grid, self._tiles_oneway_up())

            # Empieza debajo de la plataforma (box y en [8,15], plataforma en [16,31]).
            a = _actor(40, 8)
            dx, dy = pr.move_actor(a, 0, 200, idx, WORLD_W, WORLD_H)
            self.assertGreater(dy, 100)
            self.assertGreater(a.y, 31)


class MoveActorShapeTests(unittest.TestCase):
    def test_aabb_subtile_only_blocks_within_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            grid = _empty_grid()
            grid[10][2] = 0
            # Solo la mitad inferior del tile (local y 0..7) es solida -- si el tile
            # entero fuera solido, el actor quedaria en y=32 (igual que el test de
            # tile solido completo); aca debe caer mas, hasta y=24, demostrando que
            # solo el sub-aabb bloquea.
            tiles = [
                {
                    "collision": {
                        "mode": "aabb",
                        "x0": 0,
                        "y0": 0,
                        "x1": 15,
                        "y1": 7,
                    }
                }
            ]
            idx = _build_index(root, grid, tiles)

            a = _actor(40, 100)
            pr.move_actor(a, 0, -200, idx, WORLD_W, WORLD_H)
            self.assertTrue(a.grounded)
            self.assertEqual(a.y, 24)

    def test_aabb_subtile_triangle_uses_point_bbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            grid = _empty_grid()
            grid[10][2] = 0
            tiles = [
                {
                    "collision": {
                        "mode": "triangle",
                        "points": [[0, 4], [15, 4], [15, 15]],
                    }
                }
            ]
            idx = _build_index(root, grid, tiles)

            a = _actor(40, 100)
            pr.move_actor(a, 0, -200, idx, WORLD_W, WORLD_H)
            self.assertTrue(a.grounded)
            # bbox de los puntos: y local en [4,15] -> tope en 16+15=31... el actor
            # queda sobre y=32? no: el bbox top local es 15 -> tope absoluto 16+15=31,
            # el actor se detiene en 31+1=32.
            self.assertEqual(a.y, 32)


class ClampActorPosTests(unittest.TestCase):
    def test_clamps_to_world_floor_and_marks_grounded(self) -> None:
        a = _actor(10, -50)
        pr.clamp_actor_pos(a, WORLD_W, WORLD_H)
        self.assertEqual(a.y, 0)
        self.assertTrue(a.grounded)

    def test_clamps_to_world_ceiling_without_grounding(self) -> None:
        a = _actor(10, 10_000)
        pr.clamp_actor_pos(a, WORLD_W, WORLD_H)
        self.assertEqual(a.y, (WORLD_H - 1) - a.col_y1)
        self.assertFalse(a.grounded)


class TruncDivTests(unittest.TestCase):
    def test_matches_c_style_truncation_for_negatives(self) -> None:
        self.assertEqual(pr._trunc_div(-1, 16), 0)
        self.assertEqual(pr._trunc_div(-16, 16), -1)
        self.assertEqual(pr._trunc_div(-17, 16), -1)
        self.assertEqual(pr._trunc_div(17, 16), 1)


if __name__ == "__main__":
    unittest.main()
