"""Bandas de parallax horizontal (spec/scene-v0.md): rango Y de escena -> factor de scroll.

`row["parallax_bands"]` es una lista (0..MAX_PARALLAX_BANDS) que el editor administra por
alta/baja (igual que `row["objects"]`), no filas fijas: presencia en la lista = banda activa.
El grupo de la UI tiene un checkbox que habilita/deshabilita la lista entera para la escena.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from turtlestudio.scene_tiles import _blend_rgba_pixel_inplace, scene_y_to_framebuffer_y

MAX_PARALLAX_BANDS = 8
DEFAULT_PARALLAX_X = 1.0
MIN_PARALLAX_X = 0.0
MAX_PARALLAX_X = 2.0


@dataclass(frozen=True)
class SceneParallaxBand:
    y0: int = 0
    y1: int = 0
    parallax_x: float = DEFAULT_PARALLAX_X
    fixed: bool = False
    repeat_x: bool = False


def _clamp_int(v: object, lo: int, hi: int, *, default: int) -> int:
    try:
        n = int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = default
    return max(lo, min(hi, n))


def _clamp_float(v: object, lo: float, hi: float, *, default: float) -> float:
    try:
        n = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = default
    return max(lo, min(hi, n))


def clamp_parallax_band(band: SceneParallaxBand, *, world_h: int) -> SceneParallaxBand:
    """Ordena y0<=y1 y acota ambos a [0, world_h-1]; acota parallax_x a 0.0..2.0."""
    max_y = max(0, int(world_h) - 1)
    y0, y1 = band.y0, band.y1
    if y0 > y1:
        y0, y1 = y1, y0
    y0 = max(0, min(max_y, y0))
    y1 = max(0, min(max_y, y1))
    px = max(MIN_PARALLAX_X, min(MAX_PARALLAX_X, band.parallax_x))
    return SceneParallaxBand(y0=y0, y1=y1, parallax_x=px, fixed=band.fixed, repeat_x=band.repeat_x)


def parse_parallax_band(raw: Any, *, world_h: int) -> SceneParallaxBand | None:
    if not isinstance(raw, dict):
        return None
    band = SceneParallaxBand(
        y0=_clamp_int(raw.get("y0", 0), -1_000_000, 1_000_000, default=0),
        y1=_clamp_int(raw.get("y1", 0), -1_000_000, 1_000_000, default=0),
        parallax_x=_clamp_float(
            raw.get("parallax_x", DEFAULT_PARALLAX_X),
            MIN_PARALLAX_X,
            MAX_PARALLAX_X,
            default=DEFAULT_PARALLAX_X,
        ),
        fixed=bool(raw.get("fixed", False)),
        repeat_x=bool(raw.get("repeat_x", False)),
    )
    return clamp_parallax_band(band, world_h=world_h)


def parse_scene_parallax_bands_from_row(
    row: dict[str, Any], *, world_h: int
) -> list[SceneParallaxBand]:
    """Lee `row["parallax_bands"]`; ausente/vacio = sin bandas (comportamiento de hoy)."""
    raw_bands = row.get("parallax_bands")
    if not isinstance(raw_bands, list):
        return []
    out: list[SceneParallaxBand] = []
    for raw in raw_bands:
        band = parse_parallax_band(raw, world_h=world_h)
        if band is not None:
            out.append(band)
        if len(out) >= MAX_PARALLAX_BANDS:
            break
    return out


def scene_parallax_band_to_json(band: SceneParallaxBand) -> dict[str, Any]:
    out: dict[str, Any] = {
        "y0": int(band.y0),
        "y1": int(band.y1),
        "parallax_x": float(band.parallax_x),
    }
    if band.fixed:
        out["fixed"] = True
    if band.repeat_x:
        out["repeat_x"] = True
    return out


def scene_parallax_bands_to_json(bands: list[SceneParallaxBand]) -> list[dict[str, Any]]:
    return [scene_parallax_band_to_json(b) for b in bands[:MAX_PARALLAX_BANDS]]


def apply_scene_parallax_bands_to_row(
    row: dict[str, Any], bands: list[SceneParallaxBand]
) -> None:
    """Escribe `row["parallax_bands"]`; lista vacia limpia el campo (sin bandas)."""
    if bands:
        row["parallax_bands"] = scene_parallax_bands_to_json(bands)
    else:
        row.pop("parallax_bands", None)


def find_parallax_band(y: int, bands: list[SceneParallaxBand]) -> SceneParallaxBand | None:
    for band in bands:
        if band.y0 <= y <= band.y1:
            return band
    return None


_PARALLAX_BAND_RGBA = (0.25, 0.85, 0.75, 0.16)
_PARALLAX_BAND_BORDER_RGBA = (0.25, 0.85, 0.75, 0.55)
_PARALLAX_BAND_SELECTED_RGBA = (1.0, 0.95, 0.25, 0.9)
_PARALLAX_BAND_REPEAT_HATCH_RGBA = (0.9, 1.0, 0.95, 0.4)
_PARALLAX_BAND_REPEAT_HATCH_SPACING = 8


def draw_scene_parallax_bands_on_rgba(
    rgba: list[float],
    fw: int,
    fh: int,
    bands: list[SceneParallaxBand],
    *,
    selected_index: int | None = None,
    band_rgba: tuple[float, float, float, float] = _PARALLAX_BAND_RGBA,
    border_rgba: tuple[float, float, float, float] = _PARALLAX_BAND_BORDER_RGBA,
    selected_border_rgba: tuple[float, float, float, float] = _PARALLAX_BAND_SELECTED_RGBA,
    repeat_hatch_rgba: tuple[float, float, float, float] = _PARALLAX_BAND_REPEAT_HATCH_RGBA,
    repeat_hatch_spacing: int = _PARALLAX_BAND_REPEAT_HATCH_SPACING,
) -> None:
    """Superpone cada banda como una franja horizontal translucida (rango y0..y1, espacio
    escena) con bordes, para que sea obvio a que filas de la Capa 1 afecta cada una. La banda
    seleccionada en la lista del editor se resalta con un borde mas grueso y brillante. Las
    bandas con `repeat_x` llevan ademas un rayado diagonal, para distinguir de un vistazo
    cuales repiten la imagen horizontalmente."""
    if fw <= 0 or fh <= 0 or len(rgba) < fw * fh * 4:
        return
    for i, band in enumerate(bands):
        y0 = max(0, min(fh - 1, int(band.y0)))
        y1 = max(0, min(fh - 1, int(band.y1)))
        if y0 > y1:
            y0, y1 = y1, y0
        yfb_top = scene_y_to_framebuffer_y(y1, fb_h=fh)
        yfb_bot = scene_y_to_framebuffer_y(y0, fb_h=fh)
        y_lo, y_hi = min(yfb_top, yfb_bot), max(yfb_top, yfb_bot)

        fr, fg, fb_, fa = band_rgba
        hr, hg, hb, ha = repeat_hatch_rgba
        spacing = max(2, int(repeat_hatch_spacing))
        for y_fb in range(y_lo, y_hi + 1):
            row_base = y_fb * fw * 4
            for x in range(fw):
                _blend_rgba_pixel_inplace(rgba, row_base + x * 4, fr, fg, fb_, fa)
                if band.repeat_x and (x + y_fb) % spacing == 0:
                    _blend_rgba_pixel_inplace(rgba, row_base + x * 4, hr, hg, hb, ha)

        is_selected = selected_index == i
        br, bg, bb, ba = selected_border_rgba if is_selected else border_rgba
        thickness = 2 if is_selected else 1
        for t in range(thickness):
            for y_fb in (y_lo + t, y_hi - t):
                if 0 <= y_fb < fh:
                    row_base = y_fb * fw * 4
                    for x in range(fw):
                        _blend_rgba_pixel_inplace(rgba, row_base + x * 4, br, bg, bb, ba)
