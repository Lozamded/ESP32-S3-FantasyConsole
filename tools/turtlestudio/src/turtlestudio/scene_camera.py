"""Camara de escena (viewport 164×124, default S3): posicion, objetivo y margenes de scroll."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from turtlestudio.scene_tiles import _blend_rgba_pixel_inplace, scene_y_to_framebuffer_y

# Alineado con project.VIEWPORT_PIXEL_* (evita import circular project ↔ scene_camera).
VIEWPORT_PIXEL_W = 164
VIEWPORT_PIXEL_H = 124

CAMERA_MODE_FOLLOW = "follow"
CAMERA_MODE_FIXED = "fixed"
_CAMERA_MODE_CHOICES = (CAMERA_MODE_FOLLOW, CAMERA_MODE_FIXED)

DEFAULT_CAMERA_MARGIN_X = 64
DEFAULT_CAMERA_MARGIN_Y = 48

# spec/hud-border-v0.md: minimo de playfield reservado tras aplicar hud_border (8 px por eje).
HUD_MIN_PLAYFIELD = 8

_SCENE_CAMERA_RGBA = (1.0, 0.55, 0.2, 0.92)
_HUD_BORDER_RGBA = (0.15, 0.7, 1.0, 0.55)


@dataclass(frozen=True)
class HudBorder:
    """spec/hud-border-v0.md: cuatro bordes HUD en px de framebuffer. Todo cero = sin HUD.

    `bg_color_index`: -1 = no pintar (firmware deja los pixels HUD como los dejo `cls`).
    0..30 = pintar la region HUD una vez al comenzar la escena con ese indice de paleta.
    31 (transparente) se colapsa a -1 al parsear.
    `overlay`: false = mundo se encoge al playfield (comportamiento previo). true = mundo mantiene
    tamano canonico completo, camara no scrollea a revelar al actor detras del HUD (Metroid-style,
    el sprite del actor en la region HUD queda invisible por el clip de playfield)."""

    top: int = 0
    bottom: int = 0
    left: int = 0
    right: int = 0
    bg_color_index: int = -1
    overlay: bool = False

    def is_zero(self) -> bool:
        """True cuando NO hay HUD para pintar: los cuatro bordes en 0, sin bg color, sin overlay.
        La serializacion omite el bloque completo cuando esto es true (evita ensuciar diffs de
        escenas legado)."""
        return (self.top == 0 and self.bottom == 0 and self.left == 0 and self.right == 0
                and self.bg_color_index < 0 and not self.overlay)

    def playfield_size(
        self,
        viewport_w: int = VIEWPORT_PIXEL_W,
        viewport_h: int = VIEWPORT_PIXEL_H,
    ) -> tuple[int, int]:
        return (viewport_w - self.left - self.right, viewport_h - self.top - self.bottom)


@dataclass(frozen=True)
class SceneCameraConfig:
    mode: str = CAMERA_MODE_FOLLOW
    x: int = 0
    y: int = 0
    target: str = ""
    margin_x: int = DEFAULT_CAMERA_MARGIN_X
    margin_y: int = DEFAULT_CAMERA_MARGIN_Y
    hud_border: HudBorder = field(default_factory=HudBorder)


def _clamp_int(v: object, lo: int, hi: int, *, default: int) -> int:
    try:
        n = int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = default
    return max(lo, min(hi, n))


def clamp_camera_margin(margin: int, viewport_size: int) -> int:
    cap = max(0, (max(1, int(viewport_size)) - 1) // 2)
    return max(0, min(cap, int(margin)))


def clamp_hud_border(
    top: int,
    bottom: int,
    left: int,
    right: int,
    *,
    bg_color_index: int = -1,
    overlay: bool = False,
    viewport_w: int = VIEWPORT_PIXEL_W,
    viewport_h: int = VIEWPORT_PIXEL_H,
) -> HudBorder:
    """spec/hud-border-v0.md: mismos limites que en firmware (parse_scene_hud_border):
    cada borde en [0, viewport/2 - 1]; garantia de HUD_MIN_PLAYFIELD px de playfield por eje.
    `bg_color_index` -1..30 (31 se colapsa a -1 = no pintar). `overlay` es un simple bool."""
    max_v = max(0, viewport_h // 2 - 1)
    max_h = max(0, viewport_w // 2 - 1)
    t = max(0, min(max_v, int(top)))
    b = max(0, min(max_v, int(bottom)))
    l = max(0, min(max_h, int(left)))
    r = max(0, min(max_h, int(right)))
    if viewport_h - t - b < HUD_MIN_PLAYFIELD:
        b = max(0, viewport_h - t - HUD_MIN_PLAYFIELD)
        if b < 0:
            t = max(0, viewport_h - HUD_MIN_PLAYFIELD)
            b = 0
    if viewport_w - l - r < HUD_MIN_PLAYFIELD:
        r = max(0, viewport_w - l - HUD_MIN_PLAYFIELD)
        if r < 0:
            l = max(0, viewport_w - HUD_MIN_PLAYFIELD)
            r = 0
    bg = int(bg_color_index)
    if bg < 0 or bg > 30:
        bg = -1
    return HudBorder(top=t, bottom=b, left=l, right=r, bg_color_index=bg,
                     overlay=bool(overlay))


def parse_hud_border(raw: Any) -> HudBorder:
    if not isinstance(raw, dict):
        return HudBorder()
    return clamp_hud_border(
        _clamp_int(raw.get("top", 0), 0, VIEWPORT_PIXEL_H, default=0),
        _clamp_int(raw.get("bottom", 0), 0, VIEWPORT_PIXEL_H, default=0),
        _clamp_int(raw.get("left", 0), 0, VIEWPORT_PIXEL_W, default=0),
        _clamp_int(raw.get("right", 0), 0, VIEWPORT_PIXEL_W, default=0),
        bg_color_index=_clamp_int(raw.get("bg_color_index", -1), -1, 31, default=-1),
        overlay=bool(raw.get("overlay", False)),
    )


def clamp_camera_position(
    cam_x: int,
    cam_y: int,
    *,
    world_w: int,
    world_h: int,
    viewport_w: int = VIEWPORT_PIXEL_W,
    viewport_h: int = VIEWPORT_PIXEL_H,
) -> tuple[int, int]:
    ww = max(1, int(world_w))
    wh = max(1, int(world_h))
    vw = max(1, int(viewport_w))
    vh = max(1, int(viewport_h))
    max_x = max(0, ww - vw)
    max_y = max(0, wh - vh)
    return (
        max(0, min(max_x, int(cam_x))),
        max(0, min(max_y, int(cam_y))),
    )


def parse_scene_camera(raw: Any) -> SceneCameraConfig:
    if isinstance(raw, dict):
        d = raw
    elif isinstance(raw, str):
        mode_s = raw.strip().lower()
        if mode_s in _CAMERA_MODE_CHOICES:
            return SceneCameraConfig(mode=mode_s)
        return SceneCameraConfig()
    else:
        return SceneCameraConfig()

    mode = str(d.get("mode", d.get("camera_mode", CAMERA_MODE_FOLLOW))).strip().lower()
    if mode not in _CAMERA_MODE_CHOICES:
        mode = CAMERA_MODE_FOLLOW
    target = str(d.get("target", d.get("camera_target", "")) or "").strip()
    x = _clamp_int(d.get("x", d.get("camera_x", 0)), -1_000_000, 1_000_000, default=0)
    y = _clamp_int(d.get("y", d.get("camera_y", 0)), -1_000_000, 1_000_000, default=0)
    mx = _clamp_int(
        d.get("margin_x", d.get("camera_margin_x", DEFAULT_CAMERA_MARGIN_X)),
        0,
        VIEWPORT_PIXEL_W,
        default=DEFAULT_CAMERA_MARGIN_X,
    )
    my = _clamp_int(
        d.get("margin_y", d.get("camera_margin_y", DEFAULT_CAMERA_MARGIN_Y)),
        0,
        VIEWPORT_PIXEL_H,
        default=DEFAULT_CAMERA_MARGIN_Y,
    )
    hud_border = parse_hud_border(d.get("hud_border"))
    return SceneCameraConfig(
        mode=mode,
        x=x,
        y=y,
        target=target,
        margin_x=clamp_camera_margin(mx, VIEWPORT_PIXEL_W),
        margin_y=clamp_camera_margin(my, VIEWPORT_PIXEL_H),
        hud_border=hud_border,
    )


def parse_scene_camera_from_row(row: dict[str, Any]) -> SceneCameraConfig:
    if isinstance(row.get("camera"), dict):
        return parse_scene_camera(row["camera"])
    flat = {
        "mode": row.get("camera_mode"),
        "x": row.get("camera_x"),
        "y": row.get("camera_y"),
        "target": row.get("camera_target"),
        "margin_x": row.get("camera_margin_x"),
        "margin_y": row.get("camera_margin_y"),
    }
    # spec/hud-border-v0.md: alternativa plana (camera_hud_border_*) para pipelines que
    # aplanan campos en filas; la forma canonica sigue siendo anidada bajo `camera.hud_border`.
    flat_hud = {
        "top": row.get("camera_hud_border_top"),
        "bottom": row.get("camera_hud_border_bottom"),
        "left": row.get("camera_hud_border_left"),
        "right": row.get("camera_hud_border_right"),
    }
    flat_bg = row.get("camera_hud_border_bg_color_index")
    flat_overlay = row.get("camera_hud_border_overlay")
    if any(v is not None for v in flat_hud.values()) or flat_bg is not None or flat_overlay is not None:
        hud_flat: dict[str, Any] = {k: (0 if v is None else v) for k, v in flat_hud.items()}
        if flat_bg is not None:
            hud_flat["bg_color_index"] = flat_bg
        if flat_overlay is not None:
            hud_flat["overlay"] = flat_overlay
        flat["hud_border"] = hud_flat
    if any(v is not None for v in flat.values()):
        return parse_scene_camera(flat)
    return SceneCameraConfig()


def scene_camera_to_json(cam: SceneCameraConfig) -> dict[str, Any]:
    out: dict[str, Any] = {
        "mode": cam.mode,
        "x": int(cam.x),
        "y": int(cam.y),
        "margin_x": int(cam.margin_x),
        "margin_y": int(cam.margin_y),
    }
    if cam.target.strip():
        out["target"] = cam.target.strip()
    # spec/hud-border-v0.md: se omite si es todo cero + sin bg (comportamiento pre-v0) para no
    # ensuciar diffs de escenas viejas; se emite si hay algun borde no cero o bg_color_index >= 0.
    if not cam.hud_border.is_zero():
        hb: dict[str, Any] = {
            "top": int(cam.hud_border.top),
            "bottom": int(cam.hud_border.bottom),
            "left": int(cam.hud_border.left),
            "right": int(cam.hud_border.right),
        }
        if cam.hud_border.bg_color_index >= 0:
            hb["bg_color_index"] = int(cam.hud_border.bg_color_index)
        if cam.hud_border.overlay:
            hb["overlay"] = True
        out["hud_border"] = hb
    return out


def scene_camera_flat_row_fields(cam: SceneCameraConfig) -> dict[str, Any]:
    """Campos planos en fila de escena (manifest / estado del editor)."""
    out: dict[str, Any] = {
        "camera_mode": cam.mode,
        "camera_x": int(cam.x),
        "camera_y": int(cam.y),
        "camera_margin_x": int(cam.margin_x),
        "camera_margin_y": int(cam.margin_y),
        "camera_hud_border_top": int(cam.hud_border.top),
        "camera_hud_border_bottom": int(cam.hud_border.bottom),
        "camera_hud_border_left": int(cam.hud_border.left),
        "camera_hud_border_right": int(cam.hud_border.right),
        "camera_hud_border_bg_color_index": int(cam.hud_border.bg_color_index),
        "camera_hud_border_overlay": bool(cam.hud_border.overlay),
    }
    if cam.target.strip():
        out["camera_target"] = cam.target.strip()
    elif "camera_target" in out:
        pass
    return out


def apply_scene_camera_to_row(row: dict[str, Any], cam: SceneCameraConfig) -> None:
    row.update(scene_camera_flat_row_fields(cam))
    row["camera"] = scene_camera_to_json(cam)


def resolve_follow_target_xy(
    target: str,
    objects: list[dict[str, Any]],
) -> tuple[int, int] | None:
    objs = [o for o in objects if isinstance(o, dict) and str(o.get("id", "")).strip()]
    tid = target.strip()
    if tid:
        for o in objs:
            if str(o.get("id", "")).strip() == tid:
                try:
                    return int(o["x"]), int(o["y"])
                except (TypeError, ValueError, KeyError):
                    return None
        return None
    for pref in ("character", "player"):
        for o in objs:
            if str(o.get("id", "")).strip() == pref:
                try:
                    return int(o["x"]), int(o["y"])
                except (TypeError, ValueError, KeyError):
                    continue
    if objs:
        o = objs[0]
        try:
            return int(o["x"]), int(o["y"])
        except (TypeError, ValueError, KeyError):
            return None
    return None


def compute_follow_camera(
    actor_x: int,
    actor_y: int,
    cam_x: int,
    cam_y: int,
    *,
    world_w: int,
    world_h: int,
    viewport_w: int = VIEWPORT_PIXEL_W,
    viewport_h: int = VIEWPORT_PIXEL_H,
    margin_x: int = DEFAULT_CAMERA_MARGIN_X,
    margin_y: int = DEFAULT_CAMERA_MARGIN_Y,
) -> tuple[int, int]:
    """Scroll solo cuando el actor sale del rect interior (margen desde el borde del viewport)."""
    vw = max(1, int(viewport_w))
    vh = max(1, int(viewport_h))
    mx = clamp_camera_margin(margin_x, vw)
    my = clamp_camera_margin(margin_y, vh)
    cx, cy = int(cam_x), int(cam_y)
    ax, ay = int(actor_x), int(actor_y)

    if ax < cx + mx:
        cx = ax - mx
    elif ax > cx + (vw - 1) - mx:
        cx = ax - ((vw - 1) - mx)

    if ay < cy + my:
        cy = ay - my
    elif ay > cy + (vh - 1) - my:
        cy = ay - ((vh - 1) - my)

    return clamp_camera_position(cx, cy, world_w=world_w, world_h=world_h, viewport_w=vw, viewport_h=vh)


def resolve_scene_camera_viewport(
    cam: SceneCameraConfig,
    *,
    world_w: int,
    world_h: int,
    objects: list[dict[str, Any]],
    viewport_w: int = VIEWPORT_PIXEL_W,
    viewport_h: int = VIEWPORT_PIXEL_H,
) -> tuple[int, int]:
    ww, wh = max(1, int(world_w)), max(1, int(world_h))
    vw, vh = max(1, int(viewport_w)), max(1, int(viewport_h))
    if ww <= vw and wh <= vh:
        return 0, 0
    cx, cy = clamp_camera_position(
        cam.x, cam.y, world_w=ww, world_h=wh, viewport_w=vw, viewport_h=vh
    )
    if cam.mode == CAMERA_MODE_FIXED:
        return cx, cy
    pos = resolve_follow_target_xy(cam.target, objects)
    if pos is None:
        return cx, cy
    return compute_follow_camera(
        pos[0],
        pos[1],
        cx,
        cy,
        world_w=ww,
        world_h=wh,
        viewport_w=vw,
        viewport_h=vh,
        margin_x=cam.margin_x,
        margin_y=cam.margin_y,
    )


def draw_scene_hud_border_on_rgba(
    rgba: list[float],
    fw: int,
    fh: int,
    cam_x: int,
    cam_y: int,
    hud_border: HudBorder,
    *,
    viewport_w: int = VIEWPORT_PIXEL_W,
    viewport_h: int = VIEWPORT_PIXEL_H,
    fill_rgba: tuple[float, float, float, float] = _HUD_BORDER_RGBA,
    bg_solid_rgba: tuple[float, float, float, float] | None = None,
) -> None:
    """spec/hud-border-v0.md: tinte semitransparente sobre las cuatro franjas HUD dentro del
    viewport de camara actual. Marca visualmente al autor que area del framebuffer queda
    reservada para el HUD -- el codigo del cart no puede pintar el playfield desde hud_*,
    y los actores no se derraman a estas franjas.

    Si `bg_solid_rgba` viene, pinta las franjas SOLIDAS con ese color (opaco, no blend) -- eso
    refleja el `hud_border.bg_color_index` que el firmware pinta una vez al comenzar la escena.
    En ese caso NO se aplica el tinte azul semitransparente encima, para que el autor vea el
    color HUD real."""
    if fw <= 0 or fh <= 0 or len(rgba) < fw * fh * 4:
        return
    if hud_border.is_zero():
        return
    vw = max(1, int(viewport_w))
    vh = max(1, int(viewport_h))
    x0 = max(0, int(cam_x))
    y0 = max(0, int(cam_y))
    x1 = min(fw - 1, x0 + vw - 1)
    y1 = min(fh - 1, y0 + vh - 1)
    if x0 > x1 or y0 > y1:
        return
    r, g, b, a = fill_rgba
    top = int(hud_border.top)
    bottom = int(hud_border.bottom)
    left = int(hud_border.left)
    right = int(hud_border.right)
    # Modo solido (bg_color_index configurado): sobrescribe cada pixel HUD con el color, sin
    # blend. Alpha = 1 en la salida para que el fondo checker/damero del preview no se filtre.
    solid = bg_solid_rgba is not None
    if solid:
        sr, sg, sb, _sa = bg_solid_rgba  # type: ignore[misc]

    def paint_pixel(offset: int) -> None:
        if solid:
            rgba[offset] = sr
            rgba[offset + 1] = sg
            rgba[offset + 2] = sb
            rgba[offset + 3] = 1.0
        else:
            _blend_rgba_pixel_inplace(rgba, offset, r, g, b, a)

    # Franja arriba (fb): filas scene_y en [y1 - top + 1, y1].
    top_scene_lo = max(y0, y1 - top + 1)
    for sy in range(top_scene_lo, y1 + 1):
        y_fb = scene_y_to_framebuffer_y(sy, fb_h=fh)
        row_base = y_fb * fw * 4
        for x in range(x0, x1 + 1):
            paint_pixel(row_base + x * 4)
    # Franja abajo (fb): scene_y en [y0, y0 + bottom - 1].
    bot_scene_hi = min(y1, y0 + bottom - 1)
    for sy in range(y0, bot_scene_hi + 1):
        y_fb = scene_y_to_framebuffer_y(sy, fb_h=fh)
        row_base = y_fb * fw * 4
        for x in range(x0, x1 + 1):
            paint_pixel(row_base + x * 4)
    # Franjas laterales solo cubren las filas del playfield (no repintan esquinas ya
    # pintadas arriba/abajo -- se ven mas oscuras si se acumulan dos capas del mismo tinte).
    inner_lo = min(y1, y0 + bottom)
    inner_hi = max(y0, y1 - top)
    for sy in range(inner_lo, inner_hi + 1):
        y_fb = scene_y_to_framebuffer_y(sy, fb_h=fh)
        row_base = y_fb * fw * 4
        left_hi = min(x1, x0 + left - 1)
        for x in range(x0, left_hi + 1):
            paint_pixel(row_base + x * 4)
        right_lo = max(x0, x1 - right + 1)
        for x in range(right_lo, x1 + 1):
            paint_pixel(row_base + x * 4)


def draw_scene_camera_viewport_on_rgba(
    rgba: list[float],
    fw: int,
    fh: int,
    cam_x: int,
    cam_y: int,
    *,
    viewport_w: int = VIEWPORT_PIXEL_W,
    viewport_h: int = VIEWPORT_PIXEL_H,
    line_rgba: tuple[float, float, float, float] = _SCENE_CAMERA_RGBA,
) -> None:
    """Marco del viewport (esquina inf-izq cam_x,cam_y en espacio escena)."""
    if fw <= 0 or fh <= 0 or len(rgba) < fw * fh * 4:
        return
    vw = max(1, int(viewport_w))
    vh = max(1, int(viewport_h))
    if fw <= vw and fh <= vh:
        return
    x0 = max(0, int(cam_x))
    y0 = max(0, int(cam_y))
    x1 = min(fw - 1, x0 + vw - 1)
    y1 = min(fh - 1, y0 + vh - 1)
    lr, lg, lb, la = line_rgba
    border = 2
    yfb_top = scene_y_to_framebuffer_y(y1, fb_h=fh)
    yfb_bot = scene_y_to_framebuffer_y(y0, fb_h=fh)
    y_lo = min(yfb_top, yfb_bot)
    y_hi = max(yfb_top, yfb_bot)
    for t in range(border):
        for x in (x0 + t, x1 - t):
            if x < 0 or x >= fw:
                continue
            for y_fb in range(y_lo, y_hi + 1):
                _blend_rgba_pixel_inplace(rgba, (y_fb * fw + x) * 4, lr, lg, lb, la)
        y_scene_edges = (y0 + t, y1 - t)
        for sy in y_scene_edges:
            if sy < 0 or sy >= fh:
                continue
            y_fb = scene_y_to_framebuffer_y(sy, fb_h=fh)
            row_base = y_fb * fw * 4
            for x in range(x0, x1 + 1):
                if 0 <= x < fw:
                    _blend_rgba_pixel_inplace(rgba, row_base + x * 4, lr, lg, lb, la)
