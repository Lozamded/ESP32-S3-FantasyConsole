#include "turtle_scene.h"

#include "turtle_asset_bin.h"
#include "turtle_cart.h"
#include "turtle_gpu.h"

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

static uint8_t s_sprite_pixels[kMaxSpriteW * kMaxSpriteH];
static uint8_t s_scene_pixels[kSceneW * kSceneH];

struct Placement {
  char obj_id[32];
  int x;
  int y;
};

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

static bool fill_pixels_from_asset_buffer(const char* inner, size_t len, int pw, int ph,
                                          uint8_t* out, int stride) {
  if (buffer_is_turtle_asset_bin(inner, len)) {
    return turtle_asset_bin_decode_indexed(reinterpret_cast<const uint8_t*>(inner), len, pw, ph,
                                           out, stride);
  }
  if (!inner || !len) {
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
  if (!fill_pixels_from_asset_buffer(inner, blob_len, pw, ph, s_scene_pixels, pw)) {
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
                                   int scene_x, int scene_y, uint8_t transparent_index) {
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
    if (!fill_pixels_from_asset_buffer(asset_inner, blob_len, pw, ph, s_sprite_pixels, pw)) {
      Serial.printf("turtle_scene: pixels invalidos en \"%s\"\n", sprite_id);
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

  Placement placements[kMaxPlacements];
  int npl = 0;
  if (!parse_placements(sc_start, sc_end, placements, &npl)) {
    Serial.println("turtle_scene: sin lista objects valida; solo fondo");
  }

  turtle_gpu_cls(static_cast<uint8_t>(bg));

  if (!draw_background_for_scene(json, json_end, sc_start, sc_end,
                                 static_cast<uint8_t>(transp))) {
    Serial.println("turtle_scene: aviso: fondo asset no aplicado; solo background_index");
  }

  for (int i = 0; i < npl; ++i) {
    if (!draw_sprite_for_object(json, json_end, placements[i].obj_id, placements[i].x,
                                placements[i].y, static_cast<uint8_t>(transp))) {
      Serial.printf("turtle_scene: no sprite para objeto \"%s\"\n", placements[i].obj_id);
    }
  }

  Serial.printf("turtle_scene: escena \"%s\" (%d objetos), fondo idx %d (flip = host)\n", scene_id,
                 npl, bg);
  return true;
}
