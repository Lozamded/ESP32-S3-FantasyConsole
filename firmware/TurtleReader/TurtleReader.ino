#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <string.h>

#include "turtle_cart.h"
#include "turtle_gpu.h"
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

static bool loadAndRunCart(const char* path) {
  TurtleCartBuffer cart = {};
  if (!turtle_cart_load_sd_file(path, &cart)) {
    return false;
  }

  if (cart.len < 12 || memcmp(cart.data, "TURTLECART:0", 12) != 0) {
    Serial.println("Error: header invalido (se esperaba TURTLECART:0)");
    turtle_cart_free(&cart);
    return false;
  }

  char entry[128];
  if (!turtle_cart_header_value(&cart, "ENTRY:", entry, sizeof entry) || entry[0] == '\0') {
    Serial.println("Error: cartucho sin ENTRY");
    turtle_cart_free(&cart);
    return false;
  }

  char initialScene[64];
  if (!turtle_cart_header_value(&cart, "INITIAL_SCENE:", initialScene, sizeof initialScene) ||
      initialScene[0] == '\0') {
    strncpy(initialScene, "intro", sizeof initialScene);
    initialScene[sizeof initialScene - 1] = '\0';
  }

  const char* pal_begin = nullptr;
  size_t pal_len = 0;
  if (turtle_cart_extract_palette(&cart, &pal_begin, &pal_len) && pal_begin && pal_len > 0) {
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

  const char* bundle_begin = nullptr;
  size_t bundle_len = 0;
  const bool has_bundle =
      turtle_cart_extract_embedded(&cart, "studio/project_bundle.json", &bundle_begin, &bundle_len);

  const char* lua_begin = nullptr;
  size_t lua_len = 0;
  if (!turtle_cart_extract_embedded(&cart, entry, &lua_begin, &lua_len)) {
    Serial.printf("Error: no se encontro bloque ---FILE:%s--- en cartucho\n", entry);
    turtle_cart_free(&cart);
    return false;
  }

  Serial.println("TurtleCart cargado correctamente");
  Serial.print("ENTRY: ");
  Serial.println(entry);
  Serial.print("INITIAL_SCENE: ");
  Serial.println(initialScene);
  if (has_bundle) {
    Serial.printf("Bundle embebido: %u bytes\n", static_cast<unsigned>(bundle_len));
  }

  Serial.println("--- Lua ---");
  const bool lua_ok = runCartEntryLua(lua_begin, lua_len, entry);
  if (!lua_ok) {
    Serial.println("Lua fallo (revisa ENTRY / sintaxis).");
    turtle_cart_free(&cart);
    turtle_gpu_flip();
    return true;
  }
  Serial.println("--- Lua termino sin error ---");

  if (has_bundle && bundle_begin && bundle_len > 0) {
    if (turtle_scene_draw_cart_bundle(bundle_begin, bundle_len, initialScene)) {
      Serial.println("Escena inicial (C++ desde bundle) aplicada tras Lua.");
    } else {
      Serial.println("Aviso: bundle presente pero escena C++ no aplicada.");
    }
  } else {
    Serial.println("Sin studio/project_bundle.json: omitido dibujo de escena C++.");
  }

  turtle_cart_free(&cart);
  turtle_gpu_flip();
  return true;
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println("== TurtleReader + Lua + GPU (264x198, 32 col) ==");

  turtle_gpu_init();
#if !TURTLE_USE_DISPLAY
  Serial.println("Pantalla: desactivada (TURTLE_USE_DISPLAY=0). cls/pix/flip solo en RAM.");
#endif

  if (!mountSdWithRetries()) {
    Serial.println("Error: no se pudo montar microSD");
    return;
  }

  Serial.println("microSD montada");
  Serial.println(
      "Formato paquete: main.turtlecart + backgrounds/ + sprites/ + objects/ en raiz SD.");

  if (loadAndRunCart("/main.turtlecart")) {
    Serial.println("Listo.");
    return;
  }

  Serial.println("Aviso: main.turtlecart no cargado; probando demo.turtlecart...");
  if (loadAndRunCart("/demo.turtlecart")) {
    Serial.println("Listo (demo).");
    return;
  }

  Serial.println("Error: ningun cartucho valido en la SD.");
}

void loop() {}
