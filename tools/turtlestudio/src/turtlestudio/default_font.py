"""Glifos de la fuente por defecto sembrada en cada proyecto nuevo.

Mismo diseno de pixeles (base 3x5) que usa el firmware para sus mensajes de
arranque antes de que exista un cartucho cargado
(`firmware/TurtleReader/turtle_boot_font.cpp`) -- mantener ambas tablas
sincronizadas si se edita una de las dos. Aqui se reempaqueta como fuente
`objects/Fonts/default.json` (glifo cuadrado glyph_px=8, formato normal de
`fonts.py`) para que un proyecto nuevo tenga texto utilizable con
text()/text_width() sin que el dev tenga que dibujar una fuente primero;
pueden agregar mas fuentes propias con el editor de fuentes normal.
"""

from __future__ import annotations

from turtlestudio.fonts import DEFAULT_GLYPH_PX, LATIN_CHARSET

_GLYPH_W = 3
_GLYPH_H = 5
# Margen fijo al centrar el glifo base 3x5 dentro del glyph_px x glyph_px de la
# fuente (pensado para glyph_px=8, el default de fonts.py).
_MARGIN_X = 2
_MARGIN_Y = 1

# Cada fila = 3 bits (bit mas alto = columna izquierda). Las minusculas
# reusan el glifo de su mayuscula (v0: sin formas distintas para minusculas).
_SHAPES: dict[str, tuple[int, int, int, int, int]] = {
    " ": (0b000, 0b000, 0b000, 0b000, 0b000),
    "0": (0b111, 0b101, 0b101, 0b101, 0b111),
    "1": (0b010, 0b110, 0b010, 0b010, 0b111),
    "2": (0b111, 0b001, 0b111, 0b100, 0b111),
    "3": (0b111, 0b001, 0b111, 0b001, 0b111),
    "4": (0b101, 0b101, 0b111, 0b001, 0b001),
    "5": (0b111, 0b100, 0b111, 0b001, 0b111),
    "6": (0b111, 0b100, 0b111, 0b101, 0b111),
    "7": (0b111, 0b001, 0b010, 0b010, 0b010),
    "8": (0b111, 0b101, 0b111, 0b101, 0b111),
    "9": (0b111, 0b101, 0b111, 0b001, 0b111),
    "A": (0b010, 0b101, 0b111, 0b101, 0b101),
    "B": (0b110, 0b101, 0b110, 0b101, 0b110),
    "C": (0b011, 0b100, 0b100, 0b100, 0b011),
    "D": (0b110, 0b101, 0b101, 0b101, 0b110),
    "E": (0b111, 0b100, 0b111, 0b100, 0b111),
    "F": (0b111, 0b100, 0b111, 0b100, 0b100),
    "G": (0b011, 0b100, 0b101, 0b101, 0b011),
    "H": (0b101, 0b101, 0b111, 0b101, 0b101),
    "I": (0b111, 0b010, 0b010, 0b010, 0b111),
    "J": (0b001, 0b001, 0b001, 0b101, 0b010),
    "K": (0b101, 0b110, 0b100, 0b110, 0b101),
    "L": (0b100, 0b100, 0b100, 0b100, 0b111),
    "M": (0b101, 0b111, 0b111, 0b101, 0b101),
    "N": (0b101, 0b111, 0b111, 0b111, 0b101),
    "O": (0b010, 0b101, 0b101, 0b101, 0b010),
    "P": (0b110, 0b101, 0b110, 0b100, 0b100),
    "Q": (0b010, 0b101, 0b101, 0b111, 0b011),
    "R": (0b110, 0b101, 0b110, 0b110, 0b101),
    "S": (0b011, 0b100, 0b010, 0b001, 0b110),
    "T": (0b111, 0b010, 0b010, 0b010, 0b010),
    "U": (0b101, 0b101, 0b101, 0b101, 0b111),
    "V": (0b101, 0b101, 0b101, 0b101, 0b010),
    "W": (0b101, 0b101, 0b111, 0b111, 0b101),
    "X": (0b101, 0b101, 0b010, 0b101, 0b101),
    "Y": (0b101, 0b101, 0b010, 0b010, 0b010),
    "Z": (0b111, 0b001, 0b010, 0b100, 0b111),
    ".": (0b000, 0b000, 0b000, 0b000, 0b010),
    ",": (0b000, 0b000, 0b000, 0b010, 0b100),
    ":": (0b000, 0b010, 0b000, 0b010, 0b000),
    ";": (0b000, 0b010, 0b000, 0b010, 0b100),
    "!": (0b010, 0b010, 0b010, 0b000, 0b010),
    "?": (0b111, 0b001, 0b010, 0b000, 0b010),
    "'": (0b010, 0b010, 0b000, 0b000, 0b000),
    "-": (0b000, 0b000, 0b111, 0b000, 0b000),
}


def _shape_for(ch: str) -> tuple[int, int, int, int, int]:
    if ch in _SHAPES:
        return _SHAPES[ch]
    upper = ch.upper()
    return _SHAPES.get(upper, _SHAPES[" "])


def default_font_glyph_rows(
    ch: str, px: int, *, ink_index: int, bg_index: int
) -> list[list[int]]:
    """Matriz `px`x`px` (fila 0 arriba) para `ch`; fondo `bg_index` (31 = transparente)."""
    shape = _shape_for(ch)
    rows = [[bg_index for _ in range(px)] for _ in range(px)]
    for ry in range(_GLYPH_H):
        py = _MARGIN_Y + ry
        if py < 0 or py >= px:
            continue
        bits = shape[ry]
        for cx in range(_GLYPH_W):
            if not (bits & (1 << (_GLYPH_W - 1 - cx))):
                continue
            pxx = _MARGIN_X + cx
            if 0 <= pxx < px:
                rows[py][pxx] = ink_index
    return rows


def default_font_glyphs(
    px: int = DEFAULT_GLYPH_PX, *, ink_index: int = 7, bg_index: int = 31
) -> dict[str, list[list[int]]]:
    """Glifos (mapa caracter -> filas) para toda `LATIN_CHARSET`, fuente por defecto."""
    return {
        ch: default_font_glyph_rows(ch, px, ink_index=ink_index, bg_index=bg_index)
        for ch in LATIN_CHARSET
    }
