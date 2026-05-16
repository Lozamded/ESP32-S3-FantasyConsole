#include "turtle_scene.h"

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

static uint8_t s_sprite_pixels[kMaxSpriteW * kMaxSpriteH];

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

static bool find_sprite_inner(const char* json, const char* json_end, const char* sprite_id,
                              const char** inner, const char** inner_end) {
  const char* p = strstr_bounded(json, json_end, "\"sprites\"");
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
  snprintf(pat, sizeof pat, "\"%s\":", sprite_id);
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

static bool parse_palette_rows_image(const char* inner, const char* inner_end, int expect_w,
                                     int expect_h, uint8_t* out, int out_stride) {
  const char* im = strstr_bounded(inner, inner_end, "\"image\"");
  if (!im) {
    return false;
  }
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
    ++p;
    int x = 0;
    while (p < inner_end && *p != ']') {
      while (p < inner_end && (isspace(static_cast<unsigned char>(*p)) || *p == ',')) {
        ++p;
      }
      if (p >= inner_end || *p == ']') {
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
        out[y * out_stride + x] = static_cast<uint8_t>(ci);
      }
      ++x;
    }
    if (p < inner_end && *p == ']') {
      ++p;
    }
    ++y;
  }
  return y > 0;
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
  char sprite_id[48];
  if (!json_extract_string_for_key(oinner, oinner_end, "sprite_id", sprite_id, sizeof sprite_id)) {
    return false;
  }

  const char* inner = nullptr;
  const char* inner_end = nullptr;
  if (!find_sprite_inner(json, json_end, sprite_id, &inner, &inner_end)) {
    return false;
  }

  int pw = 0;
  int ph = 0;
  if (!resolve_pixel_dims_sprite(inner, inner_end, &pw, &ph)) {
    return false;
  }
  if (pw > kMaxSpriteW || ph > kMaxSpriteH) {
    Serial.printf("turtle_scene: sprite \"%s\" %dx%d > max %dx%d\n", sprite_id, pw, ph, kMaxSpriteW,
                   kMaxSpriteH);
    return false;
  }

  if (render_mode_is_indexed_pixels(inner, inner_end)) {
    memset(s_sprite_pixels, 0, sizeof(s_sprite_pixels));
    if (!parse_palette_rows_image(inner, inner_end, pw, ph, s_sprite_pixels, pw)) {
      Serial.printf("turtle_scene: filas indexed_pixels invalidas en \"%s\"\n", sprite_id);
      return false;
    }
    turtle_gpu_blit_indexed_scene(scene_x, scene_y, pw, ph, s_sprite_pixels, pw,
                                  transparent_index);
    return true;
  }

  int pci = 0;
  if (!extract_palette_index_sprite(inner, inner_end, &pci)) {
    Serial.printf("turtle_scene: sprite solido \"%s\" sin palette_index\n", sprite_id);
    return false;
  }
  if (pci < 0) {
    pci = 0;
  }
  if (pci > 31) {
    pci = 31;
  }
  turtle_gpu_fill_rect_scene(scene_x, scene_y, pw, ph, static_cast<uint8_t>(pci));
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
