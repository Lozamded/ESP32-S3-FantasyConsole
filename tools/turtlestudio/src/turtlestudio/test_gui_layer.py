"""Pruebas de capas GUI apilables (spec/gui-layer-v0.md)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from turtlestudio.guilayers import (
    GUI_LAYER_TEXT_MAX_CHARS,
    MAX_GUI_LAYER_LABELS,
    MAX_GUI_LAYER_RECTS,
    SCENE_PIXEL_H,
    SCENE_PIXEL_W,
    GuiLayer,
    GuiRect,
    GuiTextLabel,
    gui_layer_to_json,
    is_valid_gui_layer_id,
    list_gui_layer_stems,
    parse_gui_layer,
    read_gui_layer_file,
    write_gui_layer_file,
)


class GuiLayerIdValidationTests(unittest.TestCase):
    def test_valid_stems(self) -> None:
        for s in ("pause", "pause_menu", "menu-1", "a", "A9"):
            self.assertTrue(is_valid_gui_layer_id(s), s)

    def test_invalid_stems(self) -> None:
        for s in ("", "1menu", "-menu", "_menu", "menu with space", "menu/foo",
                  "x" * 33):
            self.assertFalse(is_valid_gui_layer_id(s), s)


class GuiLayerParseTests(unittest.TestCase):
    def test_missing_id_rejects(self) -> None:
        self.assertIsNone(parse_gui_layer({}))
        self.assertIsNone(parse_gui_layer({"id": "1bad"}))

    def test_defaults_when_only_id(self) -> None:
        ly = parse_gui_layer({"id": "menu"})
        assert ly is not None
        self.assertEqual((ly.x, ly.y, ly.w, ly.h), (0, 0, SCENE_PIXEL_W, SCENE_PIXEL_H))
        self.assertEqual(ly.bg_color_index, 0)
        self.assertFalse(ly.transparent_bg)
        self.assertFalse(ly.pauses_scene)
        self.assertFalse(ly.captures_input)
        self.assertEqual(ly.z, 0)
        self.assertEqual(ly.rects, ())
        self.assertEqual(ly.text_labels, ())

    def test_layer_rect_clamped_to_framebuffer(self) -> None:
        ly = parse_gui_layer({"id": "menu", "x": 100, "y": 100, "w": 999, "h": 999})
        assert ly is not None
        self.assertEqual(ly.x + ly.w, SCENE_PIXEL_W)
        self.assertEqual(ly.y + ly.h, SCENE_PIXEL_H)

    def test_rects_clamped_and_capped(self) -> None:
        rects = [{"x": 0, "y": 0, "w": 4, "h": 4, "color_index": i} for i in range(30)]
        ly = parse_gui_layer({"id": "menu", "rects": rects})
        assert ly is not None
        self.assertLessEqual(len(ly.rects), MAX_GUI_LAYER_RECTS)

    def test_labels_reject_missing_id_or_font(self) -> None:
        labels = [
            {"id": "", "font": "f"},
            {"id": "title", "font": ""},
            {"id": "title", "font": "f"},  # solo esta pasa
        ]
        ly = parse_gui_layer({"id": "menu", "text_labels": labels})
        assert ly is not None
        self.assertEqual(len(ly.text_labels), 1)
        self.assertEqual(ly.text_labels[0].id, "title")

    def test_label_text_truncated(self) -> None:
        long = "a" * (GUI_LAYER_TEXT_MAX_CHARS + 20)
        ly = parse_gui_layer(
            {
                "id": "menu",
                "text_labels": [{"id": "big", "font": "f", "text": long}],
            }
        )
        assert ly is not None
        self.assertEqual(len(ly.text_labels[0].text), GUI_LAYER_TEXT_MAX_CHARS)

    def test_label_tint_clamped(self) -> None:
        ly = parse_gui_layer(
            {
                "id": "menu",
                "text_labels": [
                    {"id": "a", "font": "f", "color_index": 31},  # 31 -> 30
                    {"id": "b", "font": "f", "color_index": -5},  # -5 -> -1
                ],
            }
        )
        assert ly is not None
        self.assertEqual(ly.text_labels[0].color_index, 30)
        self.assertEqual(ly.text_labels[1].color_index, -1)

    def test_labels_capped_at_max(self) -> None:
        labels = [{"id": f"t{i}", "font": "f"} for i in range(30)]
        ly = parse_gui_layer({"id": "menu", "text_labels": labels})
        assert ly is not None
        self.assertLessEqual(len(ly.text_labels), MAX_GUI_LAYER_LABELS)


class GuiLayerRoundtripTests(unittest.TestCase):
    def test_full_layer_roundtrips(self) -> None:
        ly = GuiLayer(
            id="pause",
            x=0, y=0, w=SCENE_PIXEL_W, h=SCENE_PIXEL_H,
            bg_color_index=1,
            transparent_bg=False,
            pauses_scene=True,
            captures_input=True,
            z=100,
            rects=(GuiRect(x=20, y=40, w=124, h=44, color_index=5),),
            text_labels=(
                GuiTextLabel(id="title", font="font_main", text="PAUSED",
                             x=40, y=50, color_index=7),
                GuiTextLabel(id="hint", font="font_main", text="A=RESUME",
                             x=30, y=70),
            ),
        )
        js = gui_layer_to_json(ly)
        ly2 = parse_gui_layer(js)
        assert ly2 is not None
        self.assertEqual(ly2, ly)

    def test_tint_absent_when_negative(self) -> None:
        lbl = GuiTextLabel(id="x", font="f", text="hi")
        ly = GuiLayer(id="menu", text_labels=(lbl,))
        js = gui_layer_to_json(ly)
        self.assertNotIn("color_index", js["text_labels"][0])


class GuiLayerDiscoveryTests(unittest.TestCase):
    def test_write_read_roundtrip_via_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ly = GuiLayer(
                id="pause",
                bg_color_index=3,
                pauses_scene=True,
                text_labels=(
                    GuiTextLabel(id="title", font="font_main", text="PAUSED"),
                ),
            )
            write_gui_layer_file(root, ly)
            self.assertEqual(list_gui_layer_stems(root), ["pause"])
            reread = read_gui_layer_file(root, "pause")
            self.assertEqual(reread, ly)

    def test_uses_stem_as_fallback_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "guilayers").mkdir()
            (root / "guilayers" / "menu_a.json").write_text(
                json.dumps({"x": 0, "y": 0, "w": 100, "h": 60}),
                encoding="utf-8",
            )
            ly = read_gui_layer_file(root, "menu_a")
            self.assertEqual(ly.id, "menu_a")

    def test_invalid_stem_ignored_by_listing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "guilayers").mkdir()
            (root / "guilayers" / "1bad.json").write_text('{"id":"x"}', encoding="utf-8")
            (root / "guilayers" / "good.json").write_text('{"id":"good"}', encoding="utf-8")
            self.assertEqual(list_gui_layer_stems(root), ["good"])


if __name__ == "__main__":
    unittest.main()
