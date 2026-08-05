#pragma once

#include <stddef.h>
#include <stdint.h>

/**
 * Fuente bitmap cargada desde .tfn (ver spec/asset-bin-v0.md). Glifos cuadrados
 * glyph_px x glyph_px, indices de paleta 0..31, fila 0 = arriba (igual que sprites/tiles).
 *
 * El orden de glifos es implicito en el .tfn (no incluye el charset): coincide con
 * turtle_font_charset_index() en turtle_font.cpp, que debe mantenerse sincronizado con
 * LATIN_CHARSET en tools/turtlestudio/src/turtlestudio/fonts.py. Ver nota en
 * spec/asset-bin-v0.md.
 */
struct TurtleFont {
  uint16_t glyph_px;
  uint16_t line_height;
  uint16_t baseline;
  uint16_t glyph_count;
  uint8_t* pixels;    // glyph_count * glyph_px * glyph_px bytes, indices 0..31
  uint8_t* advances;  // glyph_count bytes
  bool in_psram;
};

/** Decodifica buffer .tfn (o archivo SD ya cargado). */
bool turtle_font_load_tfn(const uint8_t* data, size_t len, TurtleFont* out);

void turtle_font_free(TurtleFont* f);

/** Puntero a glyph_px×glyph_px indices (fila 0 = arriba); null si index invalido. */
const uint8_t* turtle_font_glyph_pixels(const TurtleFont* f, int glyph_index);

/** Avance en px del glifo; 0 si index invalido. */
uint8_t turtle_font_glyph_advance(const TurtleFont* f, int glyph_index);

/**
 * Indice de glifo para un caracter, segun el charset fijo v0 (espacio, A-Z, a-z, 0-9,
 * puntuacion minima). -1 si el caracter no esta en el charset.
 */
int turtle_font_charset_index(char ch);

/**
 * Ancho en px de `str` (suma de avances). Caracteres fuera del charset avanzan
 * como si fueran un glifo en blanco (glyph_px). 0 si f/str son null.
 */
int turtle_font_measure(const TurtleFont* f, const char* str);

/**
 * Dibuja `str` en escena: (sx, sy) = esquina inferior izquierda del primer glifo
 * (misma convencion que turtle_gpu_fill_rect_scene/spix — ver spec/scene-v0.md),
 * una sola linea (sin wrap ni saltos de linea; v0). Devuelve el ancho total dibujado.
 */
int turtle_font_draw_scene(const TurtleFont* f, int sx, int sy, const char* str,
                           uint8_t transparent_index);

/**
 * Igual que turtle_font_draw_scene, pero pinta cada pixel no transparente con
 * `tint_color_index` en vez del indice propio del glifo (util para reusar una misma
 * fuente en varios colores de HUD sin duplicar el asset). Mismas posiciones de pixel
 * pixel-a-pixel que la version sin tint (misma formula fila->y de escena).
 */
int turtle_font_draw_scene_tint(const TurtleFont* f, int sx, int sy, const char* str,
                                uint8_t transparent_index, uint8_t tint_color_index);
