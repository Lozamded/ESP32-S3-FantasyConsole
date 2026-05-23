#pragma once

#include <stddef.h>
#include <stdint.h>

struct TurtleTileset {
  uint8_t tile_px;
  uint16_t tile_count;
  uint8_t* pixels;
  bool in_psram;
};

/** Decodifica buffer .tts (o archivo SD ya cargado). */
bool turtle_tileset_load_tts(const uint8_t* data, size_t len, TurtleTileset* out);

void turtle_tileset_free(TurtleTileset* ts);

/** Puntero a tile_px×tile_px indices; null si index invalido. */
const uint8_t* turtle_tileset_tile(const TurtleTileset* ts, int index);
