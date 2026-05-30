#include "turtle_gpu.h"

#include <Arduino.h>
#include <ctype.h>
#include <stdlib.h>
#include <string.h>

#if defined(ESP32) && TURTLE_USE_DISPLAY
#include <esp_heap_caps.h>
#endif

extern "C" {
#include <lua.h>
#include <lauxlib.h>
}

static constexpr int kW = 264;
static constexpr int kH = 198;
static constexpr int kNColors = 32;

static uint8_t s_fb[kW * kH];
static uint8_t s_static_fb[kW * kH];
static bool s_has_static = false;
static uint16_t s_palette[kNColors];

static bool s_dirty_valid = false;
static bool s_force_full_flip = true;
static int s_dirty_x0 = 0;
static int s_dirty_y0 = 0;
static int s_dirty_x1 = 0;
static int s_dirty_y1 = 0;

static void dirty_mark_fb_clamped(int x0, int y0, int x1, int y1) {
  if (x0 < 0) {
    x0 = 0;
  }
  if (y0 < 0) {
    y0 = 0;
  }
  if (x1 >= kW) {
    x1 = kW - 1;
  }
  if (y1 >= kH) {
    y1 = kH - 1;
  }
  if (x0 > x1 || y0 > y1) {
    return;
  }
  if (!s_dirty_valid) {
    s_dirty_x0 = x0;
    s_dirty_y0 = y0;
    s_dirty_x1 = x1;
    s_dirty_y1 = y1;
    s_dirty_valid = true;
    return;
  }
  if (x0 < s_dirty_x0) {
    s_dirty_x0 = x0;
  }
  if (y0 < s_dirty_y0) {
    s_dirty_y0 = y0;
  }
  if (x1 > s_dirty_x1) {
    s_dirty_x1 = x1;
  }
  if (y1 > s_dirty_y1) {
    s_dirty_y1 = y1;
  }
}

static constexpr uint16_t rgb565(uint8_t r, uint8_t g, uint8_t b) {
  return (uint16_t)(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
}

/* Paleta por defecto (Genesis-like) si el cartucho no trae PALETTE:. */
static const uint16_t k_default_palette[kNColors] = {
    rgb565(0, 0, 0),       rgb565(36, 36, 36),    rgb565(73, 73, 73),
    rgb565(109, 109, 109), rgb565(146, 146, 182), rgb565(182, 182, 219),
    rgb565(219, 219, 255), rgb565(255, 255, 255), rgb565(36, 0, 73),
    rgb565(73, 36, 109),   rgb565(109, 0, 146),   rgb565(0, 0, 109),
    rgb565(0, 36, 182),    rgb565(36, 109, 219),  rgb565(109, 182, 255),
    rgb565(0, 73, 36),     rgb565(0, 146, 73),    rgb565(73, 219, 109),
    rgb565(109, 255, 182), rgb565(73, 36, 0),      rgb565(146, 73, 36),
    rgb565(219, 109, 73),  rgb565(219, 146, 109), rgb565(255, 182, 146),
    rgb565(255, 219, 182), rgb565(109, 0, 0),     rgb565(182, 36, 36),
    rgb565(255, 73, 73),   rgb565(255, 146, 0),   rgb565(255, 219, 36),
    rgb565(255, 219, 219), rgb565(182, 146, 0),
};

void turtle_gpu_palette_reset_default(void) {
  memcpy(s_palette, k_default_palette, sizeof(s_palette));
}

static bool parse_hex_rgb_line(const char* line, size_t len, uint8_t* r, uint8_t* g,
                               uint8_t* b) {
  size_t i = 0;
  while (i < len && (line[i] == ' ' || line[i] == '\t')) {
    i++;
  }
  size_t end = len;
  while (end > i && (line[end - 1] == ' ' || line[end - 1] == '\t' || line[end - 1] == '\r')) {
    end--;
  }
  if (i >= end) {
    return false;
  }
  if (line[i] == '#') {
    i++;
  }
  size_t hexlen = end - i;
  char buf[7];
  if (hexlen == 3) {
    if (!isxdigit(static_cast<unsigned char>(line[i])) ||
        !isxdigit(static_cast<unsigned char>(line[i + 1])) ||
        !isxdigit(static_cast<unsigned char>(line[i + 2]))) {
      return false;
    }
    buf[0] = buf[1] = static_cast<char>(toupper(static_cast<unsigned char>(line[i])));
    buf[2] = buf[3] = static_cast<char>(toupper(static_cast<unsigned char>(line[i + 1])));
    buf[4] = buf[5] = static_cast<char>(toupper(static_cast<unsigned char>(line[i + 2])));
    buf[6] = '\0';
  } else if (hexlen == 6) {
    memcpy(buf, line + i, 6);
    buf[6] = '\0';
    for (int k = 0; k < 6; k++) {
      if (!isxdigit(static_cast<unsigned char>(buf[k]))) {
        return false;
      }
    }
  } else {
    return false;
  }

  char* p_end = nullptr;
  unsigned long v = strtoul(buf, &p_end, 16);
  if (p_end != buf + 6) {
    return false;
  }
  *r = static_cast<uint8_t>((v >> 16) & 0xFFu);
  *g = static_cast<uint8_t>((v >> 8) & 0xFFu);
  *b = static_cast<uint8_t>(v & 0xFFu);
  return true;
}

int turtle_gpu_palette_from_hex_text(const char* text, size_t text_len) {
  size_t pos = 0;
  int slot = 0;

  while (pos < text_len) {
    size_t nl = pos;
    while (nl < text_len && text[nl] != '\n') {
      nl++;
    }
    uint8_t r = 0, g = 0, b = 0;
    if (parse_hex_rgb_line(text + pos, nl - pos, &r, &g, &b)) {
      if (slot < kNColors) {
        s_palette[slot] = rgb565(r, g, b);
        slot++;
      }
    }
    pos = nl + 1;
  }

  const int n_user = slot;
  if (n_user == 0) {
    return 0;
  }
  while (slot < kNColors) {
    s_palette[slot++] = rgb565(0, 0, 0);
  }
  return n_user;
}

#if TURTLE_USE_DISPLAY
#define LGFX_USE_V1
#include <LovyanGFX.hpp>

class TurtleDisplay : public lgfx::LGFX_Device {
  lgfx::Panel_ILI9488 _panel_instance;
  lgfx::Bus_SPI _bus_instance;

 public:
  TurtleDisplay(void) {
    {
      auto cfg = _bus_instance.config();
      cfg.spi_host = TURTLE_DISP_SPI_HOST;
      cfg.spi_mode = 0;
      cfg.freq_write = 40000000;
      cfg.freq_read = 16000000;
      cfg.spi_3wire = false;
      cfg.use_lock = true;
      cfg.dma_channel = SPI_DMA_CH_AUTO;
      cfg.pin_sclk = TURTLE_DISP_PIN_SCK;
      cfg.pin_miso = TURTLE_DISP_PIN_MISO;
      cfg.pin_mosi = TURTLE_DISP_PIN_MOSI;
      cfg.pin_dc = TURTLE_DISP_PIN_DC;
      _bus_instance.config(cfg);
      _panel_instance.setBus(&_bus_instance);
    }
    {
      auto cfg = _panel_instance.config();
      cfg.pin_cs = TURTLE_DISP_PIN_CS;
      cfg.pin_rst = TURTLE_DISP_PIN_RST;
      cfg.pin_busy = -1;
      cfg.memory_width = 240;
      cfg.memory_height = 320;
      cfg.panel_width = 240;
      cfg.panel_height = 320;
      cfg.offset_x = 0;
      cfg.offset_y = 0;
      cfg.offset_rotation = 0;
      cfg.readable = false;
      cfg.invert = (TURTLE_PANEL_INVERT != 0);
      cfg.rgb_order = TURTLE_ILI9488_RGB_ORDER;
      cfg.dlen_16bit = false;
      cfg.bus_shared = false;
      _panel_instance.config(cfg);
    }
    setPanel(&_panel_instance);
  }
};

static TurtleDisplay s_display;
static bool s_display_ok = false;
#if TURTLE_USE_DISPLAY
static uint16_t* s_panel_rgb = nullptr;
static size_t s_panel_rgb_cap = 0;
#endif

static void turtle_display_begin(void) {
  s_display.init();
  s_display.setRotation(TURTLE_PANEL_ROTATION);
#if TURTLE_LGFX_SWAP565_BYTES
  s_display.setSwapBytes(true);
#endif
  s_display.fillScreen(0x0000u);
  s_display_ok = true;
}

static bool ensure_panel_rgb_buffer(size_t need_pixels) {
  if (s_panel_rgb && s_panel_rgb_cap >= need_pixels) {
    return true;
  }
  if (s_panel_rgb) {
    free(s_panel_rgb);
    s_panel_rgb = nullptr;
    s_panel_rgb_cap = 0;
  }
#if defined(ESP32)
  s_panel_rgb = static_cast<uint16_t*>(
      heap_caps_malloc(need_pixels * sizeof(uint16_t), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (!s_panel_rgb) {
    s_panel_rgb = static_cast<uint16_t*>(
        heap_caps_malloc(need_pixels * sizeof(uint16_t), MALLOC_CAP_8BIT));
  }
#else
  s_panel_rgb = static_cast<uint16_t*>(malloc(need_pixels * sizeof(uint16_t)));
#endif
  if (!s_panel_rgb) {
    return false;
  }
  s_panel_rgb_cap = need_pixels;
  return true;
}

static void turtle_fb_flush_full_to_display(void) {
  if (!s_display_ok) {
    return;
  }

  // Resolucion logica 264x198, panel visible 320x240 (rotado).
  const int panelW = s_display.width();
  const int panelH = s_display.height();
  if (panelW <= 0 || panelH <= 0) {
    return;
  }

  const size_t need = static_cast<size_t>(panelW) * static_cast<size_t>(panelH);
  if (!ensure_panel_rgb_buffer(need)) {
    uint16_t line[480];
    for (int py = 0; py < panelH; py++) {
      const int ly = (py * kH) / panelH;
      const uint8_t* row = &s_fb[ly * kW];
      for (int px = 0; px < panelW; px++) {
        const int lx = (px * kW) / panelW;
        line[px] = s_palette[row[lx]];
      }
      s_display.pushImage(0, py, panelW, 1, line);
    }
    return;
  }

  for (int py = 0; py < panelH; py++) {
    const int ly = (py * kH) / panelH;
    const uint8_t* row = &s_fb[ly * kW];
    uint16_t* dst = &s_panel_rgb[static_cast<size_t>(py) * static_cast<size_t>(panelW)];
    for (int px = 0; px < panelW; px++) {
      const int lx = (px * kW) / panelW;
      dst[px] = s_palette[row[lx]];
    }
  }

  s_display.startWrite();
  s_display.pushImage(0, 0, panelW, panelH, s_panel_rgb);
  s_display.endWrite();
}

static void turtle_fb_flush_dirty_to_display(void) {
  if (!s_display_ok || !s_dirty_valid) {
    return;
  }

  const int panelW = s_display.width();
  const int panelH = s_display.height();
  if (panelW <= 0 || panelH <= 0) {
    return;
  }

  const int xfb0 = s_dirty_x0;
  const int yfb0 = s_dirty_y0;
  const int xfb1 = s_dirty_x1;
  const int yfb1 = s_dirty_y1;

  int py0 = (yfb0 * panelH) / kH;
  int py1 = ((yfb1 + 1) * panelH - 1) / kH;
  if (py0 < 0) {
    py0 = 0;
  }
  if (py1 >= panelH) {
    py1 = panelH - 1;
  }

  uint16_t line[480];

  s_display.startWrite();
  for (int py = py0; py <= py1; ++py) {
    const int ly = (py * kH) / panelH;
    if (ly < yfb0 || ly > yfb1) {
      continue;
    }
    const uint8_t* row = &s_fb[ly * kW];

    int px0 = (xfb0 * panelW) / kW;
    int px1 = ((xfb1 + 1) * panelW - 1) / kW;
    if (px0 < 0) {
      px0 = 0;
    }
    if (px1 >= panelW) {
      px1 = panelW - 1;
    }
    const int pw = px1 - px0 + 1;
    if (pw <= 0 || pw > static_cast<int>(sizeof(line) / sizeof(line[0]))) {
      continue;
    }

    for (int i = 0; i < pw; ++i) {
      const int px = px0 + i;
      const int lx = (px * kW) / panelW;
      line[i] = s_palette[row[lx]];
    }
    s_display.pushImage(px0, py, pw, 1, line);
  }
  s_display.endWrite();
}

static void turtle_fb_flush_to_display(void) {
  if (s_force_full_flip || !s_dirty_valid) {
    turtle_fb_flush_full_to_display();
    s_force_full_flip = false;
    s_dirty_valid = false;
    return;
  }
  turtle_fb_flush_dirty_to_display();
  s_dirty_valid = false;
}

#else

static void turtle_display_begin(void) {}
static void turtle_fb_flush_to_display(void) {}

#endif

static uint8_t lua_color_index(lua_State* L, int arg) {
  const lua_Integer c = luaL_checkinteger(L, arg);
  if (c < 0) {
    return 0;
  }
  if (c >= kNColors) {
    return static_cast<uint8_t>(kNColors - 1);
  }
  return static_cast<uint8_t>(c);
}

static void plot_fb(int xfb, int yfb, uint8_t ci) {
  if (xfb < 0 || xfb >= kW || yfb < 0 || yfb >= kH) {
    return;
  }
  s_fb[yfb * kW + xfb] = ci;
}

static uint8_t clamp_color_index(uint8_t ci) {
  if (ci >= kNColors) {
    return static_cast<uint8_t>(kNColors - 1);
  }
  return ci;
}

void turtle_gpu_cls(uint8_t color_index) {
  memset(s_fb, clamp_color_index(color_index), sizeof(s_fb));
  turtle_gpu_request_full_flip();
}

void turtle_gpu_fill_rect_scene(int x0, int y0, int w, int h, uint8_t color_index) {
  if (w <= 0 || h <= 0) {
    return;
  }
  const uint8_t ci = clamp_color_index(color_index);
  for (int sy = y0; sy < y0 + h; ++sy) {
    const int yfb = (kH - 1) - sy;
    if (yfb < 0 || yfb >= kH) {
      continue;
    }
    for (int sx = x0; sx < x0 + w; ++sx) {
      plot_fb(sx, yfb, ci);
    }
  }
}

void turtle_gpu_blit_indexed_scene(int x0, int y0, int w, int h,
                                   const uint8_t* rows_top_first, int row_stride,
                                   uint8_t transparent_index) {
  if (w <= 0 || h <= 0 || !rows_top_first || row_stride <= 0) {
    return;
  }
  const uint8_t tr = clamp_color_index(transparent_index);
  for (int py = 0; py < h; ++py) {
    const int sy = y0 + (h - 1 - py);
    const int yfb = (kH - 1) - sy;
    if (yfb < 0 || yfb >= kH) {
      continue;
    }
    const uint8_t* row = rows_top_first + static_cast<size_t>(py) * static_cast<size_t>(row_stride);
    for (int lx = 0; lx < w; ++lx) {
      const uint8_t ci = row[lx];
      if (ci == tr) {
        continue;
      }
      plot_fb(x0 + lx, yfb, clamp_color_index(ci));
    }
  }
}

void turtle_gpu_blit_indexed_scene_anchor(int anchor_x, int anchor_y, int w, int h,
                                          const uint8_t* rows_top_first, int row_stride,
                                          uint8_t transparent_index, int origin_x, int origin_y,
                                          bool flip_h) {
  if (w <= 0 || h <= 0 || !rows_top_first || row_stride <= 0) {
    return;
  }
  const uint8_t tr = clamp_color_index(transparent_index);
  const int blit_y = anchor_y - origin_y;
  (void)origin_y;
  for (int py = 0; py < h; ++py) {
    const int sy = blit_y + (h - 1 - py);
    const int yfb = (kH - 1) - sy;
    if (yfb < 0 || yfb >= kH) {
      continue;
    }
    const uint8_t* row = rows_top_first + static_cast<size_t>(py) * static_cast<size_t>(row_stride);
    for (int lx = 0; lx < w; ++lx) {
      const int src_lx = flip_h ? (w - 1 - lx) : lx;
      const uint8_t ci = row[src_lx];
      if (ci == tr) {
        continue;
      }
      const int sx = anchor_x + (flip_h ? (origin_x - lx) : (lx - origin_x));
      plot_fb(sx, yfb, clamp_color_index(ci));
    }
  }
}

void turtle_gpu_flip(void) {
  turtle_fb_flush_to_display();
}

void turtle_gpu_dirty_reset(void) {
  s_dirty_valid = false;
}

void turtle_gpu_dirty_mark_scene_rect(int x0, int y0, int w, int h) {
  if (w <= 0 || h <= 0) {
    return;
  }
  const int sx0 = x0 - 2;
  const int sx1 = x0 + w + 1;
  const int sy0 = y0 - 2;
  const int sy1 = y0 + h + 1;
  const int yfb0 = (kH - 1) - sy1;
  const int yfb1 = (kH - 1) - sy0;
  dirty_mark_fb_clamped(sx0, yfb0, sx1, yfb1);
}

void turtle_gpu_restore_static_dirty(void) {
  if (!s_has_static || !s_dirty_valid) {
    return;
  }
  const int x0 = s_dirty_x0;
  const int y0 = s_dirty_y0;
  const int x1 = s_dirty_x1;
  const int y1 = s_dirty_y1;
  for (int y = y0; y <= y1; ++y) {
    memcpy(&s_fb[y * kW + x0], &s_static_fb[y * kW + x0],
           static_cast<size_t>(x1 - x0 + 1));
  }
}

void turtle_gpu_request_full_flip(void) {
  s_force_full_flip = true;
  s_dirty_valid = false;
}

void turtle_gpu_snapshot_static(void) {
  memcpy(s_static_fb, s_fb, sizeof(s_fb));
  s_has_static = true;
  turtle_gpu_request_full_flip();
}

void turtle_gpu_restore_static(void) {
  if (!s_has_static) {
    return;
  }
  memcpy(s_fb, s_static_fb, sizeof(s_fb));
}

bool turtle_gpu_has_static_snapshot(void) {
  return s_has_static;
}

static int l_cls(lua_State* L) {
  turtle_gpu_cls(lua_color_index(L, 1));
  return 0;
}

/** Coordenadas framebuffer: (0,0) arriba-izquierda, Y hacia abajo (como pix raster). */
static int l_pix(lua_State* L) {
  const int x = static_cast<int>(luaL_checkinteger(L, 1));
  const int y = static_cast<int>(luaL_checkinteger(L, 2));
  const uint8_t ci = lua_color_index(L, 3);
  plot_fb(x, y, ci);
  return 0;
}

/**
 * Coordenadas escena (spec/scene-v0.md): (0,0) abajo-izquierda, Y hacia arriba.
 * xfb = sx, yfb = (H - 1) - sy
 */
static int l_spix(lua_State* L) {
  const int sx = static_cast<int>(luaL_checkinteger(L, 1));
  const int sy = static_cast<int>(luaL_checkinteger(L, 2));
  const uint8_t ci = lua_color_index(L, 3);
  const int yfb = (kH - 1) - sy;
  plot_fb(sx, yfb, ci);
  return 0;
}

static int l_flip(lua_State* L) {
  (void)L;
  turtle_gpu_flip();
  return 0;
}

void turtle_gpu_init(void) {
  memset(s_fb, 0, sizeof(s_fb));
  turtle_gpu_palette_reset_default();
  turtle_display_begin();
}

void turtle_gpu_register_lua(lua_State* L) {
  lua_pushcfunction(L, l_cls);
  lua_setglobal(L, "cls");

  lua_pushcfunction(L, l_pix);
  lua_setglobal(L, "pix");

  lua_pushcfunction(L, l_spix);
  lua_setglobal(L, "spix");

  lua_pushcfunction(L, l_flip);
  lua_setglobal(L, "flip");

  lua_pushinteger(L, kW);
  lua_setglobal(L, "W");

  lua_pushinteger(L, kH);
  lua_setglobal(L, "H");

  lua_pushinteger(L, kNColors);
  lua_setglobal(L, "COLORS");
}
