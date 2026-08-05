// Phase 1 verification: decode a .tfn fixture with the REAL firmware decoder
// (turtle_font.cpp / turtle_asset_bin.cpp, unmodified) and print it in the same
// text format gen_font_fixture.py prints from decode_font_blob(), so the two can
// be diffed byte-for-byte. Not part of the Arduino sketch build. See README.md.

#include "../TurtleReader/turtle_font.h"

#include <cstdio>
#include <cstdlib>
#include <vector>

// turtle_font_draw_scene() (Phase 2) calls turtle_gpu_blit_indexed_scene(), which lives in
// turtle_gpu.cpp — a much heavier file (SPI/display driver) not worth linking into this
// lightweight harness. Provide a fake here that just records calls, so draw_scene's glyph
// positioning/advance logic can still be exercised without the real GPU subsystem.
namespace {
int g_blit_count = 0;
int g_blit_min_x0 = 0;
int g_blit_max_x1 = 0;
}  // namespace

void turtle_gpu_blit_indexed_scene(int x0, int y0, int w, int h, const uint8_t* rows_top_first,
                                   int row_stride, uint8_t transparent_index) {
  (void)y0;
  (void)h;
  (void)rows_top_first;
  (void)row_stride;
  (void)transparent_index;
  if (g_blit_count == 0 || x0 < g_blit_min_x0) {
    g_blit_min_x0 = x0;
  }
  if (g_blit_count == 0 || x0 + w > g_blit_max_x1) {
    g_blit_max_x1 = x0 + w;
  }
  ++g_blit_count;
}

// turtle_font_draw_scene_tint() (Phase 4) paints pixel-by-pixel via turtle_gpu_fill_rect_scene()
// (no tinted blit primitive exists in turtle_gpu). Fake it too: record call count, whether every
// call used the same requested color, and the x-range covered.
namespace {
int g_fill_count = 0;
bool g_fill_all_same_color = true;
uint8_t g_fill_first_color = 0;
int g_fill_min_x = 0;
int g_fill_max_x1 = 0;
}  // namespace

void turtle_gpu_fill_rect_scene(int x0, int y0, int w, int h, uint8_t color_index) {
  (void)y0;
  (void)h;
  if (g_fill_count == 0) {
    g_fill_first_color = color_index;
  } else if (color_index != g_fill_first_color) {
    g_fill_all_same_color = false;
  }
  if (g_fill_count == 0 || x0 < g_fill_min_x) {
    g_fill_min_x = x0;
  }
  if (g_fill_count == 0 || x0 + w > g_fill_max_x1) {
    g_fill_max_x1 = x0 + w;
  }
  ++g_fill_count;
}

static bool read_file(const char* path, std::vector<uint8_t>* out) {
  FILE* f = fopen(path, "rb");
  if (!f) {
    return false;
  }
  fseek(f, 0, SEEK_END);
  const long n = ftell(f);
  fseek(f, 0, SEEK_SET);
  if (n < 0) {
    fclose(f);
    return false;
  }
  out->resize(static_cast<size_t>(n));
  const size_t got = out->empty() ? 0 : fread(out->data(), 1, out->size(), f);
  fclose(f);
  return got == out->size();
}

int main(int argc, char** argv) {
  if (argc != 2) {
    fprintf(stderr, "uso: test_turtle_font <fixture.tfn>\n");
    return 2;
  }

  std::vector<uint8_t> blob;
  if (!read_file(argv[1], &blob)) {
    fprintf(stderr, "no se pudo leer %s\n", argv[1]);
    return 1;
  }

  TurtleFont font{};
  if (!turtle_font_load_tfn(blob.data(), blob.size(), &font)) {
    fprintf(stderr, "turtle_font_load_tfn fallo\n");
    return 1;
  }

  printf("HEADER px=%d lh=%d bl=%d count=%d\n", font.glyph_px, font.line_height, font.baseline,
         font.glyph_count);

  bool ok = true;
  for (int i = 0; i < font.glyph_count; ++i) {
    const uint8_t adv = turtle_font_glyph_advance(&font, i);
    const uint8_t* px = turtle_font_glyph_pixels(&font, i);
    if (!px) {
      fprintf(stderr, "glyph %d: turtle_font_glyph_pixels devolvio null\n", i);
      ok = false;
      break;
    }
    printf("GLYPH %d adv=%d px=", i, adv);
    const int n = font.glyph_px * font.glyph_px;
    for (int j = 0; j < n; ++j) {
      printf(j + 1 < n ? "%d," : "%d", px[j]);
    }
    printf("\n");
  }

  // Sanity check on the charset lookup table independent of any fixture, since it
  // has no representation in the .tfn itself (see turtle_font.h's doc comment).
  const struct { char ch; int expect; } charset_checks[] = {
      {' ', 0}, {'A', 1}, {'Z', 26}, {'a', 27}, {'z', 52}, {'0', 53}, {'9', 62},
      {'-', 70}, {(char)1, -1},
  };
  for (const auto& c : charset_checks) {
    const int got = turtle_font_charset_index(c.ch);
    if (got != c.expect) {
      fprintf(stderr, "turtle_font_charset_index('%c'=%d) = %d, esperado %d\n", c.ch, (int)c.ch,
              got, c.expect);
      ok = false;
    }
  }

  // Phase 2: turtle_font_measure/turtle_font_draw_scene must agree on width, and
  // out-of-charset characters must advance without blitting (see turtle_font.cpp).
  {
    const char* s1 = "AB ";  // all in-charset, incl. space (a real glyph, index 0)
    const int measured = turtle_font_measure(&font, s1);
    g_blit_count = 0;
    const int drawn_w = turtle_font_draw_scene(&font, 10, 20, s1, 31);
    if (drawn_w != measured) {
      fprintf(stderr, "\"%s\": draw_scene width %d != measure %d\n", s1, drawn_w, measured);
      ok = false;
    }
    if (g_blit_count != 3) {
      fprintf(stderr, "\"%s\": esperaba 3 blits (A,B,espacio), hubo %d\n", s1, g_blit_count);
      ok = false;
    }
    if (g_blit_min_x0 != 10 || g_blit_max_x1 != 10 + drawn_w) {
      fprintf(stderr, "\"%s\": rango de blits [%d,%d) no coincide con sx=10 ancho=%d\n", s1,
              g_blit_min_x0, g_blit_max_x1, drawn_w);
      ok = false;
    }

    const char* s2 = "A\tB";  // '\t' no esta en el charset v0: avanza, no se blittea
    const int measured2 = turtle_font_measure(&font, s2);
    g_blit_count = 0;
    const int drawn_w2 = turtle_font_draw_scene(&font, 0, 0, s2, 31);
    if (drawn_w2 != measured2) {
      fprintf(stderr, "\"A\\tB\": draw_scene width %d != measure %d\n", drawn_w2, measured2);
      ok = false;
    }
    if (g_blit_count != 2) {
      fprintf(stderr, "\"A\\tB\": esperaba 2 blits (A,B; tab fuera de charset), hubo %d\n",
              g_blit_count);
      ok = false;
    }
    const int expect_w2 = turtle_font_glyph_advance(&font, turtle_font_charset_index('A')) +
                          font.glyph_px +  // '\t' fuera de charset: avanza glyph_px
                          turtle_font_glyph_advance(&font, turtle_font_charset_index('B'));
    if (measured2 != expect_w2) {
      fprintf(stderr, "\"A\\tB\": measure %d != esperado %d\n", measured2, expect_w2);
      ok = false;
    }
  }

  // Phase 4: turtle_font_draw_scene_tint must draw the same width as the untinted
  // version, paint every non-transparent pixel with exactly the requested color, and
  // paint exactly as many pixels as there are non-transparent pixels in the glyphs drawn.
  {
    const char* s = "AB";
    const uint8_t transparent_index = 31;
    const uint8_t tint = 7;

    int expect_pixels = 0;
    for (const char* p = s; *p; ++p) {
      const int idx = turtle_font_charset_index(*p);
      if (idx < 0) {
        continue;
      }
      const uint8_t* px = turtle_font_glyph_pixels(&font, idx);
      const int n = font.glyph_px * font.glyph_px;
      for (int j = 0; j < n; ++j) {
        if (px[j] != transparent_index) {
          ++expect_pixels;
        }
      }
    }

    const int measured = turtle_font_measure(&font, s);
    g_fill_count = 0;
    g_fill_all_same_color = true;
    const int tinted_w =
        turtle_font_draw_scene_tint(&font, 5, 5, s, transparent_index, tint);
    if (tinted_w != measured) {
      fprintf(stderr, "tint \"%s\": width %d != measure %d\n", s, tinted_w, measured);
      ok = false;
    }
    if (g_fill_count != expect_pixels) {
      fprintf(stderr, "tint \"%s\": %d pixeles pintados, esperaba %d (no transparentes)\n", s,
              g_fill_count, expect_pixels);
      ok = false;
    }
    if (!g_fill_all_same_color || g_fill_first_color != tint) {
      fprintf(stderr, "tint \"%s\": no todos los pixeles usaron el color de tinte %d\n", s, tint);
      ok = false;
    }
    if (g_fill_count > 0 && (g_fill_min_x < 5 || g_fill_max_x1 > 5 + tinted_w)) {
      fprintf(stderr, "tint \"%s\": rango x [%d,%d) fuera de [5,%d)\n", s, g_fill_min_x,
              g_fill_max_x1, 5 + tinted_w);
      ok = false;
    }
  }

  turtle_font_free(&font);
  return ok ? 0 : 1;
}
