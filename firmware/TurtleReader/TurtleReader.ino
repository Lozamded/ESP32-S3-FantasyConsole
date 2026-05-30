#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <string.h>

#include "turtle_cart.h"
#include "turtle_gpu.h"
#include "turtle_input.h"
#include "turtle_scene.h"

extern "C" {
#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>
}

// microSD (SPI). Ajusta a tu cableado.
static const int SD_SCK_PIN = 36; //azul
static const int SD_MISO_PIN = 37; //morado
static const int SD_MOSI_PIN = 38; //gris
static const int SD_CS_PIN = 39; //blanco

SPIClass sdSPI(FSPI);

static bool mountSd(uint32_t frequencyHz) {
  sdSPI.begin(SD_SCK_PIN, SD_MISO_PIN, SD_MOSI_PIN, SD_CS_PIN);
  return SD.begin(SD_CS_PIN, sdSPI, frequencyHz);
}

static bool mountSdWithRetries() {
  const uint32_t speeds[] = {400000, 1000000, 100000};
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

static TurtleCartBuffer g_cart = {};
static TurtleCartBuffer g_bundle = {};
static char g_initial_scene[64] = "intro";
static bool g_has_bundle = false;
static bool g_runtime_active = false;
static uint32_t g_last_tick_ms = 0;

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
  Serial.println("== TurtleReader + Lua + GPU (264x198, 32 col) ==");

  turtle_gpu_init();
  turtle_input_init();
  Serial.println("Entrada: 8 botones (0-3 dir, 4-7 A-D); ajusta TURTLE_BTN_PIN_* en turtle_input.h");
#if !TURTLE_USE_DISPLAY
  Serial.println("Pantalla: desactivada (TURTLE_USE_DISPLAY=0). cls/pix/flip solo en RAM.");
#endif

  if (!mountSdWithRetries()) {
    Serial.println("Error: no se pudo montar microSD");
    return;
  }

  Serial.println("microSD montada");
  Serial.println(
      "Formato paquete: main.turtlecart + studio/project_bundle.json + backgrounds/ + "
      "sprites/ + objects/ + scripts/ en raiz SD.");
  Serial.println(
      "Lua: ENTRY (cartucho, 1x) + scripts/<stem>.lua por objeto (cada frame, ver spec/lua/firmware-bridge-v0.md)");

  if (loadCartRunLua("/main.turtlecart")) {
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
}

void loop() {
  turtle_input_poll();

  if (!g_runtime_active || !g_bundle.data || g_bundle.len == 0) {
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

  turtle_scene_runtime_tick(frame_ms);
  turtle_gpu_flip();
}
