"""Pruebas de barras de progreso + pips en capas GUI (spec/gui-layer-v0.md).

Model: parse/serialize round-trip, clamping, rangos degenerados descartados.
Editor: PyQt6 smoke (add/remove, save, preview no crashea con sprite ausente).
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from turtlestudio.guilayers import (
    MAX_GUI_BAR_RANGES,
    MAX_GUI_LAYER_PIP_BARS,
    MAX_GUI_LAYER_PROGRESS_BARS,
    MAX_PIP_COUNT,
    GuiBarRange,
    GuiLayer,
    GuiPipBar,
    GuiProgressBar,
    collect_gui_layer_sprite_ids,
    gui_bar_range_to_json,
    gui_layer_to_json,
    gui_pip_bar_to_json,
    gui_progress_bar_to_json,
    parse_gui_bar_range,
    parse_gui_layer,
    parse_gui_pip_bar,
    parse_gui_progress_bar,
    read_gui_layer_file,
    write_gui_layer_file,
)


class GuiBarRangeParseTests(unittest.TestCase):
    def test_alt_color_out_of_bounds_falls_back_to_none(self) -> None:
        r = parse_gui_bar_range({"min_pct": 0, "max_pct": 50, "alt_color_index": 55})
        assert r is not None
        self.assertEqual(r.alt_color_index, -1)

    def test_min_ge_max_returns_none(self) -> None:
        self.assertIsNone(parse_gui_bar_range({"min_pct": 50, "max_pct": 50}))
        self.assertIsNone(parse_gui_bar_range({"min_pct": 80, "max_pct": 20}))

    def test_alt_sprite_stem_validated(self) -> None:
        # `1bad` no arranca con letra: se descarta la cadena, se preserva el rango.
        r = parse_gui_bar_range({"min_pct": 0, "max_pct": 100, "alt_sprite_id": "1bad"})
        assert r is not None
        self.assertEqual(r.alt_sprite_id, "")


class GuiProgressBarParseTests(unittest.TestCase):
    def test_full_round_trip(self) -> None:
        pb = GuiProgressBar(
            id="hp",
            x=1,
            y=2,
            w=40,
            h=6,
            direction="right_to_left",
            fill_mode="sprite",
            fill_sprite_id="hp_tex",
            fill_color_index=11,
            bg_color_index=31,
            border_color_index=0,
            value_num=7,
            value_den=10,
            ranges=(
                GuiBarRange(0, 25, alt_color_index=8),
                GuiBarRange(25, 50, alt_sprite_id="hp_warn"),
            ),
        )
        d = gui_progress_bar_to_json(pb)
        self.assertEqual(parse_gui_progress_bar(d), pb)

    def test_invalid_id_returns_none(self) -> None:
        self.assertIsNone(parse_gui_progress_bar({"id": "1bad"}))
        self.assertIsNone(parse_gui_progress_bar({}))

    def test_unknown_direction_defaults_to_left_to_right(self) -> None:
        pb = parse_gui_progress_bar({"id": "hp", "direction": "diagonal"})
        assert pb is not None
        self.assertEqual(pb.direction, "left_to_right")

    def test_value_den_clamped_positive(self) -> None:
        pb = parse_gui_progress_bar({"id": "hp", "value_den": 0})
        assert pb is not None
        self.assertGreaterEqual(pb.value_den, 1)

    def test_degenerate_ranges_dropped(self) -> None:
        pb = parse_gui_progress_bar({
            "id": "hp",
            "ranges": [
                {"min_pct": 50, "max_pct": 50},  # degenerado
                {"min_pct": 0, "max_pct": 20, "alt_color_index": 8},
                {"min_pct": 20, "max_pct": 100},
            ],
        })
        assert pb is not None
        self.assertEqual(len(pb.ranges), 2)
        self.assertEqual(pb.ranges[0].min_pct, 0)

    def test_ranges_capped(self) -> None:
        pb = parse_gui_progress_bar({
            "id": "hp",
            "ranges": [{"min_pct": i, "max_pct": i + 1} for i in range(MAX_GUI_BAR_RANGES + 2)],
        })
        assert pb is not None
        self.assertLessEqual(len(pb.ranges), MAX_GUI_BAR_RANGES)


class GuiPipBarParseTests(unittest.TestCase):
    def test_full_round_trip(self) -> None:
        qb = GuiPipBar(
            id="lives",
            x=6,
            y=16,
            sprite_full_id="heart",
            direction="vertical",
            gap_px=2,
            value=3,
            max_value=5,
            ranges=(GuiBarRange(0, 30, alt_sprite_id="heart_low"),),
        )
        d = gui_pip_bar_to_json(qb)
        self.assertEqual(parse_gui_pip_bar(d), qb)

    def test_pip_without_sprite_returns_none(self) -> None:
        self.assertIsNone(parse_gui_pip_bar({"id": "lives"}))
        self.assertIsNone(parse_gui_pip_bar({"id": "lives", "sprite_full_id": "1bad"}))

    def test_value_clamped_to_max(self) -> None:
        qb = parse_gui_pip_bar({"id": "lives", "sprite_full_id": "heart", "max_value": 3, "value": 999})
        assert qb is not None
        self.assertEqual(qb.value, qb.max_value)

    def test_max_value_capped_to_pip_ceiling(self) -> None:
        qb = parse_gui_pip_bar({"id": "lives", "sprite_full_id": "heart", "max_value": 999})
        assert qb is not None
        self.assertEqual(qb.max_value, MAX_PIP_COUNT)

    def test_unknown_direction_defaults_to_horizontal(self) -> None:
        qb = parse_gui_pip_bar({"id": "lives", "sprite_full_id": "heart", "direction": "spiral"})
        assert qb is not None
        self.assertEqual(qb.direction, "horizontal")


class CollectSpriteIdsTests(unittest.TestCase):
    def test_collects_progress_sprite_only_when_fill_mode_is_sprite(self) -> None:
        ly = GuiLayer(id="l", progress_bars=(
            GuiProgressBar(id="a", fill_mode="color", fill_sprite_id="unused"),
            GuiProgressBar(id="b", fill_mode="sprite", fill_sprite_id="hp_tex"),
        ))
        self.assertEqual(collect_gui_layer_sprite_ids(ly), {"hp_tex"})

    def test_collects_pip_sprite(self) -> None:
        ly = GuiLayer(id="l", pip_bars=(
            GuiPipBar(id="lives", sprite_full_id="heart"),
        ))
        self.assertEqual(collect_gui_layer_sprite_ids(ly), {"heart"})

    def test_collects_range_alt_sprites_for_both_bar_kinds(self) -> None:
        ly = GuiLayer(id="l",
            progress_bars=(GuiProgressBar(id="a", fill_mode="sprite", fill_sprite_id="base",
                                          ranges=(GuiBarRange(0, 25, alt_sprite_id="crit"),)),),
            pip_bars=(GuiPipBar(id="p", sprite_full_id="heart",
                                ranges=(GuiBarRange(0, 25, alt_sprite_id="heart_low"),)),),
        )
        self.assertEqual(collect_gui_layer_sprite_ids(ly), {"base", "crit", "heart", "heart_low"})


class BuildExportsGuiLayerSpritesTests(unittest.TestCase):
    """El bug del usuario: un pip_bar referencia un sprite que no lo referencia ningun objeto,
    y el exportador no lo mete en el paquete SD. El sprite tiene que aparecer en el bundle
    igual que los sprites de objetos."""

    def test_pip_bar_sprite_included_in_export(self) -> None:
        from turtlestudio.build import collect_studio_bundle_files
        from turtlestudio.sprites import write_solid_sprite_json

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "objects" / "Objects").mkdir(parents=True)
            (root / "objects" / "Sprites").mkdir(parents=True)
            (root / "palettes").mkdir()
            (root / "guilayers").mkdir()
            (root / "scripts" / "main.lua").write_text("cls(0)\n", encoding="utf-8")
            (root / "palettes" / "pal.txt").write_text(
                "\n".join([f"#{i:02x}{i:02x}{i:02x}" for i in range(32)]) + "\n",
                encoding="utf-8",
            )
            # Sprite referenciado SOLO por el pip bar (ni objeto ni escena lo tocan).
            write_solid_sprite_json(root, "shell", palette_rel="palettes/pal.txt",
                                    blocks_w=1, blocks_h=1, palette_index=5)
            layer = GuiLayer(
                id="hud",
                pip_bars=(GuiPipBar(id="pips", sprite_full_id="shell", value=1, max_value=3),),
            )
            write_gui_layer_file(root, layer)

            pkg = collect_studio_bundle_files(
                root,
                scenes=[],
                active_scene="",
                transparent_index=31,
                entry_relpath="scripts/main.lua",
            )
            sidecar_paths = [rel for rel, _ in pkg.sidecar]
            # El sprite ligero (1x1 celda) puede quedar inline en el bundle o externalizarse;
            # lo que importa es que aparezca en el bundle bajo "sprites".
            bundle_text = next(
                (data for rel, data in pkg.sidecar if rel == "studio/project_bundle.json"),
                None,
            )
            assert bundle_text is not None
            self.assertIn('"shell"', bundle_text, f"sidecar rels: {sidecar_paths}")


class GuiLayerBarsRoundTripTests(unittest.TestCase):
    def test_layer_serializes_and_reparses_bars_in_place(self) -> None:
        ly = GuiLayer(
            id="hud",
            progress_bars=(
                GuiProgressBar(id="hp", x=1, y=1, w=40, h=6, value_num=8, value_den=10),
                GuiProgressBar(id="mp", x=1, y=8, w=40, h=6, value_num=2, value_den=5),
            ),
            pip_bars=(
                GuiPipBar(id="lives", x=1, y=16, sprite_full_id="heart", value=3, max_value=5),
            ),
        )
        d = gui_layer_to_json(ly)
        reparsed = parse_gui_layer(d)
        assert reparsed is not None
        self.assertEqual(reparsed.progress_bars, ly.progress_bars)
        self.assertEqual(reparsed.pip_bars, ly.pip_bars)

    def test_extra_bars_dropped_at_layer_parse(self) -> None:
        raw = {
            "id": "hud",
            "progress_bars": [
                {"id": f"bar{i}", "x": 0, "y": 0, "w": 4, "h": 4}
                for i in range(MAX_GUI_LAYER_PROGRESS_BARS + 3)
            ],
            "pip_bars": [
                {"id": f"pip{i}", "sprite_full_id": "heart"}
                for i in range(MAX_GUI_LAYER_PIP_BARS + 3)
            ],
        }
        ly = parse_gui_layer(raw)
        assert ly is not None
        self.assertLessEqual(len(ly.progress_bars), MAX_GUI_LAYER_PROGRESS_BARS)
        self.assertLessEqual(len(ly.pip_bars), MAX_GUI_LAYER_PIP_BARS)

    def test_disk_round_trip_preserves_bars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ly = GuiLayer(
                id="hud",
                progress_bars=(
                    GuiProgressBar(id="hp", w=40, h=6, value_num=4, value_den=10,
                                   ranges=(GuiBarRange(0, 30, alt_color_index=8),)),
                ),
                pip_bars=(GuiPipBar(id="lives", sprite_full_id="heart", value=1, max_value=3),),
            )
            write_gui_layer_file(root, ly)
            reread = read_gui_layer_file(root, "hud")
            self.assertEqual(reread.progress_bars, ly.progress_bars)
            self.assertEqual(reread.pip_bars, ly.pip_bars)


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


@unittest.skipUnless(_has_pyqt6(), "requires PyQt6 for the editor widget")
class GuiBarsEditorSmokeTests(unittest.TestCase):
    def test_add_progress_bar_updates_model_and_table(self) -> None:
        _ensure_qapp()
        from turtlestudio.gui_layer_editor import GuiLayerEditorWidget

        w = GuiLayerEditorWidget(Path("."))
        w.layer_id = "hud"
        self.assertEqual(len(w.progress_bars), 0)
        w._action_add_progress_bar()
        self.assertEqual(len(w.progress_bars), 1)
        self.assertEqual(w.progress_table.rowCount(), 1)
        # Auto-generated id is unique.
        w._action_add_progress_bar()
        ids = [b.id for b in w.progress_bars]
        self.assertEqual(len(ids), len(set(ids)))
        w.progress_table.setCurrentCell(0, 0)
        w._action_remove_progress_bar()
        self.assertEqual(len(w.progress_bars), 1)

    def test_add_pip_bar_requires_sprite_in_project(self) -> None:
        _ensure_qapp()
        from unittest.mock import patch

        from turtlestudio.gui_layer_editor import GuiLayerEditorWidget

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            w = GuiLayerEditorWidget(Path("."))
            w.project_root = root
            w.layer_id = "hud"
            # Sin sprites: se abre un QMessageBox y NO se agrega el bar.
            with patch("turtlestudio.gui_layer_editor.QMessageBox.warning"):
                w._action_add_pip_bar()
            self.assertEqual(len(w.pip_bars), 0)

    def test_current_layer_includes_bars(self) -> None:
        _ensure_qapp()
        from turtlestudio.gui_layer_editor import GuiLayerEditorWidget

        w = GuiLayerEditorWidget(Path("."))
        w.layer_id = "hud"
        w.progress_bars = [GuiProgressBar(id="hp", w=10, h=4, value_num=3, value_den=10)]
        w.pip_bars = [GuiPipBar(id="lives", sprite_full_id="heart", value=2, max_value=3)]
        ly = w._current_layer()
        self.assertEqual(len(ly.progress_bars), 1)
        self.assertEqual(len(ly.pip_bars), 1)
        self.assertEqual(ly.progress_bars[0].value_num, 3)

    def test_save_round_trip_with_bars(self) -> None:
        _ensure_qapp()
        from turtlestudio.gui_layer_editor import GuiLayerEditorWidget

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            initial = GuiLayer(
                id="hud",
                progress_bars=(GuiProgressBar(id="hp", w=10, h=4, value_num=3, value_den=10),),
            )
            write_gui_layer_file(root, initial)
            w = GuiLayerEditorWidget(Path("."))
            w.set_project_root(root)
            self.assertEqual(len(w.progress_bars), 1)
            # Mutate a value and save.
            w.progress_bars[0] = GuiProgressBar(id="hp", w=10, h=4, value_num=7, value_den=10)
            w._dirty = True  # simular edicion via UI
            w._action_save()
            reread = read_gui_layer_file(root, "hud")
            self.assertEqual(reread.progress_bars[0].value_num, 7)

    def test_preview_pixmap_keeps_framebuffer_size_after_adding_bar(self) -> None:
        """Regresion: al agregar una progress bar, el pixmap del preview quedaba con las
        dimensiones del fill de la barra en vez del framebuffer (fw/fh se shadowearon)."""
        _ensure_qapp()
        from turtlestudio.gui_layer_editor import PREVIEW_ZOOM, GuiLayerEditorWidget
        from turtlestudio.guilayers import SCENE_PIXEL_H, SCENE_PIXEL_W

        w = GuiLayerEditorWidget(Path("."))
        w.layer_id = "hud"
        w._refresh_preview()
        pm_before = w.preview.pixmap()
        self.assertEqual(pm_before.width(), SCENE_PIXEL_W * PREVIEW_ZOOM)
        self.assertEqual(pm_before.height(), SCENE_PIXEL_H * PREVIEW_ZOOM)
        w._action_add_progress_bar()
        pm_after = w.preview.pixmap()
        self.assertEqual(pm_after.width(), SCENE_PIXEL_W * PREVIEW_ZOOM)
        self.assertEqual(pm_after.height(), SCENE_PIXEL_H * PREVIEW_ZOOM)

    def test_preview_does_not_crash_with_bars_and_missing_sprite(self) -> None:
        _ensure_qapp()
        from turtlestudio.gui_layer_editor import GuiLayerEditorWidget

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "guilayers").mkdir()
            w = GuiLayerEditorWidget(Path("."))
            w.project_root = root
            w.layer_id = "hud"
            w.spin_w.setValue(50)
            w.spin_h.setValue(24)
            w.progress_bars = [
                GuiProgressBar(id="hp", w=40, h=6, fill_mode="sprite", fill_sprite_id="ghost",
                               value_num=6, value_den=10, border_color_index=0),
            ]
            w.pip_bars = [
                GuiPipBar(id="pips", sprite_full_id="missing", value=2, max_value=3),
            ]
            # Debe pintar el preview con el fallback gris, no crashear.
            w._refresh_preview()
            self.assertIsNotNone(w.preview.pixmap())


if __name__ == "__main__":
    unittest.main()
