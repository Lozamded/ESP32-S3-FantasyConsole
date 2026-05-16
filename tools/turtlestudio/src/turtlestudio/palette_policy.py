"""Convencion FantasyConsole: paleta de 32 indices; el 31 es siempre transparente."""

from __future__ import annotations

# Indice 32º color (base 0): reservado en cartucho, firmware y herramientas.
PALETTE_SIZE = 32
TRANSPARENT_PALETTE_INDEX = 31
MAX_OPAQUE_PALETTE_INDEX = 30

# Alias historico en manifest / bundle.
DEFAULT_TRANSPARENT_INDEX = TRANSPARENT_PALETTE_INDEX


def is_transparent_palette_index(index: int) -> bool:
    return int(index) == TRANSPARENT_PALETTE_INDEX


def clamp_palette_index(index: int, *, palette_len: int | None = None) -> int:
    """Acota a un indice de archivo de paleta (0..len-1 o 0..31)."""
    try:
        v = int(index)
    except (TypeError, ValueError):
        v = 0
    cap = PALETTE_SIZE - 1
    if palette_len is not None and palette_len > 0:
        cap = min(cap, int(palette_len) - 1)
    return max(0, min(cap, v))


def clamp_paint_palette_index(index: int, *, palette_len: int | None = None) -> int:
    """Indice elegible para pincel, fondo solido, etc. (nunca 31)."""
    v = clamp_palette_index(index, palette_len=palette_len)
    if is_transparent_palette_index(v):
        if palette_len is not None and palette_len > 0:
            return min(MAX_OPAQUE_PALETTE_INDEX, int(palette_len) - 1)
        return MAX_OPAQUE_PALETTE_INDEX
    return v


def clamp_pixel_storage_index(index: int) -> int:
    """Indice en matrices / JSON: permite 31 como transparente."""
    try:
        v = int(index)
    except (TypeError, ValueError):
        v = 0
    return max(0, min(TRANSPARENT_PALETTE_INDEX, v))


def clamp_transparent_index(_raw: object = None) -> int:
    """Manifest y bundle: transparente fijo en 31."""
    return TRANSPARENT_PALETTE_INDEX


def swatch_indices_for_palette(palette_len: int) -> list[int]:
    """Indices a mostrar como muestrario seleccionable (sin el 31)."""
    n = max(0, int(palette_len))
    if n <= 0:
        return []
    cap = min(n, PALETTE_SIZE)
    return [i for i in range(cap) if not is_transparent_palette_index(i)]


def resolve_palette_color(
    index: int,
    rgbs: list[tuple[float, float, float]],
) -> tuple[float, float, float] | None:
    """
    Color RGB 0..1 para un indice, o None si es transparente / fuera de rango.
    """
    if is_transparent_palette_index(index):
        return None
    if not rgbs:
        return (0.0, 0.0, 0.0)
    ci = clamp_palette_index(index, palette_len=len(rgbs))
    if is_transparent_palette_index(ci):
        return None
    return rgbs[ci]
