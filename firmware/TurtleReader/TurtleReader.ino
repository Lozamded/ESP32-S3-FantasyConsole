#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <string.h>

#if defined(ESP32) || defined(ESP_PLATFORM)
#include <esp_heap_caps.h>
#endif

#include "turtle_boot_font.h"
#include "turtle_cart.h"
#include "turtle_gpu.h"
#include "turtle_input.h"
#include "turtle_scene.h"

extern "C" {
#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>
}

// microSD (FSPI). No uses GPIO 33-37 con PSRAM OPI (N16R8).
// 19/20 = USB nativo en muchas placas S3: OK si programas por UART (no USB CDC en 19/20).
// Pantalla = 8-13, botones = 4-7 y 15-18 (ver turtle_gpu.h / turtle_input.h).
static const int SD_SCK_PIN = 19; //azul
static const int SD_MISO_PIN = 20; //morado
static const int SD_MOSI_PIN = 21; //gris
static const int SD_CS_PIN = 47; //blanco

SPIClass sdSPI(FSPI);

// Declarados aqui (no junto a loadCartRunLua mas abajo) porque l_text/l_text_width
// (bindings Lua de la VM ENTRY, ver mas abajo) necesitan leer g_bundle.
static TurtleCartBuffer g_cart = {};
static TurtleCartBuffer g_bundle = {};
static char g_initial_scene[64] = "intro";
static bool g_has_bundle = false;
static bool g_runtime_active = false;
static uint32_t g_last_tick_ms = 0;

#if defined(ESP32) || defined(ESP_PLATFORM)
static void log_heap_caps(const char* tag) {
  const size_t dram = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
  const size_t psram = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
  const size_t psram_largest = heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM);
  Serial.printf("[%s] DRAM libre ~%u, PSRAM libre ~%u, bloque max PSRAM ~%u",
                tag, static_cast<unsigned>(dram), static_cast<unsigned>(psram),
                static_cast<unsigned>(psram_largest));
  if (ESP.getPsramSize() > 0) {
    Serial.printf(", PSRAM total %u", static_cast<unsigned>(ESP.getPsramSize()));
  } else {
    Serial.print(", PSRAM no detectada (Tools > PSRAM?)");
  }
  Serial.println();
}
#endif

// Viewport canonico (spec/scene-v0.md); duplicado aqui (no expuesto por turtle_gpu.h)
// solo para centrar los mensajes de arranque de turtle_boot_font.
static const int kViewportW = 164;
static const int kViewportH = 124;

/** Limpia pantalla y dibuja `text` (fuente embebida de arranque) centrado. */
static void showBootMessage(const char* text) {
  turtle_gpu_cls(0);
  turtle_boot_text_draw_centered(kViewportW / 2, kViewportH / 2, text, /*color_index=*/7,
                                 /*scale=*/2);
  turtle_gpu_flip();
}

static bool mountSd(uint32_t frequencyHz) {
  sdSPI.begin(SD_SCK_PIN, SD_MISO_PIN, SD_MOSI_PIN, SD_CS_PIN);
  return SD.begin(SD_CS_PIN, sdSPI, frequencyHz);
}

static bool mountSdWithRetries() {
  // Velocidades de operacion normal (no de identificacion SD): se intentan primero
  // porque casi toda tarjeta SD-sobre-SPI las soporta una vez montada, y a 400kHz/1MHz
  // (velocidades de identificacion del propio protocolo SD) cada lectura de cartucho/
  // escena/script de actor via SD.open() paga un costo enorme innecesario.
  // El fallback a las velocidades lentas de identificacion se mantiene al final para
  // tarjetas viejas o de mala calidad que no toleren SPI rapido.
  const uint32_t speeds[] = {20000000, 10000000, 4000000, 1000000, 400000, 100000};
  constexpr int kAttempts = 8;
  for (int attempt = 0; attempt < kAttempts; attempt++) {
    for (uint32_t hz : speeds) {
      if (mountSd(hz)) {
        return true;
      }
      SD.end();
      delay(50);
    }
    Serial.printf("SD: reintento %d/%d...\n", attempt + 1, kAttempts);
    delay(150);
  }
  return false;
}

static int l_serial_print(lua_State* L) {
  int n = lua_gettop(L);
  for (int i = 1; i <= n; i++) {
    if (i > 1) {
      Serial.print('\t');
    }
    const char* s = luaL_tolstring(L, i, nullptr);
    Serial.print(s);
    lua_pop(L, 1);
  }
  Serial.println();
  return 0;
}

/**
 * text(sx, sy, str, font_id [, color_index]) -> ancho dibujado (px). (sx, sy) = esquina
 * inferior izquierda del primer glifo, espacio escena (misma convencion que spix). Fuente
 * resuelta/cacheada desde el bundle del cartucho (ver spec/asset-bin-v0.md "Fuente").
 * `color_index` (0..30) opcional tiñe el texto con ese color en vez de los colores propios
 * del glifo (ver spec/lua/firmware-bridge-v0.md "Texto").
 */
static int l_text(lua_State* L) {
  const int sx = static_cast<int>(luaL_checkinteger(L, 1));
  const int sy = static_cast<int>(luaL_checkinteger(L, 2));
  const char* str = luaL_checkstring(L, 3);
  const char* font_id = luaL_checkstring(L, 4);
  const int color_index = static_cast<int>(luaL_optinteger(L, 5, -1));
  const int w =
      turtle_scene_draw_text(g_bundle.data, g_bundle.len, font_id, sx, sy, str, color_index);
  lua_pushinteger(L, w);
  return 1;
}

/** text_width(str, font_id) -> ancho en px, sin dibujar. */
static int l_text_width(lua_State* L) {
  const char* str = luaL_checkstring(L, 1);
  const char* font_id = luaL_checkstring(L, 2);
  const int w = turtle_scene_measure_text(g_bundle.data, g_bundle.len, font_id, str);
  lua_pushinteger(L, w);
  return 1;
}

static bool runCartEntryLua(const char* source, size_t source_len, const char* chunkName) {
  if (!source || source_len == 0) {
    Serial.println("Lua: ENTRY vacio");
    return false;
  }

  lua_State* L = luaL_newstate();
  if (!L) {
    Serial.println("Lua: luaL_newstate fallo");
    return false;
  }

  luaL_openlibs(L);
  lua_pushcfunction(L, l_serial_print);
  lua_setglobal(L, "print");

  turtle_gpu_register_lua(L);
  turtle_input_register_lua(L);

  lua_pushcfunction(L, l_text);
  lua_setglobal(L, "text");
  lua_pushcfunction(L, l_text_width);
  lua_setglobal(L, "text_width");

  int st = luaL_loadbuffer(L, source, source_len, chunkName);
  if (st != LUA_OK) {
    Serial.print("Lua (carga): ");
    Serial.println(lua_tostring(L, -1));
    lua_pop(L, 1);
    lua_close(L);
    return false;
  }

  st = lua_pcall(L, 0, LUA_MULTRET, 0);
  if (st != LUA_OK) {
    Serial.print("Lua (ejecucion): ");
    Serial.println(lua_tostring(L, -1));
    lua_pop(L, 1);
    lua_close(L);
    return false;
  }

  lua_close(L);
  return true;
}

/** Lua + paleta; carga cartucho pequeno y bundle en sidecar. */
static bool loadCartRunLua(const char* path) {
  turtle_cart_free(&g_cart);
  turtle_cart_free(&g_bundle);
  g_has_bundle = false;
  g_runtime_active = false;

  if (!turtle_cart_load_sd_file(path, &g_cart)) {
    return false;
  }

  if (g_cart.len < 12 || memcmp(g_cart.data, "TURTLECART:0", 12) != 0) {
    Serial.println("Error: header invalido (se esperaba TURTLECART:0)");
    turtle_cart_free(&g_cart);
    return false;
  }

  if (!turtle_cart_load_bundle_for_cart(&g_cart, &g_bundle)) {
    Serial.println("Error: no se pudo cargar studio/project_bundle.json");
    turtle_cart_free(&g_cart);
    return false;
  }
  g_has_bundle = true;

  char entry[128];
  if (!turtle_cart_header_value(&g_cart, "ENTRY:", entry, sizeof entry) || entry[0] == '\0') {
    Serial.println("Error: cartucho sin ENTRY");
    turtle_cart_free(&g_cart);
    turtle_cart_free(&g_bundle);
    g_has_bundle = false;
    return false;
  }

  if (!turtle_cart_header_value(&g_cart, "INITIAL_SCENE:", g_initial_scene,
                                sizeof g_initial_scene) ||
      g_initial_scene[0] == '\0') {
    strncpy(g_initial_scene, "intro", sizeof g_initial_scene);
    g_initial_scene[sizeof g_initial_scene - 1] = '\0';
  }

  const char* pal_begin = nullptr;
  size_t pal_len = 0;
  if (turtle_cart_extract_palette(&g_cart, &pal_begin, &pal_len) && pal_begin && pal_len > 0) {
    const int n = turtle_gpu_palette_from_hex_text(pal_begin, pal_len);
    if (n > 0) {
      if (n < 32) {
        Serial.printf(
            "Paleta del cartucho: %d colores validos; indices %d..31 -> #000000\n", n, n);
      } else {
        Serial.printf("Paleta del cartucho: 32 colores (indices 0..31)\n");
      }
    } else {
      Serial.println(
          "PALETTE: presente pero sin lineas #RRGGBB validas; uso paleta por defecto.");
      turtle_gpu_palette_reset_default();
    }
  } else {
    Serial.println("Sin PALETTE: en cartucho; paleta por defecto (Genesis-like).");
    turtle_gpu_palette_reset_default();
  }

  const char* lua_begin = nullptr;
  size_t lua_len = 0;
  if (!turtle_cart_extract_embedded(&g_cart, entry, &lua_begin, &lua_len)) {
    Serial.printf("Error: no se encontro bloque ---FILE:%s--- en cartucho\n", entry);
    turtle_cart_free(&g_cart);
    turtle_cart_free(&g_bundle);
    g_has_bundle = false;
    return false;
  }

  Serial.println("TurtleCart cargado correctamente");
  Serial.printf("Cart: %u bytes, bundle: %u bytes\n", static_cast<unsigned>(g_cart.len),
                static_cast<unsigned>(g_bundle.len));
  Serial.print("ENTRY: ");
  Serial.println(entry);
  Serial.print("INITIAL_SCENE: ");
  Serial.println(g_initial_scene);

  Serial.println("--- Lua ---");
  const bool lua_ok = runCartEntryLua(lua_begin, lua_len, entry);
  if (!lua_ok) {
    Serial.println("Lua fallo (revisa ENTRY / sintaxis).");
    turtle_cart_free(&g_cart);
    turtle_cart_free(&g_bundle);
    g_has_bundle = false;
    turtle_gpu_flip();
    return true;
  }
  Serial.println("--- Lua termino sin error ---");

  turtle_cart_free(&g_cart);
  g_cart.data = nullptr;
  g_cart.len = 0;

  return true;
}

static void drawInitialSceneFromBundle(void) {
  g_runtime_active = false;
  if (g_has_bundle && g_bundle.data && g_bundle.len > 0) {
    if (turtle_scene_begin_runtime(g_bundle.data, g_bundle.len, g_initial_scene)) {
      g_runtime_active = turtle_scene_runtime_active();
      Serial.println("Escena inicial (runtime: fondo estatico + sprites animados).");
    } else {
      Serial.println("Aviso: bundle presente pero escena runtime no iniciada.");
    }
  } else {
    Serial.println("Sin bundle: omitido dibujo de escena C++.");
  }

  if (!g_runtime_active) {
    turtle_cart_free(&g_bundle);
    g_has_bundle = false;
  }
  turtle_gpu_flip();
  g_last_tick_ms = millis();
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println("== TurtleReader + Lua + GPU (164x124, 32 col) ==");
#if defined(ESP32) || defined(ESP_PLATFORM)
  log_heap_caps("boot");
#endif

  turtle_gpu_init();
  turtle_input_init();
  Serial.println("Entrada: 8 botones (0-3 dir, 4-7 A-D); ajusta TURTLE_BTN_PIN_* en turtle_input.h");
#if !TURTLE_USE_DISPLAY
  Serial.println("Pantalla: desactivada (TURTLE_USE_DISPLAY=0). cls/pix/flip solo en RAM.");
#endif

  showBootMessage("READING\nSD CARD...");

  if (!mountSdWithRetries()) {
    Serial.println("Error: no se pudo montar microSD");
    showBootMessage("CANNOT READ\nTHE CARTRIDGE\nPLEASE RESET\nTHE CONSOLE");
    return;
  }

  Serial.println("microSD montada");
  Serial.println(
      "Formato paquete: main.turtlecart + studio/project_bundle.json + backgrounds/ + "
      "sprites/ + objects/ + scripts/ en raiz SD.");
  Serial.println(
      "Lua: ENTRY (cartucho, 1x) + scripts/<stem>.lua por objeto (cada frame, ver spec/lua/firmware-bridge-v0.md)");

  if (loadCartRunLua("/main.turtlecart")) {
#if defined(ESP32) || defined(ESP_PLATFORM)
    log_heap_caps("tras cart+bundle");
#endif
    drawInitialSceneFromBundle();
    Serial.println("Listo.");
    return;
  }

  Serial.println("Aviso: main.turtlecart no cargado; probando demo.turtlecart...");
  if (loadCartRunLua("/demo.turtlecart")) {
    drawInitialSceneFromBundle();
    Serial.println("Listo (demo).");
    return;
  }

  Serial.println("Error: ningun cartucho valido en la SD.");
  showBootMessage("CANNOT READ\nTHE CARTRIDGE\nPLEASE RESET\nTHE CONSOLE");
}

void loop() {
  if (!g_runtime_active || !g_bundle.data || g_bundle.len == 0) {
    turtle_input_poll();
    delay(50);
    return;
  }

  const uint32_t now = millis();
  const uint32_t delta = now - g_last_tick_ms;
  g_last_tick_ms = now;

  const int target_fps = turtle_scene_target_fps();
  const uint32_t frame_ms =
      (target_fps > 0) ? (1000u / static_cast<uint32_t>(target_fps)) : 33u;

  static uint32_t accum = 0;
  accum += delta;
  if (accum < frame_ms) {
    delay(1);
    return;
  }
  accum -= frame_ms;
  if (accum > frame_ms) {
    accum %= frame_ms;
  }

  turtle_input_poll();
  turtle_scene_runtime_tick(frame_ms);
  turtle_gpu_flip();
}
