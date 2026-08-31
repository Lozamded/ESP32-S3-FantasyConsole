#include "turtle_gui_layer.h"

#include "turtle_font.h"
#include "turtle_gpu.h"
#include "turtle_json.h"
#include "turtle_scene.h"

#include <Arduino.h>
#include <ctype.h>
#include <stdlib.h>
#include <string.h>

#if defined(ESP32) || defined(ESP_PLATFORM)
#include <esp_heap_caps.h>
#endif

namespace {

constexpr int kMaxGuiLayers = 8;
constexpr int kMaxGuiLayerRects = 16;
constexpr int kMaxGuiLayerLabels = 16;
constexpr int kMaxGuiLayerProgressBars = 4;
constexpr int kMaxGuiLayerPipBars = 4;
constexpr int kMaxGuiLayerSprites = 4;
constexpr int kMaxGuiBarRanges = 3;
constexpr int kMaxPipCount = 32;
constexpr size_t kGuiLayerTextCap = 64;   // 63 chars + nul
constexpr size_t kGuiLayerFontIdCap = 48;
constexpr size_t kGuiLayerIdCap = 40;
constexpr size_t kGuiLayerLabelIdCap = 40;
constexpr size_t kGuiSpriteIdCap = 40;

// Framebuffer canonico (spec/scene-v0.md). Duplicado aca; parametrizarlo tampoco tendria
// sentido -- si cambia, todo el pipeline visual cambia.
constexpr int kSceneW = 164;
constexpr int kSceneH = 124;
constexpr uint8_t kDefaultTransparentIndex = 31;

// Tamano maximo de un sprite decodificado para las capas GUI. Compartido con
// turtle_scene (kMaxSpriteW * kMaxSpriteH); duplicarlo aca evita depender de la constante
// interna de esa unidad de compilacion. Si cambia alla, actualizar aca tambien.
constexpr int kGuiSpriteMaxW = 32;
constexpr int kGuiSpriteMaxH = 32;
constexpr size_t kGuiSpriteScratchCap = kGuiSpriteMaxW * kGuiSpriteMaxH;

enum class GuiBarDir : uint8_t {
  LeftToRight = 0,
  RightToLeft,
  TopToBottom,
  BottomToTop,
};

enum class GuiFillMode : uint8_t {
  Color = 0,
  Sprite,
};

enum class GuiPipDir : uint8_t {
  Horizontal = 0,
  Vertical,
};

struct GuiBarRange {
  uint8_t min_pct;         // 0..100 inclusivo
  uint8_t max_pct;         // 0..100 exclusivo (excepto 100 que es inclusivo, ver spec)
  int8_t alt_color_index;  // -1 = no override
  char alt_sprite_id[kGuiSpriteIdCap];  // "" = no override
};

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
  // spec/gui-layer-v0.md: rastro del rect que ocupo el texto en el frame previo (coords fb,
  // Y-abajo). paint_one_layer lo restaura desde s_static_fb antes de repintar el nuevo texto,
  // para evitar acumulacion de tinta cuando el texto cambia sobre transparent_bg (un label
  // "x0" -> "x1" dejaba los pixeles del "0" pegados detras del "1"). has_prev_blit false =
  // primer paint del label (no hay nada que borrar todavia).
  int16_t prev_blit_x;
  int16_t prev_blit_y;
  int16_t prev_blit_w;
  int16_t prev_blit_h;
  bool has_prev_blit;
};

struct GuiProgressBar {
  char id[kGuiLayerLabelIdCap];
  int16_t x;
  int16_t y;
  int16_t w;
  int16_t h;
  GuiBarDir direction;
  GuiFillMode fill_mode;
  uint8_t fill_color_index;   // usado con GuiFillMode::Color
  char fill_sprite_id[kGuiSpriteIdCap];  // usado con GuiFillMode::Sprite
  uint8_t bg_color_index;     // fondo del bar (parte vacia). 31 = transparente
  int8_t border_color_index;  // -1 = sin marco, 0..30 = color del marco 1 px
  int16_t value_num;
  int16_t value_den;
  int range_count;
  GuiBarRange ranges[kMaxGuiBarRanges];
};

struct GuiPipBar {
  char id[kGuiLayerLabelIdCap];
  int16_t x;
  int16_t y;
  char sprite_full_id[kGuiSpriteIdCap];
  GuiPipDir direction;
  uint8_t gap_px;
  int16_t value;
  int16_t max_value;
  int range_count;
  GuiBarRange ranges[kMaxGuiBarRanges];
};

struct GuiSpriteIcon {
  char id[kGuiLayerLabelIdCap];
  int16_t x;
  int16_t y;
  char sprite_id[kGuiSpriteIdCap];
  uint8_t frame_index;
  bool flip_h;
  bool flip_v;
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
  int progress_bar_count;
  int pip_bar_count;
  int sprite_count;
  GuiRect rects[kMaxGuiLayerRects];
  GuiLabel labels[kMaxGuiLayerLabels];
  GuiProgressBar progress_bars[kMaxGuiLayerProgressBars];
  GuiPipBar pip_bars[kMaxGuiLayerPipBars];
  GuiSpriteIcon sprites[kMaxGuiLayerSprites];
};

// El array vive en el heap (preferentemente PSRAM). sizeof(GuiLayer) * 8 ~= 38 KB con
// progress + pip bars incluidos (rects + labels + progress + pip + rangos por bar). Se aloja
// una sola vez la primera vez que se carga una escena y se conserva por el resto de la vida
// del console (release() solo resetea el contenido, no libera el buffer -- churn innecesario).
GuiLayer* s_layers = nullptr;
int s_layer_count = 0;
const char* s_bundle_json = nullptr;
size_t s_bundle_json_len = 0;

// Scratch de decodificacion de sprites (progress bars con sprite tileado + pip bars). ~1 KB
// PSRAM. Reutilizado entre bars dentro del mismo paint (cache de sprites de turtle_scene se
// encarga de no re-parsear el mismo sprite). Se aloja perezosamente igual que s_layers.
uint8_t* s_gui_sprite_scratch = nullptr;

// Cache de sprites que fallaron al cargar (id no existe en bundle ni SD). El pipeline de
// turtle_scene NO cachea misses: reintenta el fopen cada vez. Como el pintado de capas GUI
// corre cada frame, un sprite faltante inundaria Serial y triggerearia SD reads inutiles.
// Este ring buffer (8 slots) hace que se logue UNA vez por id y se short-circuit despues.
// Se resetea al comenzar cada escena (turtle_gui_layer_begin_scene).
constexpr int kMissingSpriteCacheSize = 8;
char s_missing_sprite_cache[kMissingSpriteCacheSize][kGuiSpriteIdCap];
int s_missing_sprite_head = 0;

bool is_sprite_known_missing(const char* id) {
  if (!id || !*id) return false;
  for (int i = 0; i < kMissingSpriteCacheSize; ++i) {
    if (s_missing_sprite_cache[i][0] && strcmp(s_missing_sprite_cache[i], id) == 0) {
      return true;
    }
  }
  return false;
}

void mark_sprite_missing(const char* id) {
  if (!id || !*id) return;
  strncpy(s_missing_sprite_cache[s_missing_sprite_head], id, kGuiSpriteIdCap - 1);
  s_missing_sprite_cache[s_missing_sprite_head][kGuiSpriteIdCap - 1] = '\0';
  s_missing_sprite_head = (s_missing_sprite_head + 1) % kMissingSpriteCacheSize;
  Serial.printf("turtle_gui_layer: sprite \"%s\" no encontrado (bar invisible)\n", id);
}

void reset_missing_sprite_cache(void) {
  memset(s_missing_sprite_cache, 0, sizeof s_missing_sprite_cache);
  s_missing_sprite_head = 0;
}

bool ensure_layers_allocated(void) {
  if (s_layers) return true;
  const size_t need = sizeof(GuiLayer) * kMaxGuiLayers;
#if defined(ESP32) || defined(ESP_PLATFORM)
  s_layers = static_cast<GuiLayer*>(
      heap_caps_malloc(need, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (!s_layers) {
    s_layers = static_cast<GuiLayer*>(
        heap_caps_malloc(need, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
  }
#else
  s_layers = static_cast<GuiLayer*>(malloc(need));
#endif
  if (!s_layers) {
    Serial.println("turtle_gui_layer: sin memoria para el buffer de capas");
    return false;
  }
  memset(s_layers, 0, need);
  return true;
}

bool ensure_sprite_scratch_allocated(void) {
  if (s_gui_sprite_scratch) return true;
#if defined(ESP32) || defined(ESP_PLATFORM)
  s_gui_sprite_scratch = static_cast<uint8_t*>(
      heap_caps_malloc(kGuiSpriteScratchCap, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (!s_gui_sprite_scratch) {
    s_gui_sprite_scratch = static_cast<uint8_t*>(
        heap_caps_malloc(kGuiSpriteScratchCap, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
  }
#else
  s_gui_sprite_scratch = static_cast<uint8_t*>(malloc(kGuiSpriteScratchCap));
#endif
  return s_gui_sprite_scratch != nullptr;
}

int find_layer_index(const char* id) {
  if (!s_layers || !id || !*id) {
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
    lbl.has_prev_blit = false;
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

GuiBarDir parse_bar_direction(const char* obj_s, const char* obj_e, GuiBarDir def) {
  char buf[24] = {0};
  if (!json_extract_string_for_key(obj_s, obj_e, "direction", buf, sizeof buf)) {
    return def;
  }
  if (strcmp(buf, "left_to_right") == 0) return GuiBarDir::LeftToRight;
  if (strcmp(buf, "right_to_left") == 0) return GuiBarDir::RightToLeft;
  if (strcmp(buf, "top_to_bottom") == 0) return GuiBarDir::TopToBottom;
  if (strcmp(buf, "bottom_to_top") == 0) return GuiBarDir::BottomToTop;
  return def;
}

GuiFillMode parse_fill_mode(const char* obj_s, const char* obj_e, GuiFillMode def) {
  char buf[16] = {0};
  if (!json_extract_string_for_key(obj_s, obj_e, "fill_mode", buf, sizeof buf)) {
    return def;
  }
  if (strcmp(buf, "sprite") == 0) return GuiFillMode::Sprite;
  return GuiFillMode::Color;
}

GuiPipDir parse_pip_direction(const char* obj_s, const char* obj_e, GuiPipDir def) {
  char buf[16] = {0};
  if (!json_extract_string_for_key(obj_s, obj_e, "direction", buf, sizeof buf)) {
    return def;
  }
  if (strcmp(buf, "vertical") == 0) return GuiPipDir::Vertical;
  return GuiPipDir::Horizontal;
}

void parse_ranges_array(const char* arr_s, const char* arr_e, GuiBarRange* out, int* out_count) {
  *out_count = 0;
  const char* p = arr_s;
  while (p < arr_e && *out_count < kMaxGuiBarRanges) {
    while (p < arr_e && (isspace(static_cast<unsigned char>(*p)) || *p == ',')) {
      ++p;
    }
    if (p >= arr_e || *p == ']') break;
    if (*p != '{') break;
    const char* oe = json_object_end(p);
    if (!oe) break;
    GuiBarRange r{};
    r.alt_color_index = -1;
    r.alt_sprite_id[0] = '\0';
    int v = 0;
    r.min_pct = json_extract_int_for_key(p, oe, "min_pct", &v)
                    ? static_cast<uint8_t>(clamp_int(v, 0, 100))
                    : 0;
    r.max_pct = json_extract_int_for_key(p, oe, "max_pct", &v)
                    ? static_cast<uint8_t>(clamp_int(v, 0, 100))
                    : 100;
    if (json_extract_int_for_key(p, oe, "alt_color_index", &v)) {
      if (v >= 0 && v <= 30) {
        r.alt_color_index = static_cast<int8_t>(v);
      }
    }
    json_extract_string_for_key(p, oe, "alt_sprite_id", r.alt_sprite_id, sizeof r.alt_sprite_id);
    p = oe;
    if (r.min_pct >= r.max_pct) {
      continue;  // rango degenerado: descartar silenciosamente
    }
    out[*out_count] = r;
    ++(*out_count);
  }
}

void parse_progress_bars_array(const char* arr_s, const char* arr_e, GuiLayer* ly) {
  ly->progress_bar_count = 0;
  const char* p = arr_s;
  while (p < arr_e && ly->progress_bar_count < kMaxGuiLayerProgressBars) {
    while (p < arr_e && (isspace(static_cast<unsigned char>(*p)) || *p == ',')) {
      ++p;
    }
    if (p >= arr_e || *p == ']') break;
    if (*p != '{') break;
    const char* oe = json_object_end(p);
    if (!oe) break;
    GuiProgressBar bar{};
    bar.id[0] = '\0';
    bar.fill_sprite_id[0] = '\0';
    bar.direction = GuiBarDir::LeftToRight;
    bar.fill_mode = GuiFillMode::Color;
    bar.fill_color_index = 11;
    bar.bg_color_index = 3;
    bar.border_color_index = -1;
    bar.value_num = 0;
    bar.value_den = 1;
    json_extract_string_for_key(p, oe, "id", bar.id, sizeof bar.id);
    int v = 0;
    bar.x = json_extract_int_for_key(p, oe, "x", &v) ? static_cast<int16_t>(v) : 0;
    bar.y = json_extract_int_for_key(p, oe, "y", &v) ? static_cast<int16_t>(v) : 0;
    bar.w = json_extract_int_for_key(p, oe, "w", &v) ? static_cast<int16_t>(clamp_int(v, 1, kSceneW)) : 1;
    bar.h = json_extract_int_for_key(p, oe, "h", &v) ? static_cast<int16_t>(clamp_int(v, 1, kSceneH)) : 1;
    bar.direction = parse_bar_direction(p, oe, GuiBarDir::LeftToRight);
    bar.fill_mode = parse_fill_mode(p, oe, GuiFillMode::Color);
    if (json_extract_int_for_key(p, oe, "fill_color_index", &v)) {
      bar.fill_color_index = static_cast<uint8_t>(clamp_int(v, 0, 31));
    }
    json_extract_string_for_key(p, oe, "fill_sprite_id", bar.fill_sprite_id,
                                sizeof bar.fill_sprite_id);
    if (json_extract_int_for_key(p, oe, "bg_color_index", &v)) {
      bar.bg_color_index = static_cast<uint8_t>(clamp_int(v, 0, 31));
    }
    if (json_extract_int_for_key(p, oe, "border_color_index", &v)) {
      bar.border_color_index = (v < 0 || v > 30) ? -1 : static_cast<int8_t>(v);
    }
    if (json_extract_int_for_key(p, oe, "value_num", &v)) {
      bar.value_num = static_cast<int16_t>(clamp_int(v, -32768, 32767));
    }
    if (json_extract_int_for_key(p, oe, "value_den", &v)) {
      bar.value_den = static_cast<int16_t>(clamp_int(v, 1, 32767));
    }
    if (bar.value_den <= 0) bar.value_den = 1;
    bar.range_count = 0;
    const char* rk = strstr_bounded(p, oe, "\"ranges\"");
    if (rk) {
      const char* rp = rk + 8;
      while (rp < oe && *rp != '[') ++rp;
      if (rp < oe && *rp == '[') {
        const char* re = json_array_end(rp);
        if (re) {
          parse_ranges_array(rp + 1, re, bar.ranges, &bar.range_count);
        }
      }
    }
    p = oe;
    if (!bar.id[0]) continue;  // sin id, bar invalido
    ly->progress_bars[ly->progress_bar_count++] = bar;
  }
}

void parse_pip_bars_array(const char* arr_s, const char* arr_e, GuiLayer* ly) {
  ly->pip_bar_count = 0;
  const char* p = arr_s;
  while (p < arr_e && ly->pip_bar_count < kMaxGuiLayerPipBars) {
    while (p < arr_e && (isspace(static_cast<unsigned char>(*p)) || *p == ',')) {
      ++p;
    }
    if (p >= arr_e || *p == ']') break;
    if (*p != '{') break;
    const char* oe = json_object_end(p);
    if (!oe) break;
    GuiPipBar bar{};
    bar.id[0] = '\0';
    bar.sprite_full_id[0] = '\0';
    bar.direction = GuiPipDir::Horizontal;
    bar.gap_px = 0;
    bar.value = 0;
    bar.max_value = 1;
    json_extract_string_for_key(p, oe, "id", bar.id, sizeof bar.id);
    int v = 0;
    bar.x = json_extract_int_for_key(p, oe, "x", &v) ? static_cast<int16_t>(v) : 0;
    bar.y = json_extract_int_for_key(p, oe, "y", &v) ? static_cast<int16_t>(v) : 0;
    json_extract_string_for_key(p, oe, "sprite_full_id", bar.sprite_full_id,
                                sizeof bar.sprite_full_id);
    bar.direction = parse_pip_direction(p, oe, GuiPipDir::Horizontal);
    if (json_extract_int_for_key(p, oe, "gap_px", &v)) {
      bar.gap_px = static_cast<uint8_t>(clamp_int(v, 0, 32));
    }
    if (json_extract_int_for_key(p, oe, "max_value", &v)) {
      bar.max_value = static_cast<int16_t>(clamp_int(v, 1, kMaxPipCount));
    }
    if (json_extract_int_for_key(p, oe, "value", &v)) {
      bar.value = static_cast<int16_t>(clamp_int(v, 0, bar.max_value));
    }
    bar.range_count = 0;
    const char* rk = strstr_bounded(p, oe, "\"ranges\"");
    if (rk) {
      const char* rp = rk + 8;
      while (rp < oe && *rp != '[') ++rp;
      if (rp < oe && *rp == '[') {
        const char* re = json_array_end(rp);
        if (re) {
          parse_ranges_array(rp + 1, re, bar.ranges, &bar.range_count);
        }
      }
    }
    p = oe;
    if (!bar.id[0] || !bar.sprite_full_id[0]) continue;
    ly->pip_bars[ly->pip_bar_count++] = bar;
  }
}

void parse_sprites_array(const char* arr_s, const char* arr_e, GuiLayer* ly) {
  ly->sprite_count = 0;
  const char* p = arr_s;
  while (p < arr_e && ly->sprite_count < kMaxGuiLayerSprites) {
    while (p < arr_e && (isspace(static_cast<unsigned char>(*p)) || *p == ',')) {
      ++p;
    }
    if (p >= arr_e || *p == ']') break;
    if (*p != '{') break;
    const char* oe = json_object_end(p);
    if (!oe) break;
    GuiSpriteIcon icon{};
    icon.id[0] = '\0';
    icon.sprite_id[0] = '\0';
    icon.frame_index = 0;
    icon.flip_h = false;
    icon.flip_v = false;
    json_extract_string_for_key(p, oe, "id", icon.id, sizeof icon.id);
    json_extract_string_for_key(p, oe, "sprite_id", icon.sprite_id, sizeof icon.sprite_id);
    int v = 0;
    icon.x = json_extract_int_for_key(p, oe, "x", &v) ? static_cast<int16_t>(v) : 0;
    icon.y = json_extract_int_for_key(p, oe, "y", &v) ? static_cast<int16_t>(v) : 0;
    if (json_extract_int_for_key(p, oe, "frame_index", &v)) {
      icon.frame_index = static_cast<uint8_t>(clamp_int(v, 0, 255));
    }
    json_extract_bool_for_key(p, oe, "flip_h", &icon.flip_h);
    json_extract_bool_for_key(p, oe, "flip_v", &icon.flip_v);
    p = oe;
    if (!icon.id[0] || !icon.sprite_id[0]) continue;  // sin id o sprite, icono invalido
    ly->sprites[ly->sprite_count++] = icon;
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
  const char* pk = strstr_bounded(obj_s, obj_e, "\"progress_bars\"");
  if (pk) {
    const char* pp = pk + 15;
    while (pp < obj_e && *pp != '[') ++pp;
    if (pp < obj_e && *pp == '[') {
      const char* pe = json_array_end(pp);
      if (pe) {
        parse_progress_bars_array(pp + 1, pe, ly);
      }
    }
  }
  const char* qk = strstr_bounded(obj_s, obj_e, "\"pip_bars\"");
  if (qk) {
    const char* qp = qk + 10;
    while (qp < obj_e && *qp != '[') ++qp;
    if (qp < obj_e && *qp == '[') {
      const char* qe = json_array_end(qp);
      if (qe) {
        parse_pip_bars_array(qp + 1, qe, ly);
      }
    }
  }
  const char* sk = strstr_bounded(obj_s, obj_e, "\"sprites\"");
  if (sk) {
    const char* sp = sk + 9;
    while (sp < obj_e && *sp != '[') ++sp;
    if (sp < obj_e && *sp == '[') {
      const char* se = json_array_end(sp);
      if (se) {
        parse_sprites_array(sp + 1, se, ly);
      }
    }
  }
  return true;
}

int effective_z(const GuiLayer* ly) {
  return ly->z_override_set ? ly->z_override : ly->z_manifest;
}

/**
 * Resuelve el rango activo (si alguno) para una fraccion actual y un array de rangos.
 * `frac_pct` es 0..100. Devuelve puntero al primer rango que cubre el porcentaje (spec:
 * el primero gana), o nullptr si ninguno matchea. Convencion: [min, max) salvo max=100
 * que es [min, 100] (asi el 100% nunca queda huerfano).
 */
const GuiBarRange* resolve_active_range(int frac_pct, const GuiBarRange* ranges, int count) {
  for (int i = 0; i < count; ++i) {
    const GuiBarRange& r = ranges[i];
    const bool hit =
        (frac_pct >= r.min_pct) &&
        ((r.max_pct >= 100) ? (frac_pct <= r.max_pct) : (frac_pct < r.max_pct));
    if (hit) return &r;
  }
  return nullptr;
}

/**
 * Blit tileado de un sprite dentro de un rect en coord de framebuffer. `src_pixels` es
 * row-first, dimensiones sw x sh. Recorta el ultimo tile parcial en cada eje al borde del rect.
 * Pixeles con indice de paleta 31 (kDefaultTransparentIndex) se saltan. Usa turtle_gpu_pixel_raw
 * (no clipea al playfield y trabaja en coord de framebuffer, no de escena) igual que el resto
 * del pintado de capas GUI.
 */
void blit_tiled_sprite_raw(int rx, int ry, int rw, int rh, const uint8_t* src_pixels, int sw,
                           int sh) {
  if (!src_pixels || sw <= 0 || sh <= 0 || rw <= 0 || rh <= 0) return;
  for (int dy = 0; dy < rh; ++dy) {
    const int sy = dy % sh;
    for (int dx = 0; dx < rw; ++dx) {
      const int sx = dx % sw;
      const uint8_t px = src_pixels[sy * sw + sx];
      if (px == kDefaultTransparentIndex) continue;
      turtle_gpu_pixel_raw(rx + dx, ry + dy, px);
    }
  }
}

/**
 * Blit 1:1 (sin escala ni tiling) de un sprite en coord de framebuffer. Contraparte de
 * turtle_gpu_blit_indexed_scene pero sin proteccion de playfield y con coord fb, para pip bars.
 */
void blit_sprite_raw(int dx, int dy, const uint8_t* src_pixels, int sw, int sh) {
  if (!src_pixels || sw <= 0 || sh <= 0) return;
  for (int y = 0; y < sh; ++y) {
    for (int x = 0; x < sw; ++x) {
      const uint8_t px = src_pixels[y * sw + x];
      if (px == kDefaultTransparentIndex) continue;
      turtle_gpu_pixel_raw(dx + x, dy + y, px);
    }
  }
}

/**
 * Variante de blit_sprite_raw con flip horizontal/vertical (para iconos sprite en capas GUI).
 * flip_h invierte la columna fuente (sw - 1 - x), flip_v invierte la fila fuente (sh - 1 - y).
 * El rect ocupado no cambia -- solo el contenido queda espejado.
 */
void blit_sprite_raw_flipped(int dx, int dy, const uint8_t* src_pixels, int sw, int sh,
                             bool flip_h, bool flip_v) {
  if (!src_pixels || sw <= 0 || sh <= 0) return;
  for (int y = 0; y < sh; ++y) {
    const int sy = flip_v ? (sh - 1 - y) : y;
    for (int x = 0; x < sw; ++x) {
      const int sx = flip_h ? (sw - 1 - x) : x;
      const uint8_t px = src_pixels[sy * sw + sx];
      if (px == kDefaultTransparentIndex) continue;
      turtle_gpu_pixel_raw(dx + x, dy + y, px);
    }
  }
}

void paint_sprite_icon(const GuiLayer* ly, const GuiSpriteIcon* icon) {
  if (!icon->sprite_id[0]) return;
  if (is_sprite_known_missing(icon->sprite_id)) return;
  if (!ensure_sprite_scratch_allocated()) return;
  int sw = 0;
  int sh = 0;
  if (!turtle_scene_load_sprite_pixels(icon->sprite_id, icon->frame_index, s_gui_sprite_scratch,
                                       kGuiSpriteScratchCap, &sw, &sh)) {
    mark_sprite_missing(icon->sprite_id);
    return;
  }
  if (sw <= 0 || sh <= 0) return;
  const int dx = ly->x + icon->x;
  const int dy = ly->y + icon->y;
  // Clamp: si el icono no cabe dentro del rect de la capa, cortar silenciosamente. El autor
  // debe posicionarlo bien; el editor puede advertir. No hay clip por-pixel aca (matchea
  // blit_sprite_raw) -- si desborda parcialmente se pinta lo que quepa dentro del framebuffer,
  // pero fuera del rect de la capa la escena de fondo se ve.
  if (dx + sw > ly->x + ly->w) return;
  if (dy + sh > ly->y + ly->h) return;
  if (icon->flip_h || icon->flip_v) {
    blit_sprite_raw_flipped(dx, dy, s_gui_sprite_scratch, sw, sh, icon->flip_h, icon->flip_v);
  } else {
    blit_sprite_raw(dx, dy, s_gui_sprite_scratch, sw, sh);
  }
}

void paint_progress_bar(const GuiLayer* ly, const GuiProgressBar* bar) {
  const int bx = ly->x + bar->x;
  const int by = ly->y + bar->y;
  int bw = bar->w;
  int bh = bar->h;
  // Clampeo defensivo al rect de la capa.
  if (bx + bw > ly->x + ly->w) bw = (ly->x + ly->w) - bx;
  if (by + bh > ly->y + ly->h) bh = (ly->y + ly->h) - by;
  if (bw <= 0 || bh <= 0) return;

  // Fondo del bar (parte vacia). 31 = transparente, no pintar.
  if (bar->bg_color_index != kDefaultTransparentIndex) {
    turtle_gpu_fill_rect_raw(bx, by, bw, bh, bar->bg_color_index);
  }

  // Fraccion 0..1 -> pixeles rellenados en el eje de direction.
  int num = bar->value_num;
  int den = bar->value_den > 0 ? bar->value_den : 1;
  if (num < 0) num = 0;
  if (num > den) num = den;
  const int frac_pct = (num * 100) / den;

  // Rango activo (si alguno). Puede reemplazar color y/o sprite base.
  const GuiBarRange* active = resolve_active_range(frac_pct, bar->ranges, bar->range_count);
  uint8_t eff_color = bar->fill_color_index;
  const char* eff_sprite = bar->fill_sprite_id;
  if (active) {
    if (active->alt_color_index >= 0) eff_color = static_cast<uint8_t>(active->alt_color_index);
    if (active->alt_sprite_id[0] != '\0') eff_sprite = active->alt_sprite_id;
  }

  // Sub-rect rellenado segun direction.
  int fx = bx, fy = by, fw = bw, fh = bh;
  switch (bar->direction) {
    case GuiBarDir::LeftToRight: {
      fw = (bw * num) / den;
      break;
    }
    case GuiBarDir::RightToLeft: {
      const int w_filled = (bw * num) / den;
      fx = bx + (bw - w_filled);
      fw = w_filled;
      break;
    }
    case GuiBarDir::TopToBottom: {
      fh = (bh * num) / den;
      break;
    }
    case GuiBarDir::BottomToTop: {
      const int h_filled = (bh * num) / den;
      fy = by + (bh - h_filled);
      fh = h_filled;
      break;
    }
  }

  if (fw > 0 && fh > 0) {
    if (bar->fill_mode == GuiFillMode::Color) {
      if (eff_color != kDefaultTransparentIndex) {
        turtle_gpu_fill_rect_raw(fx, fy, fw, fh, eff_color);
      }
    } else if (eff_sprite[0] != '\0' && !is_sprite_known_missing(eff_sprite)) {
      if (ensure_sprite_scratch_allocated()) {
        int sw = 0;
        int sh = 0;
        if (turtle_scene_load_sprite_pixels(eff_sprite, 0, s_gui_sprite_scratch,
                                            kGuiSpriteScratchCap, &sw, &sh)) {
          blit_tiled_sprite_raw(fx, fy, fw, fh, s_gui_sprite_scratch, sw, sh);
        } else {
          mark_sprite_missing(eff_sprite);
        }
      }
    }
  }

  // Marco opcional de 1 px (dibujado por encima del relleno).
  if (bar->border_color_index >= 0) {
    const uint8_t bc = static_cast<uint8_t>(bar->border_color_index);
    turtle_gpu_fill_rect_raw(bx, by, bw, 1, bc);              // top
    turtle_gpu_fill_rect_raw(bx, by + bh - 1, bw, 1, bc);     // bottom
    turtle_gpu_fill_rect_raw(bx, by, 1, bh, bc);              // left
    turtle_gpu_fill_rect_raw(bx + bw - 1, by, 1, bh, bc);     // right
  }
}

void paint_pip_bar(const GuiLayer* ly, const GuiPipBar* bar) {
  int val = bar->value;
  int maxv = bar->max_value > 0 ? bar->max_value : 1;
  if (val < 0) val = 0;
  if (val > maxv) val = maxv;
  // No early return on val==0 yet: necesitamos cargar el sprite para conocer sw/sh y borrar
  // la region completa antes de pintar -- sin esto los pips eliminados persisten en transparent_bg.

  // Rango activo puede reemplazar el sprite full.
  const int frac_pct = (val * 100) / maxv;
  const GuiBarRange* active = resolve_active_range(frac_pct, bar->ranges, bar->range_count);
  const char* eff_sprite = bar->sprite_full_id;
  if (active && active->alt_sprite_id[0] != '\0') {
    eff_sprite = active->alt_sprite_id;
  }
  if (!eff_sprite[0]) return;
  if (is_sprite_known_missing(eff_sprite)) return;

  if (!ensure_sprite_scratch_allocated()) return;
  int sw = 0;
  int sh = 0;
  if (!turtle_scene_load_sprite_pixels(eff_sprite, 0, s_gui_sprite_scratch, kGuiSpriteScratchCap,
                                       &sw, &sh)) {
    mark_sprite_missing(eff_sprite);
    return;
  }
  if (sw <= 0 || sh <= 0) return;

  // Borra el area de todos los pips (max_value) desde la capa estatica antes de repintar.
  // Sin esto, reducir `value` deja los pips sobrantes visibles en capas transparent_bg.
  const int step = (bar->direction == GuiPipDir::Horizontal ? sw : sh) + bar->gap_px;
  const int total_w = (bar->direction == GuiPipDir::Horizontal) ? (maxv * step - bar->gap_px) : sw;
  const int total_h = (bar->direction == GuiPipDir::Vertical)   ? (maxv * step - bar->gap_px) : sh;
  turtle_gpu_restore_static_rect_fb(ly->x + bar->x, ly->y + bar->y, total_w, total_h);

  if (val == 0) return;  // sin pips que pintar (region ya borrada)

  for (int i = 0; i < val; ++i) {
    int px = ly->x + bar->x;
    int py = ly->y + bar->y;
    if (bar->direction == GuiPipDir::Horizontal) {
      px += i * step;
    } else {
      py += i * step;
    }
    // Clamp: si el proximo pip cae fuera del rect de la capa, cortar el loop -- es error de
    // autoria pintar mas pips de los que caben. Silencioso; el editor debe advertir.
    if (px + sw > ly->x + ly->w) break;
    if (py + sh > ly->y + ly->h) break;
    blit_sprite_raw(px, py, s_gui_sprite_scratch, sw, sh);
  }
}

void paint_one_layer(GuiLayer* ly) {
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
  // Barras de progreso -- se pintan despues de rects (asi los rects pueden servir de marco
  // externo) y antes de labels (asi un label puede quedar encima como texto del valor).
  for (int i = 0; i < ly->progress_bar_count; ++i) {
    paint_progress_bar(ly, &ly->progress_bars[i]);
  }
  // Barras de pips -- mismo orden. Cada pip es un blit 1:1 del sprite full (o su swap por rango).
  for (int i = 0; i < ly->pip_bar_count; ++i) {
    paint_pip_bar(ly, &ly->pip_bars[i]);
  }
  // Iconos sprite -- blit 1:1 estatico (con posible flip). Van despues de pip bars asi el autor
  // puede superponer un icono sobre un bar (raro, pero coherente con el orden array).
  for (int i = 0; i < ly->sprite_count; ++i) {
    paint_sprite_icon(ly, &ly->sprites[i]);
  }
  // Etiquetas de texto. Usan turtle_scene_draw_text_absolute-like pero sin
  // proteccion de playfield -- ver turtle_font_draw_fb_raw. Antes de dibujar cada label
  // restauramos su rect previo (union con el nuevo) desde s_static_fb: sin esto, un label
  // sobre transparent_bg cuya cadena cambia (ej. contador de gears "x0"->"x1"->...) acumula
  // los pixeles de todas las cadenas anteriores porque nada limpia la region entre frames.
  for (int i = 0; i < ly->label_count; ++i) {
    GuiLabel& lbl = ly->labels[i];
    if (!s_bundle_json || s_bundle_json_len == 0) continue;
    if (!lbl.font_id[0]) continue;
    const int glyph_px =
        turtle_scene_font_glyph_px(s_bundle_json, s_bundle_json_len, lbl.font_id);
    if (glyph_px <= 0) continue;
    const int text_w = lbl.text[0]
                           ? turtle_scene_measure_text(s_bundle_json, s_bundle_json_len,
                                                       lbl.font_id, lbl.text)
                           : 0;
    const int cur_x = ly->x + lbl.x;
    const int cur_y = ly->y + lbl.y;
    const int cur_w = text_w;
    const int cur_h = text_w > 0 ? glyph_px : 0;
    // Union del rect previo (si hay) con el actual: cubre tanto el caso de cadena mas corta
    // (rect previo mayor -> hay que borrar el sobrante) como el de cadena mas larga (rect
    // actual mayor -> el sobrante nunca vio un restore).
    int ux0, uy0, ux1, uy1;
    bool have_union = false;
    if (lbl.has_prev_blit && lbl.prev_blit_w > 0 && lbl.prev_blit_h > 0) {
      ux0 = lbl.prev_blit_x;
      uy0 = lbl.prev_blit_y;
      ux1 = lbl.prev_blit_x + lbl.prev_blit_w - 1;
      uy1 = lbl.prev_blit_y + lbl.prev_blit_h - 1;
      have_union = true;
    }
    if (cur_w > 0 && cur_h > 0) {
      if (!have_union) {
        ux0 = cur_x;
        uy0 = cur_y;
        ux1 = cur_x + cur_w - 1;
        uy1 = cur_y + cur_h - 1;
        have_union = true;
      } else {
        if (cur_x < ux0) ux0 = cur_x;
        if (cur_y < uy0) uy0 = cur_y;
        if (cur_x + cur_w - 1 > ux1) ux1 = cur_x + cur_w - 1;
        if (cur_y + cur_h - 1 > uy1) uy1 = cur_y + cur_h - 1;
      }
    }
    if (have_union) {
      turtle_gpu_restore_static_rect_fb(ux0, uy0, ux1 - ux0 + 1, uy1 - uy0 + 1);
    }
    if (cur_w > 0 && cur_h > 0) {
      const int tint = (lbl.color_index >= 0) ? static_cast<int>(lbl.color_index) : -1;
      turtle_scene_draw_text_raw(s_bundle_json, s_bundle_json_len, lbl.font_id, cur_x, cur_y,
                                 lbl.text, tint);
      lbl.prev_blit_x = static_cast<int16_t>(cur_x);
      lbl.prev_blit_y = static_cast<int16_t>(cur_y);
      lbl.prev_blit_w = static_cast<int16_t>(cur_w);
      lbl.prev_blit_h = static_cast<int16_t>(cur_h);
      lbl.has_prev_blit = true;
    } else {
      // Texto vacio: ya restauramos el rect previo, no dejamos nada por borrar la proxima vez.
      lbl.has_prev_blit = false;
    }
  }
}

}  // namespace

void turtle_gui_layer_begin_scene(const char* bundle_json, size_t bundle_json_len) {
  s_layer_count = 0;
  s_bundle_json = bundle_json;
  s_bundle_json_len = bundle_json_len;
  reset_missing_sprite_cache();
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
  if (!ensure_layers_allocated()) {
    return;  // sin memoria: se ignora el catalogo silenciosamente
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
  reset_missing_sprite_cache();
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

namespace {
int find_progress_bar_index(const GuiLayer* ly, const char* bar_id) {
  if (!ly || !bar_id || !*bar_id) return -1;
  for (int i = 0; i < ly->progress_bar_count; ++i) {
    if (strcmp(ly->progress_bars[i].id, bar_id) == 0) return i;
  }
  return -1;
}
int find_pip_bar_index(const GuiLayer* ly, const char* bar_id) {
  if (!ly || !bar_id || !*bar_id) return -1;
  for (int i = 0; i < ly->pip_bar_count; ++i) {
    if (strcmp(ly->pip_bars[i].id, bar_id) == 0) return i;
  }
  return -1;
}
int find_sprite_icon_index(const GuiLayer* ly, const char* icon_id) {
  if (!ly || !icon_id || !*icon_id) return -1;
  for (int i = 0; i < ly->sprite_count; ++i) {
    if (strcmp(ly->sprites[i].id, icon_id) == 0) return i;
  }
  return -1;
}
}  // namespace

bool turtle_gui_layer_set_progress(const char* id, const char* bar_id, int value_num,
                                   bool has_max, int value_den) {
  const int idx = find_layer_index(id);
  if (idx < 0) return false;
  GuiLayer* ly = &s_layers[idx];
  const int bi = find_progress_bar_index(ly, bar_id);
  if (bi < 0) return false;
  GuiProgressBar& bar = ly->progress_bars[bi];
  if (has_max) {
    bar.value_den = static_cast<int16_t>(clamp_int(value_den, 1, 32767));
  }
  bar.value_num = static_cast<int16_t>(clamp_int(value_num, -32768, 32767));
  return true;
}

bool turtle_gui_layer_set_pips(const char* id, const char* bar_id, int value, bool has_max,
                               int max_value) {
  const int idx = find_layer_index(id);
  if (idx < 0) return false;
  GuiLayer* ly = &s_layers[idx];
  const int bi = find_pip_bar_index(ly, bar_id);
  if (bi < 0) return false;
  GuiPipBar& bar = ly->pip_bars[bi];
  if (has_max) {
    bar.max_value = static_cast<int16_t>(clamp_int(max_value, 1, kMaxPipCount));
  }
  bar.value = static_cast<int16_t>(clamp_int(value, 0, bar.max_value));
  return true;
}

bool turtle_gui_layer_set_sprite(const char* id, const char* icon_id, const char* sprite_id,
                                 bool has_frame, int frame_index) {
  const int idx = find_layer_index(id);
  if (idx < 0) return false;
  GuiLayer* ly = &s_layers[idx];
  const int ii = find_sprite_icon_index(ly, icon_id);
  if (ii < 0) return false;
  GuiSpriteIcon& icon = ly->sprites[ii];
  if (sprite_id && *sprite_id) {
    const size_t maxlen = sizeof icon.sprite_id - 1;
    strncpy(icon.sprite_id, sprite_id, maxlen);
    icon.sprite_id[maxlen] = '\0';
  }
  if (has_frame) {
    icon.frame_index = static_cast<uint8_t>(clamp_int(frame_index, 0, 255));
  }
  return true;
}
