"""Non-Qt "Play" simulation runtime: actor collision, camera, animation, input latch.

Ports firmware/TurtleReader/turtle_scene.cpp's runtime tick (resolve_axis_steps,
clamp_actor_pos, actor_touching_ground, tick_actors, update_camera_follow_player,
turtle_scene_actor_set_anim/play_anim, turtle_input.cpp's btnp latch) to pure Python,
so TurtleStudio can playtest a project live off the same in-memory project state the
static scene preview (scene_editor.py) already composites from -- no build step, no
SD card, no binary asset round-trip. Real Lua 5.4 execution lives in
play_lua_bridge.py (the only module that imports lupa); this module has no Lua
dependency and is testable headlessly (see test_play_runtime.py).

No live gameplay simulation existed on PC before this (see scene_editor.py's module
docstring) -- TortoiseStudio's pygame-embedded viewport was the only prior art in this
workspace, and its object scripts are plain Python, so it never had to solve the
interpreter-bridge problem this module + play_lua_bridge.py solve.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from turtlestudio import objects as objects_mod
from turtlestudio import tile_collision as tile_collision_mod
from turtlestudio.build import load_palette_rgb01_for_preview
from turtlestudio.fonts import (
    blit_text_scene,
    font_metrics_from_data,
    parse_font_advances,
    parse_font_glyphs,
    read_font_file,
)
from turtlestudio.palette_policy import (
    TRANSPARENT_PALETTE_INDEX,
    is_transparent_palette_index,
    resolve_palette_color,
)
from turtlestudio.project import clamp_world_steps, scene_world_pixel_size
from turtlestudio.project_runtime import scene_default_anim_fps, scene_target_fps
from turtlestudio.scene_camera import (
    CAMERA_MODE_FIXED,
    VIEWPORT_PIXEL_H,
    VIEWPORT_PIXEL_W,
    SceneCameraConfig,
    clamp_camera_position,
    compute_follow_camera,
    parse_scene_camera_from_row,
)
from turtlestudio.scene_editor import render_scene_rgba
from turtlestudio.scene_tiles import (
    SceneTileLayer,
    normalize_collision_tile_layer,
    parse_tile_layers,
    scene_tile_grid_dimensions,
)
from turtlestudio.sprites import (
    normalize_palette_rel,
    parse_sprite_all_frame_rows,
    parse_sprite_frame_count,
    parse_sprite_origin,
    read_sprite_file,
    sprite_pixel_dimensions,
)
from turtlestudio.tile_collision import (
    TILE_COLLISION_NONE,
    TILE_COLLISION_SHAPE,
    TILE_ONEWAY_DOWN,
    TILE_ONEWAY_LEFT,
    TILE_ONEWAY_RIGHT,
    TILE_ONEWAY_UP,
    TileCollisionMeta,
    parse_tileset_collision_meta,
)
from turtlestudio.tiles import read_tileset_file

MAX_BUTTONS = 8
# 0-3 direccion (izq/der/arriba/abajo), 4-7 A-D. Orden confirmado en
# firmware/TurtleReader/turtle_input.cpp (tabla k_pins).
BTN_LEFT, BTN_RIGHT, BTN_UP, BTN_DOWN, BTN_A, BTN_B, BTN_C, BTN_D = range(8)


def _trunc_div(a: int, b: int) -> int:
    """Division entera truncada hacia cero (como C int/int), no floor como //."""
    q = a // b
    if q < 0 and q * b != a:
        q += 1
    return q


def _rects_overlap(ax0: int, ay0: int, ax1: int, ay1: int, bx0: int, by0: int, bx1: int, by1: int) -> bool:
    return ax0 <= bx1 and ax1 >= bx0 and ay0 <= by1 and ay1 >= by0


# ----------------------------------------------------------------------
# Estado de actor en vivo
# ----------------------------------------------------------------------


@dataclass
class ActorRuntimeState:
    id: str
    x: int
    y: int
    pw: int
    ph: int
    origin_x: int
    origin_y: int
    col_x0: int
    col_y0: int
    col_x1: int
    col_y1: int
    sprite_id: str
    frame_count: int
    object_id: str = ""
    tags: tuple[str, ...] = ()
    visible: bool = True
    animations: dict[str, str] = field(default_factory=dict)
    script_stem: str | None = None
    grounded: bool = False
    flip_h: bool = False
    flip_v: bool = False
    anim_name: str = ""
    anim_repeat: bool = True
    anim_speed: float = 1.0
    frame_index: int = 0
    frame_accum_ms: float = 0.0
    has_text: bool = False
    text_str: str = ""
    text_dx: int = 0
    text_dy: int = 0
    text_font_id: str = ""
    text_color: int = -1


def build_actor_states(
    project_root: Path,
    placements: list[dict[str, Any]],
) -> list[ActorRuntimeState]:
    """Un ActorRuntimeState por placement con objeto+sprite validos (con o sin script)."""
    out: list[ActorRuntimeState] = []
    for p in placements:
        if not isinstance(p, dict):
            continue
        # "object" = referencia al catalogo (objects/Objects/<object>.json); fallback a "id"
        # para escenas legado (pre spec/scene-object-identity-v0.md) donde "id" cumplia ese rol.
        robj = p.get("object")
        oid = str(robj).strip() if isinstance(robj, str) and robj.strip() else str(p.get("id", "")).strip()
        if not oid:
            continue
        instance_id = str(p.get("id", "")).strip() or oid
        tags = tuple(str(t) for t in (p.get("tags") or []) if isinstance(t, str))
        visible = bool(p.get("visible", True))
        try:
            od = objects_mod.read_object_file(project_root, oid)
        except ValueError:
            continue
        sprite_id = str(od.get("sprite_id", "")).strip()
        if not sprite_id:
            continue
        try:
            sprite_data = read_sprite_file(project_root, sprite_id)
        except ValueError:
            continue
        _, pw, ph = sprite_pixel_dimensions(sprite_data)
        ox, oy = parse_sprite_origin(sprite_data, pw=pw, ph=ph)
        frame_count = parse_sprite_frame_count(sprite_data)

        # Firmware (turtle_scene.cpp init_actor_from_placement) solo lee x0/y0/x1/y1
        # planos del dict "collision" -- un collision.mode triangle/hexagon (basado en
        # "points", sin esas claves) falla esa lectura silenciosamente y el actor queda
        # con la caja por defecto inscrita en el sprite. Reproducido aca a proposito
        # (no se soporta collision punto-a-punto para actores, solo para tiles).
        col = objects_mod.parse_object_collision(od)
        if col is not None and col.get("mode") == objects_mod.OBJECT_COLLISION_MODE_AABB:
            col_x0, col_y0, col_x1, col_y1 = col["x0"], col["y0"], col["x1"], col["y1"]
        else:
            default = objects_mod.default_collision_from_sprite(sprite_data)
            col_x0, col_y0, col_x1, col_y1 = default["x0"], default["y0"], default["x1"], default["y1"]

        animations = {a["name"]: a["sprite_id"] for a in objects_mod.parse_object_animations(od)}
        script_stem = objects_mod.parse_object_script(od)
        try:
            x = int(p.get("x", 0))
            y = int(p.get("y", 0))
        except (TypeError, ValueError):
            x, y = 0, 0

        out.append(
            ActorRuntimeState(
                id=instance_id,
                object_id=oid,
                tags=tags,
                visible=visible,
                x=x,
                y=y,
                pw=pw,
                ph=ph,
                origin_x=ox,
                origin_y=oy,
                col_x0=col_x0,
                col_y0=col_y0,
                col_x1=col_x1,
                col_y1=col_y1,
                sprite_id=sprite_id,
                frame_count=frame_count,
                animations=animations,
                script_stem=script_stem,
            )
        )
    return out


def _resolve_player_actor_id(target: str, placements: list[dict[str, Any]]) -> str | None:
    """Misma politica que scene_camera.resolve_follow_target_xy (target explicito ->
    "character"/"player" -> primero), pero devuelve el id en vez de (x, y) para poder
    releer la posicion EN VIVO cada tick en vez de la del placement inicial."""
    objs = [o for o in placements if isinstance(o, dict) and str(o.get("id", "")).strip()]
    tid = target.strip()
    if tid:
        for o in objs:
            if str(o.get("id", "")).strip() == tid:
                return tid
        return None
    for pref in ("character", "player"):
        for o in objs:
            oid = str(o.get("id", "")).strip()
            if oid == pref:
                return oid
    if objs:
        return str(objs[0].get("id", "")).strip() or None
    return None


def _actor_world_aabb(a: ActorRuntimeState) -> tuple[int, int, int, int]:
    left, right = a.x + a.col_x0, a.x + a.col_x1
    bottom, top = a.y + a.col_y0, a.y + a.col_y1
    if left > right:
        left, right = right, left
    if bottom > top:
        bottom, top = top, bottom
    return left, bottom, right, top


# ----------------------------------------------------------------------
# Colision de tiles (turtle_tile_collision.cpp / tile_cell_blocks_actor)
# ----------------------------------------------------------------------


def _resolve_tile_local_aabb(shape: dict[str, Any], tile_px: int) -> tuple[int, int, int, int]:
    mode = str(shape.get("mode", "aabb"))
    if mode == "aabb":
        return (
            int(shape.get("x0", 0)),
            int(shape.get("y0", 0)),
            int(shape.get("x1", 0)),
            int(shape.get("y1", 0)),
        )
    # triangle/hexagon: bbox de los puntos. Nota: asset_bin.py (_encode_tile_collision_block)
    # todavia NO hace este bbox antes de exportar a .tts -- en hardware real un tile
    # triangle/hexagon actualmente exporta (0,0,0,0). Play mode implementa el
    # comportamiento previsto (bbox real), asi que puede divergir de un cartucho
    # exportado hasta que ese bug se corrija por separado.
    pts = shape.get("points")
    if not isinstance(pts, list) or not pts:
        return (0, 0, 0, 0)
    xs = [int(p[0]) for p in pts]
    ys = [int(p[1]) for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _tile_meta_blocks(
    meta: TileCollisionMeta,
    tile_px: int,
    tsx0: int,
    tsy0: int,
    ax0: int,
    ay0: int,
    ax1: int,
    ay1: int,
    step_dx: int,
    step_dy: int,
    ground_probe: bool,
) -> bool:
    kind = str(meta.get("kind", tile_collision_mod.TILE_COLLISION_SOLID))
    if kind == TILE_COLLISION_NONE:
        return False
    if kind == TILE_COLLISION_SHAPE:
        lx0, ly0, lx1, ly1 = _resolve_tile_local_aabb(meta.get("shape") or {}, tile_px)
    else:
        lx0, ly0, lx1, ly1 = 0, 0, tile_px - 1, tile_px - 1
    cx0, cy0, cx1, cy1 = tsx0 + lx0, tsy0 + ly0, tsx0 + lx1, tsy0 + ly1
    if not _rects_overlap(ax0, ay0, ax1, ay1, cx0, cy0, cx1, cy1):
        return False
    if not ground_probe and bool(meta.get("oneway")):
        d = meta.get("oneway_direction")
        if d == TILE_ONEWAY_UP and step_dy > 0:
            return False
        if d == TILE_ONEWAY_DOWN and step_dy < 0:
            return False
        if d == TILE_ONEWAY_LEFT and step_dx < 0:
            return False
        if d == TILE_ONEWAY_RIGHT and step_dx > 0:
            return False
    return True


@dataclass
class _TilesetCollisionCache:
    tile_px: int
    meta: list[TileCollisionMeta]


class TileCollisionIndex:
    """Colision de tiles para una escena; una instancia por begin() (cache por tileset)."""

    def __init__(
        self,
        project_root: Path,
        layers: tuple[SceneTileLayer, ...],
        *,
        tile_px: int,
        world_w: int,
        world_h: int,
        collision_tile_layer: int = 0,
    ) -> None:
        self.project_root = project_root
        self.tile_px = tile_px
        self.cols, self.rows = scene_tile_grid_dimensions(tile_px, world_w=world_w, world_h=world_h)
        # spec/scene-v0.md "Capa de colision": solo esta capa bloquea actores (paridad
        # con turtle_scene.cpp tile_cell_blocks_actor / s_runtime_collision_tile_layer).
        ly = layers[collision_tile_layer] if 0 <= collision_tile_layer < len(layers) else None
        self.layer = ly if ly is not None and ly.enabled and ly.tileset.strip() else None
        self._cache: dict[str, _TilesetCollisionCache] = {}

    def _tileset_cache(self, stem: str) -> _TilesetCollisionCache:
        cached = self._cache.get(stem)
        if cached is not None:
            return cached
        try:
            data = read_tileset_file(self.project_root, stem)
        except ValueError:
            cached = _TilesetCollisionCache(self.tile_px, [])
        else:
            tpx = int(data.get("tile_px", self.tile_px))
            cached = _TilesetCollisionCache(tpx, parse_tileset_collision_meta(data))
        self._cache[stem] = cached
        return cached

    def cell_blocks(
        self,
        gx: int,
        gy: int,
        ax0: int,
        ay0: int,
        ax1: int,
        ay1: int,
        step_dx: int,
        step_dy: int,
        ground_probe: bool = False,
    ) -> bool:
        if gx < 0 or gy < 0 or gx >= self.cols or gy >= self.rows:
            return False
        ly = self.layer
        if ly is None:
            return False
        tsx0 = gx * self.tile_px
        tsy0 = (self.rows - 1 - gy) * self.tile_px
        if gy >= len(ly.cells):
            return False
        row = ly.cells[gy]
        if gx >= len(row):
            return False
        ti = row[gx]
        if ti == TRANSPARENT_PALETTE_INDEX or ti < 0:
            return False
        cache = self._tileset_cache(ly.tileset)
        if cache.tile_px != self.tile_px or ti >= len(cache.meta):
            return False
        return _tile_meta_blocks(cache.meta[ti], self.tile_px, tsx0, tsy0, ax0, ay0, ax1, ay1, step_dx, step_dy, ground_probe)

    def actor_hits(self, ax0: int, ay0: int, ax1: int, ay1: int, step_dx: int, step_dy: int, *, ground_probe: bool = False) -> bool:
        px = self.tile_px
        gx0 = _trunc_div(ax0, px)
        gx1 = _trunc_div(ax1, px)
        gy_lo = self.rows - 1 - _trunc_div(ay1, px)
        gy_hi = self.rows - 1 - _trunc_div(ay0, px)
        for gy in range(gy_lo, gy_hi + 1):
            for gx in range(gx0, gx1 + 1):
                if self.cell_blocks(gx, gy, ax0, ay0, ax1, ay1, step_dx, step_dy, ground_probe):
                    return True
        return False


# ----------------------------------------------------------------------
# Movimiento (turtle_scene.cpp resolve_axis_steps / clamp_actor_pos / actor_touching_ground)
# ----------------------------------------------------------------------


def resolve_axis_steps(a: ActorRuntimeState, dx: int, dy: int, tile_index: TileCollisionIndex) -> tuple[int, int]:
    if dx != 0:
        step = 1 if dx > 0 else -1
        moved = 0
        for _ in range(abs(dx)):
            a.x += step
            x0, y0, x1, y1 = _actor_world_aabb(a)
            if tile_index.actor_hits(x0, y0, x1, y1, step, 0):
                a.x -= step
                break
            moved += step
        dx = moved
    if dy != 0:
        step = 1 if dy > 0 else -1
        moved = 0
        for _ in range(abs(dy)):
            a.y += step
            x0, y0, x1, y1 = _actor_world_aabb(a)
            if tile_index.actor_hits(x0, y0, x1, y1, 0, step):
                a.y -= step
                if step < 0:
                    a.grounded = True
                break
            moved += step
        dy = moved
    return dx, dy


def clamp_actor_pos(a: ActorRuntimeState, world_w: int, world_h: int) -> None:
    min_x, max_x = -a.col_x0, (world_w - 1) - a.col_x1
    min_y, max_y = -a.col_y0, (world_h - 1) - a.col_y1
    if a.x < min_x:
        a.x = min_x
    elif a.x > max_x:
        a.x = max_x
    if a.y < min_y:
        a.y = min_y
        a.grounded = True
    elif a.y > max_y:
        a.y = max_y


def actor_touching_ground(a: ActorRuntimeState, tile_index: TileCollisionIndex) -> bool:
    x0, y0, x1, y1 = _actor_world_aabb(a)
    if y0 <= 0:
        return True
    # Sondeo 1px por debajo del AABB real, caja completa desplazada (no solo la fila):
    # en reposo el borde inferior queda tocando, no solapando, la celda solida.
    probe_y0, probe_y1 = y0 - 1, y1 - 1
    px = tile_index.tile_px
    gx0 = _trunc_div(x0, px)
    gx1 = _trunc_div(x1, px)
    gy = tile_index.rows - 1 - _trunc_div(probe_y0, px)
    if gy < 0 or gy >= tile_index.rows:
        return False
    for gx in range(gx0, gx1 + 1):
        if gx < 0 or gx >= tile_index.cols:
            continue
        if tile_index.cell_blocks(gx, gy, x0, probe_y0, x1, probe_y1, 0, -1, ground_probe=True):
            return True
    return False


def move_actor(a: ActorRuntimeState, dx: int, dy: int, tile_index: TileCollisionIndex, world_w: int, world_h: int) -> tuple[int, int]:
    a.grounded = False
    out_dx, out_dy = 0, 0
    if dx != 0 or dy != 0:
        out_dx, out_dy = resolve_axis_steps(a, dx, dy, tile_index)
        clamp_actor_pos(a, world_w, world_h)
    if not a.grounded:
        a.grounded = actor_touching_ground(a, tile_index)
    return out_dx, out_dy


# ----------------------------------------------------------------------
# Animacion (turtle_scene.cpp tick_actors / actor_apply_sprite)
# ----------------------------------------------------------------------


def tick_actor_animation(a: ActorRuntimeState, delta_ms: float, default_anim_fps: int) -> None:
    if a.frame_count <= 1:
        return
    denom = max(0.0001, default_anim_fps * a.anim_speed)
    ms_per_frame = max(1.0, 1000.0 / denom)
    a.frame_accum_ms += delta_ms
    while a.frame_accum_ms >= ms_per_frame:
        a.frame_accum_ms -= ms_per_frame
        if a.frame_count <= 1:
            break
        if a.frame_index + 1 >= a.frame_count:
            if a.anim_repeat:
                a.frame_index = 0
            else:
                a.frame_index = a.frame_count - 1
                break
        else:
            a.frame_index += 1


# ----------------------------------------------------------------------
# Entrada (turtle_input.cpp: btnp con latch, no simple edge-detect)
# ----------------------------------------------------------------------


class InputState:
    """held = estado en vivo; pressed() consume un latch (sobrevive polls extra,
    igual que turtle_input.cpp -- necesario porque Qt puede entregar eventos de
    teclado entre ticks del QTimer, a diferencia de hardware real donde poll==tick."""

    def __init__(self) -> None:
        self.held_mask = 0
        self._prev_held_mask = 0
        self._press_latch_mask = 0

    def set_held_indices(self, indices: set[int]) -> None:
        mask = 0
        for i in indices:
            if 0 <= i < MAX_BUTTONS:
                mask |= 1 << i
        self.held_mask = mask

    def tick(self) -> None:
        newly = self.held_mask & ~self._prev_held_mask
        self._press_latch_mask |= newly
        self._prev_held_mask = self.held_mask

    def held(self, i: int) -> bool:
        if not (0 <= i < MAX_BUTTONS):
            return False
        return bool(self.held_mask & (1 << i))

    def pressed(self, i: int) -> bool:
        if not (0 <= i < MAX_BUTTONS):
            return False
        bit = 1 << i
        if not (self._press_latch_mask & bit):
            return False
        self._press_latch_mask &= ~bit
        return True


# ----------------------------------------------------------------------
# Blit (turtle_gpu_blit_indexed_scene_anchor / turtle_font_draw_scene[_tint])
# ----------------------------------------------------------------------


def _blit_actor_sprite(
    rgba: list[float],
    fw: int,
    fh: int,
    a: ActorRuntimeState,
    rows: list[list[int]],
    rgbs: list[tuple[float, float, float]],
    *,
    cam_x: int = 0,
    cam_y: int = 0,
) -> None:
    """(fw, fh, cam_x, cam_y): por defecto (0, 0) = comportamiento de siempre (rgba es
    el mundo entero, a.x/a.y ya en su propio espacio). Con cam_x/cam_y != 0, rgba puede
    ser un buffer mas chico (p. ej. solo el viewport) y a.x/a.y (espacio mundo) se
    trasladan restando la camara antes de dibujar -- ver PlaySession.render_rgba."""
    h = len(rows)
    if h <= 0:
        return
    w = len(rows[0]) if rows[0] else 0
    if w <= 0:
        return
    blit_y = a.y - a.origin_y
    for py in range(h):
        sy = blit_y + (h - 1 - py) - cam_y
        ty = (fh - 1) - sy
        if ty < 0 or ty >= fh:
            continue
        # flip_v: leemos las filas en orden inverso, mismo rect (paridad con
        # turtle_gpu.cpp blit_indexed_scene_anchor).
        src_py = (h - 1 - py) if a.flip_v else py
        row = rows[src_py] if src_py < len(rows) else []
        row_base = ty * fw * 4
        for lx in range(min(w, len(row))):
            idx = row[lx]
            if is_transparent_palette_index(idx):
                continue
            col = resolve_palette_color(idx, rgbs)
            if col is None:
                continue
            sx = ((a.x + a.origin_x - lx) if a.flip_h else (a.x + lx - a.origin_x)) - cam_x
            if sx < 0 or sx >= fw:
                continue
            i = row_base + sx * 4
            r, g, b = col
            rgba[i] = r
            rgba[i + 1] = g
            rgba[i + 2] = b
            rgba[i + 3] = 1.0


def _crop_world_rgba_to_viewport(
    rgba: list[float], fw: int, fh: int, cam_x: int, cam_y: int, *, viewport_w: int = VIEWPORT_PIXEL_W, viewport_h: int = VIEWPORT_PIXEL_H
) -> list[float]:
    if fw == viewport_w and fh == viewport_h:
        return list(rgba)
    vw, vh = viewport_w, viewport_h
    out = [0.0] * (vw * vh * 4)
    for i in range(3, len(out), 4):
        out[i] = 1.0
    row_base_offset = fh - vh - cam_y
    for oy in range(vh):
        ty_world = row_base_offset + oy
        if ty_world < 0 or ty_world >= fh:
            continue
        src_row_base = ty_world * fw * 4
        dst_row_base = oy * vw * 4
        for ox in range(vw):
            tx_world = cam_x + ox
            if tx_world < 0 or tx_world >= fw:
                continue
            si = src_row_base + tx_world * 4
            di = dst_row_base + ox * 4
            out[di : di + 4] = rgba[si : si + 4]
    return out


# ----------------------------------------------------------------------
# Sesion de juego
# ----------------------------------------------------------------------


class PlaySession:
    """Orquesta un scene-begin + N ticks, sin Qt. play_widget.py la maneja con un
    QTimer; play_lua_bridge.py conecta btn/btnp/move/set_anim/etc a esta clase."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.actors: list[ActorRuntimeState] = []
        self.tile_index: TileCollisionIndex | None = None
        self.input = InputState()
        self.fw = VIEWPORT_PIXEL_W
        self.fh = VIEWPORT_PIXEL_H
        self.viewport_w = VIEWPORT_PIXEL_W
        self.viewport_h = VIEWPORT_PIXEL_H
        self.tile_px = 16
        self.cam_x = 0
        self.cam_y = 0
        self.camera: SceneCameraConfig = SceneCameraConfig()
        self.player_id: str | None = None
        self.target_fps = 30
        self.default_anim_fps = 8
        self._static_rgba: list[float] = []
        self._rgbs: list[tuple[float, float, float]] = []
        self._sprite_cache: dict[str, dict[str, Any] | None] = {}
        self._font_cache: dict[str, dict[str, Any] | None] = {}
        # spec/scene-text-blink-v0.md: etiquetas con blink_ms > 0, excluidas de _static_rgba
        # (ver begin()) porque necesitan alternar visible/oculto con el tiempo -- cada entrada
        # es {"lbl": dict original, "visible": bool, "accum_ms": float}.
        self._blinking_labels: list[dict[str, Any]] = []
        # spec/lua/object-script-v0.md "Cambio de escena": id pedido por goto_scene(id) desde
        # un actor (ver play_lua_bridge.py), o None si no hay ninguno pendiente. Igual que en
        # el firmware (turtle_scene_request_switch), aplicarlo es responsabilidad del que
        # orquesta el tick (play_widget.py) -- este modulo solo guarda el pedido.
        self.pending_scene_switch: str | None = None
        self.log: list[str] = []
        self._active = False

    def request_scene_switch(self, scene_id: str) -> None:
        if scene_id:
            self.pending_scene_switch = scene_id

    # -- lifecycle --------------------------------------------------

    def begin(
        self,
        row: dict[str, Any],
        tile_px: int,
        *,
        project_target_fps: int,
        project_anim_fps: int,
        viewport_w: int = VIEWPORT_PIXEL_W,
        viewport_h: int = VIEWPORT_PIXEL_H,
    ) -> None:
        self.tile_px = tile_px
        self.viewport_w, self.viewport_h = viewport_w, viewport_h
        wsx = clamp_world_steps(row.get("world_steps_x", 1))
        wsy = clamp_world_steps(row.get("world_steps_y", 1))
        self.fw, self.fh = scene_world_pixel_size(wsx, wsy, base_w=viewport_w, base_h=viewport_h)
        self.camera = parse_scene_camera_from_row(row)
        self.target_fps = scene_target_fps(row, project_target_fps)
        self.default_anim_fps = scene_default_anim_fps(row, project_anim_fps)

        placements = row.get("objects") or []
        self.actors = build_actor_states(self.project_root, placements)
        self._sprite_cache = {}
        self._font_cache = {}

        tile_layers = parse_tile_layers(row.get("tile_layers"), tile_px=tile_px, world_w=self.fw, world_h=self.fh)
        coll_layer = normalize_collision_tile_layer(row.get("collision_tile_layer", 0))
        self.tile_index = TileCollisionIndex(
            self.project_root,
            tile_layers,
            tile_px=tile_px,
            world_w=self.fw,
            world_h=self.fh,
            collision_tile_layer=coll_layer,
        )

        palette_rel = str(row.get("palette", "")).strip()
        pal_path = (self.project_root / palette_rel).resolve() if palette_rel else None
        self._rgbs, _ = load_palette_rgb01_for_preview(pal_path if pal_path and pal_path.is_file() else None)

        # spec/scene-text-blink-v0.md: etiquetas con blink_ms > 0 no pueden ir horneadas en
        # _static_rgba (quedarian fijas para siempre, igual que el snapshot estatico del
        # firmware) -- se sacan de la lista que se hornea y se dibujan en vivo cada frame en
        # render_rgba(), igual que los actores.
        text_labels = row.get("text_labels") or []
        static_labels: list[Any] = []
        self._blinking_labels = []
        for lbl in text_labels:
            if not isinstance(lbl, dict):
                continue
            try:
                blink_ms = int(lbl.get("blink_ms", 0))
            except (TypeError, ValueError):
                blink_ms = 0
            if blink_ms > 0:
                self._blinking_labels.append({"lbl": lbl, "visible": True, "accum_ms": 0.0})
            else:
                static_labels.append(lbl)

        # Capa estatica (fondo+tiles+parallax+etiquetas sin blink): igual que render_scene_rgba,
        # pero sin objects[] -- los actores se pintan en vivo cada frame en render_rgba(), no
        # horneados aca (a diferencia del firmware, esto no se re-hornea nunca, se copia una vez
        # por frame -- barato en desktop, no vale la pena el dirty-rect).
        static_row = dict(row)
        static_row["objects"] = []
        static_row["text_labels"] = static_labels
        self._static_rgba, _sfw, _sfh = render_scene_rgba(
            self.project_root, static_row, tile_px, viewport_w=viewport_w, viewport_h=viewport_h
        )

        self.player_id = _resolve_player_actor_id(self.camera.target, list(placements))

        self.cam_x, self.cam_y = self.camera.x, self.camera.y
        self._update_camera()
        self.log = []
        self.pending_scene_switch = None
        self._active = True

    def stop(self) -> None:
        self._active = False
        self.actors = []
        self.tile_index = None

    @property
    def active(self) -> bool:
        return self._active

    # -- datos cacheados ---------------------------------------------

    def get_sprite_data(self, sprite_id: str) -> dict[str, Any] | None:
        if sprite_id in self._sprite_cache:
            return self._sprite_cache[sprite_id]
        try:
            data = read_sprite_file(self.project_root, sprite_id)
        except ValueError:
            data = None
        self._sprite_cache[sprite_id] = data
        return data

    def get_font_data(self, font_id: str) -> dict[str, Any] | None:
        if font_id in self._font_cache:
            return self._font_cache[font_id]
        try:
            data = read_font_file(self.project_root, font_id)
        except ValueError:
            data = None
        self._font_cache[font_id] = data
        return data

    def _actor_by_id(self, oid: str) -> ActorRuntimeState | None:
        for a in self.actors:
            if a.id == oid:
                return a
        return None

    # -- animacion / sprite --------------------------------------------

    def apply_sprite(self, a: ActorRuntimeState, sprite_id: str, *, restart: bool) -> bool:
        data = self.get_sprite_data(sprite_id)
        if data is None:
            return False
        _, pw, ph = sprite_pixel_dimensions(data)
        ox, oy = parse_sprite_origin(data, pw=pw, ph=ph)
        same_sprite = a.sprite_id == sprite_id
        a.sprite_id = sprite_id
        a.pw, a.ph = pw, ph
        a.origin_x, a.origin_y = ox, oy
        a.frame_count = parse_sprite_frame_count(data)
        if not same_sprite or restart:
            a.frame_index = 0
            a.frame_accum_ms = 0.0
        return True

    def set_anim(self, a: ActorRuntimeState, name: str) -> bool:
        if not name or a.anim_name == name:
            return bool(name) and a.anim_name == name
        sprite_id = a.animations.get(name)
        if not sprite_id:
            self.log.append(f'anim "{name}" no en objeto "{a.id}"')
            return False
        a.anim_repeat = True
        a.anim_speed = 1.0
        restart = sprite_id != a.sprite_id
        if not self.apply_sprite(a, sprite_id, restart=restart):
            return False
        a.anim_name = name
        return True

    def play_anim(self, a: ActorRuntimeState, name: str, speed: float = 1.0, repeat: bool = True) -> bool:
        if not name:
            return False
        sprite_id = a.animations.get(name)
        if not sprite_id:
            self.log.append(f'anim "{name}" no en objeto "{a.id}"')
            return False
        a.anim_repeat = repeat
        a.anim_speed = max(0.25, min(16.0, speed))
        if not self.apply_sprite(a, sprite_id, restart=True):
            return False
        a.anim_name = name
        return True

    def set_text(self, a: ActorRuntimeState, text: str, dx: int, dy: int, font_id: str, color_index: int) -> None:
        if not text or not font_id:
            a.has_text = False
            a.text_str = ""
            return
        a.text_str = text
        a.text_font_id = font_id
        a.text_dx = dx
        a.text_dy = dy
        a.text_color = color_index
        a.has_text = True

    def measure_text(self, font_id: str, text: str) -> int:
        data = self.get_font_data(font_id)
        if data is None:
            return 0
        px, _lh, _bl = font_metrics_from_data(data)
        advances = parse_font_advances(data)
        return sum(advances.get(ch, px) for ch in text)

    # -- camara ----------------------------------------------------

    def _scrolling(self) -> bool:
        return self.fw > self.viewport_w or self.fh > self.viewport_h

    def _update_camera(self) -> None:
        if not self._scrolling():
            self.cam_x, self.cam_y = 0, 0
            return
        if self.camera.mode == CAMERA_MODE_FIXED or self.player_id is None:
            self.cam_x, self.cam_y = clamp_camera_position(
                self.cam_x, self.cam_y, world_w=self.fw, world_h=self.fh, viewport_w=self.viewport_w, viewport_h=self.viewport_h
            )
            return
        player = self._actor_by_id(self.player_id)
        if player is None:
            self.cam_x, self.cam_y = clamp_camera_position(
                self.cam_x, self.cam_y, world_w=self.fw, world_h=self.fh, viewport_w=self.viewport_w, viewport_h=self.viewport_h
            )
            return
        self.cam_x, self.cam_y = compute_follow_camera(
            player.x,
            player.y,
            self.cam_x,
            self.cam_y,
            world_w=self.fw,
            world_h=self.fh,
            viewport_w=self.viewport_w,
            viewport_h=self.viewport_h,
            margin_x=self.camera.margin_x,
            margin_y=self.camera.margin_y,
        )

    # -- tick --------------------------------------------------------

    def tick(self, dt_seconds: float, run_actor_scripts) -> None:
        """`run_actor_scripts(actors)` es inyectado por play_lua_bridge.py (llama
        _update(dt) de cada script real vía lupa); se mantiene fuera de este modulo
        para que este archivo no dependa de lupa y sea testeable sin el."""
        self.input.tick()
        if run_actor_scripts is not None:
            run_actor_scripts(self.actors, dt_seconds)
        delta_ms = dt_seconds * 1000.0
        for a in self.actors:
            tick_actor_animation(a, delta_ms, self.default_anim_fps)
        # spec/scene-text-blink-v0.md: mismo patron acumulador que tick_text_labels en
        # turtle_scene.cpp (firmware) -- el `while` cubre un dt_seconds grande sin quedar
        # atrasado respecto al estado que corresponde.
        for state in self._blinking_labels:
            period = float(state["lbl"].get("blink_ms", 0) or 0)
            if period <= 0:
                continue
            state["accum_ms"] += delta_ms
            while state["accum_ms"] >= period:
                state["accum_ms"] -= period
                state["visible"] = not state["visible"]
        self._update_camera()

    # -- render --------------------------------------------------------

    def render_rgba(self) -> tuple[list[float], int, int]:
        # Recorta al viewport ANTES de dibujar actores (no al reves): copiar/blittear
        # contra un buffer del tamano del MUNDO entero cada fotograma escala con
        # world_steps (hasta 8x8 pasos); el crop de abajo ya es O(viewport), asi que
        # aplicarlo primero deja todo lo que sigue tambien O(viewport), sin importar
        # cuan grande sea el mundo autorado (ver plan de streaming/chunked world buffer).
        vw, vh = self.viewport_w, self.viewport_h
        if self._static_rgba:
            rgba = _crop_world_rgba_to_viewport(
                self._static_rgba, self.fw, self.fh, self.cam_x, self.cam_y, viewport_w=vw, viewport_h=vh
            )
        else:
            rgba = [0.0] * (vw * vh * 4)
            for i in range(3, len(rgba), 4):
                rgba[i] = 1.0

        # spec/scene-text-blink-v0.md: etiquetas con blink_ms > 0, dibujadas en vivo (no
        # estan en _static_rgba, ver begin()) antes de los actores para quedar en el mismo
        # orden relativo que el firmware (encima de fondo/tiles, debajo de actores).
        for state in self._blinking_labels:
            if not state["visible"]:
                continue
            lbl = state["lbl"]
            text = str(lbl.get("text", ""))
            font_id = str(lbl.get("font", "")).strip()
            if not text or not font_id:
                continue
            font_data = self.get_font_data(font_id)
            if font_data is None:
                continue
            try:
                color_index = int(lbl.get("color_index", -1))
            except (TypeError, ValueError):
                color_index = -1
            glyphs = parse_font_glyphs(font_data)
            advances = parse_font_advances(font_data)
            px, _lh, _bl = font_metrics_from_data(font_data)
            # color_index >= 0 se resuelve contra self._rgbs (paleta ACTIVA de la escena, no
            # la propia de la fuente) -- mismo motivo que _paint_scene_text_labels en
            # scene_editor.py, ver el comentario ahi.
            if color_index >= 0:
                label_rgbs = self._rgbs
            else:
                font_pal_rel = str(font_data.get("palette", "")).strip()
                font_pal_path = (self.project_root / normalize_palette_rel(font_pal_rel)).resolve() if font_pal_rel else None
                label_rgbs, _ = load_palette_rgb01_for_preview(font_pal_path if font_pal_path and font_pal_path.is_file() else None)
            blit_text_scene(
                rgba,
                vw,
                vh,
                int(lbl.get("x", 0)),
                int(lbl.get("y", 0)),
                text,
                glyphs=glyphs,
                advances=advances,
                glyph_px=px,
                rgbs=label_rgbs,
                tint_index=color_index,
                cam_x=self.cam_x,
                cam_y=self.cam_y,
            )

        for a in self.actors:
            if not a.visible:
                continue
            data = self.get_sprite_data(a.sprite_id)
            if data is None:
                continue
            frames = parse_sprite_all_frame_rows(data)
            idx = a.frame_index if a.frame_index < len(frames) else 0
            _blit_actor_sprite(rgba, vw, vh, a, frames[idx], self._rgbs, cam_x=self.cam_x, cam_y=self.cam_y)
            if a.has_text and a.text_str and a.text_font_id:
                font_data = self.get_font_data(a.text_font_id)
                if font_data is not None:
                    glyphs = parse_font_glyphs(font_data)
                    advances = parse_font_advances(font_data)
                    px, _lh, _bl = font_metrics_from_data(font_data)
                    font_pal_rel = str(font_data.get("palette", "")).strip()
                    font_pal_path = (self.project_root / normalize_palette_rel(font_pal_rel)).resolve() if font_pal_rel else None
                    font_rgbs, _ = load_palette_rgb01_for_preview(font_pal_path if font_pal_path and font_pal_path.is_file() else None)
                    blit_text_scene(
                        rgba,
                        vw,
                        vh,
                        a.x + a.text_dx,
                        a.y + a.text_dy,
                        a.text_str,
                        glyphs=glyphs,
                        advances=advances,
                        glyph_px=px,
                        rgbs=font_rgbs,
                        tint_index=a.text_color,
                        cam_x=self.cam_x,
                        cam_y=self.cam_y,
                    )
        return rgba, vw, vh
