"""Camara de escena (viewport 164×124, default S3): posicion, objetivo y margenes de scroll."""

from __future__ import annotations

from dataclasses import dataclass
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

_SCENE_CAMERA_RGBA = (1.0, 0.55, 0.2, 0.92)


@dataclass(frozen=True)
class SceneCameraConfig:
    mode: str = CAMERA_MODE_FOLLOW
    x: int = 0
    y: int = 0
    target: str = ""
    margin_x: int = DEFAULT_CAMERA_MARGIN_X
    margin_y: int = DEFAULT_CAMERA_MARGIN_Y


def _clamp_int(v: object, lo: int, hi: int, *, default: int) -> int:
    try:
        n = int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = default
    return max(lo, min(hi, n))


def clamp_camera_margin(margin: int, viewport_size: int) -> int:
    cap = max(0, (max(1, int(viewport_size)) - 1) // 2)
    return max(0, min(cap, int(margin)))


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
    return SceneCameraConfig(
        mode=mode,
        x=x,
        y=y,
        target=target,
        margin_x=clamp_camera_margin(mx, VIEWPORT_PIXEL_W),
        margin_y=clamp_camera_margin(my, VIEWPORT_PIXEL_H),
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
    return out


def scene_camera_flat_row_fields(cam: SceneCameraConfig) -> dict[str, Any]:
    """Campos planos en fila de escena (manifest / estado del editor)."""
    out: dict[str, Any] = {
        "camera_mode": cam.mode,
        "camera_x": int(cam.x),
        "camera_y": int(cam.y),
        "camera_margin_x": int(cam.margin_x),
        "camera_margin_y": int(cam.margin_y),
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
