#include "turtle_font.h"

#include "turtle_asset_bin.h"
#include "turtle_gpu.h"

#include <Arduino.h>
#include <stdlib.h>
#include <string.h>

#if defined(ESP32) || defined(ESP_PLATFORM)
#include <esp_heap_caps.h>
#endif

namespace {

constexpr uint8_t kMagicTfn[4] = {'T', 'F', 'N', 0};
constexpr size_t kTfnHeaderSize = 14;
constexpr int kMaxGlyphCount = 512;
constexpr int kMaxGlyphPx = 128;

// Debe coincidir exactamente (mismo orden) con LATIN_CHARSET en
// tools/turtlestudio/src/turtlestudio/fonts.py — el .tfn no guarda el charset,
// el indice de cada glifo es su posicion en esta cadena. Ver spec/asset-bin-v0.md.
constexpr char kCharset[] =
    " "
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789"
    ".,!?:;'-";

/** indice-en-kCharset por byte (-1 = fuera del charset v0), construido una sola vez en el
 * primer uso -- evita un strchr() sobre kCharset (~71 chars) por CADA caracter de CADA linea
 * de texto medida/dibujada (turtle_font_measure corre en cada frame para texto con overlay
 * activo). Ver turtle_font_charset_index. */
int8_t s_charset_lut[256];
bool s_charset_lut_ready = false;

void build_charset_lut() {
  for (int i = 0; i < 256; ++i) {
    s_charset_lut[i] = -1;
  }
  for (int i = 0; kCharset[i] != '\0'; ++i) {
    s_charset_lut[static_cast<unsigned char>(kCharset[i])] = static_cast<int8_t>(i);
  }
  s_charset_lut_ready = true;
}

static uint16_t read_u16_le(const uint8_t* p) {
  return static_cast<uint16_t>(p[0]) | (static_cast<uint16_t>(p[1]) << 8);
}

static uint32_t read_u32_le(const uint8_t* p) {
  return static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8) |
         (static_cast<uint32_t>(p[2]) << 16) | (static_cast<uint32_t>(p[3]) << 24);
}

static uint8_t* alloc_bytes(size_t nbytes, bool* in_psram) {
  *in_psram = false;
#if defined(ESP32) || defined(ESP_PLATFORM)
  if (heap_caps_get_free_size(MALLOC_CAP_SPIRAM) >= nbytes + 64) {
    uint8_t* p = static_cast<uint8_t*>(
        heap_caps_malloc(nbytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (p) {
      *in_psram = true;
      return p;
    }
  }
#endif
  return static_cast<uint8_t*>(malloc(nbytes));
}

static void free_bytes(uint8_t* p, bool in_psram) {
  if (!p) {
    return;
  }
#if defined(ESP32) || defined(ESP_PLATFORM)
  if (in_psram) {
    heap_caps_free(p);
    return;
  }
#endif
  free(p);
}

}  // namespace

bool turtle_font_load_tfn(const uint8_t* data, size_t len, TurtleFont* out) {
  if (!out || !data || len < kTfnHeaderSize) {
    return false;
  }
  out->glyph_px = 0;
  out->line_height = 0;
  out->baseline = 0;
  out->glyph_count = 0;
  out->pixels = nullptr;
  out->advances = nullptr;
  out->in_psram = false;

  if (memcmp(data, kMagicTfn, 4) != 0 || data[4] != 0) {
    return false;
  }

  const int px = static_cast<int>(read_u16_le(data + 6));
  const int lh = static_cast<int>(read_u16_le(data + 8));
  const int bl = static_cast<int>(read_u16_le(data + 10));
  const int count = static_cast<int>(read_u16_le(data + 12));
  if (px < 1 || px > kMaxGlyphPx || count < 0 || count > kMaxGlyphCount) {
    return false;
  }

  // Una sola reserva: advances (count bytes) seguido de pixels (count*px*px bytes),
  // para tener un unico puntero base / flag in_psram que liberar (igual espiritu que
  // el buffer plano unico de TurtleTileset).
  const size_t glyph_bytes = static_cast<size_t>(px) * static_cast<size_t>(px);
  const size_t pixel_total = static_cast<size_t>(count) * glyph_bytes;
  const size_t total = static_cast<size_t>(count) + pixel_total;
  bool in_psram = false;
  uint8_t* buf = alloc_bytes(total, &in_psram);
  if (!buf && total > 0) {
    Serial.printf("turtle_font: sin RAM para %u bytes (%d glifos)\n",
                  static_cast<unsigned>(total), count);
    return false;
  }
  uint8_t* advances = buf;
  uint8_t* pixels = buf + count;

  size_t off = kTfnHeaderSize;
  for (int i = 0; i < count; ++i) {
    if (off + 1 + 4 > len) {
      free_bytes(buf, in_psram);
      return false;
    }
    advances[i] = data[off];
    off += 1;
    const uint32_t chunk_len = read_u32_le(data + off);
    off += 4;
    if (chunk_len < 11 || off + chunk_len > len) {
      free_bytes(buf, in_psram);
      return false;
    }
    if (!turtle_asset_bin_decode_indexed(data + off, chunk_len, px, px,
                                         pixels + static_cast<size_t>(i) * glyph_bytes, px)) {
      free_bytes(buf, in_psram);
      return false;
    }
    off += chunk_len;
  }

  out->glyph_px = static_cast<uint16_t>(px);
  out->line_height = static_cast<uint16_t>(lh);
  out->baseline = static_cast<uint16_t>(bl);
  out->glyph_count = static_cast<uint16_t>(count);
  out->pixels = pixels;
  out->advances = advances;
  out->in_psram = in_psram;

  Serial.printf("turtle_font: %d glifos %dx%d lh=%d bl=%d (%u bytes)\n", count, px, px, lh, bl,
                static_cast<unsigned>(total));
  return true;
}

void turtle_font_free(TurtleFont* f) {
  if (!f) {
    return;
  }
  // advances es la base de la reserva unica (pixels apunta dentro del mismo bloque).
  free_bytes(f->advances, f->in_psram);
  f->pixels = nullptr;
  f->advances = nullptr;
  f->glyph_count = 0;
  f->in_psram = false;
}

const uint8_t* turtle_font_glyph_pixels(const TurtleFont* f, int glyph_index) {
  if (!f || !f->pixels || glyph_index < 0 || glyph_index >= f->glyph_count) {
    return nullptr;
  }
  const size_t glyph_bytes = static_cast<size_t>(f->glyph_px) * static_cast<size_t>(f->glyph_px);
  return f->pixels + static_cast<size_t>(glyph_index) * glyph_bytes;
}

uint8_t turtle_font_glyph_advance(const TurtleFont* f, int glyph_index) {
  if (!f || !f->advances || glyph_index < 0 || glyph_index >= f->glyph_count) {
    return 0;
  }
  return f->advances[glyph_index];
}

int turtle_font_charset_index(char ch) {
  if (ch == '\0') {
    return -1;
  }
  if (!s_charset_lut_ready) {
    build_charset_lut();
  }
  return s_charset_lut[static_cast<unsigned char>(ch)];
}

int turtle_font_measure(const TurtleFont* f, const char* str) {
  if (!f || !str) {
    return 0;
  }
  int total = 0;
  for (const char* p = str; *p; ++p) {
    const int idx = turtle_font_charset_index(*p);
    // Caracter fuera del charset v0: avanza como glifo en blanco en vez de cortar la medida.
    total += (idx >= 0) ? turtle_font_glyph_advance(f, idx) : f->glyph_px;
  }
  return total;
}

int turtle_font_draw_scene(const TurtleFont* f, int sx, int sy, const char* str,
                           uint8_t transparent_index) {
  if (!f || !str) {
    return 0;
  }
  int x = sx;
  for (const char* p = str; *p; ++p) {
    const int idx = turtle_font_charset_index(*p);
    if (idx < 0) {
      x += f->glyph_px;
      continue;
    }
    const uint8_t* pixels = turtle_font_glyph_pixels(f, idx);
    if (pixels) {
      turtle_gpu_blit_indexed_scene(x, sy, f->glyph_px, f->glyph_px, pixels, f->glyph_px,
                                    transparent_index);
    }
    x += turtle_font_glyph_advance(f, idx);
  }
  return x - sx;
}

int turtle_font_draw_fb_raw(const TurtleFont* f, int xfb, int yfb_top, const char* str,
                            uint8_t transparent_index, int tint_color_index) {
  if (!f || !str) {
    return 0;
  }
  const int glyph_px = f->glyph_px;
  int x = xfb;
  for (const char* p = str; *p; ++p) {
    const int idx = turtle_font_charset_index(*p);
    if (idx < 0) {
      x += glyph_px;
      continue;
    }
    const uint8_t* pixels = turtle_font_glyph_pixels(f, idx);
    if (pixels) {
      for (int py = 0; py < glyph_px; ++py) {
        const uint8_t* row = pixels + static_cast<size_t>(py) * static_cast<size_t>(glyph_px);
        for (int px = 0; px < glyph_px; ++px) {
          const uint8_t ci = row[px];
          if (ci == transparent_index) {
            continue;
          }
          const int fb_x = x + px;
          const int fb_y = yfb_top + py;
          const uint8_t out_ci =
              (tint_color_index >= 0) ? static_cast<uint8_t>(tint_color_index) : ci;
          turtle_gpu_pixel_raw(fb_x, fb_y, out_ci);
        }
      }
    }
    x += turtle_font_glyph_advance(f, idx);
  }
  return x - xfb;
}

int turtle_font_draw_fb_absolute(const TurtleFont* f, int xfb, int yfb_top, const char* str,
                                 uint8_t transparent_index, int tint_color_index) {
  if (!f || !str) {
    return 0;
  }
  const int glyph_px = f->glyph_px;
  int x = xfb;
  for (const char* p = str; *p; ++p) {
    const int idx = turtle_font_charset_index(*p);
    if (idx < 0) {
      x += glyph_px;
      continue;
    }
    const uint8_t* pixels = turtle_font_glyph_pixels(f, idx);
    if (pixels) {
      for (int py = 0; py < glyph_px; ++py) {
        const uint8_t* row = pixels + static_cast<size_t>(py) * static_cast<size_t>(glyph_px);
        for (int px = 0; px < glyph_px; ++px) {
          const uint8_t ci = row[px];
          if (ci == transparent_index) {
            continue;
          }
          const int fb_x = x + px;
          const int fb_y = yfb_top + py;
          const uint8_t out_ci =
              (tint_color_index >= 0) ? static_cast<uint8_t>(tint_color_index) : ci;
          turtle_gpu_pixel_absolute(fb_x, fb_y, out_ci);
        }
      }
    }
    x += turtle_font_glyph_advance(f, idx);
  }
  return x - xfb;
}

int turtle_font_draw_scene_tint(const TurtleFont* f, int sx, int sy, const char* str,
                                uint8_t transparent_index, uint8_t tint_color_index) {
  if (!f || !str) {
    return 0;
  }
  int x = sx;
  for (const char* p = str; *p; ++p) {
    const int idx = turtle_font_charset_index(*p);
    if (idx < 0) {
      x += f->glyph_px;
      continue;
    }
    const uint8_t* pixels = turtle_font_glyph_pixels(f, idx);
    if (pixels) {
      turtle_gpu_blit_indexed_scene_tint(x, sy, f->glyph_px, f->glyph_px, pixels, f->glyph_px,
                                         transparent_index, tint_color_index);
    }
    x += turtle_font_glyph_advance(f, idx);
  }
  return x - sx;
}
