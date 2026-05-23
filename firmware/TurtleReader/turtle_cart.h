#pragma once

#include <stddef.h>
#include <stdint.h>

/** Buffer de cartucho cargado desde SD (preferir PSRAM si esta disponible). */
struct TurtleCartBuffer {
  char* data;
  size_t len;
  bool in_psram;
};

/**
 * Lee el archivo completo; `data` es null si falla (SD, OOM).
 * @param quiet Si true, menos lineas Serial (assets en cadena).
 */
bool turtle_cart_load_sd_file(const char* path, TurtleCartBuffer* out, bool quiet = false);

void turtle_cart_free(TurtleCartBuffer* buf);

/** Busca `---FILE:<relPath>---` y devuelve rango hasta `---END---` (sin copiar). */
bool turtle_cart_extract_embedded(const TurtleCartBuffer* cart, const char* rel_path,
                                const char** out_begin, size_t* out_len);

/** Valor de cabecera en una linea `KEY:valor` (copia corta a `out`, max 127 chars). */
bool turtle_cart_header_value(const TurtleCartBuffer* cart, const char* key, char* out,
                              size_t out_cap);

/** Texto entre `PALETTE:` y el primer `---FILE:` (puede estar vacio). */
bool turtle_cart_extract_palette(const TurtleCartBuffer* cart, const char** out_begin,
                                 size_t* out_len);

/**
 * Carga `studio/project_bundle.json` segun BUNDLE_FILE: del cartucho, o embebido (legacy).
 * `cart` puede ser solo la cabecera + ENTRY (pequeno).
 */
bool turtle_cart_load_bundle_for_cart(const TurtleCartBuffer* cart, TurtleCartBuffer* out,
                                      bool quiet = false);
