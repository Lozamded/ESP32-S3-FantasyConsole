#include "turtle_scene.h"

#include "turtle_asset_bin.h"
#include "turtle_cart.h"
#include "turtle_gpu.h"
#include "turtle_tileset.h"

#include <Arduino.h>
#include <ctype.h>
#include <stdlib.h>
#include <string.h>

namespace {

constexpr int kMaxPlacements = 96;
/** Mismo default que TurtleStudio (sprites.DEFAULT_CELL_PX). */
constexpr int kDefaultCellPx = 4;
constexpr int kDefaultTransparentIndex = 31;
constexpr int kMaxSpriteW = 128;
constexpr int kMaxSpriteH = 128;
/** Escena canonica (spec/scene-v0.md); fondos indexed_pixels a pantalla completa. */
constexpr int kSceneW = 264;
constexpr int kSceneH = 198;
constexpr int kMaxTileLayers = 4;
constexpr int kMaxTileCols = 17;
constexpr int kMaxTileRows = 13;

struct TileLayer {
  bool enabled;
  char tileset[48];
  int cols;
  int rows;
  uint8_t cells[kMaxTileRows][kMaxTileCols];
};

struct Placement {
  char obj_id[32];
  int x;
  int y;
};

struct SceneActor {
  char obj_id[32];
  char sprite_id[48];
  int x;
  int y;
  int pw;
  int ph;
  int origin_x;
  int origin_y;
  uint8_t frame_index;
  uint8_t frame_count;
  uint16_t anim_speed_x16;
  uint32_t frame_accum_ms;
};

static uint8_t s_sprite_pixels[kMaxSpriteW * kMaxSpriteH];
static uint8_t s_scene_pixels[kSceneW * kSceneH];
/** Fuera del stack de loopTask (ESP32 ~8 KB); parse_placements + tile_layers juntos overflow. */
static Placement s_placements[kMaxPlacements];
static TileLayer s_tile_layers[kMaxTileLayers];
static TurtleTileset s_tileset_draw;
static SceneActor s_actors[kMaxPlacements];
static int s_actor_count = 0;
static const char* s_runtime_json = nullptr;
static const char* s_runtime_json_end = nullptr;
static uint8_t s_runtime_transp = 31;
static bool s_runtime_active = false;
static int s_target_fps = 30;
static int s_default_anim_fps = 8;

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

static bool buffer_is_turtle_tileset_bin(const char* data, size_t len) {
  return len >= 10 && data && data[0] == 'T' && data[1] == 'T' && data[2] == 'S' && data[3] == 0;
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
    if (buffer_is_turtle_asset_bin(buf.data, buf.len)) {
      int bw = 0;
      int bh = 0;
      read_asset_bin_dims(buf.data, buf.len, &bw, &bh);
      const uint8_t mode = (buf.len >= 11) ? static_cast<uint8_t>(buf.data[10]) : 0;
      Serial.printf("turtle_scene: bin SD %s %dx%d mode %u (%u bytes)\n", path, bw, bh,
                    static_cast<unsigned>(mode), static_cast<unsigned>(buf.len));
    } else {
      Serial.printf("turtle_scene: json SD %s (%u bytes)\n", path, static_cast<unsigned>(buf.len));
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

static void extract_sprite_origin(const char* inner, const char* inner_end, int pw, int ph, int* ox,
                                  int* oy) {
  int tx = 0;
  int ty = 0;
  if (!json_extract_int_for_key(inner, inner_end, "origin_x", &tx)) {
    tx = 0;
  }
  if (!json_extract_int_for_key(inner, inner_end, "origin_y", &ty)) {
    ty = 0;
  }
  if (pw < 1) {
    pw = 1;
  }
  if (ph < 1) {
    ph = 1;
  }
  if (tx < 0) {
    tx = 0;
  }
  if (ty < 0) {
    ty = 0;
  }
  if (tx >= pw) {
    tx = pw - 1;
  }
  if (ty >= ph) {
    ty = ph - 1;
  }
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

static bool draw_indexed_asset_at_origin(const char* inner, const char* inner_end, const char* label,
                                         int pw, int ph, uint8_t transparent_index) {
  if (pw <= 0 || ph <= 0) {
    return false;
  }
  if (pw > kSceneW || ph > kSceneH) {
    Serial.printf("turtle_scene: %s %dx%d > escena %dx%d\n", label, pw, ph, kSceneW, kSceneH);
    return false;
  }
  const size_t need = static_cast<size_t>(pw) * static_cast<size_t>(ph);
  if (need > sizeof(s_scene_pixels)) {
    return false;
  }
  memset(s_scene_pixels, 0, need);
  const size_t blob_len = (inner_end > inner) ? static_cast<size_t>(inner_end - inner) : 0;
  if (!fill_pixels_from_asset_buffer(inner, blob_len, pw, ph, s_scene_pixels, pw, 0)) {
    Serial.printf("turtle_scene: pixels invalidos en %s\n", label);
    return false;
  }
  turtle_gpu_blit_indexed_scene(0, 0, pw, ph, s_scene_pixels, pw, transparent_index);
  return true;
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
  if (pw > kSceneW) {
    pw = kSceneW;
  }
  if (ph > kSceneH) {
    ph = kSceneH;
  }
  turtle_gpu_fill_rect_scene(0, 0, pw, ph, static_cast<uint8_t>(pci));
  return true;
}

static bool draw_background_for_scene(const char* json, const char* json_end,
                                      const char* scene_start, const char* scene_end,
                                      uint8_t transparent_index) {
  char bg_id[48];
  if (!json_extract_string_for_key(scene_start, scene_end, "background", bg_id, sizeof bg_id)) {
    return true;
  }
  if (!bg_id[0]) {
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

  const size_t sp_blob_len =
      (asset_inner_end > asset_inner) ? static_cast<size_t>(asset_inner_end - asset_inner) : 0;

  int pw = 0;
  int ph = 0;
  if (!read_asset_bin_dims(asset_inner, sp_blob_len, &pw, &ph) &&
      !resolve_pixel_dims_sprite(asset_inner, asset_inner_end, &pw, &ph)) {
    return false;
  }
  if (pw > kMaxSpriteW || ph > kMaxSpriteH) {
    Serial.printf("turtle_scene: sprite \"%s\" %dx%d > max %dx%d\n", sprite_id, pw, ph, kMaxSpriteW,
                   kMaxSpriteH);
    return false;
  }

  int origin_x = 0;
  int origin_y = 0;
  extract_sprite_origin(asset_inner, asset_inner_end, pw, ph, &origin_x, &origin_y);
  const int blit_x = scene_x - origin_x;
  const int blit_y = scene_y - origin_y;

  if (render_mode_is_indexed_pixels(asset_inner, asset_inner_end) ||
      buffer_is_turtle_asset_bin(asset_inner, static_cast<size_t>(asset_inner_end - asset_inner))) {
    memset(s_sprite_pixels, 0, sizeof(s_sprite_pixels));
    const size_t blob_len =
        (asset_inner_end > asset_inner) ? static_cast<size_t>(asset_inner_end - asset_inner) : 0;
    if (!fill_pixels_from_asset_buffer(asset_inner, blob_len, pw, ph, s_sprite_pixels, pw,
                                       frame_index)) {
      Serial.printf("turtle_scene: pixels invalidos en \"%s\" f%d\n", sprite_id, frame_index);
      return false;
    }
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
  turtle_gpu_fill_rect_scene(blit_x, blit_y, pw, ph, static_cast<uint8_t>(pci));
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

static void tile_grid_dims(int tile_px, int* cols, int* rows) {
  int px = tile_px;
  if (px < 1) {
    px = 16;
  }
  int c = kSceneW / px;
  int r = kSceneH / px;
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
    return turtle_tileset_load_tts(reinterpret_cast<const uint8_t*>(asset_inner), blob_len, ts);
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
  return turtle_tileset_load_tts(reinterpret_cast<const uint8_t*>(sd->buf.data), sd->buf.len, ts);
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

static void parse_bundle_timing(const char* json, const char* json_end) {
  int tf = 30;
  int af = 8;
  if (!json_extract_int_for_key(json, json_end, "target_fps", &tf) || tf < 15 || tf > 60) {
    tf = 30;
  }
  if (!json_extract_int_for_key(json, json_end, "default_anim_fps", &af) || af < 1 || af > 30) {
    af = 8;
  }
  s_target_fps = tf;
  s_default_anim_fps = af;
}

static bool init_actor_from_placement(const char* json, const char* json_end,
                                      const Placement* pl, SceneActor* actor) {
  const char* od = find_root_objects_dict_brace(json, json_end);
  if (!od || *od != '{') {
    return false;
  }
  const char* od_end = json_object_end(od);
  if (!od_end) {
    return false;
  }

  char pat[40];
  snprintf(pat, sizeof pat, "\"%s\":", pl->obj_id);
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

  snprintf(actor->obj_id, sizeof actor->obj_id, "%s", pl->obj_id);
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

  AssetSdLoad sd;
  const char* asset_inner = nullptr;
  const char* asset_inner_end = nullptr;
  if (!resolve_sprite_inner(json, json_end, actor->sprite_id, &sd, &asset_inner, &asset_inner_end)) {
    return false;
  }

  const size_t blob_len =
      (asset_inner_end > asset_inner) ? static_cast<size_t>(asset_inner_end - asset_inner) : 0;
  actor->pw = 0;
  actor->ph = 0;
  if (!read_asset_bin_dims(asset_inner, blob_len, &actor->pw, &actor->ph) &&
      !resolve_pixel_dims_sprite(asset_inner, asset_inner_end, &actor->pw, &actor->ph)) {
    return false;
  }
  extract_sprite_origin(asset_inner, asset_inner_end, actor->pw, actor->ph, &actor->origin_x,
                        &actor->origin_y);
  actor->frame_count =
      static_cast<uint8_t>(sprite_frame_count_from_asset(asset_inner, asset_inner_end, blob_len));
  if (actor->frame_count < 1) {
    actor->frame_count = 1;
  }
  return true;
}

static void draw_all_actors(void) {
  if (!s_runtime_json || !s_runtime_json_end) {
    return;
  }
  turtle_gpu_restore_static();
  for (int i = 0; i < s_actor_count; ++i) {
    const SceneActor* a = &s_actors[i];
    if (!draw_sprite_for_object(s_runtime_json, s_runtime_json_end, a->obj_id, a->x, a->y,
                                s_runtime_transp, a->frame_index)) {
      Serial.printf("turtle_scene: no sprite para \"%s\"\n", a->obj_id);
    }
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
      a->frame_index = static_cast<uint8_t>((a->frame_index + 1) % a->frame_count);
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
  s_runtime_json = nullptr;
  s_runtime_json_end = nullptr;

  if (!json || json_len == 0 || !scene_id || !scene_id[0]) {
    return false;
  }
  const char* json_end = json + json_len;
  parse_bundle_timing(json, json_end);

  const char* sc_start = nullptr;
  const char* sc_end = nullptr;
  if (!find_scene_block(json, json_end, scene_id, &sc_start, &sc_end)) {
    Serial.printf("turtle_scene: escena \"%s\" no encontrada en bundle\n", scene_id);
    return false;
  }

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
  s_runtime_transp = static_cast<uint8_t>(transp);

  int npl = 0;
  if (!parse_placements(sc_start, sc_end, s_placements, &npl)) {
    Serial.println("turtle_scene: sin lista objects valida; solo fondo");
  }

  turtle_gpu_cls(static_cast<uint8_t>(bg));
  if (!draw_background_for_scene(json, json_end, sc_start, sc_end, s_runtime_transp)) {
    Serial.println("turtle_scene: aviso: fondo asset no aplicado; solo background_index");
  }
  draw_tile_layers_for_scene(json, json_end, sc_start, sc_end, s_runtime_transp);
  turtle_gpu_snapshot_static();

  s_runtime_json = json;
  s_runtime_json_end = json_end;
  s_actor_count = 0;
  for (int i = 0; i < npl && s_actor_count < kMaxPlacements; ++i) {
    if (init_actor_from_placement(json, json_end, &s_placements[i], &s_actors[s_actor_count])) {
      ++s_actor_count;
    }
  }

  draw_all_actors();
  s_runtime_active = true;

  Serial.printf(
      "turtle_scene: runtime escena \"%s\" (%d actores), target_fps=%d anim_fps=%d (capa "
      "estatica OK)\n",
      scene_id, s_actor_count, s_target_fps, s_default_anim_fps);
  return true;
}

void turtle_scene_runtime_tick(uint32_t delta_ms) {
  if (!s_runtime_active || delta_ms == 0) {
    return;
  }
  tick_actors(delta_ms);
  draw_all_actors();
}

bool turtle_scene_runtime_active(void) {
  return s_runtime_active;
}

int turtle_scene_target_fps(void) {
  return s_target_fps;
}
