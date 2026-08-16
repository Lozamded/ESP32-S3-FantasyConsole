"""Pruebas de play_lua_bridge.py contra exampleprojects/demo1: Lua 5.4 real via lupa
(compilado contra firmware/libraries/lua54, ver README.md seccion "Play"), corriendo
scripts/character.lua sobre la escena "intro" durante N ticks sinteticos.

Se salta si lupa no esta instalado (build opcional, `pip install -e ".[play]"` +
el paso de compilacion contra Lua 5.4 -- el wheel de PyPI trae 5.5 y no sirve)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from turtlestudio import play_runtime as pr
from turtlestudio.scene_editor import _normalize_row
from turtlestudio.tiles import parse_tile_px_from_manifest

try:
    from turtlestudio import play_lua_bridge as plb
except ImportError:
    plb = None  # type: ignore[assignment]

DEMO1_ROOT = Path(__file__).resolve().parents[2] / "exampleprojects" / "demo1"


def _lupa_ready() -> bool:
    return plb is not None and plb.lupa_available()


@unittest.skipUnless(_lupa_ready(), "lupa (Lua 5.4 build) no disponible")
class PlayLuaBridgeDemo1Tests(unittest.TestCase):
    def _begin_intro_session(self) -> tuple[pr.PlaySession, dict]:
        data = json.loads((DEMO1_ROOT / "turtlestudio.json").read_text(encoding="utf-8"))
        tile_px = parse_tile_px_from_manifest(data)
        scenes = {s["id"]: s for s in data["scenes"]}
        row = _normalize_row(scenes["intro"], tile_px)
        sess = pr.PlaySession(DEMO1_ROOT)
        sess.begin(
            row,
            tile_px,
            project_target_fps=data.get("target_fps", 30),
            project_anim_fps=data.get("default_anim_fps", 8),
        )
        return sess, data

    def test_binds_character_script(self) -> None:
        sess, _data = self._begin_intro_session()
        run_actor_scripts, bridge = plb.make_run_actor_scripts(sess)
        self.assertIn("character", bridge._update_refs)
        self.assertEqual(sess.log, [])

    def test_gravity_settles_character_on_ground(self) -> None:
        sess, _data = self._begin_intro_session()
        run_actor_scripts, _bridge = plb.make_run_actor_scripts(sess)
        a = sess.actors[0]
        for _ in range(30):
            sess.tick(1.0 / 30.0, run_actor_scripts)
        self.assertTrue(a.grounded)
        self.assertEqual(sess.log, [])

    def test_holding_right_walks_and_flips_back_holding_left(self) -> None:
        sess, _data = self._begin_intro_session()
        run_actor_scripts, _bridge = plb.make_run_actor_scripts(sess)
        a = sess.actors[0]
        for _ in range(30):
            sess.tick(1.0 / 30.0, run_actor_scripts)
        start_x = a.x

        sess.input.set_held_indices({pr.BTN_RIGHT})
        for _ in range(30):
            sess.tick(1.0 / 30.0, run_actor_scripts)
        self.assertGreater(a.x, start_x)
        self.assertFalse(a.flip_h)
        self.assertEqual(a.anim_name, "walk")

        sess.input.set_held_indices({pr.BTN_LEFT})
        for _ in range(30):
            sess.tick(1.0 / 30.0, run_actor_scripts)
        self.assertTrue(a.flip_h)
        self.assertEqual(sess.log, [])

    def test_jump_leaves_ground_then_lands_again(self) -> None:
        sess, _data = self._begin_intro_session()
        run_actor_scripts, _bridge = plb.make_run_actor_scripts(sess)
        a = sess.actors[0]
        for _ in range(30):
            sess.tick(1.0 / 30.0, run_actor_scripts)
        self.assertTrue(a.grounded)

        sess.input.set_held_indices({pr.BTN_A})
        sess.tick(1.0 / 30.0, run_actor_scripts)
        sess.input.set_held_indices(set())
        self.assertFalse(a.grounded)

        for _ in range(60):
            sess.tick(1.0 / 30.0, run_actor_scripts)
        self.assertTrue(a.grounded)
        self.assertEqual(sess.log, [])

    def test_entry_script_runs_once_without_error(self) -> None:
        sess, data = self._begin_intro_session()
        entry_bridge = plb.EntryLuaBridge(sess)
        entry_bridge.run(data.get("entry", "scripts/global.lua"))
        self.assertEqual(sess.log, ["demo1 global"])


if __name__ == "__main__":
    unittest.main()
