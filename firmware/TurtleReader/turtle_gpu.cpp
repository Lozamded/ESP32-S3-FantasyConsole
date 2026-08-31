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

static constexpr int kW = 164;
static constexpr int kH = 124;
static constexpr int kNColors = 32;

static uint8_t s_fb[kW * kH];
static uint8_t s_static_fb[kW * kH];
static bool s_has_static = false;
static uint16_t s_palette[kNColors];

static bool s_dirty_valid = false;
static bool s_force_full_flip = true;
static int s_cam_x = 0;
static int s_cam_y = 0;

// spec/hud-border-v0.md: playfield = subrectangulo del framebuffer donde se pintan escena +
// actores; el area fuera es la region HUD (nunca la tocan blits de escena). Defecto = todo
// el framebuffer, es decir sin HUD, para carts que no usen el mecanismo. turtle_scene.cpp
// llama a set_playfield en cada begin_runtime con los valores derivados del manifest.
static int s_pf_ox = 0;
static int s_pf_oy = 0;
static int s_pf_w = kW;
static int s_pf_h = kH;

// Grilla de celdas sucias (en vez de un unico rect englobante): dos sprites en extremos
// opuestos de la pantalla ya no inflan la region sucia a casi toda la pantalla, cada uno
// solo ensucia sus propias celdas. 16px/celda: 11x8 celdas, barrerla entera cada frame
// es trivial (<=88 iteraciones) frente al costo de SPI/paleta que evita.
static constexpr int kTileSize = 16;
static constexpr int kGridCols = (kW + kTileSize - 1) / kTileSize;
static constexpr int kGridRows = (kH + kTileSize - 1) / kTileSize;
static uint8_t s_dirty_cell[kGridRows][kGridCols];

static void dirty_mark_fb_clamped(int x0, int y0, int x1, int y1) {
  // +-1px: mismo margen que antes cubria turtle_gpu_dirty_slack_for_scale() sobre el bbox
  // final (holgura de redondeo fb->panel), aplicado por-rect aca en vez de una vez al
  // final -- evita tener que dilatar celdas *enteras* de 16px de la grilla para lograr el
  // mismo margen de 1px real (eso infla muchisimo el area sucia de un actor chico).
  x0 -= 1;
  y0 -= 1;
  x1 += 1;
  y1 += 1;
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
  const int cx0 = x0 / kTileSize;
  const int cx1 = x1 / kTileSize;
  const int cy0 = y0 / kTileSize;
  const int cy1 = y1 / kTileSize;
  for (int cy = cy0; cy <= cy1; ++cy) {
    for (int cx = cx0; cx <= cx1; ++cx) {
      s_dirty_cell[cy][cx] = 1;
    }
  }
  s_dirty_valid = true;
}

/**
 * Recorre celdas sucias contiguas (horizontalmente) en la fila de grilla `cy`, empezando
 * en *cx. Devuelve false cuando no queda ninguna racha desde *cx en adelante. Usado tanto
 * para restaurar la capa estatica como para el flush a pantalla, fusionando celdas sueltas
 * en un solo rect en vez de una llamada/copia por celda de 16x16.
 */
static bool dirty_row_next_span(int cy, int* cx, int* out_cx0, int* out_cx1) {
  int cx0 = *cx;
  while (cx0 < kGridCols && !s_dirty_cell[cy][cx0]) {
    ++cx0;
  }
  if (cx0 >= kGridCols) {
    *cx = cx0;
    return false;
  }
  int cx1 = cx0;
  while (cx1 + 1 < kGridCols && s_dirty_cell[cy][cx1 + 1]) {
    ++cx1;
  }
  *out_cx0 = cx0;
  *out_cx1 = cx1;
  *cx = cx1 + 1;
  return true;
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

// LUT del reescalado nearest-neighbor fb(164x124) -> panel (fijo por sesion: mismo panel/
// rotacion siempre). Evita repetir (px*kW)/panelW y (py*kH)/panelH -division entera- por
// cada pixel de cada fila de cada flip; se calcula una vez y se cachea.
static int16_t s_lut_lx[480];
static int16_t s_lut_ly[480];
static bool s_lut_ready = false;
static int s_lut_panelW = -1;
static int s_lut_panelH = -1;

static void ensure_upscale_lut(int panelW, int panelH) {
  if (s_lut_ready && s_lut_panelW == panelW && s_lut_panelH == panelH) {
    return;
  }
  const int nx = panelW < 480 ? panelW : 480;
  const int ny = panelH < 480 ? panelH : 480;
  for (int px = 0; px < nx; ++px) {
    s_lut_lx[px] = static_cast<int16_t>((px * kW) / panelW);
  }
  for (int py = 0; py < ny; ++py) {
    s_lut_ly[py] = static_cast<int16_t>((py * kH) / panelH);
  }
  s_lut_panelW = panelW;
  s_lut_panelH = panelH;
  s_lut_ready = true;
}

static void turtle_fb_flush_full_to_display(void) {
  if (!s_display_ok) {
    return;
  }

  // Resolucion logica 164x124, panel visible 320x240 (rotado).
  const int panelW = s_display.width();
  const int panelH = s_display.height();
  if (panelW <= 0 || panelH <= 0) {
    return;
  }

  ensure_upscale_lut(panelW, panelH);

  const size_t need = static_cast<size_t>(panelW) * static_cast<size_t>(panelH);
  if (!ensure_panel_rgb_buffer(need)) {
    uint16_t line[480];
    for (int py = 0; py < panelH; py++) {
      const int ly = s_lut_ly[py];
      const uint8_t* row = &s_fb[ly * kW];
      for (int px = 0; px < panelW; px++) {
        const int lx = s_lut_lx[px];
        line[px] = s_palette[row[lx]];
      }
      s_display.pushImage(0, py, panelW, 1, line);
    }
    return;
  }

  for (int py = 0; py < panelH; py++) {
    const int ly = s_lut_ly[py];
    const uint8_t* row = &s_fb[ly * kW];
    uint16_t* dst = &s_panel_rgb[static_cast<size_t>(py) * static_cast<size_t>(panelW)];
    for (int px = 0; px < panelW; px++) {
      const int lx = s_lut_lx[px];
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
  ensure_upscale_lut(panelW, panelH);

  const size_t panel_pixels = static_cast<size_t>(panelW) * static_cast<size_t>(panelH);
  const bool have_buf = ensure_panel_rgb_buffer(panel_pixels);
  uint16_t fallback_line[480];

  s_display.startWrite();
  // Cada fila de grilla puede tener varias rachas de celdas sucias separadas por celdas
  // limpias (p. ej. dos actores lejos entre si); cada racha se funde en un solo rect y se
  // envia con un solo pushImage (DMA de un bloque contiguo) en vez de linea por linea.
  for (int cy = 0; cy < kGridRows; ++cy) {
    const int yfb0 = cy * kTileSize;
    if (yfb0 >= kH) {
      break;
    }
    int yfb1 = yfb0 + kTileSize - 1;
    if (yfb1 >= kH) {
      yfb1 = kH - 1;
    }

    int cx = 0;
    int cx0 = 0;
    int cx1 = 0;
    while (dirty_row_next_span(cy, &cx, &cx0, &cx1)) {
      const int xfb0 = cx0 * kTileSize;
      int xfb1 = cx1 * kTileSize + kTileSize - 1;
      if (xfb1 >= kW) {
        xfb1 = kW - 1;
      }

      int px0 = (xfb0 * panelW) / kW;
      int px1 = ((xfb1 + 1) * panelW - 1) / kW;
      if (px0 < 0) {
        px0 = 0;
      }
      if (px1 >= panelW) {
        px1 = panelW - 1;
      }
      int py0 = (yfb0 * panelH) / kH;
      int py1 = ((yfb1 + 1) * panelH - 1) / kH;
      if (py0 < 0) {
        py0 = 0;
      }
      if (py1 >= panelH) {
        py1 = panelH - 1;
      }

      const int pw = px1 - px0 + 1;
      const int ph = py1 - py0 + 1;
      if (pw <= 0 || ph <= 0) {
        continue;
      }

      if (have_buf && static_cast<size_t>(pw) * static_cast<size_t>(ph) <= s_panel_rgb_cap) {
        for (int py = py0; py <= py1; ++py) {
          const int ly = s_lut_ly[py];
          if (ly < yfb0 || ly > yfb1) {
            continue;
          }
          const uint8_t* row = &s_fb[ly * kW];
          uint16_t* dst = &s_panel_rgb[static_cast<size_t>(py - py0) * static_cast<size_t>(pw)];
          for (int i = 0; i < pw; ++i) {
            int lx = s_lut_lx[px0 + i];
            if (lx < xfb0) {
              lx = xfb0;
            } else if (lx > xfb1) {
              lx = xfb1;
            }
            dst[i] = s_palette[row[lx]];
          }
        }
        s_display.pushImage(px0, py0, pw, ph, s_panel_rgb);
      } else if (pw <= static_cast<int>(sizeof(fallback_line) / sizeof(fallback_line[0]))) {
        // Sin buffer PSRAM contiguo disponible: cae a linea por linea (correcto, mas lento).
        for (int py = py0; py <= py1; ++py) {
          const int ly = s_lut_ly[py];
          if (ly < yfb0 || ly > yfb1) {
            continue;
          }
          const uint8_t* row = &s_fb[ly * kW];
          for (int i = 0; i < pw; ++i) {
            int lx = s_lut_lx[px0 + i];
            if (lx < xfb0) {
              lx = xfb0;
            } else if (lx > xfb1) {
              lx = xfb1;
            }
            fallback_line[i] = s_palette[row[lx]];
          }
          s_display.pushImage(px0, py, pw, 1, fallback_line);
        }
      }
    }
  }
  s_display.endWrite();
}

static void turtle_fb_flush_to_display(void) {
  if (s_force_full_flip) {
    turtle_fb_flush_full_to_display();
    s_force_full_flip = false;
    s_dirty_valid = false;
    return;
  }
  if (!s_dirty_valid) {
    turtle_fb_flush_full_to_display();
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

// Fwd decl: definido mas abajo pero necesario para turtle_gpu_pixel_absolute /
// _fill_rect_absolute (declaradas antes en el orden actual del archivo). Basura si el
// caller pasa un color >= kNColors -- clampea al ultimo indice valido.
static uint8_t clamp_color_index(uint8_t ci);

static void plot_fb(int xfb, int yfb, uint8_t ci) {
  if (xfb < 0 || xfb >= kW || yfb < 0 || yfb >= kH) {
    return;
  }
  s_fb[yfb * kW + xfb] = ci;
}

// spec/hud-border-v0.md: plot dentro del playfield partiendo de coords viewport-relativas
// (vx: 0..pf_w-1 hacia la derecha; vy_scene: 0..pf_h-1 hacia arriba, misma convencion Y-up
// que usan blit_indexed_scene y familia). Fuera del playfield es no-op.
static inline void plot_playfield(int vx, int vy_scene, uint8_t ci) {
  if (vx < 0 || vx >= s_pf_w || vy_scene < 0 || vy_scene >= s_pf_h) {
    return;
  }
  const int xfb = s_pf_ox + vx;
  const int yfb = s_pf_oy + (s_pf_h - 1) - vy_scene;
  s_fb[yfb * kW + xfb] = ci;
}

void turtle_gpu_set_camera(int cam_x, int cam_y) {
  s_cam_x = cam_x;
  s_cam_y = cam_y;
}

void turtle_gpu_get_camera(int* cam_x, int* cam_y) {
  if (cam_x) {
    *cam_x = s_cam_x;
  }
  if (cam_y) {
    *cam_y = s_cam_y;
  }
}

void turtle_gpu_set_playfield(int ox, int oy, int pw, int ph) {
  // Clamp defensivo: valores erroneos aca desalinean todo el pipeline de dibujo. El
  // parser del manifest (turtle_scene.cpp) ya valida rangos con reglas de spec, pero
  // este es la ultima linea de defensa (unit tests, llamadas fuera de scene).
  if (pw < 1) {
    pw = 1;
  }
  if (ph < 1) {
    ph = 1;
  }
  if (ox < 0) {
    ox = 0;
  }
  if (oy < 0) {
    oy = 0;
  }
  if (ox + pw > kW) {
    pw = kW - ox;
  }
  if (oy + ph > kH) {
    ph = kH - oy;
  }
  s_pf_ox = ox;
  s_pf_oy = oy;
  s_pf_w = pw;
  s_pf_h = ph;
}

void turtle_gpu_get_playfield(int* ox, int* oy, int* pw, int* ph) {
  if (ox) {
    *ox = s_pf_ox;
  }
  if (oy) {
    *oy = s_pf_oy;
  }
  if (pw) {
    *pw = s_pf_w;
  }
  if (ph) {
    *ph = s_pf_h;
  }
}

bool turtle_gpu_playfield_contains(int x, int y) {
  return x >= s_pf_ox && x < s_pf_ox + s_pf_w && y >= s_pf_oy && y < s_pf_oy + s_pf_h;
}

// spec/hud-border-v0.md: escritura HUD absoluta. `s_fb` y `s_static_fb` se mantienen en
// sincronia para que restore_static_dirty no revierta el HUD si un dirty rect de actores
// se derrama a la region HUD (por la holgura ±4 de dirty_mark_scene_rect). La celda dirty
// se marca aca directamente en fb-coords (no scene-space), sin la holgura de escena que
// solo tiene sentido para blits de actor.
static inline void mark_panel_dirty_pixel_fb(int xfb, int yfb) {
  if (xfb < 0 || xfb >= kW || yfb < 0 || yfb >= kH) {
    return;
  }
  s_dirty_cell[yfb / kTileSize][xfb / kTileSize] = 1;
  s_dirty_valid = true;
}

void turtle_gpu_pixel_absolute(int x, int y, uint8_t color_index) {
  if (x < 0 || x >= kW || y < 0 || y >= kH) {
    return;
  }
  if (turtle_gpu_playfield_contains(x, y)) {
    return;  // proteccion: hud_* no puede pintar el area de juego
  }
  const uint8_t ci = clamp_color_index(color_index);
  s_fb[y * kW + x] = ci;
  if (s_has_static) {
    s_static_fb[y * kW + x] = ci;
  }
  mark_panel_dirty_pixel_fb(x, y);
}

void turtle_gpu_pixel_raw(int x, int y, uint8_t color_index) {
  if (x < 0 || x >= kW || y < 0 || y >= kH) {
    return;
  }
  const uint8_t ci = clamp_color_index(color_index);
  // A diferencia de pixel_absolute, NO se toca s_static_fb: contenido dinamico de capas GUI
  // se repinta cada frame, si lo horneamos aca los labels con texto variable acumulan tinta.
  s_fb[y * kW + x] = ci;
  mark_panel_dirty_pixel_fb(x, y);
}

void turtle_gpu_fill_rect_raw(int x, int y, int w, int h, uint8_t color_index) {
  if (w <= 0 || h <= 0) {
    return;
  }
  const uint8_t ci = clamp_color_index(color_index);
  int x0 = x;
  int y0 = y;
  int x1 = x + w - 1;
  int y1 = y + h - 1;
  if (x0 < 0) x0 = 0;
  if (y0 < 0) y0 = 0;
  if (x1 >= kW) x1 = kW - 1;
  if (y1 >= kH) y1 = kH - 1;
  if (x0 > x1 || y0 > y1) {
    return;
  }
  // Ver comentario en turtle_gpu_pixel_raw: no se escribe en s_static_fb.
  for (int yy = y0; yy <= y1; ++yy) {
    uint8_t* row_fb = &s_fb[yy * kW + x0];
    memset(row_fb, ci, static_cast<size_t>(x1 - x0 + 1));
  }
  dirty_mark_fb_clamped(x0, y0, x1, y1);
}

void turtle_gpu_restore_static_rect_fb(int x, int y, int w, int h) {
  if (!s_has_static || w <= 0 || h <= 0) {
    return;
  }
  int x0 = x;
  int y0 = y;
  int x1 = x + w - 1;
  int y1 = y + h - 1;
  if (x0 < 0) x0 = 0;
  if (y0 < 0) y0 = 0;
  if (x1 >= kW) x1 = kW - 1;
  if (y1 >= kH) y1 = kH - 1;
  if (x0 > x1 || y0 > y1) {
    return;
  }
  const size_t n = static_cast<size_t>(x1 - x0 + 1);
  for (int yy = y0; yy <= y1; ++yy) {
    memcpy(&s_fb[yy * kW + x0], &s_static_fb[yy * kW + x0], n);
  }
  dirty_mark_fb_clamped(x0, y0, x1, y1);
}

void turtle_gpu_fill_rect_absolute(int x, int y, int w, int h, uint8_t color_index) {
  if (w <= 0 || h <= 0) {
    return;
  }
  const uint8_t ci = clamp_color_index(color_index);
  int x0 = x;
  int y0 = y;
  int x1 = x + w - 1;
  int y1 = y + h - 1;
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
  const int pf_x0 = s_pf_ox;
  const int pf_y0 = s_pf_oy;
  const int pf_x1 = s_pf_ox + s_pf_w - 1;
  const int pf_y1 = s_pf_oy + s_pf_h - 1;
  for (int yy = y0; yy <= y1; ++yy) {
    for (int xx = x0; xx <= x1; ++xx) {
      // Playfield: no-op (proteccion). El rect puede cruzar bordes sin efecto ahi.
      if (xx >= pf_x0 && xx <= pf_x1 && yy >= pf_y0 && yy <= pf_y1) {
        continue;
      }
      s_fb[yy * kW + xx] = ci;
      if (s_has_static) {
        s_static_fb[yy * kW + xx] = ci;
      }
    }
  }
  // Marca panel-dirty a nivel de celda (16 px) englobando el rect entero; el interior
  // playfield-only se restaura desde s_static_fb (identidad) en el proximo frame, sin costo.
  dirty_mark_fb_clamped(x0, y0, x1, y1);
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

void turtle_gpu_playfield_clear(uint8_t color_index) {
  const uint8_t ci = clamp_color_index(color_index);
  const int y0 = s_pf_oy;
  const int y1 = s_pf_oy + s_pf_h;
  const int x0 = s_pf_ox;
  const int span = s_pf_w;
  for (int yy = y0; yy < y1; ++yy) {
    memset(&s_fb[yy * kW + x0], ci, static_cast<size_t>(span));
  }
  turtle_gpu_request_full_flip();
}

void turtle_gpu_fill_rect_scene(int x0, int y0, int w, int h, uint8_t color_index) {
  if (w <= 0 || h <= 0) {
    return;
  }
  const uint8_t ci = clamp_color_index(color_index);
  for (int sy = y0; sy < y0 + h; ++sy) {
    const int vy = sy - s_cam_y;
    if (vy < 0 || vy >= s_pf_h) {
      continue;
    }
    for (int sx = x0; sx < x0 + w; ++sx) {
      const int vx = sx - s_cam_x;
      if (vx < 0 || vx >= s_pf_w) {
        continue;
      }
      plot_playfield(vx, vy, ci);
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
    const int vy = sy - s_cam_y;
    if (vy < 0 || vy >= s_pf_h) {
      continue;
    }
    const uint8_t* row = rows_top_first + static_cast<size_t>(py) * static_cast<size_t>(row_stride);
    for (int lx = 0; lx < w; ++lx) {
      const uint8_t ci = row[lx];
      if (ci == tr) {
        continue;
      }
      const int vx = x0 + lx - s_cam_x;
      if (vx < 0 || vx >= s_pf_w) {
        continue;
      }
      plot_playfield(vx, vy, clamp_color_index(ci));
    }
  }
}

void turtle_gpu_blit_indexed_scene_tint(int x0, int y0, int w, int h,
                                        const uint8_t* rows_top_first, int row_stride,
                                        uint8_t transparent_index, uint8_t tint_color_index) {
  if (w <= 0 || h <= 0 || !rows_top_first || row_stride <= 0) {
    return;
  }
  const uint8_t tr = clamp_color_index(transparent_index);
  const uint8_t tint = clamp_color_index(tint_color_index);
  for (int py = 0; py < h; ++py) {
    const int sy = y0 + (h - 1 - py);
    const int vy = sy - s_cam_y;
    if (vy < 0 || vy >= s_pf_h) {
      continue;
    }
    const uint8_t* row = rows_top_first + static_cast<size_t>(py) * static_cast<size_t>(row_stride);
    for (int lx = 0; lx < w; ++lx) {
      if (row[lx] == tr) {
        continue;
      }
      const int vx = x0 + lx - s_cam_x;
      if (vx < 0 || vx >= s_pf_w) {
        continue;
      }
      plot_playfield(vx, vy, tint);
    }
  }
}

void turtle_gpu_blit_indexed_row_banded(int scene_y, const uint8_t* sample_row,
                                        int sample_row_len, int x_offset, bool wrap_x,
                                        uint8_t transparent_index) {
  if (!sample_row || sample_row_len <= 0) {
    return;
  }
  const int vy = scene_y - s_cam_y;
  if (vy < 0 || vy >= s_pf_h) {
    return;
  }
  const uint8_t tr = clamp_color_index(transparent_index);
  for (int vx = 0; vx < s_pf_w; ++vx) {
    int sx = vx + x_offset;
    if (wrap_x) {
      sx %= sample_row_len;
      if (sx < 0) {
        sx += sample_row_len;
      }
    } else if (sx < 0 || sx >= sample_row_len) {
      continue;
    }
    const uint8_t ci = sample_row[sx];
    if (ci == tr) {
      continue;
    }
    plot_playfield(vx, vy, clamp_color_index(ci));
  }
}

void turtle_gpu_blit_indexed_scene_anchor(int anchor_x, int anchor_y, int w, int h,
                                          const uint8_t* rows_top_first, int row_stride,
                                          uint8_t transparent_index, int origin_x, int origin_y,
                                          bool flip_h, bool flip_v) {
  if (w <= 0 || h <= 0 || !rows_top_first || row_stride <= 0) {
    return;
  }
  const uint8_t tr = clamp_color_index(transparent_index);
  const int blit_y = anchor_y - origin_y;
  (void)origin_y;
  for (int py = 0; py < h; ++py) {
    const int sy = blit_y + (h - 1 - py);
    const int vy = sy - s_cam_y;
    if (vy < 0 || vy >= s_pf_h) {
      continue;
    }
    // flip_v: sample rows in reverse (dibuja el sprite cabeza abajo pero en el mismo rect).
    const int src_py = flip_v ? (h - 1 - py) : py;
    const uint8_t* row =
        rows_top_first + static_cast<size_t>(src_py) * static_cast<size_t>(row_stride);
    for (int lx = 0; lx < w; ++lx) {
      const uint8_t ci = row[lx];
      if (ci == tr) {
        continue;
      }
      const int sx =
          flip_h ? (anchor_x + origin_x - lx) : (anchor_x + lx - origin_x);
      const int vx = sx - s_cam_x;
      if (vx < 0 || vx >= s_pf_w) {
        continue;
      }
      plot_playfield(vx, vy, clamp_color_index(ci));
    }
  }
}

void turtle_gpu_flip(void) {
  turtle_fb_flush_to_display();
}

void turtle_gpu_dirty_reset(void) {
  // Incondicional: s_dirty_valid puede quedar en false (tras un flip) con celdas de un
  // frame anterior todavia marcadas en la grilla -- no alcanza con mirar el flag.
  memset(s_dirty_cell, 0, sizeof(s_dirty_cell));
  s_dirty_valid = false;
}

void turtle_gpu_dirty_mark_scene_rect(int x0, int y0, int w, int h) {
  if (w <= 0 || h <= 0) {
    return;
  }
  /* Margen extra: borrado prev_blit + holgura por mapeo fb 164 -> panel ~320.
   * spec/hud-border-v0.md: los rects marcados aca vienen del camino de camara fija
   * (draw_all_actors, ver comentario alli). El caller pasa coords de escena Y-arriba
   * viewport-relativas (equivalen a viewport-relative con cam=(0,0)); aca se convierten
   * a coords de framebuffer aplicando el offset del playfield -- si hay HUD en top>0
   * los dirty cells caen desplazados hacia abajo, y no se cruzan a la region HUD
   * (dirty_mark_fb_clamped clampea al framebuffer completo; los pixeles HUD que caigan
   * en un rect sucio se restauran desde s_static_fb, que hud_pixel_absolute actualiza
   * en cada escritura, asi que el HUD queda correcto). */
  const int sx0 = x0 - 4;
  const int sx1 = x0 + w + 3;
  const int sy0 = y0 - 4;
  const int sy1 = y0 + h + 3;
  const int xfb0 = s_pf_ox + sx0;
  const int xfb1 = s_pf_ox + sx1;
  const int yfb0 = s_pf_oy + (s_pf_h - 1) - sy1;
  const int yfb1 = s_pf_oy + (s_pf_h - 1) - sy0;
  dirty_mark_fb_clamped(xfb0, yfb0, xfb1, yfb1);
}

/**
 * No-op: el margen de holgura por redondeo fb->panel ahora se aplica por-rect dentro de
 * dirty_mark_fb_clamped (ver comentario ahi). Se mantiene por compatibilidad de API --
 * turtle_scene.cpp la sigue llamando una vez por frame despues de marcar los rects.
 */
void turtle_gpu_dirty_slack_for_scale(void) {}

bool turtle_gpu_dirty_valid(void) {
  return s_dirty_valid;
}

void turtle_gpu_dirty_mark_fb_full(void) {
  memset(s_dirty_cell, 1, sizeof(s_dirty_cell));
  s_dirty_valid = true;
}

void turtle_gpu_restore_static_dirty(void) {
  if (!s_has_static || !s_dirty_valid) {
    return;
  }
  for (int cy = 0; cy < kGridRows; ++cy) {
    const int y0 = cy * kTileSize;
    if (y0 >= kH) {
      break;
    }
    int y1 = y0 + kTileSize - 1;
    if (y1 >= kH) {
      y1 = kH - 1;
    }

    int cx = 0;
    int cx0 = 0;
    int cx1 = 0;
    while (dirty_row_next_span(cy, &cx, &cx0, &cx1)) {
      const int x0 = cx0 * kTileSize;
      int x1 = cx1 * kTileSize + kTileSize - 1;
      if (x1 >= kW) {
        x1 = kW - 1;
      }
      const size_t n = static_cast<size_t>(x1 - x0 + 1);
      for (int y = y0; y <= y1; ++y) {
        memcpy(&s_fb[y * kW + x0], &s_static_fb[y * kW + x0], n);
      }
    }
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
 * Coordenadas escena (spec/scene-v0.md): (0,0) esquina inferior-izq del playfield, Y-arriba.
 * spec/hud-border-v0.md: si hay `camera.hud_border`, `sx`/`sy` son viewport-relativas al
 * playfield reducido (no al framebuffer completo). Fuera del playfield es no-op. Durante
 * la ejecucion de la VM ENTRY antes de comenzar la primera escena, playfield = framebuffer
 * entero, asi que el comportamiento es identico al de antes de v0.
 */
static int l_spix(lua_State* L) {
  const int sx = static_cast<int>(luaL_checkinteger(L, 1));
  const int sy = static_cast<int>(luaL_checkinteger(L, 2));
  const uint8_t ci = lua_color_index(L, 3);
  plot_playfield(sx, sy, ci);
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
