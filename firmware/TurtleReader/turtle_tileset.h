#pragma once

#include <stddef.h>
#include <stdint.h>

#include "turtle_tile_collision.h"

struct TurtleTileset {
  uint8_t tile_px;
  uint16_t tile_count;
  uint8_t* pixels;
  bool in_psram;
  TurtleTileCollEntry coll[kTurtleTileCollMax];
  /** true si algun tile del set tiene collision != none (ver turtle_tile_collision.cpp). */
  bool has_solid_tiles;
  /** version del .tts origen (0 = sin bloque de colision embebido, 1 = con bloque). */
  uint8_t format_version;
};

/** Decodifica buffer .tts (o archivo SD ya cargado). */
bool turtle_tileset_load_tts(const uint8_t* data, size_t len, TurtleTileset* out);

void turtle_tileset_free(TurtleTileset* ts);

/** Puntero a tile_px×tile_px indices; null si index invalido. */
const uint8_t* turtle_tileset_tile(const TurtleTileset* ts, int index);
