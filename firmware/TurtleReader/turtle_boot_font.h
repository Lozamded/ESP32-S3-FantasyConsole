#pragma once

#include <stdint.h>

/**
 * Fuente 3x5 embebida en el firmware (no viene de un .tfn/cartucho): la usan solo los
 * mensajes de arranque (montaje de SD, error de cartucho) que deben poder dibujarse
 * *antes* de que exista un bundle con su propia fuente, o cuando el cartucho nunca
 * llega a cargar. Ver turtle_font.h para la fuente normal basada en cartucho.
 *
 * Charset: espacio, A-Z, 0-9, ". , : ! ' -". Caracteres fuera de ese set se omiten
 * (avanzan como espacio en blanco).
 */

/**
 * Dibuja `text` centrado en (center_x, center_y) (coords escena, spec/scene-v0.md).
 * `text` puede incluir '\n' para varias lineas; el bloque completo se centra
 * verticalmente y cada linea se centra horizontalmente por separado. `scale` es el
 * tamano de cada "pixel" logico del glifo (glifo base 3x5).
 */
void turtle_boot_text_draw_centered(int center_x, int center_y, const char* text,
                                    uint8_t color_index, int scale);
