#include "turtle_gui_layer.h"

#include "turtle_font.h"
#include "turtle_gpu.h"
#include "turtle_json.h"
#include "turtle_scene.h"

#include <Arduino.h>
#include <ctype.h>
#include <string.h>

#if defined(ESP32) || defined(ESP_PLATFORM)
#include <esp_attr.h>
#define TURTLE_GUI_BSS_PSRAM EXT_RAM_ATTR
#else
#define TURTLE_GUI_BSS_PSRAM
#endif

namespace {

constexpr int kMaxGuiLayers = 8;
constexpr int kMaxGuiLayerRects = 16;
constexpr int kMaxGuiLayerLabels = 16;
constexpr size_t kGuiLayerTextCap = 64;   // 63 chars + nul
constexpr size_t kGuiLayerFontIdCap = 48;
constexpr size_t kGuiLayerIdCap = 40;
constexpr size_t kGuiLayerLabelIdCap = 40;

// Framebuffer canonico (spec/scene-v0.md). Duplicado aca; parametrizarlo tampoco tendria
// sentido -- si cambia, todo el pipeline visual cambia.
constexpr int kSceneW = 164;
constexpr int kSceneH = 124;
constexpr uint8_t kDefaultTransparentIndex = 31;

struct GuiRect {
  int16_t x;
  int16_t y;
  int16_t w;
  int16_t h;
  uint8_t color_index;
};

struct GuiLabel {
  char id[kGuiLayerLabelIdCap];
  int16_t x;
  int16_t y;
  char font_id[kGuiLayerFontIdCap];
  char text[kGuiLayerTextCap];
  int8_t color_index;  // -1 = sin tinte, 0..30 = tinte plano
};

struct GuiLayer {
  char id[kGuiLayerIdCap];
  int16_t x;
  int16_t y;
  int16_t w;
  int16_t h;
  uint8_t bg_color_index;
  bool transparent_bg;
  bool pauses_scene;
  bool captures_input;
  int16_t z_manifest;
  int16_t z_override;
  bool z_override_set;
  bool visible;
  int rect_count;
  int label_count;
  GuiRect rects[kMaxGuiLayerRects];
  GuiLabel labels[kMaxGuiLayerLabels];
};

TURTLE_GUI_BSS_PSRAM GuiLayer s_layers[kMaxGuiLayers];
int s_layer_count = 0;
const char* s_bundle_json = nullptr;
size_t s_bundle_json_len = 0;

int find_layer_index(const char* id) {
  if (!id || !*id) {
    return -1;
  }
  for (int i = 0; i < s_layer_count; ++i) {
    if (strcmp(s_layers[i].id, id) == 0) {
      return i;
    }
  }
  return -1;
}

int find_label_index(const GuiLayer* ly, const char* label_id) {
  if (!ly || !label_id || !*label_id) {
    return -1;
  }
  for (int i = 0; i < ly->label_count; ++i) {
    if (strcmp(ly->labels[i].id, label_id) == 0) {
      return i;
    }
  }
  return -1;
}

int clamp_int(int v, int lo, int hi) {
  if (v < lo) return lo;
  if (v > hi) return hi;
  return v;
}

/* Parseo de rects/labels dentro del objeto de una capa. */

void parse_rects_array(const char* arr_s, const char* arr_e, GuiLayer* ly) {
  ly->rect_count = 0;
  const char* p = arr_s;
  while (p < arr_e && ly->rect_count < kMaxGuiLayerRects) {
    while (p < arr_e && (isspace(static_cast<unsigned char>(*p)) || *p == ',')) {
      ++p;
    }
    if (p >= arr_e || *p == ']') {
      break;
    }
    if (*p != '{') {
      break;
    }
    const char* oe = json_object_end(p);
    if (!oe) {
      break;
    }
    GuiRect r{};
    int v = 0;
    r.x = json_extract_int_for_key(p, oe, "x", &v) ? static_cast<int16_t>(v) : 0;
    r.y = json_extract_int_for_key(p, oe, "y", &v) ? static_cast<int16_t>(v) : 0;
    r.w = json_extract_int_for_key(p, oe, "w", &v) ? static_cast<int16_t>(v) : 1;
    r.h = json_extract_int_for_key(p, oe, "h", &v) ? static_cast<int16_t>(v) : 1;
    r.color_index = json_extract_int_for_key(p, oe, "color_index", &v)
                        ? static_cast<uint8_t>(clamp_int(v, 0, 31))
                        : 0;
    ly->rects[ly->rect_count++] = r;
    p = oe;
  }
}

void parse_labels_array(const char* arr_s, const char* arr_e, GuiLayer* ly) {
  ly->label_count = 0;
  const char* p = arr_s;
  while (p < arr_e && ly->label_count < kMaxGuiLayerLabels) {
    while (p < arr_e && (isspace(static_cast<unsigned char>(*p)) || *p == ',')) {
      ++p;
    }
    if (p >= arr_e || *p == ']') {
      break;
    }
    if (*p != '{') {
      break;
    }
    const char* oe = json_object_end(p);
    if (!oe) {
      break;
    }
    GuiLabel lbl{};
    lbl.id[0] = '\0';
    lbl.font_id[0] = '\0';
    lbl.text[0] = '\0';
    lbl.color_index = -1;
    int v = 0;
    json_extract_string_for_key(p, oe, "id", lbl.id, sizeof lbl.id);
    lbl.x = json_extract_int_for_key(p, oe, "x", &v) ? static_cast<int16_t>(v) : 0;
    lbl.y = json_extract_int_for_key(p, oe, "y", &v) ? static_cast<int16_t>(v) : 0;
    json_extract_string_for_key(p, oe, "font", lbl.font_id, sizeof lbl.font_id);
    json_extract_string_for_key(p, oe, "text", lbl.text, sizeof lbl.text);
    if (json_extract_int_for_key(p, oe, "color_index", &v)) {
      if (v < 0) {
        lbl.color_index = -1;
      } else if (v > 30) {
        lbl.color_index = 30;
      } else {
        lbl.color_index = static_cast<int8_t>(v);
      }
    }
    if (!lbl.id[0] || !lbl.font_id[0]) {
      p = oe;
      continue;  // silenciosamente descartada: id o font faltantes son error de autoria
    }
    ly->labels[ly->label_count++] = lbl;
    p = oe;
  }
}

bool parse_one_layer(const char* obj_s, const char* obj_e, GuiLayer* ly) {
  memset(ly, 0, sizeof(*ly));
  ly->w = kSceneW;
  ly->h = kSceneH;
  ly->transparent_bg = false;
  ly->pauses_scene = false;
  ly->captures_input = false;
  ly->z_manifest = 0;
  ly->z_override_set = false;
  ly->visible = false;
  json_extract_string_for_key(obj_s, obj_e, "id", ly->id, sizeof ly->id);
  if (!ly->id[0]) {
    return false;  // sin id, capa invalida
  }
  int v = 0;
  if (json_extract_int_for_key(obj_s, obj_e, "x", &v)) ly->x = clamp_int(v, 0, kSceneW - 1);
  if (json_extract_int_for_key(obj_s, obj_e, "y", &v)) ly->y = clamp_int(v, 0, kSceneH - 1);
  if (json_extract_int_for_key(obj_s, obj_e, "w", &v)) ly->w = clamp_int(v, 1, kSceneW);
  if (json_extract_int_for_key(obj_s, obj_e, "h", &v)) ly->h = clamp_int(v, 1, kSceneH);
  // Recorta el rect al framebuffer -- x + w y y + h no pueden salir.
  if (ly->x + ly->w > kSceneW) ly->w = kSceneW - ly->x;
  if (ly->y + ly->h > kSceneH) ly->h = kSceneH - ly->y;
  if (json_extract_int_for_key(obj_s, obj_e, "bg_color_index", &v)) {
    ly->bg_color_index = static_cast<uint8_t>(clamp_int(v, 0, 31));
  }
  json_extract_bool_for_key(obj_s, obj_e, "transparent_bg", &ly->transparent_bg);
  json_extract_bool_for_key(obj_s, obj_e, "pauses_scene", &ly->pauses_scene);
  json_extract_bool_for_key(obj_s, obj_e, "captures_input", &ly->captures_input);
  if (json_extract_int_for_key(obj_s, obj_e, "z", &v)) {
    ly->z_manifest = static_cast<int16_t>(clamp_int(v, -1000, 1000));
  }
  // Sub-arrays: rects y text_labels.
  const char* rk = strstr_bounded(obj_s, obj_e, "\"rects\"");
  if (rk) {
    const char* rp = rk + 7;
    while (rp < obj_e && *rp != '[') ++rp;
    if (rp < obj_e && *rp == '[') {
      const char* re = json_array_end(rp);
      if (re) {
        parse_rects_array(rp + 1, re, ly);
      }
    }
  }
  const char* lk = strstr_bounded(obj_s, obj_e, "\"text_labels\"");
  if (lk) {
    const char* lp = lk + 13;
    while (lp < obj_e && *lp != '[') ++lp;
    if (lp < obj_e && *lp == '[') {
      const char* le = json_array_end(lp);
      if (le) {
        parse_labels_array(lp + 1, le, ly);
      }
    }
  }
  return true;
}

int effective_z(const GuiLayer* ly) {
  return ly->z_override_set ? ly->z_override : ly->z_manifest;
}

void paint_one_layer(const GuiLayer* ly) {
  // Fondo (rectangulo entero de la capa) primero.
  if (!ly->transparent_bg) {
    turtle_gpu_fill_rect_raw(ly->x, ly->y, ly->w, ly->h, ly->bg_color_index);
  }
  // Rectangulos internos, orden del array (0 primero, N-1 encima).
  for (int i = 0; i < ly->rect_count; ++i) {
    const GuiRect& r = ly->rects[i];
    const int rx = ly->x + r.x;
    const int ry = ly->y + r.y;
    // Clampeo defensivo al rect de la capa (el manifest ya suele traerlo bien).
    int rw = r.w;
    int rh = r.h;
    if (rx + rw > ly->x + ly->w) rw = (ly->x + ly->w) - rx;
    if (ry + rh > ly->y + ly->h) rh = (ly->y + ly->h) - ry;
    if (rw <= 0 || rh <= 0) continue;
    turtle_gpu_fill_rect_raw(rx, ry, rw, rh, r.color_index);
  }
  // Etiquetas de texto. Usan turtle_scene_draw_text_absolute-like pero sin
  // proteccion de playfield -- ver turtle_font_draw_fb_raw.
  for (int i = 0; i < ly->label_count; ++i) {
    const GuiLabel& lbl = ly->labels[i];
    if (!lbl.text[0]) continue;
    // Resolver la fuente contra el bundle actual (mismo cache que scene text).
    if (!s_bundle_json || s_bundle_json_len == 0) continue;
    const int tint = (lbl.color_index >= 0) ? static_cast<int>(lbl.color_index) : -1;
    turtle_scene_draw_text_raw(s_bundle_json, s_bundle_json_len, lbl.font_id, ly->x + lbl.x,
                               ly->y + lbl.y, lbl.text, tint);
  }
}

}  // namespace

void turtle_gui_layer_begin_scene(const char* bundle_json, size_t bundle_json_len) {
  s_layer_count = 0;
  s_bundle_json = bundle_json;
  s_bundle_json_len = bundle_json_len;
  if (!bundle_json || bundle_json_len == 0) {
    return;
  }
  const char* end = bundle_json + bundle_json_len;
  const char* gk = strstr_bounded(bundle_json, end, "\"guilayers\"");
  if (!gk) {
    return;  // catalogo vacio, ok
  }
  const char* p = gk + strlen("\"guilayers\"");
  while (p < end && *p != '[') ++p;
  if (p >= end || *p != '[') {
    return;
  }
  ++p;
  int discarded = 0;
  while (p < end && s_layer_count < kMaxGuiLayers) {
    while (p < end && (isspace(static_cast<unsigned char>(*p)) || *p == ',')) {
      ++p;
    }
    if (p >= end || *p == ']') break;
    if (*p != '{') break;
    const char* oe = json_object_end(p);
    if (!oe) break;
    GuiLayer* ly = &s_layers[s_layer_count];
    if (parse_one_layer(p, oe, ly)) {
      ++s_layer_count;
    } else {
      ++discarded;
    }
    p = oe;
  }
  if (s_layer_count > 0 || discarded > 0) {
    Serial.printf("turtle_gui_layer: %d capas cargadas (%d descartadas)\n", s_layer_count,
                  discarded);
  }
}

void turtle_gui_layer_release(void) {
  s_layer_count = 0;
  s_bundle_json = nullptr;
  s_bundle_json_len = 0;
}

bool turtle_gui_layer_any_pauses(void) {
  for (int i = 0; i < s_layer_count; ++i) {
    if (s_layers[i].visible && s_layers[i].pauses_scene) return true;
  }
  return false;
}

bool turtle_gui_layer_any_captures_input(void) {
  for (int i = 0; i < s_layer_count; ++i) {
    if (s_layers[i].visible && s_layers[i].captures_input) return true;
  }
  return false;
}

void turtle_gui_layer_paint_all(void) {
  if (s_layer_count == 0) return;
  // Orden por z ascendente. Con kMaxGuiLayers=8 es <=64 comparaciones por frame; O(n^2)
  // insertion sort en un buffer de indices basta y evita mutar el array real (que preserva
  // el orden de manifest para desempate estable).
  int order[kMaxGuiLayers];
  int active = 0;
  for (int i = 0; i < s_layer_count; ++i) {
    if (s_layers[i].visible) {
      order[active++] = i;
    }
  }
  if (active == 0) return;
  for (int i = 1; i < active; ++i) {
    const int cur = order[i];
    const int cur_z = effective_z(&s_layers[cur]);
    int j = i - 1;
    while (j >= 0 && effective_z(&s_layers[order[j]]) > cur_z) {
      order[j + 1] = order[j];
      --j;
    }
    order[j + 1] = cur;
  }
  for (int i = 0; i < active; ++i) {
    paint_one_layer(&s_layers[order[i]]);
  }
}

bool turtle_gui_layer_show(const char* id, bool has_z_override, int z_override) {
  const int idx = find_layer_index(id);
  if (idx < 0) return false;
  GuiLayer* ly = &s_layers[idx];
  ly->visible = true;
  if (has_z_override) {
    ly->z_override_set = true;
    ly->z_override = static_cast<int16_t>(clamp_int(z_override, -1000, 1000));
  }
  return true;
}

bool turtle_gui_layer_hide(const char* id) {
  const int idx = find_layer_index(id);
  if (idx < 0) return false;
  GuiLayer* ly = &s_layers[idx];
  ly->visible = false;
  ly->z_override_set = false;
  return true;
}

bool turtle_gui_layer_is_visible(const char* id) {
  const int idx = find_layer_index(id);
  if (idx < 0) return false;
  return s_layers[idx].visible;
}

void turtle_gui_layer_hide_all(void) {
  for (int i = 0; i < s_layer_count; ++i) {
    s_layers[i].visible = false;
    s_layers[i].z_override_set = false;
  }
}

bool turtle_gui_layer_set_text(const char* id, const char* label_id, const char* str) {
  const int idx = find_layer_index(id);
  if (idx < 0) return false;
  GuiLayer* ly = &s_layers[idx];
  const int li = find_label_index(ly, label_id);
  if (li < 0) return false;
  GuiLabel& lbl = ly->labels[li];
  if (!str) {
    lbl.text[0] = '\0';
    return true;
  }
  const size_t maxlen = sizeof lbl.text - 1;
  strncpy(lbl.text, str, maxlen);
  lbl.text[maxlen] = '\0';
  return true;
}
