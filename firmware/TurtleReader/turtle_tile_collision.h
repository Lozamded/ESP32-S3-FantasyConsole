#pragma once

#include <stdbool.h>
#include <stdint.h>

struct TurtleTileset;

/** Por indice de tile (alineado con .tts / tiles[] del JSON). */
enum TurtleTileCollKind : uint8_t {
  TURTLE_TILE_COLL_SOLID = 0,
  TURTLE_TILE_COLL_NONE = 1,
  TURTLE_TILE_COLL_AABB = 2,
};

enum TurtleTileOnewayDir : uint8_t {
  TURTLE_TILE_ONEWAY_UP = 0,
  TURTLE_TILE_ONEWAY_DOWN = 1,
  TURTLE_TILE_ONEWAY_LEFT = 2,
  TURTLE_TILE_ONEWAY_RIGHT = 3,
};

struct TurtleTileCollEntry {
  uint8_t kind;
  uint8_t oneway;
  uint8_t oneway_dir;
  int16_t x0;
  int16_t y0;
  int16_t x1;
  int16_t y1;
};

constexpr int kTurtleTileCollMax = 256;

void turtle_tile_collision_defaults(struct TurtleTileset* ts);

/** Parsea tiles[] desde tiles/<id>.json (o JSON inline del bundle). */
bool turtle_tile_collision_parse_json(struct TurtleTileset* ts, const char* json,
                                    const char* json_end);

/** Recalcula TurtleTileset::has_solid_tiles a partir de ts->coll[] actual. */
void turtle_tile_collision_recompute_has_solid(struct TurtleTileset* ts);

/**
 * true si el tile bloquea el AABB del actor en mundo.
 * tw*: bounds de la celda en espacio escena (Y arriba).
 * step_dx/dy: paso que se intenta (oneway). ground_probe ignora oneway.
 */
bool turtle_tile_collision_blocks(const struct TurtleTileCollEntry* e, int tile_px, int twx0,
                                  int twy0, int twx1, int twy1, int ax0, int ay0, int ax1,
                                  int ay1, int step_dx, int step_dy, bool ground_probe);
