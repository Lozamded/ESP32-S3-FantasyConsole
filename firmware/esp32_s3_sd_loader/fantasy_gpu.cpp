#include "fantasy_gpu.h"

#include <Arduino.h>
#include <ctype.h>
#include <stdlib.h>
#include <string.h>

extern "C" {
#include <lua.h>
#include <lauxlib.h>
}

static constexpr int kW = 240;
static constexpr int kH = 180;
static constexpr int kNColors = 32;

static uint8_t s_fb[kW * kH];
static uint16_t s_palette[kNColors];

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

void fantasy_gpu_palette_reset_default(void) {
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

int fantasy_gpu_palette_from_hex_text(const char* text, size_t text_len) {
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

#if FANTASY_USE_DISPLAY
#define LGFX_USE_V1
#include <LovyanGFX.hpp>

class LGFX : public lgfx::LGFX_Device {
  lgfx::Panel_ILI9488 _panel_instance;
  lgfx::Bus_SPI _bus_instance;

 public:
  LGFX(void) {
    {
      auto cfg = _bus_instance.config();
      cfg.spi_host = FANTASY_DISP_SPI_HOST;
      cfg.spi_mode = 0;
      cfg.freq_write = 40000000;
      cfg.freq_read = 16000000;
      cfg.spi_3wire = false;
      cfg.use_lock = true;
      cfg.dma_channel = SPI_DMA_CH_AUTO;
      cfg.pin_sclk = FANTASY_DISP_PIN_SCK;
      cfg.pin_miso = FANTASY_DISP_PIN_MISO;
      cfg.pin_mosi = FANTASY_DISP_PIN_MOSI;
      cfg.pin_dc = FANTASY_DISP_PIN_DC;
      _bus_instance.config(cfg);
      _panel_instance.setBus(&_bus_instance);
    }
    {
      auto cfg = _panel_instance.config();
      cfg.pin_cs = FANTASY_DISP_PIN_CS;
      cfg.pin_rst = FANTASY_DISP_PIN_RST;
      cfg.pin_busy = -1;
      cfg.memory_width = 480;
      cfg.memory_height = 320;
      cfg.panel_width = 480;
      cfg.panel_height = 320;
      cfg.offset_x = 0;
      cfg.offset_y = 0;
      cfg.offset_rotation = 0;
      cfg.readable = false;
      cfg.invert = false;
      cfg.rgb_order = false;
      cfg.dlen_16bit = false;
      cfg.bus_shared = false;
      _panel_instance.config(cfg);
    }
    setPanel(&_panel_instance);
  }
};

static LGFX s_display;
static bool s_display_ok = false;

static void fantasy_display_begin(void) {
  s_display.init();
  s_display.setRotation(0);
  s_display.fillScreen(0x0000u);
  s_display_ok = true;
}

static void fantasy_fb_flush_to_display(void) {
  if (!s_display_ok) {
    return;
  }
  constexpr int dx = (480 - kW) / 2;
  constexpr int dy = (320 - kH) / 2;
  uint16_t line[kW];
  for (int y = 0; y < kH; y++) {
    const uint8_t* row = &s_fb[y * kW];
    for (int x = 0; x < kW; x++) {
      line[x] = s_palette[row[x]];
    }
    s_display.pushImage(dx, dy + y, kW, 1, line);
  }
}

#else

static void fantasy_display_begin(void) {}

static void fantasy_fb_flush_to_display(void) {}

#endif

static int l_cls(lua_State* L) {
  const lua_Integer c = luaL_checkinteger(L, 1);
  uint8_t ci;
  if (c < 0) {
    ci = 0;
  } else if (c >= kNColors) {
    ci = static_cast<uint8_t>(kNColors - 1);
  } else {
    ci = static_cast<uint8_t>(c);
  }
  memset(s_fb, ci, sizeof(s_fb));
  return 0;
}

static int l_pix(lua_State* L) {
  const int x = static_cast<int>(luaL_checkinteger(L, 1));
  const int y = static_cast<int>(luaL_checkinteger(L, 2));
  const lua_Integer c = luaL_checkinteger(L, 3);
  uint8_t ci;
  if (c < 0) {
    ci = 0;
  } else if (c >= kNColors) {
    ci = static_cast<uint8_t>(kNColors - 1);
  } else {
    ci = static_cast<uint8_t>(c);
  }
  if (x < 0 || x >= kW || y < 0 || y >= kH) {
    return 0;
  }
  s_fb[y * kW + x] = ci;
  return 0;
}

static int l_flip(lua_State* L) {
  (void)L;
  fantasy_fb_flush_to_display();
  return 0;
}

void fantasy_gpu_init(void) {
  memset(s_fb, 0, sizeof(s_fb));
  fantasy_gpu_palette_reset_default();
  fantasy_display_begin();
}

void fantasy_gpu_register_lua(lua_State* L) {
  lua_pushcfunction(L, l_cls);
  lua_setglobal(L, "cls");

  lua_pushcfunction(L, l_pix);
  lua_setglobal(L, "pix");

  lua_pushcfunction(L, l_flip);
  lua_setglobal(L, "flip");

  lua_pushinteger(L, kW);
  lua_setglobal(L, "W");

  lua_pushinteger(L, kH);
  lua_setglobal(L, "H");

  lua_pushinteger(L, kNColors);
  lua_setglobal(L, "COLORS");
}
