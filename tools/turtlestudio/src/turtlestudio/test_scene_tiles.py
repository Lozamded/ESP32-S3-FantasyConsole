"""Pruebas del cache de render de tiles por bloque (perf editor con world_steps
grandes; ver spec/scene-v0.md y el plan de streaming/chunked world buffer)."""

from __future__ import annotations

import unittest
from pathlib import Path

from turtlestudio.scene_tiles import (
    TILE_CACHE_BLOCK_CELLS,
    SceneTileLayer,
    paint_tile_layers_on_rgba,
    paint_tile_layers_on_rgba_blocked,
    tile_block_key,
)

_DEMO_PROJECT_ROOT = (
    Path(__file__).resolve().parents[2] / "exampleprojects" / "demo_platformer"
)
_TILESET_STEM = "greenfield"
_TILE_PX = 16
_RGBS = [(0.1, 0.1, 0.1)] * 32


def _make_grid_layer(cols: int, rows: int, *, fill: int = 0) -> SceneTileLayer:
    return SceneTileLayer(
        enabled=True,
        tileset=_TILESET_STEM,
        cells=tuple(tuple(fill for _ in range(cols)) for _ in range(rows)),
    )


class TileBlockKeyTests(unittest.TestCase):
    def test_key_math(self) -> None:
        self.assertEqual(tile_block_key(0, 0), (0, 0))
        self.assertEqual(tile_block_key(TILE_CACHE_BLOCK_CELLS - 1, 0), (0, 0))
        self.assertEqual(tile_block_key(TILE_CACHE_BLOCK_CELLS, 0), (1, 0))
        self.assertEqual(tile_block_key(0, TILE_CACHE_BLOCK_CELLS * 2), (0, 2))


class PaintTileLayersBlockedTests(unittest.TestCase):
    def setUp(self) -> None:
        if not _DEMO_PROJECT_ROOT.is_dir():
            self.skipTest("exampleprojects/demo_platformer no disponible")
        # Mundo mas grande que un solo bloque en ambos ejes (ceil(40/16) = 3 bloques
        # por eje = 9 bloques totales) para ejercer la particion, no solo el caso trivial.
        self.cols, self.rows = 40, 40
        self.fw = self.cols * _TILE_PX
        self.fh = self.rows * _TILE_PX
        self.layers = (_make_grid_layer(self.cols, self.rows),)

    def _direct_render(self) -> list[float]:
        rgba = [0.0] * (self.fw * self.fh * 4)
        paint_tile_layers_on_rgba(
            rgba, self.fw, self.fh, self.layers, _DEMO_PROJECT_ROOT, _RGBS, tile_px=_TILE_PX
        )
        return rgba

    def test_no_cache_matches_direct_render(self) -> None:
        """block_cache=None debe delegar integramente en paint_tile_layers_on_rgba."""
        expected = self._direct_render()
        actual = [0.0] * (self.fw * self.fh * 4)
        paint_tile_layers_on_rgba_blocked(
            actual, self.fw, self.fh, self.layers, _DEMO_PROJECT_ROOT, _RGBS, tile_px=_TILE_PX
        )
        self.assertEqual(actual, expected)

    def test_blocked_render_matches_direct_render(self) -> None:
        """Con cache (vacio -> se llena), el resultado debe ser identico al render directo."""
        expected = self._direct_render()
        actual = [0.0] * (self.fw * self.fh * 4)
        cache: dict = {}
        paint_tile_layers_on_rgba_blocked(
            actual, self.fw, self.fh, self.layers, _DEMO_PROJECT_ROOT, _RGBS,
            tile_px=_TILE_PX, block_cache=cache,
        )
        self.assertEqual(actual, expected)
        # 3x3 bloques de 16 celdas para una rejilla de 40x40.
        self.assertEqual(len(cache), 9)

    def test_editing_one_cell_only_invalidates_its_block(self) -> None:
        """Tras invalidar solo el bloque de una celda editada, los demas bloques
        cacheados deben reutilizarse tal cual (misma identidad de objeto), y el
        resultado final debe coincidir con un render directo del estado nuevo."""
        cache: dict = {}
        rgba = [0.0] * (self.fw * self.fh * 4)
        paint_tile_layers_on_rgba_blocked(
            rgba, self.fw, self.fh, self.layers, _DEMO_PROJECT_ROOT, _RGBS,
            tile_px=_TILE_PX, block_cache=cache,
        )
        untouched_key = (2, 2)  # bloque lejos de la celda que vamos a editar
        untouched_entry_before = cache[untouched_key]

        # "Editar" la celda (0, 0): cambiar a transparente (indice 31) y re-renderizar
        # solo tras invalidar su bloque -- igual que _on_canvas_cell_clicked.
        gx, gy = 0, 0
        edited_cells = list(list(row) for row in self.layers[0].cells)
        edited_cells[gy][gx] = 31
        edited_layers = (
            SceneTileLayer(enabled=True, tileset=_TILESET_STEM, cells=tuple(tuple(r) for r in edited_cells)),
        )
        cache.pop(tile_block_key(gx, gy), None)

        rgba2 = [0.0] * (self.fw * self.fh * 4)
        paint_tile_layers_on_rgba_blocked(
            rgba2, self.fw, self.fh, edited_layers, _DEMO_PROJECT_ROOT, _RGBS,
            tile_px=_TILE_PX, block_cache=cache,
        )

        # El bloque lejano no debio recalcularse: mismo objeto en cache.
        self.assertIs(cache[untouched_key], untouched_entry_before)

        # El resultado debe coincidir con un render directo del estado editado.
        expected = [0.0] * (self.fw * self.fh * 4)
        paint_tile_layers_on_rgba(
            expected, self.fw, self.fh, edited_layers, _DEMO_PROJECT_ROOT, _RGBS, tile_px=_TILE_PX
        )
        self.assertEqual(rgba2, expected)


if __name__ == "__main__":
    unittest.main()
