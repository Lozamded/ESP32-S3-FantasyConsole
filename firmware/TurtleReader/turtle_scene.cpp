#include "turtle_scene.h"

#include "turtle_actor_lua.h"
#include "turtle_asset_bin.h"
#include "turtle_cart.h"
#include "turtle_font.h"
#include "turtle_gpu.h"
#include "turtle_tileset.h"
#include "turtle_tile_collision.h"

#include <Arduino.h>
#include <ctype.h>
#include <stdlib.h>
#include <string.h>

#if defined(ESP32) || defined(ESP_PLATFORM)
#include <esp_heap_caps.h>
#include <esp_attr.h>
#define TURTLE_BSS_PSRAM EXT_RAM_ATTR
#else
#define TURTLE_BSS_PSRAM
#endif

namespace {

constexpr int kMaxPlacements = 96;
/** Mismo default que TurtleStudio (sprites.DEFAULT_CELL_PX). */
constexpr int kDefaultCellPx = 4;
constexpr int kDefaultTransparentIndex = 31;
constexpr int kMaxSpriteW = 128;
constexpr int kMaxSpriteH = 128;
/** Escena canonica (spec/scene-v0.md); viewport = kSceneW x kSceneH. */
constexpr int kSceneW = 264;
constexpr int kSceneH = 198;
constexpr int kMaxWorldSteps = 2;
constexpr int kMaxWorldW = kSceneW * kMaxWorldSteps;
constexpr int kMaxWorldH = kSceneH * kMaxWorldSteps;
constexpr int kMaxTileLayers = 4;
constexpr int kMaxTileCols = 34;  /* kMaxWorldW / 16 */
constexpr int kMaxTileRows = 25;  /* kMaxWorldH / 16 */
/** spec/scene-v0.md: bandas de parallax horizontal por rango Y de escena. */
constexpr int kMaxParallaxBands = 8;

struct TileLayer {
  bool enabled;
  char tileset[48];
  int cols;
  int rows;
  uint8_t cells[kMaxTileRows][kMaxTileCols];
  /** Precomputado en coll_tileset_cache_prewarm(): evita tocar la cache de tileset
   *  de colision (single-entry, ver s_tileset_coll) en capas puramente decorativas. */
  bool has_solid_tiles;
};

struct Placement {
  char obj_id[32];
  int x;
  int y;
};

/** spec/scene-v0.md: rango Y (escena, inclusive) con su propio factor de scroll
 *  horizontal sobre el mismo s_world_bg. Filas fuera de todas las bandas usan
 *  el comportamiento de hoy (parallax_x=1, fixed=false, repeat_x=false). */
struct ParallaxBand {
  int16_t y0;
  int16_t y1;
  float parallax_x;
  bool fixed;
  bool repeat_x;
};

constexpr int kMaxBgImageLayers = 4;

/** spec/scene-v0.md "Capas de fondo con imagen": capa extra de background_layers[i] con
 *  su propia imagen (ademas del `background` principal, que sigue siendo el unico elegible
 *  para parallax_bands). Un solo factor de scroll uniforme (sin bandas por fila): mas barato
 *  de renderizar, y evita tener que elegir "que capa tiene bandas" en mas de un lugar. Cada
 *  capa habilitada reserva su propio buffer (alloc_scene_pixel_buffer), ademas de s_world_bg. */
struct BgImageLayer {
  bool enabled;
  char background_id[48];
  float parallax_x;
  bool fixed;
  bool repeat_x;
  uint8_t* pixels;
  int pw;
  int ph;
  bool loaded;
};

struct SceneActor {
  char obj_id[32];
  char sprite_id[48];
  char anim_name[33];
  char script_stem[40];
  int x;
  int y;
  int pw;
  int ph;
  int origin_x;
  int origin_y;
  int col_x0;
  int col_y0;
  int col_x1;
  int col_y1;
  bool grounded;
  bool anim_repeat;
  bool flip_h;
  uint8_t frame_index;
  uint8_t frame_count;
  uint16_t anim_speed_x16;
  uint32_t frame_accum_ms;
  int prev_blit_x;
  int prev_blit_y;
  int prev_blit_w;
  int prev_blit_h;
  bool has_prev_blit;
  // Overlay de texto (turtle_scene_actor_set_text): rect propio, independiente del
  // prev_blit_* del sprite (no coinciden). Persiste hasta que el script vuelva a llamar
  // text() o lo borre con text(nil)/text(""), igual que set_anim con la animacion activa.
  char text_buf[48];
  int text_dx;
  int text_dy;
  char text_font_id[48];
  int text_color;  // -1 = sin tinte (colores propios del glifo), 0..30 = tinte solido
  bool has_text;
  int text_prev_blit_x;
  int text_prev_blit_y;
  int text_prev_blit_w;
  int text_prev_blit_h;
  bool text_has_prev_blit;
};

TURTLE_BSS_PSRAM static uint8_t s_sprite_pixels[kMaxSpriteW * kMaxSpriteH];
/** Decode temporal (fondos <= 1 pantalla); mundos grandes usan s_world_bg en PSRAM. */
TURTLE_BSS_PSRAM static uint8_t s_scene_pixels[kSceneW * kSceneH];
/** Fondo indexado del mundo completo (scroll); se pinta por ventana con la camara. */
static uint8_t* s_world_bg = nullptr;
static int s_world_bg_w = 0;
static int s_world_bg_h = 0;
static bool s_world_static_ready = false;
/** Fuera del stack de loopTask (ESP32 ~8 KB); parse_placements + tile_layers juntos overflow. */
TURTLE_BSS_PSRAM static Placement s_placements[kMaxPlacements];
TURTLE_BSS_PSRAM static TileLayer s_tile_layers[kMaxTileLayers];
TURTLE_BSS_PSRAM static TurtleTileset s_tileset_draw;
TURTLE_BSS_PSRAM static SceneActor s_actors[kMaxPlacements];
static int s_actor_count = 0;
static int s_player_actor = -1;
static int s_lua_actor_target = -1;
static const char* s_runtime_json = nullptr;
static const char* s_runtime_json_end = nullptr;
static const char* s_runtime_sc_start = nullptr;
static const char* s_runtime_sc_end = nullptr;
static uint8_t s_runtime_transp = 31;
static bool s_runtime_active = false;
static int s_target_fps = 30;
static int s_default_anim_fps = 8;
static int s_runtime_tile_px = 16;
static int s_runtime_tile_layer_count = 0;
static int s_world_w = kSceneW;
static int s_world_h = kSceneH;
static int s_cam_x = 0;
static int s_cam_y = 0;
static bool s_camera_fixed = false;
static char s_camera_target[48];
static int s_camera_margin_x = 64;
static int s_camera_margin_y = 48;
static int s_runtime_bg = 0;
static ParallaxBand s_parallax_bands[kMaxParallaxBands];
static int s_parallax_band_count = 0;
static BgImageLayer s_bg_image_layers[kMaxBgImageLayers];
static int s_bg_image_layer_count = 0;

static void coll_tileset_cache_clear(void);
static void font_cache_clear_all(void);
static const ParallaxBand* find_parallax_band(int scene_y);
static const TurtleFont* font_cache_get(const char* json, const char* json_end,
                                        const char* font_id);
static char s_seen_asset_paths[24][112];
static int s_seen_asset_paths_count = 0;

struct ActorDrawCache {
  char sprite_id[48];
  uint8_t frame_index;
  bool pixels_valid;
};

static ActorDrawCache s_actor_draw_cache[kMaxPlacements];

constexpr int kMaxSpriteCache = 48;
constexpr int kMaxObjectCache = 8;

struct SpriteBlobCacheEntry {
  char id[48];
  char* data;
  size_t len;
  bool in_psram;
};

static SpriteBlobCacheEntry s_sprite_cache[kMaxSpriteCache];
static int s_sprite_cache_count = 0;

struct ObjectJsonCacheEntry {
  char id[48];
  char* data;
  size_t len;
  bool in_psram;
};

static ObjectJsonCacheEntry s_object_cache[kMaxObjectCache];
static int s_object_cache_count = 0;

static constexpr size_t kScenePixelsMaxBytes =
    static_cast<size_t>(kMaxWorldW) * static_cast<size_t>(kMaxWorldH);
static constexpr size_t kScenePixelsViewportBytes =
    static_cast<size_t>(kSceneW) * static_cast<size_t>(kSceneH);

static void world_bg_release(void) {
  if (!s_world_bg) {
    s_world_bg_w = 0;
    s_world_bg_h = 0;
    return;
  }
#if defined(ESP32) || defined(ESP_PLATFORM)
  heap_caps_free(s_world_bg);
#else
  free(s_world_bg);
#endif
  s_world_bg = nullptr;
  s_world_bg_w = 0;
  s_world_bg_h = 0;
}

static void bg_image_layers_release(void) {
  for (int i = 0; i < kMaxBgImageLayers; ++i) {
    BgImageLayer* ly = &s_bg_image_layers[i];
    if (ly->pixels) {
#if defined(ESP32) || defined(ESP_PLATFORM)
      heap_caps_free(ly->pixels);
#else
      free(ly->pixels);
#endif
    }
    ly->pixels = nullptr;
    ly->pw = 0;
    ly->ph = 0;
    ly->loaded = false;
  }
  s_bg_image_layer_count = 0;
}

static void scene_asset_buffers_release(void) {
  s_world_static_ready = false;
  world_bg_release();
  bg_image_layers_release();
}

static void world_buffer_put_scene_pixel(int sx, int sy, uint8_t ci) {
  if (!s_world_bg || sx < 0 || sy < 0 || sx >= s_world_bg_w || sy >= s_world_bg_h) {
    return;
  }
  const int ty = (s_world_bg_h - 1) - sy;
  s_world_bg[static_cast<size_t>(ty) * static_cast<size_t>(s_world_bg_w) +
              static_cast<size_t>(sx)] = ci;
}

static void object_cache_free_entry(ObjectJsonCacheEntry* e) {
  if (!e || !e->data) {
    return;
  }
#if defined(ESP32) || defined(ESP_PLATFORM)
  if (e->in_psram) {
    heap_caps_free(e->data);
  } else {
    free(e->data);
  }
#else
  free(e->data);
#endif
  e->data = nullptr;
  e->len = 0;
  e->in_psram = false;
}

static void object_cache_clear_all(void) {
  for (int i = 0; i < s_object_cache_count; ++i) {
    object_cache_free_entry(&s_object_cache[i]);
    s_object_cache[i].id[0] = '\0';
  }
  s_object_cache_count = 0;
}

static bool object_cache_find(const char* obj_id, const char** inner, const char** inner_end) {
  if (!obj_id || !obj_id[0] || !inner || !inner_end) {
    return false;
  }
  for (int i = 0; i < s_object_cache_count; ++i) {
    if (strcmp(s_object_cache[i].id, obj_id) == 0 && s_object_cache[i].data) {
      *inner = s_object_cache[i].data;
      *inner_end = s_object_cache[i].data + s_object_cache[i].len;
      return true;
    }
  }
  return false;
}

static bool object_cache_add_move(const char* obj_id, TurtleCartBuffer* buf) {
  if (!obj_id || !obj_id[0] || !buf || !buf->data) {
    return false;
  }
  const char* existing_a = nullptr;
  const char* existing_b = nullptr;
  if (object_cache_find(obj_id, &existing_a, &existing_b)) {
    turtle_cart_free(buf);
    return true;
  }
  if (s_object_cache_count >= kMaxObjectCache) {
    return false;
  }
  ObjectJsonCacheEntry* e = &s_object_cache[s_object_cache_count];
  snprintf(e->id, sizeof e->id, "%s", obj_id);
  e->data = buf->data;
  e->len = buf->len;
  e->in_psram = buf->in_psram;
  buf->data = nullptr;
  buf->len = 0;
  buf->in_psram = false;
  ++s_object_cache_count;
  return true;
}

static void sprite_cache_free_entry(SpriteBlobCacheEntry* e) {
  if (!e || !e->data) {
    return;
  }
#if defined(ESP32) || defined(ESP_PLATFORM)
  if (e->in_psram) {
    heap_caps_free(e->data);
  } else {
    free(e->data);
  }
#else
  free(e->data);
#endif
  e->data = nullptr;
  e->len = 0;
  e->in_psram = false;
}

static void sprite_cache_clear_all(void) {
  for (int i = 0; i < s_sprite_cache_count; ++i) {
    sprite_cache_free_entry(&s_sprite_cache[i]);
    s_sprite_cache[i].id[0] = '\0';
  }
  s_sprite_cache_count = 0;
  object_cache_clear_all();
  coll_tileset_cache_clear();
  font_cache_clear_all();
  scene_asset_buffers_release();
}

static bool sprite_cache_find(const char* sprite_id, const char** inner, const char** inner_end) {
  if (!sprite_id || !sprite_id[0] || !inner || !inner_end) {
    return false;
  }
  for (int i = 0; i < s_sprite_cache_count; ++i) {
    if (strcmp(s_sprite_cache[i].id, sprite_id) == 0 && s_sprite_cache[i].data) {
      *inner = s_sprite_cache[i].data;
      *inner_end = s_sprite_cache[i].data + s_sprite_cache[i].len;
      return true;
    }
  }
  return false;
}

static bool sprite_cache_add_move(const char* sprite_id, TurtleCartBuffer* buf) {
  if (!sprite_id || !sprite_id[0] || !buf || !buf->data) {
    return false;
  }
  const char* existing_a = nullptr;
  const char* existing_b = nullptr;
  if (sprite_cache_find(sprite_id, &existing_a, &existing_b)) {
    turtle_cart_free(buf);
    return true;
  }
  if (s_sprite_cache_count >= kMaxSpriteCache) {
    return false;
  }
  SpriteBlobCacheEntry* e = &s_sprite_cache[s_sprite_cache_count];
  snprintf(e->id, sizeof e->id, "%s", sprite_id);
  e->data = buf->data;
  e->len = buf->len;
  e->in_psram = buf->in_psram;
  buf->data = nullptr;
  buf->len = 0;
  buf->in_psram = false;
  ++s_sprite_cache_count;
  return true;
}

static const char* strstr_bounded(const char* s, const char* e, const char* needle) {
  const size_t nl = strlen(needle);
  if (nl == 0 || s + nl > e) {
    return nullptr;
  }
  for (const char* p = s; p + nl <= e; ++p) {
    if (memcmp(p, needle, nl) == 0) {
      return p;
    }
  }
  return nullptr;
}

static const char* json_object_end(const char* p) {
  if (!p || *p != '{') {
    return nullptr;
  }
  int depth = 1;
  ++p;
  while (*p && depth > 0) {
    if (*p == '"') {
      ++p;
      while (*p && *p != '"') {
        if (*p == '\\' && p[1]) {
          p += 2;
        } else {
          ++p;
        }
      }
      if (*p == '"') {
        ++p;
      }
      continue;
    }
    if (*p == '{') {
      ++depth;
    } else if (*p == '}') {
      --depth;
    }
    if (depth > 0) {
      ++p;
    }
  }
  if (depth == 0) {
    return p + 1;
  }
  return nullptr;
}

static bool parse_int_bounded(const char* p, const char* e, int* out) {
  while (p < e && isspace(static_cast<unsigned char>(*p))) {
    ++p;
  }
  if (p >= e) {
    return false;
  }
  char buf[16];
  size_t i = 0;
  while (p < e && i + 1 < sizeof(buf) && (*p == '-' || isdigit(static_cast<unsigned char>(*p)))) {
    buf[i++] = *p++;
  }
  if (i == 0) {
    return false;
  }
  buf[i] = '\0';
  *out = atoi(buf);
  return true;
}

static bool parse_float_bounded(const char* p, const char* e, float* out) {
  while (p < e && isspace(static_cast<unsigned char>(*p))) {
    ++p;
  }
  if (p >= e) {
    return false;
  }
  char buf[32];
  size_t i = 0;
  while (p < e && i + 1 < sizeof(buf) &&
         (*p == '-' || *p == '+' || *p == '.' || isdigit(static_cast<unsigned char>(*p)))) {
    buf[i++] = *p++;
  }
  if (i == 0) {
    return false;
  }
  buf[i] = '\0';
  *out = static_cast<float>(atof(buf));
  return true;
}

static bool json_extract_string_for_key(const char* s, const char* e, const char* key_name,
                                        char* out, size_t outsz) {
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
  if (p >= e || *p != '"') {
    return false;
  }
  ++p;
  size_t i = 0;
  while (p < e && *p != '"' && i + 1 < outsz) {
    if (*p == '\\' && p + 1 < e) {
      p += 2;
      continue;
    }
    out[i++] = *p++;
  }
  out[i] = '\0';
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
  while (p < e && isspace(static_cast<unsigned char>(*p))) {
    ++p;
  }
  return parse_int_bounded(p, e, outv);
}

static bool json_extract_float_for_key(const char* s, const char* e, const char* key_name,
                                       float* outv) {
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
  return parse_float_bounded(p, e, outv);
}

static bool extract_palette_index_sprite(const char* inner, const char* inner_end, int* pal_idx) {
  const char* r = strstr_bounded(inner, inner_end, "\"render\"");
  if (!r) {
    return json_extract_int_for_key(inner, inner_end, "palette_index", pal_idx);
  }
  while (r < inner_end && *r != ':') {
    ++r;
  }
  if (r >= inner_end) {
    return false;
  }
  ++r;
  while (r < inner_end && isspace(static_cast<unsigned char>(*r))) {
    ++r;
  }
  if (r >= inner_end || *r != '{') {
    return json_extract_int_for_key(inner, inner_end, "palette_index", pal_idx);
  }
  const char* rb = r;
  const char* re = json_object_end(rb);
  if (!re) {
    return false;
  }
  return json_extract_int_for_key(rb, re, "palette_index", pal_idx);
}

/** Primer `"objects"` cuyo valor es objeto `{` (manifest raiz), no array `[` (lista en escena). */
static const char* find_root_objects_dict_brace(const char* json, const char* json_end) {
  const char* p = json;
  while (p < json_end) {
    const char* hit = strstr_bounded(p, json_end, "\"objects\"");
    if (!hit) {
      return nullptr;
    }
    const char* q = hit + 9;
    while (q < json_end && *q != ':') {
      ++q;
    }
    if (q >= json_end) {
      return nullptr;
    }
    ++q;
    while (q < json_end && isspace(static_cast<unsigned char>(*q))) {
      ++q;
    }
    if (q < json_end && *q == '{') {
      return q;
    }
    p = hit + 10;
  }
  return nullptr;
}

static bool find_asset_inner(const char* json, const char* json_end, const char* dict_key,
                             const char* asset_id, const char** inner, const char** inner_end) {
  char dict_pat[24];
  snprintf(dict_pat, sizeof dict_pat, "\"%s\"", dict_key);
  const char* p = strstr_bounded(json, json_end, dict_pat);
  if (!p) {
    return false;
  }
  while (p < json_end && *p != ':') {
    ++p;
  }
  if (p >= json_end) {
    return false;
  }
  ++p;
  while (p < json_end && isspace(static_cast<unsigned char>(*p))) {
    ++p;
  }
  if (p >= json_end || *p != '{') {
    return false;
  }
  const char* sd = p;
  const char* sd_end = json_object_end(sd);
  if (!sd_end) {
    return false;
  }

  char pat[56];
  snprintf(pat, sizeof pat, "\"%s\":", asset_id);
  const char* hit = strstr_bounded(sd, sd_end, pat);
  if (!hit) {
    return false;
  }
  const char* in = strchr(hit + strlen(pat), '{');
  if (!in || in >= sd_end) {
    return false;
  }
  const char* in_end = json_object_end(in);
  if (!in_end) {
    return false;
  }
  *inner = in;
  *inner_end = in_end;
  return true;
}

static bool find_sprite_inner(const char* json, const char* json_end, const char* sprite_id,
                              const char** inner, const char** inner_end) {
  return find_asset_inner(json, json_end, "sprites", sprite_id, inner, inner_end);
}

static bool find_background_inner(const char* json, const char* json_end, const char* bg_id,
                                  const char** inner, const char** inner_end) {
  return find_asset_inner(json, json_end, "backgrounds", bg_id, inner, inner_end);
}

static bool find_tileset_inner(const char* json, const char* json_end, const char* tileset_id,
                               const char** inner, const char** inner_end) {
  return find_asset_inner(json, json_end, "tilesets", tileset_id, inner, inner_end);
}

static bool find_font_inner(const char* json, const char* json_end, const char* font_id,
                            const char** inner, const char** inner_end) {
  return find_asset_inner(json, json_end, "fonts", font_id, inner, inner_end);
}

static bool buffer_is_turtle_tileset_bin(const char* data, size_t len) {
  return len >= 10 && data && data[0] == 'T' && data[1] == 'T' && data[2] == 'S' && data[3] == 0;
}

static bool buffer_is_turtle_font_bin(const char* data, size_t len) {
  return len >= 14 && data && data[0] == 'T' && data[1] == 'F' && data[2] == 'N' && data[3] == 0;
}

static bool buffer_is_turtle_asset_bin(const char* data, size_t len) {
  if (!data || len < 11) {
    return false;
  }
  if (data[0] != 'T' || data[3] != 0) {
    return false;
  }
  return (data[1] == 'B' && data[2] == 'G') || (data[1] == 'S' && data[2] == 'P');
}

static bool should_log_asset_path(const char* path) {
  if (!path || !path[0]) {
    return false;
  }
  for (int i = 0; i < s_seen_asset_paths_count; ++i) {
    if (strcmp(s_seen_asset_paths[i], path) == 0) {
      return false;
    }
  }
  if (s_seen_asset_paths_count < static_cast<int>(sizeof(s_seen_asset_paths) /
                                                   sizeof(s_seen_asset_paths[0]))) {
    snprintf(s_seen_asset_paths[s_seen_asset_paths_count],
             sizeof(s_seen_asset_paths[s_seen_asset_paths_count]), "%s", path);
    ++s_seen_asset_paths_count;
  }
  return true;
}

static bool read_asset_bin_dims(const char* data, size_t len, int* pw, int* ph) {
  if (!buffer_is_turtle_asset_bin(data, len) || len < 11 || !pw || !ph) {
    return false;
  }
  *pw = static_cast<int>(static_cast<unsigned>(static_cast<uint8_t>(data[6])) |
                         (static_cast<unsigned>(static_cast<uint8_t>(data[7])) << 8));
  *ph = static_cast<int>(static_cast<unsigned>(static_cast<uint8_t>(data[8])) |
                         (static_cast<unsigned>(static_cast<uint8_t>(data[9])) << 8));
  return *pw > 0 && *ph > 0;
}

/** Carga asset desde SD (.tbg / .tsp binario o .json legacy). */
struct AssetSdLoad {
  TurtleCartBuffer buf = {};
  bool loaded = false;

  ~AssetSdLoad() { turtle_cart_free(&buf); }

  bool resolve(const char* inner, const char* inner_end, const char** use_inner,
               const char** use_inner_end) {
    char rel[96];
    if (!json_extract_string_for_key(inner, inner_end, "file", rel, sizeof rel) || !rel[0]) {
      *use_inner = inner;
      *use_inner_end = inner_end;
      return true;
    }
    char path[112];
    if (rel[0] == '/') {
      snprintf(path, sizeof path, "%s", rel);
    } else {
      snprintf(path, sizeof path, "/%s", rel);
    }
    if (!turtle_cart_load_sd_file(path, &buf, true)) {
      Serial.printf("turtle_scene: no pudo cargar asset SD %s\n", path);
      return false;
    }
    loaded = true;
    *use_inner = buf.data;
    *use_inner_end = buf.data + buf.len;
    if (should_log_asset_path(path)) {
      if (buffer_is_turtle_asset_bin(buf.data, buf.len)) {
        int bw = 0;
        int bh = 0;
        read_asset_bin_dims(buf.data, buf.len, &bw, &bh);
        const uint8_t mode = (buf.len >= 11) ? static_cast<uint8_t>(buf.data[10]) : 0;
        Serial.printf("turtle_scene: bin SD %s %dx%d mode %u (%u bytes)\n", path, bw, bh,
                      static_cast<unsigned>(mode), static_cast<unsigned>(buf.len));
      } else {
        Serial.printf("turtle_scene: json SD %s (%u bytes)\n", path,
                      static_cast<unsigned>(buf.len));
      }
    }
    return true;
  }

  bool load_path(const char* path) {
    if (!turtle_cart_load_sd_file(path, &buf, true)) {
      return false;
    }
    loaded = true;
    return true;
  }
};

static bool resolve_tileset_tts(const char* json, const char* json_end, const char* tileset_id,
                                AssetSdLoad* sd, TurtleTileset* ts);

static AssetSdLoad s_tileset_coll_sd;
static char s_tileset_coll_loaded_id[48];

/** Un tileset cargado para colision (evita N× coll[256] en DRAM). */
TURTLE_BSS_PSRAM static TurtleTileset s_tileset_coll;
static char s_tileset_coll_active_id[48];

static void coll_tileset_cache_clear(void) {
  turtle_tileset_free(&s_tileset_coll);
  s_tileset_coll_active_id[0] = '\0';
}

static const TurtleTileset* coll_tileset_cache_get(const char* json, const char* json_end,
                                                   const char* tileset_id) {
  if (!tileset_id || !tileset_id[0]) {
    return nullptr;
  }
  if (strcmp(s_tileset_coll_active_id, tileset_id) == 0 && s_tileset_coll.pixels) {
    return &s_tileset_coll;
  }
  turtle_tileset_free(&s_tileset_coll);
  s_tileset_coll_active_id[0] = '\0';
  if (!resolve_tileset_tts(json, json_end, tileset_id, &s_tileset_coll_sd, &s_tileset_coll)) {
    return nullptr;
  }
  snprintf(s_tileset_coll_active_id, sizeof s_tileset_coll_active_id, "%s", tileset_id);
  return &s_tileset_coll;
}

static void coll_tileset_cache_prewarm(const char* json, const char* json_end) {
  for (int li = 0; li < s_runtime_tile_layer_count; ++li) {
    TileLayer* ly = &s_tile_layers[li];
    // Conservador por defecto: si no se puede determinar, se trata como solida.
    ly->has_solid_tiles = true;
    if (!ly->enabled || !ly->tileset[0]) {
      continue;
    }
    int dup_of = -1;
    for (int j = 0; j < li; ++j) {
      if (strcmp(s_tile_layers[j].tileset, ly->tileset) == 0) {
        dup_of = j;
        break;
      }
    }
    if (dup_of >= 0) {
      ly->has_solid_tiles = s_tile_layers[dup_of].has_solid_tiles;
      continue;
    }
    const TurtleTileset* ts = coll_tileset_cache_get(json, json_end, ly->tileset);
    ly->has_solid_tiles = ts ? ts->has_solid_tiles : true;
  }
}

static void tileset_load_collision_meta(const char* json, const char* json_end,
                                        const char* tileset_id, const char* inner,
                                        const char* inner_end, TurtleTileset* ts) {
  turtle_tile_collision_defaults(ts);
  if (inner && inner_end > inner &&
      strstr_bounded(inner, inner_end, "\"tiles\"") != nullptr) {
    if (turtle_tile_collision_parse_json(ts, inner, inner_end)) {
      return;
    }
  }
  char jpath[80];
  snprintf(jpath, sizeof jpath, "/tiles/%s.json", tileset_id);
  if (s_tileset_coll_sd.load_path(jpath)) {
    turtle_tile_collision_parse_json(ts, s_tileset_coll_sd.buf.data,
                                     s_tileset_coll_sd.buf.data + s_tileset_coll_sd.buf.len);
  }
  (void)json;
  (void)json_end;
}

static bool resolve_sprite_inner(const char* json, const char* json_end, const char* sprite_id,
                                 AssetSdLoad* sd, const char** inner, const char** inner_end);

static bool resolve_sprite_asset(const char* json, const char* json_end, const char* sprite_id,
                                 AssetSdLoad* sd, const char** inner, const char** inner_end);

static bool resolve_sprite_inner(const char* json, const char* json_end, const char* sprite_id,
                                 AssetSdLoad* sd, const char** inner, const char** inner_end) {
  const char* in = nullptr;
  const char* in_end = nullptr;
  if (find_sprite_inner(json, json_end, sprite_id, &in, &in_end)) {
    return sd->resolve(in, in_end, inner, inner_end);
  }
  char path[80];
  snprintf(path, sizeof path, "/sprites/%s.tsp", sprite_id);
  if (!sd->load_path(path)) {
    snprintf(path, sizeof path, "/sprites/%s.json", sprite_id);
    if (!sd->load_path(path)) {
      Serial.printf("turtle_scene: sprite \"%s\" no en bundle ni .tsp/.json en SD\n", sprite_id);
      return false;
    }
  }
  *inner = sd->buf.data;
  *inner_end = sd->buf.data + sd->buf.len;
  if (buffer_is_turtle_asset_bin(sd->buf.data, sd->buf.len)) {
    int bw = 0;
    int bh = 0;
    read_asset_bin_dims(sd->buf.data, sd->buf.len, &bw, &bh);
    Serial.printf("turtle_scene: sprite \"%s\" bin %dx%d (%u bytes)\n", sprite_id, bw, bh,
                  static_cast<unsigned>(sd->buf.len));
  } else {
    Serial.printf("turtle_scene: sprite \"%s\" json SD (%u bytes)\n", sprite_id,
                  static_cast<unsigned>(sd->buf.len));
  }
  return true;
}

static bool resolve_pixel_dims_sprite(const char* inner, const char* inner_end, int* pw,
                                      int* ph) {
  if (json_extract_int_for_key(inner, inner_end, "pixel_w", pw) &&
      json_extract_int_for_key(inner, inner_end, "pixel_h", ph) && *pw > 0 && *ph > 0) {
    return true;
  }
  int bw = 1;
  int bh = 1;
  int cp = kDefaultCellPx;
  json_extract_int_for_key(inner, inner_end, "blocks_w", &bw);
  json_extract_int_for_key(inner, inner_end, "blocks_h", &bh);
  json_extract_int_for_key(inner, inner_end, "cell_px", &cp);
  if (bw < 1) {
    bw = 1;
  }
  if (bh < 1) {
    bh = 1;
  }
  if (cp < 1) {
    cp = kDefaultCellPx;
  }
  *pw = bw * cp;
  *ph = bh * cp;
  return *pw > 0 && *ph > 0;
}

static bool render_mode_is_indexed_pixels(const char* inner, const char* inner_end) {
  const char* r = strstr_bounded(inner, inner_end, "\"render\"");
  if (!r) {
    return false;
  }
  while (r < inner_end && *r != ':') {
    ++r;
  }
  if (r >= inner_end) {
    return false;
  }
  ++r;
  while (r < inner_end && isspace(static_cast<unsigned char>(*r))) {
    ++r;
  }
  if (r >= inner_end || *r != '{') {
    return false;
  }
  const char* rb = r;
  const char* re = json_object_end(rb);
  if (!re) {
    return false;
  }
  char mode[32];
  if (!json_extract_string_for_key(rb, re, "mode", mode, sizeof mode)) {
    return false;
  }
  return strcmp(mode, "indexed_pixels") == 0;
}

static bool parse_palette_row_rle(const char* row_start, const char* row_end, int expect_w,
                                  uint8_t* out_row, int out_stride) {
  const char* p = row_start;
  int x = 0;
  while (p < row_end && *p != ']' && x < expect_w) {
    while (p < row_end && (isspace(static_cast<unsigned char>(*p)) || *p == ',')) {
      ++p;
    }
    if (p >= row_end || *p == ']') {
      break;
    }
    if (*p != '[') {
      return false;
    }
    ++p;
    int idx = 0;
    int cnt = 0;
    int field = 0;
    while (p < row_end && *p != ']') {
      while (p < row_end && (isspace(static_cast<unsigned char>(*p)) || *p == ',')) {
        ++p;
      }
      if (p >= row_end || *p == ']') {
        break;
      }
      int v = 0;
      if (!parse_int_bounded(p, row_end, &v)) {
        return false;
      }
      while (p < row_end && (*p == '-' || isdigit(static_cast<unsigned char>(*p)))) {
        ++p;
      }
      if (field == 0) {
        idx = v;
        field = 1;
      } else {
        cnt = v;
        break;
      }
    }
    if (p < row_end && *p == ']') {
      ++p;
    }
    if (cnt < 1) {
      cnt = 1;
    }
    if (idx < 0) {
      idx = 0;
    }
    if (idx > 31) {
      idx = 31;
    }
    const uint8_t ci = static_cast<uint8_t>(idx);
    for (int i = 0; i < cnt && x < expect_w; ++i, ++x) {
      out_row[x] = ci;
    }
  }
  return x > 0;
}

static bool parse_palette_rows_image(const char* inner, const char* inner_end, int expect_w,
                                     int expect_h, uint8_t* out, int out_stride) {
  const char* im = strstr_bounded(inner, inner_end, "\"image\"");
  if (!im) {
    return false;
  }
  const bool use_rle = strstr_bounded(im, inner_end, "\"palette_rows_rle\"") != nullptr;
  const char* rows_k = strstr_bounded(im, inner_end, "\"rows\"");
  if (!rows_k) {
    return false;
  }
  const char* p = rows_k + 6;
  while (p < inner_end && *p != '[') {
    ++p;
  }
  if (p >= inner_end || *p != '[') {
    return false;
  }
  ++p;

  int y = 0;
  while (p < inner_end && *p != ']' && y < expect_h) {
    while (p < inner_end && (isspace(static_cast<unsigned char>(*p)) || *p == ',')) {
      ++p;
    }
    if (p >= inner_end || *p == ']') {
      break;
    }
    if (*p != '[') {
      return false;
    }
    const char* row_begin = p;
    ++p;
    const char* row_end = p;
    while (row_end < inner_end && *row_end != ']') {
      ++row_end;
    }
    uint8_t* out_row = out + static_cast<size_t>(y) * static_cast<size_t>(out_stride);
    if (use_rle) {
      if (!parse_palette_row_rle(row_begin, row_end, expect_w, out_row, out_stride)) {
        return false;
      }
    } else {
      int x = 0;
      p = row_begin + 1;
      while (p < row_end && *p != ']') {
        while (p < inner_end && (isspace(static_cast<unsigned char>(*p)) || *p == ',')) {
          ++p;
        }
        if (p >= row_end || *p == ']') {
          break;
        }
        int v = 0;
        if (!parse_int_bounded(p, inner_end, &v)) {
          return false;
        }
        while (p < inner_end && (*p == '-' || isdigit(static_cast<unsigned char>(*p)))) {
          ++p;
        }
        if (x < expect_w && x < out_stride) {
          int ci = v;
          if (ci < 0) {
            ci = 0;
          }
          if (ci > 31) {
            ci = 31;
          }
          out_row[x] = static_cast<uint8_t>(ci);
        }
        ++x;
      }
    }
    if (row_end < inner_end && *row_end == ']') {
      p = row_end + 1;
    }
    ++y;
    if ((y & 15) == 0) {
      yield();
    }
  }
  return y > 0;
}

static void clamp_sprite_origin(int pw, int ph, int* ox, int* oy) {
  if (pw < 1) {
    pw = 1;
  }
  if (ph < 1) {
    ph = 1;
  }
  if (*ox < 0) {
    *ox = 0;
  }
  if (*oy < 0) {
    *oy = 0;
  }
  if (*ox >= pw) {
    *ox = pw - 1;
  }
  if (*oy >= ph) {
    *oy = ph - 1;
  }
}

/** Origen del ancla: JSON inline, metadatos del bundle (.tsp ref), o convencion pies-centro. */
static void extract_sprite_origin(const char* meta_inner, const char* meta_inner_end,
                                  const char* asset_inner, const char* asset_inner_end, int pw,
                                  int ph, int* ox, int* oy) {
  const size_t blob_len =
      (asset_inner && asset_inner_end > asset_inner)
          ? static_cast<size_t>(asset_inner_end - asset_inner)
          : 0;
  const bool asset_is_bin =
      asset_inner && buffer_is_turtle_asset_bin(asset_inner, blob_len);

  int tx = 0;
  int ty = 0;

  if (asset_is_bin) {
    tx = pw / 2;
    ty = 0;
    if (meta_inner && meta_inner_end) {
      if (!json_extract_int_for_key(meta_inner, meta_inner_end, "origin_x", &tx)) {
        tx = pw / 2;
      }
      if (!json_extract_int_for_key(meta_inner, meta_inner_end, "origin_y", &ty)) {
        ty = 0;
      }
    }
  } else {
    const char* src = asset_inner ? asset_inner : meta_inner;
    const char* src_end = asset_inner ? asset_inner_end : meta_inner_end;
    if (!json_extract_int_for_key(src, src_end, "origin_x", &tx)) {
      tx = 0;
    }
    if (!json_extract_int_for_key(src, src_end, "origin_y", &ty)) {
      ty = 0;
    }
  }

  clamp_sprite_origin(pw, ph, &tx, &ty);
  *ox = tx;
  *oy = ty;
}

static int sprite_frame_count_from_asset(const char* inner, const char* inner_end, size_t len) {
  if (buffer_is_turtle_asset_bin(inner, len)) {
    const int fc =
        turtle_asset_bin_sprite_frame_count(reinterpret_cast<const uint8_t*>(inner), len);
    return fc > 0 ? fc : 1;
  }
  int fc = 1;
  if (inner && inner_end && json_extract_int_for_key(inner, inner_end, "frame_count", &fc)) {
    if (fc < 1) {
      fc = 1;
    }
    if (fc > 32) {
      fc = 32;
    }
    return fc;
  }
  return 1;
}

static bool buffer_is_turtle_background_bin(const char* data, size_t len) {
  return len >= 11 && data && data[0] == 'T' && data[1] == 'B' && data[2] == 'G' && data[3] == 0;
}

static bool fill_pixels_from_asset_buffer(const char* inner, size_t len, int pw, int ph,
                                          uint8_t* out, int stride, int frame_index) {
  if (buffer_is_turtle_background_bin(inner, len)) {
    if (frame_index != 0) {
      return false;
    }
    return turtle_asset_bin_decode_indexed(reinterpret_cast<const uint8_t*>(inner), len, pw, ph,
                                           out, stride);
  }
  if (buffer_is_turtle_asset_bin(inner, len)) {
    return turtle_asset_bin_decode_sprite_frame(reinterpret_cast<const uint8_t*>(inner), len,
                                                frame_index, pw, ph, out, stride);
  }
  if (!inner || !len) {
    return false;
  }
  if (frame_index != 0) {
    return false;
  }
  return parse_palette_rows_image(inner, inner + len, pw, ph, out, stride);
}

static bool decode_indexed_asset_to_buffer(const char* inner, const char* inner_end,
                                           const char* label, int pw, int ph,
                                           uint8_t* out, int stride) {
  if (pw <= 0 || ph <= 0 || !out || stride < pw) {
    return false;
  }
  const size_t need = static_cast<size_t>(pw) * static_cast<size_t>(ph);
  memset(out, 0, need);
  const size_t blob_len = (inner_end > inner) ? static_cast<size_t>(inner_end - inner) : 0;
  if (!fill_pixels_from_asset_buffer(inner, blob_len, pw, ph, out, stride, 0)) {
    Serial.printf("turtle_scene: pixels invalidos en %s\n", label);
    return false;
  }
  return true;
}

static bool draw_indexed_asset_at_origin(const char* inner, const char* inner_end, const char* label,
                                         int pw, int ph, uint8_t transparent_index) {
  if (pw <= 0 || ph <= 0) {
    return false;
  }
  if (pw > s_world_w || ph > s_world_h) {
    Serial.printf("turtle_scene: %s %dx%d > mundo %dx%d\n", label, pw, ph, s_world_w, s_world_h);
    return false;
  }
  const size_t need = static_cast<size_t>(pw) * static_cast<size_t>(ph);
  if (need > kScenePixelsViewportBytes) {
    Serial.printf(
        "turtle_scene: %s %dx%d demasiado grande para decode puntual (max %dx%d); usa cache de "
        "fondo\n",
        label, pw, ph, kSceneW, kSceneH);
    return false;
  }
  if (!decode_indexed_asset_to_buffer(inner, inner_end, label, pw, ph, s_scene_pixels, pw)) {
    return false;
  }
  turtle_gpu_blit_indexed_scene(0, 0, pw, ph, s_scene_pixels, pw, transparent_index);
  return true;
}

/** Bandas de parallax activas (spec/scene-v0.md): una fila a la vez, cada una con su
 *  propio offset horizontal segun la banda que cubra ese scene_y (find_parallax_band).
 *  Filas sin banda usan parallax_x=1/fixed=false/repeat_x=false, es decir el mismo
 *  mapeo que el blit unico de paint_cached_world_background. */
static void paint_world_background_banded(int cam_x, int vis_y0, int vis_y1,
                                          uint8_t transparent_index) {
  for (int scene_y = vis_y0; scene_y <= vis_y1; ++scene_y) {
    const int row_top = (s_world_bg_h - 1) - scene_y;
    const uint8_t* row =
        s_world_bg + static_cast<size_t>(row_top) * static_cast<size_t>(s_world_bg_w);
    const ParallaxBand* band = find_parallax_band(scene_y);
    const float parallax_x = band ? band->parallax_x : 1.0f;
    const bool fixed = band ? band->fixed : false;
    const bool repeat_x = band ? band->repeat_x : false;
    const int x_offset = fixed ? 0 : static_cast<int>(cam_x * parallax_x);
    turtle_gpu_blit_indexed_row_banded(scene_y, row, s_world_bg_w, x_offset, repeat_x,
                                       transparent_index);
  }
}

static void paint_cached_world_background(uint8_t transparent_index) {
  if (!s_world_bg || s_world_bg_w <= 0 || s_world_bg_h <= 0) {
    return;
  }
  /*
   * Blitea solo la ventana visible (viewport) del buffer del mundo, no el buffer
   * entero (hasta kMaxWorldSteps por eje = hasta 4x pixeles de sobra). Se lee la
   * camara real de turtle_gpu (no el espejo s_cam_x/y) para no desalinearse con
   * el clip que hace turtle_gpu_blit_indexed_scene internamente.
   */
  int cam_x = 0;
  int cam_y = 0;
  turtle_gpu_get_camera(&cam_x, &cam_y);

  int vis_x0 = cam_x;
  int vis_y0 = cam_y;
  int vis_x1 = cam_x + kSceneW - 1;
  int vis_y1 = cam_y + kSceneH - 1;
  if (vis_x0 < 0) {
    vis_x0 = 0;
  }
  if (vis_y0 < 0) {
    vis_y0 = 0;
  }
  if (vis_x1 >= s_world_bg_w) {
    vis_x1 = s_world_bg_w - 1;
  }
  if (vis_y1 >= s_world_bg_h) {
    vis_y1 = s_world_bg_h - 1;
  }
  const int vis_w = vis_x1 - vis_x0 + 1;
  const int vis_h = vis_y1 - vis_y0 + 1;
  if (vis_w <= 0 || vis_h <= 0) {
    return;
  }

  if (s_parallax_band_count > 0) {
    paint_world_background_banded(cam_x, vis_y0, vis_y1, transparent_index);
    return;
  }

  const int row_top = (s_world_bg_h - 1) - vis_y1;
  const uint8_t* src = s_world_bg +
                       static_cast<size_t>(row_top) * static_cast<size_t>(s_world_bg_w) +
                       static_cast<size_t>(vis_x0);
  turtle_gpu_blit_indexed_scene(vis_x0, vis_y0, vis_w, vis_h, src, s_world_bg_w,
                                transparent_index);
}

/** spec/scene-v0.md "Capas de fondo con imagen": una pasada extra por capa habilitada,
 *  encima del fondo principal y por debajo de los tiles. A diferencia de este ultimo, no
 *  se hornea (cada capa debe poder desplazarse a su propio ritmo segun la camara), asi que
 *  se repinta cada vez que se repinta el fondo -- ese es el costo en tiempo de frame que
 *  paga cada capa habilitada, ademas de su propio buffer en RAM. */
static void paint_bg_image_layers(uint8_t transparent_index) {
  if (s_bg_image_layer_count <= 0) {
    return;
  }
  int cam_x = 0;
  int cam_y = 0;
  turtle_gpu_get_camera(&cam_x, &cam_y);

  int vis_y0 = cam_y;
  int vis_y1 = cam_y + kSceneH - 1;
  if (vis_y0 < 0) {
    vis_y0 = 0;
  }
  if (vis_y1 >= s_world_h) {
    vis_y1 = s_world_h - 1;
  }
  if (vis_y1 < vis_y0) {
    return;
  }

  for (int i = 0; i < s_bg_image_layer_count; ++i) {
    const BgImageLayer* ly = &s_bg_image_layers[i];
    if (!ly->loaded || !ly->pixels || ly->pw <= 0 || ly->ph <= 0) {
      continue;
    }
    const int x_offset = ly->fixed ? 0 : static_cast<int>(cam_x * ly->parallax_x);
    for (int scene_y = vis_y0; scene_y <= vis_y1; ++scene_y) {
      if (scene_y >= ly->ph) {
        // Capa mas baja que el mundo: ancla abajo, no cubre filas por encima de su altura.
        continue;
      }
      const int row_top = (ly->ph - 1) - scene_y;
      const uint8_t* row = ly->pixels + static_cast<size_t>(row_top) * static_cast<size_t>(ly->pw);
      turtle_gpu_blit_indexed_row_banded(scene_y, row, ly->pw, x_offset, ly->repeat_x,
                                         transparent_index);
    }
  }
}

static bool draw_solid_asset_at_origin(const char* inner, const char* inner_end, const char* label,
                                       int pw, int ph) {
  int pci = 0;
  if (!extract_palette_index_sprite(inner, inner_end, &pci)) {
    Serial.printf("turtle_scene: %s solido sin palette_index\n", label);
    return false;
  }
  if (pci < 0) {
    pci = 0;
  }
  if (pci > 31) {
    pci = 31;
  }
  if (pw < 1) {
    pw = kSceneW;
  }
  if (ph < 1) {
    ph = kSceneH;
  }
  if (pw > s_world_w) {
    pw = s_world_w;
  }
  if (ph > s_world_h) {
    ph = s_world_h;
  }
  turtle_gpu_fill_rect_scene(0, 0, pw, ph, static_cast<uint8_t>(pci));
  return true;
}

/** spec/scene-v0.md "Capas de fondo con imagen": capa 1 (indice 0 de background_layers) es la
 *  capa base -- su "background" es el que se hornea en el mundo estatico junto a los tiles
 *  (unico elegible para parallax_bands; capas 2-4 quedan en s_bg_image_layers, independientes).
 *  Solo se lee el "background" del PRIMER objeto del array (nunca una busqueda libre en toda
 *  la escena, para no cruzarse con el "background" propio de las capas 2-4). Si esa capa no
 *  tiene imagen, cae al campo suelto "background" a nivel de escena (formato pre-unificacion,
 *  carts ya exportados) buscando solo fuera del array de capas. */
static bool resolve_scene_base_background_id(const char* sc_start, const char* sc_end, char* out,
                                              size_t outsz) {
  out[0] = '\0';
  const char* after_layers = sc_start;
  const char* pk = strstr_bounded(sc_start, sc_end, "\"background_layers\"");
  if (pk) {
    const char* p = pk + strlen("\"background_layers\"");
    while (p < sc_end && *p != '[') {
      ++p;
    }
    if (p < sc_end) {
      ++p;
      bool first = true;
      while (p < sc_end && *p != ']') {
        while (p < sc_end && (isspace(static_cast<unsigned char>(*p)) || *p == ',')) {
          ++p;
        }
        if (p >= sc_end || *p != '{') {
          break;
        }
        const char* oe = json_object_end(p);
        if (!oe) {
          break;
        }
        if (first) {
          json_extract_string_for_key(p, oe, "background", out, outsz);
          first = false;
        }
        p = oe;
      }
      while (p < sc_end && *p != ']') {
        ++p;
      }
      if (p < sc_end) {
        ++p;
      }
      after_layers = p;
    }
  }
  if (out[0]) {
    return true;
  }
  char before[48];
  before[0] = '\0';
  if (pk && json_extract_string_for_key(sc_start, pk, "background", before, sizeof before) &&
      before[0]) {
    snprintf(out, outsz, "%s", before);
    return true;
  }
  return json_extract_string_for_key(after_layers, sc_end, "background", out, outsz) && out[0];
}

static bool draw_background_for_scene(const char* json, const char* json_end,
                                      const char* scene_start, const char* scene_end,
                                      uint8_t transparent_index) {
  char bg_id[48];
  if (!resolve_scene_base_background_id(scene_start, scene_end, bg_id, sizeof bg_id)) {
    return true;
  }

  const char* inner = nullptr;
  const char* inner_end = nullptr;
  if (!find_background_inner(json, json_end, bg_id, &inner, &inner_end)) {
    Serial.printf("turtle_scene: fondo \"%s\" no encontrado en bundle\n", bg_id);
    return false;
  }

  AssetSdLoad sd;
  const char* asset_inner = inner;
  const char* asset_inner_end = inner_end;
  if (!sd.resolve(inner, inner_end, &asset_inner, &asset_inner_end)) {
    return false;
  }

  const size_t bg_blob_len =
      (asset_inner_end > asset_inner) ? static_cast<size_t>(asset_inner_end - asset_inner) : 0;

  int pw = 0;
  int ph = 0;
  if (!read_asset_bin_dims(asset_inner, bg_blob_len, &pw, &ph) &&
      !resolve_pixel_dims_sprite(asset_inner, asset_inner_end, &pw, &ph)) {
    Serial.printf("turtle_scene: fondo \"%s\" sin pixel_w/pixel_h\n", bg_id);
    return false;
  }
  if (render_mode_is_indexed_pixels(asset_inner, asset_inner_end) ||
      buffer_is_turtle_asset_bin(asset_inner, bg_blob_len)) {
    if (!draw_indexed_asset_at_origin(asset_inner, asset_inner_end, bg_id, pw, ph,
                                      transparent_index)) {
      return false;
    }
    Serial.printf("turtle_scene: fondo \"%s\" indexed %dx%d\n", bg_id, pw, ph);
    return true;
  }

  if (!draw_solid_asset_at_origin(asset_inner, asset_inner_end, bg_id, pw, ph)) {
    return false;
  }
  Serial.printf("turtle_scene: fondo \"%s\" solido %dx%d\n", bg_id, pw, ph);
  return true;
}

static bool load_sprite_pixels_by_id(const char* json, const char* json_end, const char* sprite_id,
                                     int frame_index, int* out_pw, int* out_ph) {
  AssetSdLoad sd;
  const char* asset_inner = nullptr;
  const char* asset_inner_end = nullptr;
  if (!resolve_sprite_asset(json, json_end, sprite_id, &sd, &asset_inner, &asset_inner_end)) {
    return false;
  }

  const size_t sp_blob_len =
      (asset_inner_end > asset_inner) ? static_cast<size_t>(asset_inner_end - asset_inner) : 0;

  int pw = 0;
  int ph = 0;
  if (!read_asset_bin_dims(asset_inner, sp_blob_len, &pw, &ph) &&
      !resolve_pixel_dims_sprite(asset_inner, asset_inner_end, &pw, &ph)) {
    return false;
  }
  if (pw > kMaxSpriteW || ph > kMaxSpriteH) {
    return false;
  }

  if (render_mode_is_indexed_pixels(asset_inner, asset_inner_end) ||
      buffer_is_turtle_asset_bin(asset_inner, static_cast<size_t>(asset_inner_end - asset_inner))) {
    memset(s_sprite_pixels, 0, sizeof s_sprite_pixels);
    const size_t blob_len =
        (asset_inner_end > asset_inner) ? static_cast<size_t>(asset_inner_end - asset_inner) : 0;
    if (!fill_pixels_from_asset_buffer(asset_inner, blob_len, pw, ph, s_sprite_pixels, pw,
                                       frame_index)) {
      return false;
    }
    if (out_pw) {
      *out_pw = pw;
    }
    if (out_ph) {
      *out_ph = ph;
    }
    return true;
  }
  return false;
}

static bool draw_sprite_for_object(const char* json, const char* json_end, const char* obj_id,
                                   int scene_x, int scene_y, uint8_t transparent_index,
                                   int frame_index) {
  const char* od = find_root_objects_dict_brace(json, json_end);
  if (!od || *od != '{') {
    return false;
  }
  const char* od_end = json_object_end(od);
  if (!od_end) {
    return false;
  }

  char pat[40];
  snprintf(pat, sizeof pat, "\"%s\":", obj_id);
  const char* hit = strstr_bounded(od, od_end, pat);
  if (!hit) {
    return false;
  }
  const char* oinner = strchr(hit + strlen(pat), '{');
  if (!oinner || oinner >= od_end) {
    return false;
  }
  const char* oinner_end = json_object_end(oinner);
  if (!oinner_end) {
    return false;
  }

  AssetSdLoad obj_sd;
  const char* obj_inner = oinner;
  const char* obj_inner_end = oinner_end;
  if (!obj_sd.resolve(oinner, oinner_end, &obj_inner, &obj_inner_end)) {
    return false;
  }

  char sprite_id[48];
  if (!json_extract_string_for_key(obj_inner, obj_inner_end, "sprite_id", sprite_id,
                                   sizeof sprite_id)) {
    return false;
  }

  AssetSdLoad sd;
  const char* asset_inner = nullptr;
  const char* asset_inner_end = nullptr;
  if (!resolve_sprite_inner(json, json_end, sprite_id, &sd, &asset_inner, &asset_inner_end)) {
    return false;
  }

  const char* meta_inner = nullptr;
  const char* meta_inner_end = nullptr;
  find_sprite_inner(json, json_end, sprite_id, &meta_inner, &meta_inner_end);

  int pw = 0;
  int ph = 0;
  if (load_sprite_pixels_by_id(json, json_end, sprite_id, frame_index, &pw, &ph)) {
    int origin_x = 0;
    int origin_y = 0;
    extract_sprite_origin(meta_inner, meta_inner_end, asset_inner, asset_inner_end, pw, ph,
                          &origin_x, &origin_y);
    const int blit_x = scene_x - origin_x;
    const int blit_y = scene_y - origin_y;
    turtle_gpu_blit_indexed_scene(blit_x, blit_y, pw, ph, s_sprite_pixels, pw, transparent_index);
    return true;
  }

  int pci = 0;
  if (!extract_palette_index_sprite(asset_inner, asset_inner_end, &pci)) {
    Serial.printf("turtle_scene: sprite solido \"%s\" sin palette_index\n", sprite_id);
    return false;
  }
  if (pci < 0) {
    pci = 0;
  }
  if (pci > 31) {
    pci = 31;
  }
  const size_t sp_blob_len =
      (asset_inner_end > asset_inner) ? static_cast<size_t>(asset_inner_end - asset_inner) : 0;
  if (!read_asset_bin_dims(asset_inner, sp_blob_len, &pw, &ph) &&
      !resolve_pixel_dims_sprite(asset_inner, asset_inner_end, &pw, &ph)) {
    return false;
  }
  int origin_x = 0;
  int origin_y = 0;
  extract_sprite_origin(meta_inner, meta_inner_end, asset_inner, asset_inner_end, pw, ph,
                        &origin_x, &origin_y);
  const int blit_x = scene_x - origin_x;
  const int blit_y = scene_y - origin_y;
  turtle_gpu_fill_rect_scene(blit_x, blit_y, pw, ph, static_cast<uint8_t>(pci));
  return true;
}

/** Rectangulo en escena que cubre todos los pixeles del sprite (ancla + origin). */
static void actor_sprite_scene_bounds(const SceneActor* a, int* out_x0, int* out_y0, int* out_w,
                                      int* out_h) {
  *out_x0 = a->x - a->origin_x;
  *out_y0 = a->y - a->origin_y;
  *out_w = a->pw;
  *out_h = a->ph;
}

/**
 * Rectangulo en escena del overlay de texto del actor (si tiene uno activo con fuente
 * resoluble). false si no hay texto que dibujar este frame (para no ensuciar el rect
 * previo de draw_all_actors con datos parciales).
 */
static bool actor_text_scene_bounds(const SceneActor* a, int* out_x0, int* out_y0, int* out_w,
                                    int* out_h) {
  if (!a->has_text || !a->text_buf[0] || !a->text_font_id[0]) {
    return false;
  }
  const TurtleFont* font = font_cache_get(s_runtime_json, s_runtime_json_end, a->text_font_id);
  if (!font) {
    return false;
  }
  *out_x0 = a->x + a->text_dx;
  *out_y0 = a->y + a->text_dy;
  *out_w = turtle_font_measure(font, a->text_buf);
  *out_h = font->glyph_px;
  return true;
}

static bool draw_actor_runtime(int actor_index) {
  if (!s_runtime_json || !s_runtime_json_end || actor_index < 0 || actor_index >= s_actor_count) {
    return false;
  }
  SceneActor* a = &s_actors[actor_index];
  ActorDrawCache* cache = &s_actor_draw_cache[actor_index];

  const bool need_reload = !cache->pixels_valid || strcmp(cache->sprite_id, a->sprite_id) != 0 ||
                           cache->frame_index != a->frame_index;
  if (need_reload) {
    if (!load_sprite_pixels_by_id(s_runtime_json, s_runtime_json_end, a->sprite_id, a->frame_index,
                                 &a->pw, &a->ph)) {
      return false;
    }
    snprintf(cache->sprite_id, sizeof cache->sprite_id, "%s", a->sprite_id);
    cache->frame_index = a->frame_index;
    cache->pixels_valid = true;
  }

  turtle_gpu_blit_indexed_scene_anchor(a->x, a->y, a->pw, a->ph, s_sprite_pixels, a->pw,
                                       s_runtime_transp, a->origin_x, a->origin_y, a->flip_h);

  actor_sprite_scene_bounds(a, &a->prev_blit_x, &a->prev_blit_y, &a->prev_blit_w, &a->prev_blit_h);
  a->has_prev_blit = true;

  int tx0 = 0, ty0 = 0, tw = 0, th = 0;
  if (actor_text_scene_bounds(a, &tx0, &ty0, &tw, &th)) {
    const TurtleFont* font = font_cache_get(s_runtime_json, s_runtime_json_end, a->text_font_id);
    if (font) {
      if (a->text_color >= 0) {
        turtle_font_draw_scene_tint(font, tx0, ty0, a->text_buf, s_runtime_transp,
                                    static_cast<uint8_t>(a->text_color));
      } else {
        turtle_font_draw_scene(font, tx0, ty0, a->text_buf, s_runtime_transp);
      }
    }
    a->text_prev_blit_x = tx0;
    a->text_prev_blit_y = ty0;
    a->text_prev_blit_w = tw;
    a->text_prev_blit_h = th;
    a->text_has_prev_blit = true;
  } else {
    a->text_has_prev_blit = false;
  }
  return true;
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

static bool scene_uses_scrolling(void) {
  return s_world_w > kSceneW || s_world_h > kSceneH;
}

static void parse_scene_world(const char* sc_start, const char* sc_end) {
  s_world_w = kSceneW;
  s_world_h = kSceneH;
  int sx = 1;
  int sy = 1;
  if (json_extract_int_for_key(sc_start, sc_end, "world_steps_x", &sx)) {
    if (sx < 1) {
      sx = 1;
    }
    if (sx > kMaxWorldSteps) {
      sx = kMaxWorldSteps;
    }
  }
  if (json_extract_int_for_key(sc_start, sc_end, "world_steps_y", &sy)) {
    if (sy < 1) {
      sy = 1;
    }
    if (sy > kMaxWorldSteps) {
      sy = kMaxWorldSteps;
    }
  }
  s_world_w = kSceneW * sx;
  s_world_h = kSceneH * sy;
}

static int clamp_camera_margin(int margin, int viewport_size) {
  const int cap = (viewport_size - 1) / 2;
  if (margin < 0) {
    return 0;
  }
  if (margin > cap) {
    return cap;
  }
  return margin;
}

static void clamp_camera_to_world(int* cx, int* cy) {
  const int max_x = s_world_w - kSceneW;
  const int max_y = s_world_h - kSceneH;
  if (*cx < 0) {
    *cx = 0;
  } else if (*cx > max_x) {
    *cx = max_x;
  }
  if (*cy < 0) {
    *cy = 0;
  } else if (*cy > max_y) {
    *cy = max_y;
  }
}

static bool find_scene_nested_object(const char* sc_start, const char* sc_end, const char* key,
                                     const char** out_inner, const char** out_inner_end) {
  char pattern[40];
  snprintf(pattern, sizeof pattern, "\"%s\"", key);
  const char* p = strstr_bounded(sc_start, sc_end, pattern);
  if (!p) {
    return false;
  }
  p += strlen(pattern);
  while (p < sc_end && isspace(static_cast<unsigned char>(*p))) {
    ++p;
  }
  if (p >= sc_end || *p != ':') {
    return false;
  }
  ++p;
  while (p < sc_end && isspace(static_cast<unsigned char>(*p))) {
    ++p;
  }
  if (p >= sc_end || *p != '{') {
    return false;
  }
  const char* ie = json_object_end(p);
  if (!ie) {
    return false;
  }
  *out_inner = p;
  *out_inner_end = ie;
  return true;
}

static void parse_scene_camera(const char* sc_start, const char* sc_end) {
  s_camera_fixed = false;
  s_camera_target[0] = '\0';
  s_cam_x = 0;
  s_cam_y = 0;
  s_camera_margin_x = 64;
  s_camera_margin_y = 48;
  const char* cam_s = sc_start;
  const char* cam_e = sc_end;
  const char* nested = nullptr;
  const char* nested_end = nullptr;
  if (find_scene_nested_object(sc_start, sc_end, "camera", &nested, &nested_end)) {
    cam_s = nested;
    cam_e = nested_end;
  }
  char mode[16];
  if (json_extract_string_for_key(cam_s, cam_e, "mode", mode, sizeof mode) ||
      json_extract_string_for_key(sc_start, sc_end, "camera_mode", mode, sizeof mode)) {
    if (strcmp(mode, "fixed") == 0) {
      s_camera_fixed = true;
    }
  }
  if (!json_extract_int_for_key(cam_s, cam_e, "x", &s_cam_x)) {
    json_extract_int_for_key(sc_start, sc_end, "camera_x", &s_cam_x);
  }
  if (!json_extract_int_for_key(cam_s, cam_e, "y", &s_cam_y)) {
    json_extract_int_for_key(sc_start, sc_end, "camera_y", &s_cam_y);
  }
  if (!json_extract_int_for_key(cam_s, cam_e, "margin_x", &s_camera_margin_x)) {
    json_extract_int_for_key(sc_start, sc_end, "camera_margin_x", &s_camera_margin_x);
  }
  if (!json_extract_int_for_key(cam_s, cam_e, "margin_y", &s_camera_margin_y)) {
    json_extract_int_for_key(sc_start, sc_end, "camera_margin_y", &s_camera_margin_y);
  }
  if (!json_extract_string_for_key(cam_s, cam_e, "target", s_camera_target,
                                   sizeof s_camera_target)) {
    json_extract_string_for_key(sc_start, sc_end, "camera_target", s_camera_target,
                                sizeof s_camera_target);
  }
  if (s_cam_x < 0) {
    s_cam_x = 0;
  }
  if (s_cam_y < 0) {
    s_cam_y = 0;
  }
  s_camera_margin_x = clamp_camera_margin(s_camera_margin_x, kSceneW);
  s_camera_margin_y = clamp_camera_margin(s_camera_margin_y, kSceneH);
  clamp_camera_to_world(&s_cam_x, &s_cam_y);
}

/** spec/scene-v0.md "Bandas de parallax horizontal": array opcional
 *  `"parallax_bands"` en el bloque de la escena. Llamar despues de
 *  parse_scene_world() (usa s_world_h para acotar y0/y1). Sin el campo (o
 *  array vacio), s_parallax_band_count queda en 0 y paint_cached_world_background
 *  usa el blit unico de siempre (comportamiento identico a hoy). */
static void parse_scene_parallax_bands(const char* sc_start, const char* sc_end) {
  s_parallax_band_count = 0;
  const char* pk = strstr_bounded(sc_start, sc_end, "\"parallax_bands\"");
  if (!pk) {
    return;
  }
  const char* p = pk + strlen("\"parallax_bands\"");
  while (p < sc_end && *p != '[') {
    ++p;
  }
  if (p >= sc_end) {
    return;
  }
  ++p;
  const int max_y = (s_world_h > 0 ? s_world_h : kSceneH) - 1;
  while (p < sc_end && *p != ']' && s_parallax_band_count < kMaxParallaxBands) {
    while (p < sc_end && (isspace(static_cast<unsigned char>(*p)) || *p == ',')) {
      ++p;
    }
    if (p >= sc_end || *p == ']') {
      break;
    }
    if (*p != '{') {
      break;
    }
    const char* oe = json_object_end(p);
    if (!oe) {
      break;
    }
    int y0 = 0;
    int y1 = 0;
    float px = 1.0f;
    bool fixed = false;
    bool repeat_x = false;
    json_extract_int_for_key(p, oe, "y0", &y0);
    json_extract_int_for_key(p, oe, "y1", &y1);
    if (!json_extract_float_for_key(p, oe, "parallax_x", &px)) {
      px = 1.0f;
    }
    json_extract_bool_for_key(p, oe, "fixed", &fixed);
    json_extract_bool_for_key(p, oe, "repeat_x", &repeat_x);

    if (y0 > y1) {
      const int t = y0;
      y0 = y1;
      y1 = t;
    }
    if (y0 < 0) {
      y0 = 0;
    }
    if (y1 < 0) {
      y1 = 0;
    }
    if (y0 > max_y) {
      y0 = max_y;
    }
    if (y1 > max_y) {
      y1 = max_y;
    }
    if (px < 0.0f) {
      px = 0.0f;
    } else if (px > 2.0f) {
      px = 2.0f;
    }

    ParallaxBand* band = &s_parallax_bands[s_parallax_band_count++];
    band->y0 = static_cast<int16_t>(y0);
    band->y1 = static_cast<int16_t>(y1);
    band->parallax_x = px;
    band->fixed = fixed;
    band->repeat_x = repeat_x;

    p = oe;
  }
}

static const ParallaxBand* find_parallax_band(int scene_y) {
  for (int i = 0; i < s_parallax_band_count; ++i) {
    const ParallaxBand* b = &s_parallax_bands[i];
    if (scene_y >= b->y0 && scene_y <= b->y1) {
      return b;
    }
  }
  return nullptr;
}

/** spec/scene-v0.md "Capas de fondo con imagen": array `"background_layers"` en el bloque
 *  de la escena (mismo array que ya escribe TurtleStudio para las 4 capas de color plano;
 *  aqui solo se leen los campos nuevos `background`/`parallax_x`/`fixed`/`repeat_x`,
 *  `color_index`/`opacity` siguen siendo del dominio de firmware_background_index_from_layers
 *  en Python, ya resuelto en el `background_index` plano que usa cls()). Solo llena metadatos;
 *  la carga real del asset (con su propio buffer PSRAM) la hace load_bg_image_layers().
 */
static void parse_scene_bg_image_layers(const char* sc_start, const char* sc_end) {
  s_bg_image_layer_count = 0;
  const char* pk = strstr_bounded(sc_start, sc_end, "\"background_layers\"");
  if (!pk) {
    return;
  }
  const char* p = pk + strlen("\"background_layers\"");
  while (p < sc_end && *p != '[') {
    ++p;
  }
  if (p >= sc_end) {
    return;
  }
  ++p;
  // El primer objeto del array (indice 0) es la capa base: se hornea en el mundo estatico
  // (resolve_scene_base_background_id / bake_indexed_background_into_world), no vive en
  // s_bg_image_layers -- solo las capas 2-4 son BgImageLayer independientes.
  bool first = true;
  while (p < sc_end && *p != ']' && s_bg_image_layer_count < kMaxBgImageLayers) {
    while (p < sc_end && (isspace(static_cast<unsigned char>(*p)) || *p == ',')) {
      ++p;
    }
    if (p >= sc_end || *p == ']') {
      break;
    }
    if (*p != '{') {
      break;
    }
    const char* oe = json_object_end(p);
    if (!oe) {
      break;
    }
    if (first) {
      first = false;
      p = oe;
      continue;
    }
    BgImageLayer* ly = &s_bg_image_layers[s_bg_image_layer_count++];
    bool enabled = false;
    json_extract_bool_for_key(p, oe, "enabled", &enabled);
    ly->enabled = enabled;
    if (!json_extract_string_for_key(p, oe, "background", ly->background_id,
                                     sizeof ly->background_id)) {
      ly->background_id[0] = '\0';
    }
    float px = 1.0f;
    if (!json_extract_float_for_key(p, oe, "parallax_x", &px)) {
      px = 1.0f;
    }
    if (px < 0.0f) {
      px = 0.0f;
    } else if (px > 2.0f) {
      px = 2.0f;
    }
    ly->parallax_x = px;
    bool fixed = false;
    json_extract_bool_for_key(p, oe, "fixed", &fixed);
    ly->fixed = fixed;
    bool repeat_x = false;
    json_extract_bool_for_key(p, oe, "repeat_x", &repeat_x);
    ly->repeat_x = repeat_x;
    ly->pixels = nullptr;
    ly->pw = 0;
    ly->ph = 0;
    ly->loaded = false;

    p = oe;
  }
}

static void resolve_player_actor_index(void) {
  s_player_actor = -1;
  if (s_camera_target[0]) {
    for (int i = 0; i < s_actor_count; ++i) {
      if (strcmp(s_actors[i].obj_id, s_camera_target) == 0) {
        s_player_actor = i;
        return;
      }
    }
  }
  for (int i = 0; i < s_actor_count; ++i) {
    if (strcmp(s_actors[i].obj_id, "player") == 0 ||
        strcmp(s_actors[i].obj_id, "character") == 0) {
      s_player_actor = i;
      return;
    }
  }
  if (s_actor_count > 0) {
    s_player_actor = 0;
  }
}

static void update_camera_follow_player(void) {
  if (!scene_uses_scrolling()) {
    s_cam_x = 0;
    s_cam_y = 0;
    turtle_gpu_set_camera(0, 0);
    return;
  }
  if (s_camera_fixed) {
    clamp_camera_to_world(&s_cam_x, &s_cam_y);
    turtle_gpu_set_camera(s_cam_x, s_cam_y);
    return;
  }
  if (s_player_actor < 0 || s_player_actor >= s_actor_count) {
    clamp_camera_to_world(&s_cam_x, &s_cam_y);
    turtle_gpu_set_camera(s_cam_x, s_cam_y);
    return;
  }
  const SceneActor* p = &s_actors[s_player_actor];
  int cx = s_cam_x;
  int cy = s_cam_y;
  const int mx = s_camera_margin_x;
  const int my = s_camera_margin_y;
  if (p->x < cx + mx) {
    cx = p->x - mx;
  } else if (p->x > cx + (kSceneW - 1) - mx) {
    cx = p->x - ((kSceneW - 1) - mx);
  }
  if (p->y < cy + my) {
    cy = p->y - my;
  } else if (p->y > cy + (kSceneH - 1) - my) {
    cy = p->y - ((kSceneH - 1) - my);
  }
  clamp_camera_to_world(&cx, &cy);
  s_cam_x = cx;
  s_cam_y = cy;
  turtle_gpu_set_camera(s_cam_x, s_cam_y);
}

static void tile_grid_dims(int tile_px, int* cols, int* rows) {
  int px = tile_px;
  if (px < 1) {
    px = 16;
  }
  int c = s_world_w / px;
  int r = s_world_h / px;
  if (c < 1) {
    c = 1;
  }
  if (r < 1) {
    r = 1;
  }
  if (c > kMaxTileCols) {
    c = kMaxTileCols;
  }
  if (r > kMaxTileRows) {
    r = kMaxTileRows;
  }
  *cols = c;
  *rows = r;
}

static bool parse_tile_cells(const char* layer_start, const char* layer_end, int cols, int rows,
                             uint8_t fill, uint8_t cells[kMaxTileRows][kMaxTileCols]) {
  for (int gy = 0; gy < rows; ++gy) {
    for (int gx = 0; gx < cols; ++gx) {
      cells[gy][gx] = fill;
    }
  }
  const char* ck = strstr_bounded(layer_start, layer_end, "\"cells\"");
  if (!ck) {
    return false;
  }
  const char* p = ck + 7;
  while (p < layer_end && *p != '[') {
    ++p;
  }
  if (p >= layer_end || *p != '[') {
    return false;
  }
  ++p;

  int gy = 0;
  while (gy < rows && p < layer_end) {
    while (p < layer_end &&
           (isspace(static_cast<unsigned char>(*p)) || *p == ',')) {
      ++p;
    }
    if (p >= layer_end || *p == ']') {
      break;
    }
    if (*p != '[') {
      return false;
    }
    ++p;

    int gx = 0;
    while (gx < cols && p < layer_end) {
      while (p < layer_end &&
             (isspace(static_cast<unsigned char>(*p)) || *p == ',')) {
        ++p;
      }
      if (p >= layer_end) {
        break;
      }
      if (*p == ']') {
        break;
      }
      int v = 0;
      if (!parse_int_bounded(p, layer_end, &v)) {
        break;
      }
      while (p < layer_end && (*p == '-' || isdigit(static_cast<unsigned char>(*p)))) {
        ++p;
      }
      if (v < 0) {
        v = 0;
      }
      if (v > 255) {
        v = 255;
      }
      cells[gy][gx] = static_cast<uint8_t>(v);
      ++gx;
    }
    while (p < layer_end && isspace(static_cast<unsigned char>(*p))) {
      ++p;
    }
    if (p < layer_end && *p == ']') {
      ++p;
    }
    ++gy;
  }
  return gy > 0;
}

static int parse_tile_layers(const char* sc_start, const char* sc_end, int tile_px, TileLayer* out,
                             int max_out) {
  int cols = 0;
  int rows = 0;
  tile_grid_dims(tile_px, &cols, &rows);

  const char* tk = strstr_bounded(sc_start, sc_end, "\"tile_layers\"");
  if (!tk) {
    return 0;
  }
  const char* p = tk + 13;
  while (p < sc_end && *p != '[') {
    ++p;
  }
  if (p >= sc_end || *p != '[') {
    return 0;
  }
  ++p;

  int n = 0;
  while (p < sc_end && *p != ']' && n < max_out) {
    while (p < sc_end && (isspace(static_cast<unsigned char>(*p)) || *p == ',')) {
      ++p;
    }
    if (p >= sc_end || *p == ']') {
      break;
    }
    if (*p != '{') {
      break;
    }
    const char* ob = p;
    const char* oe = json_object_end(ob);
    if (!oe) {
      break;
    }

    TileLayer* ly = &out[n];
    ly->enabled = false;
    ly->tileset[0] = '\0';
    ly->cols = cols;
    ly->rows = rows;
    json_extract_bool_for_key(ob, oe, "enabled", &ly->enabled);
    json_extract_string_for_key(ob, oe, "tileset", ly->tileset, sizeof ly->tileset);
    if (!ly->tileset[0]) {
      json_extract_string_for_key(ob, oe, "tileset_id", ly->tileset, sizeof ly->tileset);
    }
    parse_tile_cells(ob, oe, cols, rows, static_cast<uint8_t>(kDefaultTransparentIndex),
                     ly->cells);
    ++n;
    p = oe;
  }
  return n;
}

static bool resolve_tileset_tts(const char* json, const char* json_end, const char* tileset_id,
                                AssetSdLoad* sd, TurtleTileset* ts) {
  turtle_tileset_free(ts);
  s_tileset_coll_loaded_id[0] = '\0';

  const char* inner = nullptr;
  const char* inner_end = nullptr;
  if (find_tileset_inner(json, json_end, tileset_id, &inner, &inner_end)) {
    const char* asset_inner = inner;
    const char* asset_inner_end = inner_end;
    if (!sd->resolve(inner, inner_end, &asset_inner, &asset_inner_end)) {
      return false;
    }
    const size_t blob_len = (asset_inner_end > asset_inner)
                                ? static_cast<size_t>(asset_inner_end - asset_inner)
                                : 0;
    if (!buffer_is_turtle_tileset_bin(asset_inner, blob_len)) {
      Serial.printf("turtle_scene: tileset \"%s\" en bundle no es .tts binario\n", tileset_id);
      return false;
    }
    if (!turtle_tileset_load_tts(reinterpret_cast<const uint8_t*>(asset_inner), blob_len, ts)) {
      return false;
    }
    // v1 .tts ya trae colision embebida (ver turtle_tileset_load_tts); el fallback JSON
    // solo aplica a binarios v0 legacy, si no pisaria los datos recien parseados.
    if (ts->format_version == 0) {
      tileset_load_collision_meta(json, json_end, tileset_id, inner, inner_end, ts);
    }
    snprintf(s_tileset_coll_loaded_id, sizeof s_tileset_coll_loaded_id, "%s", tileset_id);
    return true;
  }

  char path[80];
  snprintf(path, sizeof path, "/tiles/%s.tts", tileset_id);
  if (!sd->load_path(path)) {
    Serial.printf("turtle_scene: tileset \"%s\" no en bundle ni %s en SD\n", tileset_id, path);
    return false;
  }
  if (!buffer_is_turtle_tileset_bin(sd->buf.data, sd->buf.len)) {
    Serial.printf("turtle_scene: %s no es .tts valido\n", path);
    return false;
  }
  if (!turtle_tileset_load_tts(reinterpret_cast<const uint8_t*>(sd->buf.data), sd->buf.len, ts)) {
    return false;
  }
  if (ts->format_version == 0) {
    tileset_load_collision_meta(json, json_end, tileset_id, nullptr, nullptr, ts);
  }
  snprintf(s_tileset_coll_loaded_id, sizeof s_tileset_coll_loaded_id, "%s", tileset_id);
  return true;
}

/** Carga un .tfn desde el bundle (ref o inline) o SD (/fonts/<id>.tfn) directo. */
static bool resolve_font_tfn(const char* json, const char* json_end, const char* font_id,
                             AssetSdLoad* sd, TurtleFont* font) {
  turtle_font_free(font);

  const char* inner = nullptr;
  const char* inner_end = nullptr;
  if (find_font_inner(json, json_end, font_id, &inner, &inner_end)) {
    const char* asset_inner = inner;
    const char* asset_inner_end = inner_end;
    if (!sd->resolve(inner, inner_end, &asset_inner, &asset_inner_end)) {
      return false;
    }
    const size_t blob_len = (asset_inner_end > asset_inner)
                                ? static_cast<size_t>(asset_inner_end - asset_inner)
                                : 0;
    if (!buffer_is_turtle_font_bin(asset_inner, blob_len)) {
      Serial.printf("turtle_scene: fuente \"%s\" en bundle no es .tfn binario\n", font_id);
      return false;
    }
    return turtle_font_load_tfn(reinterpret_cast<const uint8_t*>(asset_inner), blob_len, font);
  }

  char path[80];
  snprintf(path, sizeof path, "/fonts/%s.tfn", font_id);
  if (!sd->load_path(path)) {
    Serial.printf("turtle_scene: fuente \"%s\" no en bundle ni %s en SD\n", font_id, path);
    return false;
  }
  if (!buffer_is_turtle_font_bin(sd->buf.data, sd->buf.len)) {
    Serial.printf("turtle_scene: %s no es .tfn valido\n", path);
    return false;
  }
  return turtle_font_load_tfn(reinterpret_cast<const uint8_t*>(sd->buf.data), sd->buf.len, font);
}

// Pequena cache residente de fuentes ya decodificadas (glifos redibujados cada frame en
// HUD/dialogo; re-decodificar por caracter/frame seria un desperdicio, y una fuente
// completa es pequena frente al resto de buffers del runtime — ver spec/asset-bin-v0.md).
// Tamano fijo (no una entrada por fuente vista) para no mantener N structs residentes sin
// limite, mismo espiritu que el comentario de s_tileset_coll de mas arriba.
constexpr int kMaxFontCache = 4;

struct FontCacheEntry {
  char id[48] = "";
  TurtleFont font = {};
  bool valid = false;
};

static FontCacheEntry s_font_cache[kMaxFontCache];
static int s_font_cache_next_evict = 0;

static void font_cache_clear_all(void) {
  for (int i = 0; i < kMaxFontCache; ++i) {
    turtle_font_free(&s_font_cache[i].font);
    s_font_cache[i].id[0] = '\0';
    s_font_cache[i].valid = false;
  }
  s_font_cache_next_evict = 0;
}

static const TurtleFont* font_cache_get(const char* json, const char* json_end,
                                        const char* font_id) {
  if (!font_id || !font_id[0]) {
    return nullptr;
  }
  for (int i = 0; i < kMaxFontCache; ++i) {
    if (s_font_cache[i].valid && strcmp(s_font_cache[i].id, font_id) == 0) {
      return &s_font_cache[i].font;
    }
  }
  int slot = -1;
  for (int i = 0; i < kMaxFontCache; ++i) {
    if (!s_font_cache[i].valid) {
      slot = i;
      break;
    }
  }
  if (slot < 0) {
    slot = s_font_cache_next_evict;
    s_font_cache_next_evict = (s_font_cache_next_evict + 1) % kMaxFontCache;
  }
  s_font_cache[slot].valid = false;
  AssetSdLoad sd;
  if (!resolve_font_tfn(json, json_end, font_id, &sd, &s_font_cache[slot].font)) {
    return nullptr;
  }
  snprintf(s_font_cache[slot].id, sizeof s_font_cache[slot].id, "%s", font_id);
  s_font_cache[slot].valid = true;
  return &s_font_cache[slot].font;
}

static uint8_t* alloc_scene_pixel_buffer(size_t need, int* out_in_psram) {
  if (need == 0 || need > kScenePixelsMaxBytes) {
    return nullptr;
  }
  if (out_in_psram) {
    *out_in_psram = 0;
  }
#if defined(ESP32) || defined(ESP_PLATFORM)
  uint8_t* p = static_cast<uint8_t*>(
      heap_caps_malloc(need, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (p) {
    if (out_in_psram) {
      *out_in_psram = 1;
    }
    return p;
  }
  p = static_cast<uint8_t*>(
      heap_caps_malloc(need, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
  if (p) {
    return p;
  }
#else
  uint8_t* p = static_cast<uint8_t*>(malloc(need));
  if (p) {
    return p;
  }
#endif
  return nullptr;
}

static bool ensure_world_buffer_filled(uint8_t fill_ci) {
  if (s_world_bg && s_world_bg_w == s_world_w && s_world_bg_h == s_world_h) {
    return true;
  }
  world_bg_release();
  const size_t need = static_cast<size_t>(s_world_w) * static_cast<size_t>(s_world_h);
  int in_psram = 0;
  uint8_t* buf = alloc_scene_pixel_buffer(need, &in_psram);
  if (!buf) {
    Serial.printf("turtle_scene: sin RAM para mundo estatico %ux%u (necesita ~%u bytes)\n",
                  static_cast<unsigned>(s_world_w), static_cast<unsigned>(s_world_h),
                  static_cast<unsigned>(need));
#if defined(ESP32) || defined(ESP_PLATFORM)
    Serial.printf("  PSRAM libre ~%u, bloque max ~%u\n",
                  static_cast<unsigned>(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)),
                  static_cast<unsigned>(
                      heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM)));
#endif
    return false;
  }
  s_world_bg = buf;
  s_world_bg_w = s_world_w;
  s_world_bg_h = s_world_h;
  memset(s_world_bg, fill_ci, need);
  Serial.printf("turtle_scene: buffer mundo %dx%d (%s)\n", s_world_bg_w, s_world_bg_h,
                in_psram ? "PSRAM" : "DRAM");
  return true;
}

static bool bake_indexed_background_into_world(const char* json, const char* json_end,
                                               const char* scene_start,
                                               const char* scene_end) {
  char bg_id[48];
  if (!resolve_scene_base_background_id(scene_start, scene_end, bg_id, sizeof bg_id)) {
    return true;
  }

  const char* inner = nullptr;
  const char* inner_end = nullptr;
  if (!find_background_inner(json, json_end, bg_id, &inner, &inner_end)) {
    return false;
  }

  AssetSdLoad sd;
  const char* asset_inner = inner;
  const char* asset_inner_end = inner_end;
  if (!sd.resolve(inner, inner_end, &asset_inner, &asset_inner_end)) {
    return false;
  }

  const size_t bg_blob_len =
      (asset_inner_end > asset_inner) ? static_cast<size_t>(asset_inner_end - asset_inner) : 0;

  int pw = 0;
  int ph = 0;
  if (!read_asset_bin_dims(asset_inner, bg_blob_len, &pw, &ph) &&
      !resolve_pixel_dims_sprite(asset_inner, asset_inner_end, &pw, &ph)) {
    return false;
  }
  if (!render_mode_is_indexed_pixels(asset_inner, asset_inner_end) &&
      !buffer_is_turtle_asset_bin(asset_inner, bg_blob_len)) {
    int pci = 0;
    if (!extract_palette_index_sprite(asset_inner, asset_inner_end, &pci)) {
      return false;
    }
    if (pci < 0) {
      pci = 0;
    }
    if (pci > 31) {
      pci = 31;
    }
    if (pw < 1) {
      pw = s_world_w;
    }
    if (ph < 1) {
      ph = s_world_h;
    }
    if (pw > s_world_w) {
      pw = s_world_w;
    }
    if (ph > s_world_h) {
      ph = s_world_h;
    }
    for (int sy = 0; sy < ph; ++sy) {
      for (int sx = 0; sx < pw; ++sx) {
        world_buffer_put_scene_pixel(sx, sy, static_cast<uint8_t>(pci));
      }
    }
    return true;
  }
  if (pw <= 0 || ph <= 0) {
    return false;
  }
  if (pw > s_world_bg_w || ph > s_world_bg_h) {
    Serial.printf("turtle_scene: fondo %dx%d > buffer %dx%d\n", pw, ph, s_world_bg_w, s_world_bg_h);
    return false;
  }
  return decode_indexed_asset_to_buffer(asset_inner, asset_inner_end, bg_id, pw, ph, s_world_bg,
                                        s_world_bg_w);
}

/** Carga una capa extra (spec/scene-v0.md "Capas de fondo con imagen") en SU PROPIO buffer
 *  (no se hornea junto a s_world_bg: necesita permanecer independiente para poder desplazarse
 *  a su propio parallax_x en paint_bg_image_layers). Solo acepta assets indexed_pixels/.tbg;
 *  un fondo solido no aporta nada como capa aparte (ya existe color_index/opacity para eso). */
static bool load_one_bg_image_layer(const char* json, const char* json_end, BgImageLayer* ly) {
  if (!ly->enabled || !ly->background_id[0]) {
    return false;
  }
  const char* inner = nullptr;
  const char* inner_end = nullptr;
  if (!find_background_inner(json, json_end, ly->background_id, &inner, &inner_end)) {
    Serial.printf("turtle_scene: capa fondo \"%s\" no encontrada en bundle\n", ly->background_id);
    return false;
  }
  AssetSdLoad sd;
  const char* asset_inner = inner;
  const char* asset_inner_end = inner_end;
  if (!sd.resolve(inner, inner_end, &asset_inner, &asset_inner_end)) {
    return false;
  }
  const size_t blob_len =
      (asset_inner_end > asset_inner) ? static_cast<size_t>(asset_inner_end - asset_inner) : 0;
  int pw = 0;
  int ph = 0;
  if (!read_asset_bin_dims(asset_inner, blob_len, &pw, &ph) &&
      !resolve_pixel_dims_sprite(asset_inner, asset_inner_end, &pw, &ph)) {
    return false;
  }
  if (!render_mode_is_indexed_pixels(asset_inner, asset_inner_end) &&
      !buffer_is_turtle_asset_bin(asset_inner, blob_len)) {
    Serial.printf("turtle_scene: capa fondo \"%s\" no es indexed_pixels; se omite\n",
                  ly->background_id);
    return false;
  }
  if (pw <= 0 || ph <= 0) {
    return false;
  }
  const size_t need = static_cast<size_t>(pw) * static_cast<size_t>(ph);
  int in_psram = 0;
  uint8_t* buf = alloc_scene_pixel_buffer(need, &in_psram);
  if (!buf) {
    Serial.printf("turtle_scene: sin RAM para capa fondo \"%s\" (%dx%d)\n", ly->background_id, pw,
                  ph);
    return false;
  }
  if (!decode_indexed_asset_to_buffer(asset_inner, asset_inner_end, ly->background_id, pw, ph, buf,
                                      pw)) {
#if defined(ESP32) || defined(ESP_PLATFORM)
    heap_caps_free(buf);
#else
    free(buf);
#endif
    return false;
  }
  ly->pixels = buf;
  ly->pw = pw;
  ly->ph = ph;
  ly->loaded = true;
  Serial.printf("turtle_scene: capa fondo \"%s\" %dx%d cargada (%s, parallax_x=%d/100)\n",
                ly->background_id, pw, ph, in_psram ? "PSRAM" : "DRAM",
                static_cast<int>(ly->parallax_x * 100));
  return true;
}

static void load_bg_image_layers(const char* json, const char* json_end) {
  for (int i = 0; i < s_bg_image_layer_count; ++i) {
    load_one_bg_image_layer(json, json_end, &s_bg_image_layers[i]);
  }
}

static void bake_tile_cell_into_world(int gx, int gy, int rows, int px, const uint8_t* tile,
                                      uint8_t transparent_index) {
  if (!tile || px <= 0) {
    return;
  }
  const int sy0 = (rows - 1 - gy) * px;
  for (int tpy = 0; tpy < px; ++tpy) {
    for (int tpx = 0; tpx < px; ++tpx) {
      const uint8_t ci = tile[static_cast<size_t>(tpy) * static_cast<size_t>(px) +
                            static_cast<size_t>(tpx)];
      if (ci == transparent_index) {
        continue;
      }
      const int sx = gx * px + tpx;
      const int sy = sy0 + (px - 1 - tpy);
      world_buffer_put_scene_pixel(sx, sy, ci);
    }
  }
}

static bool bake_tile_layers_into_world(const char* json, const char* json_end,
                                        const char* scene_start, const char* scene_end,
                                        uint8_t transparent_index) {
  int tile_px = s_runtime_tile_px;
  if (tile_px < 4 || tile_px > 64) {
    tile_px = 16;
  }
  const int nl =
      parse_tile_layers(scene_start, scene_end, tile_px, s_tile_layers, kMaxTileLayers);
  s_runtime_tile_layer_count = nl;
  if (nl <= 0) {
    return true;
  }

  int painted = 0;
  char last_id[48] = "";
  turtle_tileset_free(&s_tileset_draw);
  AssetSdLoad sd;

  for (int li = 0; li < nl; ++li) {
    const TileLayer* ly = &s_tile_layers[li];
    if (!ly->enabled || !ly->tileset[0]) {
      continue;
    }
    if (strcmp(last_id, ly->tileset) != 0) {
      turtle_tileset_free(&s_tileset_draw);
      if (!resolve_tileset_tts(json, json_end, ly->tileset, &sd, &s_tileset_draw)) {
        last_id[0] = '\0';
        continue;
      }
      snprintf(last_id, sizeof last_id, "%s", ly->tileset);
    }
    if (s_tileset_draw.tile_px != static_cast<uint8_t>(tile_px)) {
      continue;
    }

    const int cols = ly->cols;
    const int rows = ly->rows;
    for (int gy = 0; gy < rows; ++gy) {
      for (int gx = 0; gx < cols; ++gx) {
        const int ti = ly->cells[gy][gx];
        if (ti == static_cast<int>(transparent_index) || ti < 0) {
          continue;
        }
        const uint8_t* tile = turtle_tileset_tile(&s_tileset_draw, ti);
        if (!tile) {
          continue;
        }
        bake_tile_cell_into_world(gx, gy, rows, tile_px, tile, transparent_index);
        ++painted;
      }
    }
  }
  turtle_tileset_free(&s_tileset_draw);
  if (painted > 0) {
    Serial.printf("turtle_scene: tiles horneados en buffer mundo (%d celdas)\n", painted);
  }
  return true;
}

static bool prepare_world_static_composite(const char* json, const char* json_end,
                                           const char* scene_start, const char* scene_end) {
  s_world_static_ready = false;
  if (!scene_uses_scrolling()) {
    return false;
  }
  if (!ensure_world_buffer_filled(static_cast<uint8_t>(s_runtime_bg))) {
    return false;
  }
  if (!bake_indexed_background_into_world(json, json_end, scene_start, scene_end)) {
    Serial.println("turtle_scene: aviso: fondo indexado no horneado");
  }
  load_bg_image_layers(json, json_end);
  if (!bake_tile_layers_into_world(json, json_end, scene_start, scene_end, s_runtime_transp)) {
    Serial.println("turtle_scene: aviso: tiles no horneados");
  }
  s_world_static_ready = true;
  return true;
}

static void draw_tile_layers_for_scene(const char* json, const char* json_end,
                                       const char* scene_start, const char* scene_end,
                                       uint8_t transparent_index) {
  int tile_px = 16;
  if (!json_extract_int_for_key(json, json_end, "tile_px", &tile_px) || tile_px < 4 ||
      tile_px > 64) {
    tile_px = 16;
  }

  const int nl =
      parse_tile_layers(scene_start, scene_end, tile_px, s_tile_layers, kMaxTileLayers);
  if (nl <= 0) {
    return;
  }

  int painted = 0;
  char last_id[48] = "";
  turtle_tileset_free(&s_tileset_draw);
  AssetSdLoad sd;

  for (int li = 0; li < nl; ++li) {
    const TileLayer* ly = &s_tile_layers[li];
    if (!ly->enabled || !ly->tileset[0]) {
      continue;
    }
    if (strcmp(last_id, ly->tileset) != 0) {
      turtle_tileset_free(&s_tileset_draw);
      if (!resolve_tileset_tts(json, json_end, ly->tileset, &sd, &s_tileset_draw)) {
        last_id[0] = '\0';
        continue;
      }
      snprintf(last_id, sizeof last_id, "%s", ly->tileset);
      Serial.printf("turtle_scene: tileset \"%s\" listo (%u tiles, %u px)\n", ly->tileset,
                    static_cast<unsigned>(s_tileset_draw.tile_count),
                    static_cast<unsigned>(s_tileset_draw.tile_px));
    }
    if (s_tileset_draw.tile_px != static_cast<uint8_t>(tile_px)) {
      Serial.printf("turtle_scene: tileset \"%s\" tile_px=%u != bundle %d; capa omitida\n",
                    ly->tileset, static_cast<unsigned>(s_tileset_draw.tile_px), tile_px);
      continue;
    }

    const int cols = ly->cols;
    const int rows = ly->rows;
    const int px = tile_px;
    for (int gy = 0; gy < rows; ++gy) {
      const int sy0 = (rows - 1 - gy) * px;
      for (int gx = 0; gx < cols; ++gx) {
        const int ti = ly->cells[gy][gx];
        if (ti == static_cast<int>(transparent_index) || ti < 0) {
          continue;
        }
        const uint8_t* tile = turtle_tileset_tile(&s_tileset_draw, ti);
        if (!tile) {
          continue;
        }
        turtle_gpu_blit_indexed_scene(gx * px, sy0, px, px, tile, px, transparent_index);
        ++painted;
        if ((painted & 7) == 0) {
          yield();
        }
      }
    }
  }
  turtle_tileset_free(&s_tileset_draw);
  s_runtime_tile_px = tile_px;
  s_runtime_tile_layer_count = nl;
  if (painted > 0) {
    Serial.printf("turtle_scene: %d celdas tile pintadas (%d capas)\n", painted, nl);
  }
}

static bool parse_placements(const char* scene_start, const char* scene_end, Placement* out,
                             int* out_count) {
  *out_count = 0;
  const char* ok = strstr_bounded(scene_start, scene_end, "\"objects\"");
  if (!ok) {
    return false;
  }
  const char* p = ok + 9;
  while (p < scene_end && *p != ':') {
    ++p;
  }
  if (p >= scene_end) {
    return false;
  }
  ++p;
  while (p < scene_end && isspace(static_cast<unsigned char>(*p))) {
    ++p;
  }
  if (p >= scene_end || *p != '[') {
    return false;
  }
  ++p;
  int n = 0;
  while (p < scene_end && *p != ']') {
    while (p < scene_end && (isspace(static_cast<unsigned char>(*p)) || *p == ',')) {
      ++p;
    }
    if (p >= scene_end || *p == ']') {
      break;
    }
    if (*p != '{') {
      return false;
    }
    const char* ob = p;
    const char* oe = json_object_end(ob);
    if (!oe) {
      return false;
    }
    if (n >= kMaxPlacements) {
      return false;
    }
    if (!json_extract_string_for_key(ob, oe, "id", out[n].obj_id, sizeof(out[n].obj_id))) {
      return false;
    }
    if (!json_extract_int_for_key(ob, oe, "x", &out[n].x)) {
      return false;
    }
    if (!json_extract_int_for_key(ob, oe, "y", &out[n].y)) {
      return false;
    }
    ++n;
    p = oe;
  }
  *out_count = n;
  return true;
}

static bool scene_block_is_scene_layer(const char* block_start, const char* block_end) {
  return strstr_bounded(block_start, block_end, "\"background_index\"") != nullptr;
}

static bool find_scene_block(const char* json, const char* json_end, const char* scene_id,
                             const char** scene_begin, const char** scene_end) {
  const char* scenes_key = strstr_bounded(json, json_end, "\"scenes\"");
  if (!scenes_key) {
    return false;
  }
  const char* br = strchr(scenes_key, '[');
  if (!br || br >= json_end) {
    return false;
  }
  const char* p = br + 1;
  while (p < json_end && *p != ']') {
    while (p < json_end && (isspace(static_cast<unsigned char>(*p)) || *p == ',')) {
      ++p;
    }
    if (p >= json_end || *p == ']') {
      break;
    }
    if (*p != '{') {
      return false;
    }
    const char* obj_begin = p;
    const char* obj_end = json_object_end(obj_begin);
    if (!obj_end) {
      return false;
    }
    if (scene_block_is_scene_layer(obj_begin, obj_end)) {
      char sid[40];
      if (json_extract_string_for_key(obj_begin, obj_end, "id", sid, sizeof sid) &&
          strcmp(sid, scene_id) == 0) {
        *scene_begin = obj_begin;
        *scene_end = obj_end;
        return true;
      }
    }
    p = obj_end;
  }
  return false;
}

static void parse_scene_timing(const char* json, const char* json_end, const char* sc_start,
                               const char* sc_end) {
  int tf = 30;
  int af = 8;
  if (!json_extract_int_for_key(json, json_end, "target_fps", &tf) || tf < 15 || tf > 60) {
    tf = 30;
  }
  if (!json_extract_int_for_key(json, json_end, "default_anim_fps", &af) || af < 1 || af > 30) {
    af = 8;
  }
  if (sc_start && sc_end && sc_end > sc_start) {
    int stf = 0;
    int saf = 0;
    if (json_extract_int_for_key(sc_start, sc_end, "target_fps", &stf) && stf >= 15 &&
        stf <= 60) {
      tf = stf;
    }
    if (json_extract_int_for_key(sc_start, sc_end, "default_anim_fps", &saf) && saf >= 1 &&
        saf <= 30) {
      af = saf;
    }
  }
  s_target_fps = tf;
  s_default_anim_fps = af;
}

static bool resolve_object_json(const char* json, const char* json_end, const char* obj_id,
                                const char** out_inner, const char** out_inner_end) {
  if (!json || !json_end || !obj_id || !obj_id[0] || !out_inner || !out_inner_end) {
    return false;
  }
  if (object_cache_find(obj_id, out_inner, out_inner_end)) {
    return true;
  }

  const char* od = find_root_objects_dict_brace(json, json_end);
  if (!od || *od != '{') {
    return false;
  }
  const char* od_end = json_object_end(od);
  if (!od_end) {
    return false;
  }

  char pat[40];
  snprintf(pat, sizeof pat, "\"%s\":", obj_id);
  const char* hit = strstr_bounded(od, od_end, pat);
  if (!hit) {
    return false;
  }
  const char* oinner = strchr(hit + strlen(pat), '{');
  if (!oinner || oinner >= od_end) {
    return false;
  }
  const char* oinner_end = json_object_end(oinner);
  if (!oinner_end) {
    return false;
  }

  AssetSdLoad obj_sd;
  const char* obj_inner = oinner;
  const char* obj_inner_end = oinner_end;
  if (!obj_sd.resolve(oinner, oinner_end, &obj_inner, &obj_inner_end)) {
    return false;
  }

  if (obj_sd.loaded && obj_sd.buf.data) {
    if (object_cache_add_move(obj_id, &obj_sd.buf)) {
      return object_cache_find(obj_id, out_inner, out_inner_end);
    }
    return false;
  }

  *out_inner = obj_inner;
  *out_inner_end = obj_inner_end;
  return true;
}

/** Cache PSRAM para .tsp en SD; datos inline del bundle no se copian. */
static bool resolve_sprite_asset(const char* json, const char* json_end, const char* sprite_id,
                                 AssetSdLoad* sd, const char** inner, const char** inner_end) {
  if (sprite_cache_find(sprite_id, inner, inner_end)) {
    return true;
  }

  if (!resolve_sprite_inner(json, json_end, sprite_id, sd, inner, inner_end)) {
    return false;
  }

  if (sd->loaded && sd->buf.data) {
    if (sprite_cache_add_move(sprite_id, &sd->buf)) {
      return sprite_cache_find(sprite_id, inner, inner_end);
    }
  }
  return true;
}

static void sprite_cache_touch(const char* json, const char* json_end, const char* sprite_id) {
  if (!sprite_id || !sprite_id[0]) {
    return;
  }
  AssetSdLoad sd;
  const char* inner = nullptr;
  const char* inner_end = nullptr;
  resolve_sprite_asset(json, json_end, sprite_id, &sd, &inner, &inner_end);
}

static void prewarm_actor_sprites(const char* json, const char* json_end, int actor_index) {
  if (actor_index < 0 || actor_index >= s_actor_count) {
    return;
  }
  sprite_cache_touch(json, json_end, s_actors[actor_index].sprite_id);

  const char* obj_inner = nullptr;
  const char* obj_inner_end = nullptr;
  if (!resolve_object_json(json, json_end, s_actors[actor_index].obj_id, &obj_inner,
                           &obj_inner_end)) {
    return;
  }

  const char* key = strstr_bounded(obj_inner, obj_inner_end, "\"animations\"");
  if (!key) {
    return;
  }
  const char* p = strchr(key + 12, '[');
  if (!p || p >= obj_inner_end) {
    return;
  }
  ++p;
  while (p < obj_inner_end) {
    while (p < obj_inner_end &&
           (isspace(static_cast<unsigned char>(*p)) || *p == ',' || *p == '\n' || *p == '\r')) {
      ++p;
    }
    if (p >= obj_inner_end || *p == ']') {
      break;
    }
    if (*p != '{') {
      ++p;
      continue;
    }
    const char* ob = p;
    const char* oe = json_object_end(ob);
    if (!oe) {
      break;
    }
    char spr[48];
    if (json_extract_string_for_key(ob, oe, "sprite_id", spr, sizeof spr) && spr[0]) {
      sprite_cache_touch(json, json_end, spr);
    }
    p = oe + 1;
  }
}

/** Busca `anim_name` en `animations` del objeto; resultado en buffer estatico (un hilo). */
static const char* lookup_anim_sprite(int actor_index, const char* anim_name) {
  static char sprite_out[48];
  sprite_out[0] = '\0';

  if (!anim_name || !anim_name[0] || actor_index < 0 || actor_index >= s_actor_count ||
      !s_runtime_json || !s_runtime_json_end) {
    return nullptr;
  }

  const char* obj_inner = nullptr;
  const char* obj_inner_end = nullptr;
  if (!resolve_object_json(s_runtime_json, s_runtime_json_end, s_actors[actor_index].obj_id,
                           &obj_inner, &obj_inner_end)) {
    return nullptr;
  }

  const char* key = strstr_bounded(obj_inner, obj_inner_end, "\"animations\"");
  if (!key) {
    return nullptr;
  }
  const char* p = strchr(key + 12, '[');
  if (!p || p >= obj_inner_end) {
    return nullptr;
  }
  ++p;
  while (p < obj_inner_end) {
    while (p < obj_inner_end &&
           (isspace(static_cast<unsigned char>(*p)) || *p == ',' || *p == '\n' || *p == '\r')) {
      ++p;
    }
    if (p >= obj_inner_end || *p == ']') {
      break;
    }
    if (*p != '{') {
      ++p;
      continue;
    }
    const char* ob = p;
    const char* oe = json_object_end(ob);
    if (!oe) {
      break;
    }
    char name[33];
    char spr[48];
    if (json_extract_string_for_key(ob, oe, "name", name, sizeof name) &&
        json_extract_string_for_key(ob, oe, "sprite_id", spr, sizeof spr) && name[0] && spr[0] &&
        strcmp(name, anim_name) == 0) {
      snprintf(sprite_out, sizeof sprite_out, "%s", spr);
      return sprite_out;
    }
    p = oe + 1;
  }
  return nullptr;
}

static uint16_t anim_speed_from_float(float speed) {
  if (speed < 0.25f) {
    speed = 0.25f;
  }
  if (speed > 16.0f) {
    speed = 16.0f;
  }
  int v = static_cast<int>(speed * 16.0f + 0.5f);
  if (v < 1) {
    v = 1;
  }
  if (v > 255) {
    v = 255;
  }
  return static_cast<uint16_t>(v);
}

static bool actor_apply_sprite(int actor_index, const char* sprite_id, bool restart) {
  if (!sprite_id || !sprite_id[0] || actor_index < 0 || actor_index >= s_actor_count ||
      !s_runtime_json || !s_runtime_json_end) {
    return false;
  }
  SceneActor* a = &s_actors[actor_index];
  const bool same_sprite = (strcmp(a->sprite_id, sprite_id) == 0);

  AssetSdLoad sd;
  const char* asset_inner = nullptr;
  const char* asset_inner_end = nullptr;
  if (!resolve_sprite_asset(s_runtime_json, s_runtime_json_end, sprite_id, &sd, &asset_inner,
                            &asset_inner_end)) {
    return false;
  }

  const char* meta_inner = nullptr;
  const char* meta_inner_end = nullptr;
  find_sprite_inner(s_runtime_json, s_runtime_json_end, sprite_id, &meta_inner, &meta_inner_end);

  const size_t blob_len =
      (asset_inner_end > asset_inner) ? static_cast<size_t>(asset_inner_end - asset_inner) : 0;
  int pw = 0;
  int ph = 0;
  if (!read_asset_bin_dims(asset_inner, blob_len, &pw, &ph) &&
      !resolve_pixel_dims_sprite(asset_inner, asset_inner_end, &pw, &ph)) {
    return false;
  }

  snprintf(a->sprite_id, sizeof a->sprite_id, "%s", sprite_id);
  a->pw = pw;
  a->ph = ph;
  extract_sprite_origin(meta_inner, meta_inner_end, asset_inner, asset_inner_end, a->pw, a->ph,
                        &a->origin_x, &a->origin_y);
  a->frame_count =
      static_cast<uint8_t>(sprite_frame_count_from_asset(asset_inner, asset_inner_end, blob_len));
  if (a->frame_count < 1) {
    a->frame_count = 1;
  }

  if (!same_sprite || restart) {
    a->frame_index = 0;
    a->frame_accum_ms = 0;
  }

  s_actor_draw_cache[actor_index].pixels_valid = false;
  return true;
}

static bool init_actor_from_placement(const char* json, const char* json_end,
                                      const Placement* pl, SceneActor* actor) {
  const char* obj_inner = nullptr;
  const char* obj_inner_end = nullptr;
  if (!resolve_object_json(json, json_end, pl->obj_id, &obj_inner, &obj_inner_end)) {
    return false;
  }

  snprintf(actor->obj_id, sizeof actor->obj_id, "%s", pl->obj_id);
  actor->script_stem[0] = '\0';
  json_extract_string_for_key(obj_inner, obj_inner_end, "script", actor->script_stem,
                              sizeof actor->script_stem);
  actor->sprite_id[0] = '\0';
  if (!json_extract_string_for_key(obj_inner, obj_inner_end, "sprite_id", actor->sprite_id,
                                   sizeof actor->sprite_id)) {
    return false;
  }
  actor->x = pl->x;
  actor->y = pl->y;
  actor->frame_index = 0;
  actor->frame_accum_ms = 0;
  actor->anim_speed_x16 = 16;
  actor->anim_repeat = true;
  actor->anim_name[0] = '\0';
  actor->flip_h = false;
  actor->has_prev_blit = false;
  actor->has_text = false;
  actor->text_has_prev_blit = false;
  actor->text_buf[0] = '\0';
  actor->text_font_id[0] = '\0';
  actor->text_color = -1;

  AssetSdLoad sd;
  const char* asset_inner = nullptr;
  const char* asset_inner_end = nullptr;
  if (!resolve_sprite_asset(json, json_end, actor->sprite_id, &sd, &asset_inner, &asset_inner_end)) {
    return false;
  }

  const char* meta_inner = nullptr;
  const char* meta_inner_end = nullptr;
  find_sprite_inner(json, json_end, actor->sprite_id, &meta_inner, &meta_inner_end);

  const size_t blob_len =
      (asset_inner_end > asset_inner) ? static_cast<size_t>(asset_inner_end - asset_inner) : 0;
  actor->pw = 0;
  actor->ph = 0;
  if (!read_asset_bin_dims(asset_inner, blob_len, &actor->pw, &actor->ph) &&
      !resolve_pixel_dims_sprite(asset_inner, asset_inner_end, &actor->pw, &actor->ph)) {
    return false;
  }
  extract_sprite_origin(meta_inner, meta_inner_end, asset_inner, asset_inner_end, actor->pw,
                        actor->ph, &actor->origin_x, &actor->origin_y);
  actor->frame_count =
      static_cast<uint8_t>(sprite_frame_count_from_asset(asset_inner, asset_inner_end, blob_len));
  if (actor->frame_count < 1) {
    actor->frame_count = 1;
  }

  actor->col_x0 = -actor->origin_x;
  actor->col_y0 = -actor->origin_y;
  actor->col_x1 = actor->pw - 1 - actor->origin_x;
  actor->col_y1 = actor->ph - 1 - actor->origin_y;
  actor->grounded = false;

  const char* coll_key = strstr_bounded(obj_inner, obj_inner_end, "\"collision\"");
  if (coll_key) {
    const char* cob = strchr(coll_key + 11, '{');
    if (cob && cob < obj_inner_end) {
      const char* coe = json_object_end(cob);
      if (coe) {
        int cx0 = 0;
        int cy0 = 0;
        int cx1 = 0;
        int cy1 = 0;
        if (json_extract_int_for_key(cob, coe, "x0", &cx0) &&
            json_extract_int_for_key(cob, coe, "y0", &cy0) &&
            json_extract_int_for_key(cob, coe, "x1", &cx1) &&
            json_extract_int_for_key(cob, coe, "y1", &cy1)) {
          actor->col_x0 = cx0;
          actor->col_y0 = cy0;
          actor->col_x1 = cx1;
          actor->col_y1 = cy1;
        }
      }
    }
  }

  return true;
}

static void actor_world_aabb(const SceneActor* a, int* x0, int* y0, int* x1, int* y1) {
  int left = a->x + a->col_x0;
  int right = a->x + a->col_x1;
  int bottom = a->y + a->col_y0;
  int top = a->y + a->col_y1;
  if (left > right) {
    const int t = left;
    left = right;
    right = t;
  }
  if (bottom > top) {
    const int t = bottom;
    bottom = top;
    top = t;
  }
  *x0 = left;
  *y0 = bottom;
  *x1 = right;
  *y1 = top;
}

static bool tile_cell_blocks_actor(int gx, int gy, int ax0, int ay0, int ax1, int ay1, int step_dx,
                                   int step_dy, bool ground_probe) {
  if (gx < 0 || gy < 0 || gx >= kMaxTileCols || gy >= kMaxTileRows) {
    return false;
  }
  if (!s_runtime_json || !s_runtime_json_end) {
    return false;
  }
  const int px = s_runtime_tile_px;
  if (px < 1) {
    return false;
  }
  int cols = 0;
  int rows = 0;
  tile_grid_dims(px, &cols, &rows);
  if (gx >= cols || gy >= rows) {
    return false;
  }
  const int tsy0 = (rows - 1 - gy) * px;
  const int tsy1 = tsy0 + px - 1;
  const int tsx0 = gx * px;
  const int tsx1 = tsx0 + px - 1;

  for (int li = 0; li < s_runtime_tile_layer_count; ++li) {
    const TileLayer* ly = &s_tile_layers[li];
    // Capa sin ningun tile solido (p. ej. decorativa): se salta antes de tocar la
    // cache de tileset de colision, que solo tiene 1 entrada (evita thrashing).
    if (!ly->enabled || !ly->tileset[0] || !ly->has_solid_tiles) {
      continue;
    }
    if (gx >= ly->cols || gy >= ly->rows) {
      continue;
    }
    const int ti = ly->cells[gy][gx];
    if (ti < 0 || ti == static_cast<int>(s_runtime_transp)) {
      continue;
    }
    const TurtleTileset* ts =
        coll_tileset_cache_get(s_runtime_json, s_runtime_json_end, ly->tileset);
    if (!ts) {
      continue;
    }
    if (ti >= static_cast<int>(ts->tile_count)) {
      continue;
    }
    const TurtleTileCollEntry* ce = &ts->coll[ti];
    if (turtle_tile_collision_blocks(ce, px, tsx0, tsy0, tsx1, tsy1, ax0, ay0, ax1, ay1, step_dx,
                                     step_dy, ground_probe)) {
      return true;
    }
  }
  return false;
}

static bool rects_overlap(int ax0, int ay0, int ax1, int ay1, int bx0, int by0, int bx1,
                            int by1) {
  return ax0 <= bx1 && ax1 >= bx0 && ay0 <= by1 && ay1 >= by0;
}

static bool aabb_overlaps_solid_tiles(int x0, int y0, int x1, int y1, int step_dx, int step_dy,
                                      bool ground_probe) {
  const int px = s_runtime_tile_px;
  if (px < 1) {
    return false;
  }
  int cols = 0;
  int rows = 0;
  tile_grid_dims(px, &cols, &rows);

  const int gx0 = x0 / px;
  const int gx1 = x1 / px;
  const int gy_lo = rows - 1 - (y1 / px);
  const int gy_hi = rows - 1 - (y0 / px);
  for (int gy = gy_lo; gy <= gy_hi; ++gy) {
    if (gy < 0 || gy >= rows) {
      continue;
    }
    for (int gx = gx0; gx <= gx1; ++gx) {
      if (gx < 0 || gx >= cols) {
        continue;
      }
      if (tile_cell_blocks_actor(gx, gy, x0, y0, x1, y1, step_dx, step_dy, ground_probe)) {
        return true;
      }
    }
  }
  return false;
}

static bool actor_aabb_hits_tiles(const SceneActor* a, int step_dx, int step_dy) {
  int x0 = 0;
  int y0 = 0;
  int x1 = 0;
  int y1 = 0;
  actor_world_aabb(a, &x0, &y0, &x1, &y1);
  return aabb_overlaps_solid_tiles(x0, y0, x1, y1, step_dx, step_dy, false);
}

static bool actor_touching_ground(const SceneActor* a) {
  int x0 = 0;
  int y0 = 0;
  int x1 = 0;
  int y1 = 0;
  actor_world_aabb(a, &x0, &y0, &x1, &y1);
  if (y0 <= 0) {
    return true;
  }
  // Sondeo 1px por debajo del AABB real: en reposo el borde inferior del actor
  // queda justo tocando (no solapando) la celda solida, asi que hay que desplazar
  // toda la caja hacia abajo antes del test de overlap, no solo elegir la fila.
  const int probe_y0 = y0 - 1;
  const int probe_y1 = y1 - 1;
  const int px = s_runtime_tile_px;
  if (px < 1) {
    return false;
  }
  int cols = 0;
  int rows = 0;
  tile_grid_dims(px, &cols, &rows);
  const int gx0 = x0 / px;
  const int gx1 = x1 / px;
  const int gy = rows - 1 - (probe_y0 / px);
  if (gy < 0 || gy >= rows) {
    return false;
  }
  for (int gx = gx0; gx <= gx1; ++gx) {
    if (gx < 0 || gx >= cols) {
      continue;
    }
    if (tile_cell_blocks_actor(gx, gy, x0, probe_y0, x1, probe_y1, 0, -1, true)) {
      return true;
    }
  }
  return false;
}

static void resolve_axis_steps(SceneActor* a, int* dx, int* dy) {
  if (*dx != 0) {
    const int step = (*dx > 0) ? 1 : -1;
    const int steps = (*dx > 0) ? *dx : -*dx;
    *dx = 0;
    for (int i = 0; i < steps; ++i) {
      a->x += step;
      if (actor_aabb_hits_tiles(a, step, 0)) {
        a->x -= step;
        break;
      }
      *dx += step;
    }
  }

  if (*dy != 0) {
    const int step = (*dy > 0) ? 1 : -1;
    const int steps = (*dy > 0) ? *dy : -*dy;
    *dy = 0;
    for (int i = 0; i < steps; ++i) {
      a->y += step;
      if (actor_aabb_hits_tiles(a, 0, step)) {
        a->y -= step;
        if (step < 0) {
          a->grounded = true;
        }
        break;
      }
      *dy += step;
    }
  }
}

static void paint_scene_static_layers(void) {
  turtle_gpu_set_camera(s_cam_x, s_cam_y);
  turtle_gpu_cls(static_cast<uint8_t>(s_runtime_bg));
  if (s_world_static_ready && s_world_bg) {
    paint_cached_world_background(s_runtime_transp);
    paint_bg_image_layers(s_runtime_transp);
    return;
  }
  if (s_world_bg) {
    paint_cached_world_background(s_runtime_transp);
    paint_bg_image_layers(s_runtime_transp);
  } else if (!draw_background_for_scene(s_runtime_json, s_runtime_json_end, s_runtime_sc_start,
                                          s_runtime_sc_end, s_runtime_transp)) {
    Serial.println("turtle_scene: aviso: fondo asset no aplicado; solo background_index");
  }
  draw_tile_layers_for_scene(s_runtime_json, s_runtime_json_end, s_runtime_sc_start,
                             s_runtime_sc_end, s_runtime_transp);
}

static void draw_all_actors(void) {
  if (!s_runtime_json || !s_runtime_json_end) {
    return;
  }

  update_camera_follow_player();

  if (scene_uses_scrolling()) {
    paint_scene_static_layers();

    int cam_x = 0;
    int cam_y = 0;
    turtle_gpu_get_camera(&cam_x, &cam_y);
    const int view_x1 = cam_x + kSceneW - 1;
    const int view_y1 = cam_y + kSceneH - 1;

    for (int i = 0; i < s_actor_count; ++i) {
      SceneActor* a = &s_actors[i];
      int bx0 = 0, by0 = 0, bw = 0, bh = 0;
      actor_sprite_scene_bounds(a, &bx0, &by0, &bw, &bh);
      // Fuera de la ventana de camara: no vale la pena cargar/blittear el sprite.
      if (!rects_overlap(bx0, by0, bx0 + bw - 1, by0 + bh - 1, cam_x, cam_y, view_x1, view_y1)) {
        continue;
      }
      if (!draw_actor_runtime(i)) {
        Serial.printf("turtle_scene: no sprite para \"%s\"\n", a->obj_id);
      }
    }
    turtle_gpu_request_full_flip();
    return;
  }

  // Camara fija: solo repinta la union de rects previos/actuales de los actores
  // (turtle_gpu_dirty_mark_scene_rect asume cam=(0,0), no aplica offset de camara).
  turtle_gpu_set_camera(0, 0);

  turtle_gpu_dirty_reset();
  for (int i = 0; i < s_actor_count; ++i) {
    SceneActor* a = &s_actors[i];
    if (a->has_prev_blit) {
      turtle_gpu_dirty_mark_scene_rect(a->prev_blit_x, a->prev_blit_y, a->prev_blit_w,
                                       a->prev_blit_h);
    }
    int cx0 = 0, cy0 = 0, cw = 0, ch = 0;
    actor_sprite_scene_bounds(a, &cx0, &cy0, &cw, &ch);
    turtle_gpu_dirty_mark_scene_rect(cx0, cy0, cw, ch);

    // Overlay de texto: rect independiente del sprite (union con su propio prev_blit_*,
    // ver draw_actor_runtime). Mismo motivo que arriba: borra donde estaba, pinta donde va.
    if (a->text_has_prev_blit) {
      turtle_gpu_dirty_mark_scene_rect(a->text_prev_blit_x, a->text_prev_blit_y,
                                       a->text_prev_blit_w, a->text_prev_blit_h);
    }
    int tx0 = 0, ty0 = 0, tw = 0, th = 0;
    if (actor_text_scene_bounds(a, &tx0, &ty0, &tw, &th)) {
      turtle_gpu_dirty_mark_scene_rect(tx0, ty0, tw, th);
    }
  }
  turtle_gpu_dirty_slack_for_scale();
  turtle_gpu_restore_static_dirty();

  for (int i = 0; i < s_actor_count; ++i) {
    if (!draw_actor_runtime(i)) {
      Serial.printf("turtle_scene: no sprite para \"%s\"\n", s_actors[i].obj_id);
    }
  }
}

static void clamp_actor_pos(SceneActor* a) {
  const int min_x = -a->col_x0;
  const int max_x = (s_world_w - 1) - a->col_x1;
  const int min_y = -a->col_y0;
  const int max_y = (s_world_h - 1) - a->col_y1;
  if (a->x < min_x) {
    a->x = min_x;
  } else if (a->x > max_x) {
    a->x = max_x;
  }
  if (a->y < min_y) {
    a->y = min_y;
    a->grounded = true;
  } else if (a->y > max_y) {
    a->y = max_y;
  }
}

static void tick_actors(uint32_t delta_ms) {
  for (int i = 0; i < s_actor_count; ++i) {
    SceneActor* a = &s_actors[i];
    if (a->frame_count <= 1) {
      continue;
    }
    const uint32_t speed = a->anim_speed_x16;
    const uint32_t denom =
        static_cast<uint32_t>(s_default_anim_fps) * speed;
    if (denom == 0) {
      continue;
    }
    uint32_t ms_per_frame = (1000u * 16u) / denom;
    if (ms_per_frame < 1) {
      ms_per_frame = 1;
    }
    a->frame_accum_ms += delta_ms;
    while (a->frame_accum_ms >= ms_per_frame) {
      a->frame_accum_ms -= ms_per_frame;
      if (a->frame_count <= 1) {
        break;
      }
      if (a->frame_index + 1 >= a->frame_count) {
        if (a->anim_repeat) {
          a->frame_index = 0;
        } else {
          a->frame_index = static_cast<uint8_t>(a->frame_count - 1);
          break;
        }
      } else {
        a->frame_index = static_cast<uint8_t>(a->frame_index + 1);
      }
    }
  }
}

}  // namespace

bool turtle_scene_draw_cart_bundle(const char* json, size_t json_len, const char* scene_id) {
  if (!json || json_len == 0 || !scene_id || !scene_id[0]) {
    return false;
  }
  const char* json_end = json + json_len;
  const char *sc_start = nullptr, *sc_end = nullptr;
  if (!find_scene_block(json, json_end, scene_id, &sc_start, &sc_end)) {
    Serial.printf("turtle_scene: escena \"%s\" no encontrada en bundle\n", scene_id);
    return false;
  }
  parse_scene_world(sc_start, sc_end);
  parse_scene_camera(sc_start, sc_end);
  parse_scene_parallax_bands(sc_start, sc_end);
  parse_scene_bg_image_layers(sc_start, sc_end);

  int bg = 0;
  if (!json_extract_int_for_key(sc_start, sc_end, "background_index", &bg)) {
    bg = 0;
  }
  if (bg < 0) {
    bg = 0;
  }
  if (bg > 31) {
    bg = 31;
  }

  int transp = kDefaultTransparentIndex;
  if (!json_extract_int_for_key(json, json_end, "transparent_index", &transp)) {
    transp = kDefaultTransparentIndex;
  }
  if (transp < 0) {
    transp = 0;
  }
  if (transp > 31) {
    transp = 31;
  }

  int npl = 0;
  if (!parse_placements(sc_start, sc_end, s_placements, &npl)) {
    Serial.println("turtle_scene: sin lista objects valida; solo fondo");
  }

  turtle_gpu_set_camera(0, 0);
  turtle_gpu_cls(static_cast<uint8_t>(bg));

  if (!draw_background_for_scene(json, json_end, sc_start, sc_end,
                                 static_cast<uint8_t>(transp))) {
    Serial.println("turtle_scene: aviso: fondo asset no aplicado; solo background_index");
  }

  draw_tile_layers_for_scene(json, json_end, sc_start, sc_end, static_cast<uint8_t>(transp));

  for (int i = 0; i < npl; ++i) {
    if (!draw_sprite_for_object(json, json_end, s_placements[i].obj_id, s_placements[i].x,
                                s_placements[i].y, static_cast<uint8_t>(transp), 0)) {
      Serial.printf("turtle_scene: no sprite para objeto \"%s\"\n", s_placements[i].obj_id);
    }
    if ((i & 3) == 3) {
      yield();
    }
  }

  Serial.printf("turtle_scene: escena \"%s\" (%d objetos), fondo idx %d (flip = host)\n", scene_id,
                 npl, bg);
  return true;
}

bool turtle_scene_begin_runtime(const char* json, size_t json_len, const char* scene_id) {
  s_runtime_active = false;
  s_actor_count = 0;
  s_player_actor = -1;
  s_seen_asset_paths_count = 0;
  sprite_cache_clear_all();
  s_runtime_json = nullptr;
  s_runtime_json_end = nullptr;

  if (!json || json_len == 0 || !scene_id || !scene_id[0]) {
    return false;
  }
  const char* json_end = json + json_len;

  const char* sc_start = nullptr;
  const char* sc_end = nullptr;
  if (!find_scene_block(json, json_end, scene_id, &sc_start, &sc_end)) {
    Serial.printf("turtle_scene: escena \"%s\" no encontrada en bundle\n", scene_id);
    return false;
  }
  parse_scene_timing(json, json_end, sc_start, sc_end);
  parse_scene_world(sc_start, sc_end);
  parse_scene_camera(sc_start, sc_end);
  parse_scene_parallax_bands(sc_start, sc_end);
  parse_scene_bg_image_layers(sc_start, sc_end);

  int bg = 0;
  if (!json_extract_int_for_key(sc_start, sc_end, "background_index", &bg)) {
    bg = 0;
  }
  if (bg < 0) {
    bg = 0;
  }
  if (bg > 31) {
    bg = 31;
  }
  s_runtime_bg = bg;

  int transp = kDefaultTransparentIndex;
  if (!json_extract_int_for_key(json, json_end, "transparent_index", &transp)) {
    transp = kDefaultTransparentIndex;
  }
  if (transp < 0) {
    transp = 0;
  }
  if (transp > 31) {
    transp = 31;
  }
  s_runtime_transp = static_cast<uint8_t>(transp);

  int npl = 0;
  if (!parse_placements(sc_start, sc_end, s_placements, &npl)) {
    Serial.println("turtle_scene: sin lista objects valida; solo fondo");
  }

  s_runtime_json = json;
  s_runtime_json_end = json_end;
  s_runtime_sc_start = sc_start;
  s_runtime_sc_end = sc_end;
  turtle_gpu_set_camera(0, 0);
  turtle_gpu_cls(static_cast<uint8_t>(bg));
  {
    int tile_px = 16;
    if (!json_extract_int_for_key(json, json_end, "tile_px", &tile_px) || tile_px < 4 ||
        tile_px > 64) {
      tile_px = 16;
    }
    s_runtime_tile_px = tile_px;
  }
  if (scene_uses_scrolling()) {
    if (!prepare_world_static_composite(json, json_end, sc_start, sc_end)) {
      Serial.println("turtle_scene: aviso: buffer mundo estatico fallo; reintento por frame");
      if (!draw_background_for_scene(json, json_end, sc_start, sc_end, s_runtime_transp)) {
        Serial.println("turtle_scene: aviso: fondo asset no aplicado; solo background_index");
      }
      draw_tile_layers_for_scene(json, json_end, sc_start, sc_end, s_runtime_transp);
    } else {
      paint_cached_world_background(s_runtime_transp);
      paint_bg_image_layers(s_runtime_transp);
    }
  } else {
    if (!draw_background_for_scene(json, json_end, sc_start, sc_end, s_runtime_transp)) {
      Serial.println("turtle_scene: aviso: fondo asset no aplicado; solo background_index");
    }
    draw_tile_layers_for_scene(json, json_end, sc_start, sc_end, s_runtime_transp);
    turtle_gpu_snapshot_static();
  }
  s_actor_count = 0;
  for (int i = 0; i < kMaxPlacements; ++i) {
    s_actor_draw_cache[i].sprite_id[0] = '\0';
    s_actor_draw_cache[i].frame_index = 0;
    s_actor_draw_cache[i].pixels_valid = false;
  }
  for (int i = 0; i < npl && s_actor_count < kMaxPlacements; ++i) {
    if (init_actor_from_placement(json, json_end, &s_placements[i], &s_actors[s_actor_count])) {
      ++s_actor_count;
    }
  }
  resolve_player_actor_index();

  for (int i = 0; i < s_actor_count; ++i) {
    prewarm_actor_sprites(json, json_end, i);
  }

  if (s_runtime_tile_layer_count <= 0) {
    s_runtime_tile_layer_count =
        parse_tile_layers(sc_start, sc_end, s_runtime_tile_px, s_tile_layers, kMaxTileLayers);
  }
  coll_tileset_cache_prewarm(json, json_end);

  draw_all_actors();
  s_runtime_active = true;

  turtle_actor_lua_init();
  turtle_actor_lua_bind_actors_from_scene();

  Serial.printf(
      "turtle_scene: runtime escena \"%s\" mundo %dx%d camara %s (%d actores), target_fps=%d "
      "anim_fps=%d\n",
      scene_id, s_world_w, s_world_h, scene_uses_scrolling() ? "scroll" : "fija",
      s_actor_count, s_target_fps, s_default_anim_fps);
  if (s_player_actor >= 0) {
    Serial.printf("turtle_scene: actor jugador (indice %d) = %s\n", s_player_actor,
                  s_actors[s_player_actor].obj_id);
  }
  return true;
}

void turtle_scene_runtime_tick(uint32_t delta_ms) {
  if (!s_runtime_active || delta_ms == 0) {
    return;
  }
  turtle_actor_lua_tick_all(delta_ms);
  tick_actors(delta_ms);
  draw_all_actors();
}

bool turtle_scene_runtime_active(void) {
  return s_runtime_active;
}

int turtle_scene_target_fps(void) {
  return s_target_fps;
}

int turtle_scene_actor_count(void) {
  return s_actor_count;
}

bool turtle_scene_actor_script_stem(int index, char* out, size_t out_cap) {
  if (!out || out_cap == 0 || index < 0 || index >= s_actor_count) {
    return false;
  }
  if (!s_actors[index].script_stem[0]) {
    return false;
  }
  snprintf(out, out_cap, "%s", s_actors[index].script_stem);
  return true;
}

void turtle_scene_actor_set_lua_target(int index) {
  s_lua_actor_target = index;
}

bool turtle_scene_actor_pos(int* x, int* y) {
  if (!x || !y || s_lua_actor_target < 0 || s_lua_actor_target >= s_actor_count) {
    return false;
  }
  const SceneActor* a = &s_actors[s_lua_actor_target];
  *x = a->x;
  *y = a->y;
  return true;
}

void turtle_scene_actor_move(int dx, int dy, int* out_dx, int* out_dy) {
  if (out_dx) {
    *out_dx = 0;
  }
  if (out_dy) {
    *out_dy = 0;
  }
  if (s_lua_actor_target < 0 || s_lua_actor_target >= s_actor_count) {
    return;
  }
  SceneActor* a = &s_actors[s_lua_actor_target];
  a->grounded = false;

  if (dx != 0 || dy != 0) {
    resolve_axis_steps(a, &dx, &dy);
    clamp_actor_pos(a);
    if (out_dx) {
      *out_dx = dx;
    }
    if (out_dy) {
      *out_dy = dy;
    }
  }

  if (!a->grounded) {
    a->grounded = actor_touching_ground(a);
  }
}

bool turtle_scene_actor_on_ground(void) {
  if (s_lua_actor_target < 0 || s_lua_actor_target >= s_actor_count) {
    return false;
  }
  return s_actors[s_lua_actor_target].grounded;
}

bool turtle_scene_actor_set_anim(const char* name) {
  if (!name || !name[0] || s_lua_actor_target < 0 || s_lua_actor_target >= s_actor_count) {
    return false;
  }

  SceneActor* a = &s_actors[s_lua_actor_target];
  if (strcmp(a->anim_name, name) == 0) {
    return true;
  }

  const char* sprite_id = lookup_anim_sprite(s_lua_actor_target, name);
  if (!sprite_id) {
    static char s_last_anim_miss_obj[48];
    static char s_last_anim_miss_name[33];
    if (strcmp(s_last_anim_miss_obj, a->obj_id) != 0 || strcmp(s_last_anim_miss_name, name) != 0) {
      snprintf(s_last_anim_miss_obj, sizeof s_last_anim_miss_obj, "%s", a->obj_id);
      snprintf(s_last_anim_miss_name, sizeof s_last_anim_miss_name, "%s", name);
      Serial.printf("turtle_scene: anim \"%s\" no en objeto \"%s\"\n", name, a->obj_id);
    }
    return false;
  }

  a->anim_repeat = true;
  a->anim_speed_x16 = anim_speed_from_float(1.0f);
  const bool restart = strcmp(a->sprite_id, sprite_id) != 0;
  if (!actor_apply_sprite(s_lua_actor_target, sprite_id, restart)) {
    return false;
  }
  snprintf(a->anim_name, sizeof a->anim_name, "%s", name);
  return true;
}

bool turtle_scene_actor_play_anim(const char* name, float speed, bool repeat) {
  if (!name || !name[0] || s_lua_actor_target < 0 || s_lua_actor_target >= s_actor_count) {
    return false;
  }

  const char* sprite_id = lookup_anim_sprite(s_lua_actor_target, name);
  if (!sprite_id) {
    SceneActor* miss_a = &s_actors[s_lua_actor_target];
    static char s_last_play_miss_obj[48];
    static char s_last_play_miss_name[33];
    if (strcmp(s_last_play_miss_obj, miss_a->obj_id) != 0 ||
        strcmp(s_last_play_miss_name, name) != 0) {
      snprintf(s_last_play_miss_obj, sizeof s_last_play_miss_obj, "%s", miss_a->obj_id);
      snprintf(s_last_play_miss_name, sizeof s_last_play_miss_name, "%s", name);
      Serial.printf("turtle_scene: anim \"%s\" no en objeto \"%s\"\n", name, miss_a->obj_id);
    }
    return false;
  }

  SceneActor* a = &s_actors[s_lua_actor_target];
  a->anim_repeat = repeat;
  a->anim_speed_x16 = anim_speed_from_float(speed);

  if (!actor_apply_sprite(s_lua_actor_target, sprite_id, true)) {
    return false;
  }
  snprintf(a->anim_name, sizeof a->anim_name, "%s", name);
  return true;
}

void turtle_scene_actor_set_flip_h(bool flip_h) {
  if (s_lua_actor_target < 0 || s_lua_actor_target >= s_actor_count) {
    return;
  }
  s_actors[s_lua_actor_target].flip_h = flip_h;
}

void turtle_scene_actor_set_text(const char* str, int dx, int dy, const char* font_id,
                                 int color_index) {
  if (s_lua_actor_target < 0 || s_lua_actor_target >= s_actor_count) {
    return;
  }
  SceneActor* a = &s_actors[s_lua_actor_target];
  // text(nil)/text("") borra el overlay; persiste si no se vuelve a llamar (igual que
  // set_anim con la animacion activa) — el script NO necesita llamar text() cada frame
  // solo para mantener visible un valor de HUD que no cambio.
  if (!str || !str[0] || !font_id || !font_id[0]) {
    a->has_text = false;
    a->text_buf[0] = '\0';
    return;
  }
  snprintf(a->text_buf, sizeof a->text_buf, "%s", str);
  snprintf(a->text_font_id, sizeof a->text_font_id, "%s", font_id);
  a->text_dx = dx;
  a->text_dy = dy;
  a->text_color = color_index;
  a->has_text = true;
}

int turtle_scene_measure_text_active(const char* font_id, const char* str) {
  if (!s_runtime_json || !s_runtime_json_end || !font_id || !str) {
    return 0;
  }
  const TurtleFont* font = font_cache_get(s_runtime_json, s_runtime_json_end, font_id);
  if (!font) {
    return 0;
  }
  return turtle_font_measure(font, str);
}

int turtle_scene_draw_text(const char* bundle_json, size_t bundle_json_len, const char* font_id,
                           int sx, int sy, const char* str, int color_index) {
  if (!bundle_json || bundle_json_len == 0 || !font_id || !str) {
    return 0;
  }
  const TurtleFont* font =
      font_cache_get(bundle_json, bundle_json + bundle_json_len, font_id);
  if (!font) {
    return 0;
  }
  if (color_index >= 0) {
    return turtle_font_draw_scene_tint(font, sx, sy, str,
                                       static_cast<uint8_t>(kDefaultTransparentIndex),
                                       static_cast<uint8_t>(color_index));
  }
  return turtle_font_draw_scene(font, sx, sy, str, static_cast<uint8_t>(kDefaultTransparentIndex));
}

int turtle_scene_measure_text(const char* bundle_json, size_t bundle_json_len,
                              const char* font_id, const char* str) {
  if (!bundle_json || bundle_json_len == 0 || !font_id || !str) {
    return 0;
  }
  const TurtleFont* font =
      font_cache_get(bundle_json, bundle_json + bundle_json_len, font_id);
  if (!font) {
    return 0;
  }
  return turtle_font_measure(font, str);
}
