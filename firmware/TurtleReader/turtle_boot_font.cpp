#include "turtle_boot_font.h"

#include <string.h>

#include "turtle_gpu.h"

namespace {

constexpr int kGlyphW = 3;
constexpr int kGlyphH = 5;
constexpr int kGapPx = 1;      // separacion horizontal entre glifos, sin escalar
constexpr int kLineGapPx = 1;  // separacion vertical entre lineas, sin escalar

// Cada glifo: 5 filas (arriba->abajo), bits 2..0 de cada byte = columnas izq->der.
struct Glyph {
  char ch;
  uint8_t rows[kGlyphH];
};

const Glyph kGlyphs[] = {
    {' ', {0b000, 0b000, 0b000, 0b000, 0b000}},

    {'0', {0b111, 0b101, 0b101, 0b101, 0b111}},
    {'1', {0b010, 0b110, 0b010, 0b010, 0b111}},
    {'2', {0b111, 0b001, 0b111, 0b100, 0b111}},
    {'3', {0b111, 0b001, 0b111, 0b001, 0b111}},
    {'4', {0b101, 0b101, 0b111, 0b001, 0b001}},
    {'5', {0b111, 0b100, 0b111, 0b001, 0b111}},
    {'6', {0b111, 0b100, 0b111, 0b101, 0b111}},
    {'7', {0b111, 0b001, 0b010, 0b010, 0b010}},
    {'8', {0b111, 0b101, 0b111, 0b101, 0b111}},
    {'9', {0b111, 0b101, 0b111, 0b001, 0b111}},

    {'A', {0b010, 0b101, 0b111, 0b101, 0b101}},
    {'B', {0b110, 0b101, 0b110, 0b101, 0b110}},
    {'C', {0b011, 0b100, 0b100, 0b100, 0b011}},
    {'D', {0b110, 0b101, 0b101, 0b101, 0b110}},
    {'E', {0b111, 0b100, 0b111, 0b100, 0b111}},
    {'F', {0b111, 0b100, 0b111, 0b100, 0b100}},
    {'G', {0b011, 0b100, 0b101, 0b101, 0b011}},
    {'H', {0b101, 0b101, 0b111, 0b101, 0b101}},
    {'I', {0b111, 0b010, 0b010, 0b010, 0b111}},
    {'J', {0b001, 0b001, 0b001, 0b101, 0b010}},
    {'K', {0b101, 0b110, 0b100, 0b110, 0b101}},
    {'L', {0b100, 0b100, 0b100, 0b100, 0b111}},
    {'M', {0b101, 0b111, 0b111, 0b101, 0b101}},
    {'N', {0b101, 0b111, 0b111, 0b111, 0b101}},
    {'O', {0b010, 0b101, 0b101, 0b101, 0b010}},
    {'P', {0b110, 0b101, 0b110, 0b100, 0b100}},
    {'Q', {0b010, 0b101, 0b101, 0b111, 0b011}},
    {'R', {0b110, 0b101, 0b110, 0b110, 0b101}},
    {'S', {0b011, 0b100, 0b010, 0b001, 0b110}},
    {'T', {0b111, 0b010, 0b010, 0b010, 0b010}},
    {'U', {0b101, 0b101, 0b101, 0b101, 0b111}},
    {'V', {0b101, 0b101, 0b101, 0b101, 0b010}},
    {'W', {0b101, 0b101, 0b111, 0b111, 0b101}},
    {'X', {0b101, 0b101, 0b010, 0b101, 0b101}},
    {'Y', {0b101, 0b101, 0b010, 0b010, 0b010}},
    {'Z', {0b111, 0b001, 0b010, 0b100, 0b111}},

    {'.', {0b000, 0b000, 0b000, 0b000, 0b010}},
    {',', {0b000, 0b000, 0b000, 0b010, 0b100}},
    {':', {0b000, 0b010, 0b000, 0b010, 0b000}},
    {'!', {0b010, 0b010, 0b010, 0b000, 0b010}},
    {'\'', {0b010, 0b010, 0b000, 0b000, 0b000}},
    {'-', {0b000, 0b000, 0b111, 0b000, 0b000}},
};
constexpr int kGlyphCount = sizeof(kGlyphs) / sizeof(kGlyphs[0]);

const uint8_t* find_glyph_rows(char ch) {
  for (int i = 0; i < kGlyphCount; i++) {
    if (kGlyphs[i].ch == ch) {
      return kGlyphs[i].rows;
    }
  }
  return nullptr;  // fuera del charset: se omite, pero igual avanza el ancho de un glifo
}

int line_width_px(int char_count, int scale) {
  if (char_count <= 0) {
    return 0;
  }
  const int advance = (kGlyphW + kGapPx) * scale;
  return char_count * advance - kGapPx * scale;
}

}  // namespace

void turtle_boot_text_draw_centered(int center_x, int center_y, const char* text,
                                    uint8_t color_index, int scale) {
  if (!text || scale <= 0) {
    return;
  }

  int line_count = 1;
  for (const char* p = text; *p; p++) {
    if (*p == '\n') {
      line_count++;
    }
  }

  const int line_pitch = (kGlyphH + kLineGapPx) * scale;
  const int block_h = line_count * line_pitch - kLineGapPx * scale;
  // y = esquina inferior-izquierda de los glifos de la linea actual (coords escena, Y arriba).
  int y = center_y + block_h / 2 - kGlyphH * scale;

  const char* line_start = text;
  for (;;) {
    const char* line_end = strchr(line_start, '\n');
    const int len = line_end ? static_cast<int>(line_end - line_start)
                             : static_cast<int>(strlen(line_start));

    int x = center_x - line_width_px(len, scale) / 2;
    for (int i = 0; i < len; i++) {
      const uint8_t* rows = find_glyph_rows(line_start[i]);
      if (rows) {
        for (int row = 0; row < kGlyphH; row++) {
          const uint8_t bits = rows[row];
          const int py = y + (kGlyphH - 1 - row) * scale;
          for (int col = 0; col < kGlyphW; col++) {
            if (bits & (1 << (kGlyphW - 1 - col))) {
              turtle_gpu_fill_rect_scene(x + col * scale, py, scale, scale, color_index);
            }
          }
        }
      }
      x += (kGlyphW + kGapPx) * scale;
    }

    y -= line_pitch;
    if (!line_end) {
      break;
    }
    line_start = line_end + 1;
  }
}
