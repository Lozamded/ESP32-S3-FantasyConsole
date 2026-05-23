#pragma once

#include <stddef.h>
#include <stdint.h>

/**
 * Decodifica asset binario exportado (.tbg fondo, .tsp sprite v0/v1).
 * Fila 0 = arriba; indices 0..31. Devuelve false si magic/version/modo invalido.
 */
bool turtle_asset_bin_decode_indexed(const uint8_t* data, size_t len, int expect_w, int expect_h,
                                     uint8_t* out_rows_top_first, int row_stride);

/** Fotogramas en .tsp v1; v0 devuelve 1. 0 si invalido. */
int turtle_asset_bin_sprite_frame_count(const uint8_t* data, size_t len);

/**
 * Decodifica un fotograma de .tsp (v0 = solo indice 0).
 * chunk interno v1: [mode][payload...]
 */
bool turtle_asset_bin_decode_sprite_frame(const uint8_t* data, size_t len, int frame_index,
                                          int expect_w, int expect_h,
                                          uint8_t* out_rows_top_first, int row_stride);
