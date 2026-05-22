#pragma once

#include <stddef.h>
#include <stdint.h>

/**
 * Decodifica asset binario exportado (.tbg fondo, .tsp sprite).
 * Fila 0 = arriba; indices 0..31. Devuelve false si magic/version/modo invalido.
 */
bool turtle_asset_bin_decode_indexed(const uint8_t* data, size_t len, int expect_w, int expect_h,
                                     uint8_t* out_rows_top_first, int row_stride);
