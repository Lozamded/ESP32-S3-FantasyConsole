#include "turtle_tile_collision.h"

#include "turtle_tileset.h"

#include <Arduino.h>
#include <ctype.h>
#include <string.h>

namespace {

constexpr int kCollMax = kTurtleTileCollMax;

static const char* strstr_bounded(const char* s, const char* e, const char* needle) {
  if (!s || !e || !needle || !needle[0]) {
    return nullptr;
  }
  const size_t nlen = strlen(needle);
  if (nlen == 0 || static_cast<size_t>(e - s) < nlen) {
    return nullptr;
  }
  for (const char* p = s; p + nlen <= e; ++p) {
    if (memcmp(p, needle, nlen) == 0) {
      return p;
    }
  }
  return nullptr;
}

static const char* json_object_end(const char* p) {
  if (!p || *p != '{') {
    return nullptr;
  }
  int depth = 0;
  for (const char* q = p; *q; ++q) {
    if (*q == '{') {
      ++depth;
    } else if (*q == '}') {
      --depth;
      if (depth == 0) {
        return q + 1;
      }
    }
  }
  return nullptr;
}

static bool parse_int_bounded(const char* p, const char* e, int* out) {
  if (!p || !e || !out || p >= e) {
    return false;
  }
  while (p < e && isspace(static_cast<unsigned char>(*p))) {
    ++p;
  }
  if (p >= e) {
    return false;
  }
  bool neg = false;
  if (*p == '-') {
    neg = true;
    ++p;
  }
  if (p >= e || !isdigit(static_cast<unsigned char>(*p))) {
    return false;
  }
  long v = 0;
  while (p < e && isdigit(static_cast<unsigned char>(*p))) {
    v = v * 10 + (*p - '0');
    ++p;
  }
  *out = neg ? static_cast<int>(-v) : static_cast<int>(v);
  return true;
}

static bool json_extract_int_for_key(const char* s, const char* e, const char* key_name, int* outv) {
  char pattern[40];
  snprintf(pattern, sizeof pattern, "\"%s\"", key_name);
  const char* p = strstr_bounded(s, e, pattern);
  if (!p) {
    return false;
  }
  p += strlen(pattern);
  while (p < e && isspace(static_cast<unsigned char>(*p))) {
    ++p;
  }
  if (p >= e || *p != ':') {
    return false;
  }
  ++p;
  return parse_int_bounded(p, e, outv);
}

static bool json_extract_bool_for_key(const char* s, const char* e, const char* key_name, bool* out) {
  char pattern[40];
  snprintf(pattern, sizeof pattern, "\"%s\"", key_name);
  const char* p = strstr_bounded(s, e, pattern);
  if (!p) {
    return false;
  }
  p += strlen(pattern);
  while (p < e && isspace(static_cast<unsigned char>(*p))) {
    ++p;
  }
  if (p >= e || *p != ':') {
    return false;
  }
  ++p;
  while (p < e && isspace(static_cast<unsigned char>(*p))) {
    ++p;
  }
  if (p + 4 <= e && memcmp(p, "true", 4) == 0) {
    *out = true;
    return true;
  }
  if (p + 5 <= e && memcmp(p, "false", 5) == 0) {
    *out = false;
    return true;
  }
  int v = 0;
  if (parse_int_bounded(p, e, &v)) {
    *out = v != 0;
    return true;
  }
  return false;
}

static bool json_extract_string_for_key(const char* s, const char* e, const char* key_name, char* out,
                                        size_t out_cap) {
  char pattern[40];
  snprintf(pattern, sizeof pattern, "\"%s\"", key_name);
  const char* p = strstr_bounded(s, e, pattern);
  if (!p || !out || out_cap < 2) {
    return false;
  }
  out[0] = '\0';
  p += strlen(pattern);
  while (p < e && isspace(static_cast<unsigned char>(*p))) {
    ++p;
  }
  if (p >= e || *p != ':') {
    return false;
  }
  ++p;
  while (p < e && isspace(static_cast<unsigned char>(*p))) {
    ++p;
  }
  if (p >= e || *p != '"') {
    return false;
  }
  ++p;
  size_t n = 0;
  while (p < e && *p != '"' && n + 1 < out_cap) {
    out[n++] = *p++;
  }
  out[n] = '\0';
  return n > 0;
}

static int clamp_coord(int v) {
  if (v < -256) {
    return -256;
  }
  if (v > 256) {
    return 256;
  }
  return v;
}

static uint8_t normalize_oneway_dir(const char* s) {
  if (!s || !s[0]) {
    return TURTLE_TILE_ONEWAY_UP;
  }
  if (strcmp(s, "down") == 0 || strcmp(s, "abajo") == 0) {
    return TURTLE_TILE_ONEWAY_DOWN;
  }
  if (strcmp(s, "left") == 0 || strcmp(s, "izquierda") == 0) {
    return TURTLE_TILE_ONEWAY_LEFT;
  }
  if (strcmp(s, "right") == 0 || strcmp(s, "derecha") == 0) {
    return TURTLE_TILE_ONEWAY_RIGHT;
  }
  return TURTLE_TILE_ONEWAY_UP;
}

static void entry_defaults(TurtleTileCollEntry* e) {
  e->kind = TURTLE_TILE_COLL_SOLID;
  e->oneway = 0;
  e->oneway_dir = TURTLE_TILE_ONEWAY_UP;
  e->x0 = 0;
  e->y0 = 0;
  e->x1 = 0;
  e->y1 = 0;
}

static void read_oneway_from(const char* obj_s, const char* obj_e, bool* oneway,
                             uint8_t* oneway_dir) {
  bool ow = false;
  if (json_extract_bool_for_key(obj_s, obj_e, "oneway", &ow)) {
    *oneway = ow;
  }
  char dir[16];
  if (json_extract_string_for_key(obj_s, obj_e, "oneway_direction", dir, sizeof dir)) {
    *oneway_dir = normalize_oneway_dir(dir);
  } else if (json_extract_string_for_key(obj_s, obj_e, "oneway_dir", dir, sizeof dir)) {
    *oneway_dir = normalize_oneway_dir(dir);
  }
}

static bool points_span_aabb(const char* coll_s, const char* coll_e, int* x0, int* y0, int* x1,
                             int* y1) {
  const char* pk = strstr_bounded(coll_s, coll_e, "\"points\"");
  if (!pk) {
    return false;
  }
  const char* p = pk + 8;
  while (p < coll_e && *p != '[') {
    ++p;
  }
  if (p >= coll_e) {
    return false;
  }
  ++p;
  int minx = 256;
  int maxx = -256;
  int miny = 256;
  int maxy = -256;
  int found = 0;
  while (p < coll_e && *p != ']') {
    while (p < coll_e && (isspace(static_cast<unsigned char>(*p)) || *p == ',')) {
      ++p;
    }
    if (p >= coll_e || *p == ']') {
      break;
    }
    if (*p != '[') {
      break;
    }
    ++p;
    int vx = 0;
    int vy = 0;
    int field = 0;
    while (p < coll_e && *p != ']') {
      while (p < coll_e && (isspace(static_cast<unsigned char>(*p)) || *p == ',')) {
        ++p;
      }
      if (p >= coll_e || *p == ']') {
        break;
      }
      int v = 0;
      if (!parse_int_bounded(p, coll_e, &v)) {
        break;
      }
      while (p < coll_e && (*p == '-' || isdigit(static_cast<unsigned char>(*p)))) {
        ++p;
      }
      if (field == 0) {
        vx = v;
        field = 1;
      } else {
        vy = v;
        field = 2;
        break;
      }
    }
    if (field >= 2) {
      vx = clamp_coord(vx);
      vy = clamp_coord(vy);
      if (vx < minx) {
        minx = vx;
      }
      if (vx > maxx) {
        maxx = vx;
      }
      if (vy < miny) {
        miny = vy;
      }
      if (vy > maxy) {
        maxy = vy;
      }
      ++found;
    }
    while (p < coll_e && *p != ']') {
      ++p;
    }
    if (p < coll_e && *p == ']') {
      ++p;
    }
  }
  if (found < 1 || maxx < minx) {
    return false;
  }
  *x0 = minx;
  *y0 = miny;
  *x1 = maxx;
  *y1 = maxy;
  return true;
}

static void parse_collision_object(const char* coll_s, const char* coll_e, TurtleTileCollEntry* e,
                                   int tile_px) {
  char mode[24];
  bool oneway = false;
  uint8_t odir = TURTLE_TILE_ONEWAY_UP;
  read_oneway_from(coll_s, coll_e, &oneway, &odir);
  e->oneway = oneway ? 1 : 0;
  e->oneway_dir = odir;

  if (!json_extract_string_for_key(coll_s, coll_e, "mode", mode, sizeof mode)) {
    e->kind = TURTLE_TILE_COLL_AABB;
    e->x0 = 0;
    e->y0 = 0;
    e->x1 = static_cast<int16_t>(tile_px - 1);
    e->y1 = static_cast<int16_t>(tile_px - 1);
    return;
  }
  if (strcmp(mode, "aabb") == 0) {
    int x0 = 0;
    int y0 = 0;
    int x1 = 0;
    int y1 = 0;
    json_extract_int_for_key(coll_s, coll_e, "x0", &x0);
    json_extract_int_for_key(coll_s, coll_e, "y0", &y0);
    json_extract_int_for_key(coll_s, coll_e, "x1", &x1);
    json_extract_int_for_key(coll_s, coll_e, "y1", &y1);
    e->kind = TURTLE_TILE_COLL_AABB;
    e->x0 = static_cast<int16_t>(clamp_coord(x0));
    e->y0 = static_cast<int16_t>(clamp_coord(y0));
    e->x1 = static_cast<int16_t>(clamp_coord(x1));
    e->y1 = static_cast<int16_t>(clamp_coord(y1));
    return;
  }
  if (strcmp(mode, "triangle") == 0 || strcmp(mode, "hexagon") == 0) {
    int x0 = 0;
    int y0 = 0;
    int x1 = 0;
    int y1 = 0;
    if (points_span_aabb(coll_s, coll_e, &x0, &y0, &x1, &y1)) {
      e->kind = TURTLE_TILE_COLL_AABB;
      e->x0 = static_cast<int16_t>(x0);
      e->y0 = static_cast<int16_t>(y0);
      e->x1 = static_cast<int16_t>(x1);
      e->y1 = static_cast<int16_t>(y1);
      return;
    }
  }
  e->kind = TURTLE_TILE_COLL_SOLID;
}

static void parse_tile_entry(const char* obj_s, const char* obj_e, TurtleTileCollEntry* e,
                             int tile_px) {
  entry_defaults(e);
  const char* ck = strstr_bounded(obj_s, obj_e, "\"collision\"");
  if (!ck) {
    return;
  }
  bool oneway = false;
  uint8_t odir = TURTLE_TILE_ONEWAY_UP;
  read_oneway_from(obj_s, obj_e, &oneway, &odir);

  const char* p = ck + 11;
  while (p < obj_e && isspace(static_cast<unsigned char>(*p))) {
    ++p;
  }
  if (p >= obj_e) {
    return;
  }
  if (*p == '"') {
    ++p;
    char word[16];
    size_t n = 0;
    while (p < obj_e && *p != '"' && n + 1 < sizeof word) {
      word[n++] = static_cast<char>(tolower(static_cast<unsigned char>(*p++)));
    }
    word[n] = '\0';
    if (strcmp(word, "none") == 0 || strcmp(word, "pass") == 0) {
      e->kind = TURTLE_TILE_COLL_NONE;
      e->oneway = 0;
      return;
    }
    e->kind = TURTLE_TILE_COLL_SOLID;
    e->oneway = oneway ? 1 : 0;
    e->oneway_dir = odir;
    return;
  }
  if (*p == '{') {
    const char* ce = json_object_end(p);
    if (!ce) {
      return;
    }
    parse_collision_object(p, ce, e, tile_px);
    if (!e->oneway) {
      e->oneway = oneway ? 1 : 0;
      e->oneway_dir = odir;
    }
    return;
  }
  e->oneway = oneway ? 1 : 0;
  e->oneway_dir = odir;
}

static bool rects_overlap(int ax0, int ay0, int ax1, int ay1, int bx0, int by0, int bx1, int by1) {
  return ax0 <= bx1 && ax1 >= bx0 && ay0 <= by1 && ay1 >= by0;
}

static void update_has_solid_tiles(TurtleTileset* ts) {
  const int n = ts->tile_count > kCollMax ? kCollMax : static_cast<int>(ts->tile_count);
  ts->has_solid_tiles = false;
  for (int i = 0; i < n; ++i) {
    if (ts->coll[i].kind != TURTLE_TILE_COLL_NONE) {
      ts->has_solid_tiles = true;
      break;
    }
  }
}

}  // namespace

void turtle_tile_collision_recompute_has_solid(TurtleTileset* ts) {
  if (!ts) {
    return;
  }
  update_has_solid_tiles(ts);
}

void turtle_tile_collision_defaults(TurtleTileset* ts) {
  if (!ts) {
    return;
  }
  const int n = ts->tile_count > kCollMax ? kCollMax : static_cast<int>(ts->tile_count);
  for (int i = 0; i < n; ++i) {
    entry_defaults(&ts->coll[i]);
  }
  // Sin datos de collision por tile aun: por defecto todos son "solid" (ver entry_defaults).
  update_has_solid_tiles(ts);
}

bool turtle_tile_collision_parse_json(TurtleTileset* ts, const char* json, const char* json_end) {
  if (!ts || !json || !json_end || json_end <= json) {
    return false;
  }
  turtle_tile_collision_defaults(ts);

  const char* tk = strstr_bounded(json, json_end, "\"tiles\"");
  if (!tk) {
    return false;
  }
  const char* p = tk + 7;
  while (p < json_end && *p != '[') {
    ++p;
  }
  if (p >= json_end || *p != '[') {
    return false;
  }
  ++p;

  int idx = 0;
  while (p < json_end && *p != ']' && idx < static_cast<int>(ts->tile_count) &&
         idx < kCollMax) {
    while (p < json_end &&
           (isspace(static_cast<unsigned char>(*p)) || *p == ',')) {
      ++p;
    }
    if (p >= json_end || *p == ']') {
      break;
    }
    if (*p != '{') {
      break;
    }
    const char* oe = json_object_end(p);
    if (!oe) {
      break;
    }
    parse_tile_entry(p, oe, &ts->coll[idx], static_cast<int>(ts->tile_px));
    ++idx;
    p = oe;
  }
  update_has_solid_tiles(ts);
  return idx > 0;
}

bool turtle_tile_collision_blocks(const TurtleTileCollEntry* e, int tile_px, int twx0, int twy0,
                                  int twx1, int twy1, int ax0, int ay0, int ax1, int ay1,
                                  int step_dx, int step_dy, bool ground_probe) {
  if (!e || e->kind == TURTLE_TILE_COLL_NONE) {
    return false;
  }
  int cx0 = twx0;
  int cy0 = twy0;
  int cx1 = twx1;
  int cy1 = twy1;
  if (e->kind == TURTLE_TILE_COLL_AABB) {
    cx0 = twx0 + e->x0;
    cy0 = twy0 + e->y0;
    cx1 = twx0 + e->x1;
    cy1 = twy0 + e->y1;
  }
  if (!rects_overlap(ax0, ay0, ax1, ay1, cx0, cy0, cx1, cy1)) {
    return false;
  }
  if (!ground_probe && e->oneway) {
    if (e->oneway_dir == TURTLE_TILE_ONEWAY_UP && step_dy > 0) {
      return false;
    }
    if (e->oneway_dir == TURTLE_TILE_ONEWAY_DOWN && step_dy < 0) {
      return false;
    }
    if (e->oneway_dir == TURTLE_TILE_ONEWAY_LEFT && step_dx < 0) {
      return false;
    }
    if (e->oneway_dir == TURTLE_TILE_ONEWAY_RIGHT && step_dx > 0) {
      return false;
    }
  }
  (void)tile_px;
  return true;
}
