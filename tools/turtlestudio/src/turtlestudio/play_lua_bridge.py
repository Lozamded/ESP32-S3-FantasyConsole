"""Ejecucion real de Lua 5.4 para PlaySession, via lupa compilado contra el Lua 5.4.6
vendorizado en firmware/libraries/lua54 (ver tools/turtlestudio/README.md, seccion
"Play" -- el wheel de PyPI trae Lua 5.5 y NO sirve para esto).

Unico modulo de play_runtime/play_lua_bridge/play_widget que importa lupa: play_widget.py
atrapa ImportError al construirlo y desactiva el tab en vez de romper el arranque de la
app; play_runtime.py no depende de esto y es testeable sin lupa instalado. (lua_bytecode.py
tambien importa lupa, con el mismo criterio de guardia, para compilar bytecode en `build`
-- ver ese modulo; no comparte runtime con este, ver el comentario ahi del porque.)

Reproduce fielmente firmware/TurtleReader/turtle_actor_lua.cpp: UN solo lua_State
compartido por todos los actores con script de la escena (no un runtime por actor) --
cada script se ejecuta una vez al bind (turtle_actor_lua_bind_actors_from_scene /
load_script_update_ref), capturando su `_update` global como referencia propia; los
`local` de nivel de chunk quedan aislados por actor (nuevo chunk = nuevos upvalues en
cada ejecucion), pero variables verdaderamente globales SI se comparten entre actores
que usan el mismo state -- reproducido a proposito, no es un bug de esta capa.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

try:
    import lupa
except ImportError as _exc:  # pragma: no cover - entorno sin build de lupa
    lupa = None  # type: ignore[assignment]
    _IMPORT_ERROR: Exception | None = _exc
else:
    _IMPORT_ERROR = None

from turtlestudio.palette_policy import PALETTE_SIZE
from turtlestudio.play_runtime import ActorRuntimeState, PlaySession, move_actor


def lupa_available() -> bool:
    return lupa is not None


def lupa_import_error() -> str:
    return str(_IMPORT_ERROR) if _IMPORT_ERROR is not None else ""


def _require_lupa() -> None:
    if lupa is None:
        raise RuntimeError(f"lupa no disponible: {lupa_import_error()}")


def _round_half_away_from_zero(v: float) -> int:
    """lua_round_to_int (turtle_actor_lua.cpp) -- NO es round() de Python (banker's)."""
    if v >= 0.0:
        return int(v + 0.5)
    return int(v - 0.5)


# ----------------------------------------------------------------------
# VM de actores: un lua_State compartido, contexto "actor activo" mutable
# (equivalente a turtle_scene_actor_set_lua_target)
# ----------------------------------------------------------------------


class ActorLuaBridge:
    def __init__(self, session: PlaySession) -> None:
        _require_lupa()
        self.session = session
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)  # type: ignore[union-attr]
        self.current_actor: ActorRuntimeState | None = None
        self._update_refs: dict[str, Any] = {}
        self._register()

    def _register(self) -> None:
        g = self.lua.globals()
        g.print = self._l_print
        g.btn = self._l_btn
        g.btnp = self._l_btnp
        g.axis = self._l_axis
        g.posx = self._l_posx
        g.posy = self._l_posy
        g.move = self._l_move
        g.on_ground = self._l_on_ground
        g.set_anim = self._l_set_anim
        g.play_anim = self._l_play_anim
        g.flip_h = self._l_flip_h
        g.text = self._l_text
        g.text_width = self._l_text_width
        g.goto_scene = self._l_goto_scene

    # -- puente, firmas verificadas contra turtle_actor_lua.cpp -----------

    def _l_print(self, *args: Any) -> None:
        self.session.log.append("\t".join(str(a) for a in args))

    def _l_btn(self, i: Any) -> bool:
        return self.session.input.held(int(i))

    def _l_btnp(self, i: Any) -> bool:
        return self.session.input.pressed(int(i))

    def _l_axis(self, neg: Any, pos: Any) -> int:
        v = 0
        if self.session.input.held(int(neg)):
            v -= 1
        if self.session.input.held(int(pos)):
            v += 1
        return v

    def _l_posx(self) -> int:
        a = self.current_actor
        return int(a.x) if a is not None else 0

    def _l_posy(self) -> int:
        a = self.current_actor
        return int(a.y) if a is not None else 0

    def _l_move(self, dx: Any, dy: Any) -> tuple[int, int]:
        a = self.current_actor
        if a is None or self.session.tile_index is None:
            return 0, 0
        idx = _round_half_away_from_zero(float(dx))
        idy = _round_half_away_from_zero(float(dy))
        return move_actor(a, idx, idy, self.session.tile_index, self.session.fw, self.session.fh)

    def _l_on_ground(self) -> bool:
        a = self.current_actor
        return bool(a.grounded) if a is not None else False

    def _l_set_anim(self, name: Any) -> None:
        a = self.current_actor
        if a is not None:
            self.session.set_anim(a, str(name))

    def _l_play_anim(self, name: Any, speed: Any = 1.0, repeat: Any = True) -> None:
        a = self.current_actor
        if a is not None:
            self.session.play_anim(a, str(name), float(speed), bool(repeat))

    def _l_flip_h(self, value: Any = False) -> None:
        a = self.current_actor
        if a is not None:
            a.flip_h = bool(value)

    def _l_text(self, s: Any, font_id: Any = "", dx: Any = 0, dy: Any = 0, color_index: Any = -1) -> None:
        a = self.current_actor
        if a is not None:
            self.session.set_text(a, str(s), int(dx), int(dy), str(font_id), int(color_index))

    def _l_text_width(self, s: Any, font_id: Any) -> int:
        return self.session.measure_text(str(font_id), str(s))

    def _l_goto_scene(self, scene_id: Any) -> None:
        """spec/lua/object-script-v0.md "Cambio de escena": mismo diferido que
        turtle_scene_request_switch en firmware -- solo guarda el pedido, play_widget.py lo
        aplica despues de terminar el tick de este fotograma."""
        self.session.request_scene_switch(str(scene_id))

    # -- bind / tick --------------------------------------------------

    def bind_actors(self, actors: list[ActorRuntimeState]) -> None:
        """Equivalente a turtle_actor_lua_bind_actors_from_scene + load_script_update_ref:
        carga y ejecuta /scripts/<stem>.lua una vez por actor con script, capturando su
        `_update` global inmediatamente despues (antes de que el siguiente actor lo
        pise, si comparte stem)."""
        self._update_refs.clear()
        for a in actors:
            stem = a.script_stem
            if not stem:
                continue
            path = self.session.project_root / "scripts" / f"{stem}.lua"
            if not path.is_file():
                self.session.log.append(f'falta scripts/{stem}.lua (actor "{a.id}")')
                continue
            try:
                src = path.read_text(encoding="utf-8")
                self.lua.execute(src)
            except Exception as exc:  # lupa.LuaError u otro error de sintaxis
                self.session.log.append(f'error cargando scripts/{stem}.lua: {exc}')
                continue
            update_fn = self.lua.globals()["_update"]
            if update_fn is None or not callable(update_fn):
                self.session.log.append(f'scripts/{stem}.lua sin funcion _update(dt) (actor "{a.id}")')
                continue
            self._update_refs[a.id] = update_fn

    def tick(self, actors: list[ActorRuntimeState], dt_seconds: float) -> None:
        for a in actors:
            update_fn = self._update_refs.get(a.id)
            if update_fn is None:
                continue
            self.current_actor = a
            try:
                update_fn(dt_seconds)
            except Exception as exc:  # lupa.LuaError -- log y seguir, como lua_pcall
                self.session.log.append(f'_update actor "{a.id}": {exc}')
        self.current_actor = None


# ----------------------------------------------------------------------
# VM de ENTRY: corre una sola vez en begin(), igual que runCartEntryLua() en setup().
# Su dibujo queda invisible en cuanto arranca la escena (turtle_scene_begin_runtime hace
# cls + snapshot_static), asi que aca cls/pix/spix/flip son no-op deliberados -- Play
# mode siempre tiene una escena, nunca el caso "cartucho de solo splash" donde ENTRY
# persistiria en hardware real.
# ----------------------------------------------------------------------


class EntryLuaBridge:
    def __init__(self, session: PlaySession) -> None:
        _require_lupa()
        self.session = session
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)  # type: ignore[union-attr]
        self._register()

    def _register(self) -> None:
        g = self.lua.globals()
        g.print = lambda *a: self.session.log.append("\t".join(str(x) for x in a))
        g.cls = lambda *a: None
        g.pix = lambda *a: None
        g.spix = lambda *a: None
        g.flip = lambda: None
        g.W = self.session.viewport_w
        g.H = self.session.viewport_h
        g.COLORS = PALETTE_SIZE
        g.btn = lambda i: self.session.input.held(int(i))
        g.btnp = lambda i: False  # sin poll() antes de ENTRY en hardware real -- fuera de alcance v0
        g.text = lambda sx, sy, s, font_id, color_index=-1: self.session.measure_text(str(font_id), str(s))
        g.text_width = lambda s, font_id: self.session.measure_text(str(font_id), str(s))

    def run(self, entry_relpath: str) -> None:
        path = (self.session.project_root / entry_relpath).resolve()
        if not path.is_file():
            return
        try:
            src = path.read_text(encoding="utf-8")
            self.lua.execute(src)
        except Exception as exc:  # lupa.LuaError u otro error de sintaxis
            self.session.log.append(f"error en ENTRY ({entry_relpath}): {exc}")


# ----------------------------------------------------------------------
# Fabrica: enlaza un ActorLuaBridge a session.tick() sin que play_runtime.py
# importe lupa.
# ----------------------------------------------------------------------


def make_run_actor_scripts(session: PlaySession) -> tuple[Callable[[list[ActorRuntimeState], float], None], ActorLuaBridge]:
    bridge = ActorLuaBridge(session)
    bridge.bind_actors(session.actors)
    return bridge.tick, bridge
