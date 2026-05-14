#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <string.h>

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

String readFile(const char* path) {
  File file = SD.open(path, FILE_READ);
  if (!file) {
    return "";
  }

  String content;
  while (file.available()) {
    content += static_cast<char>(file.read());
  }
  file.close();
  return content;
}

String getHeaderValue(const String& cartContent, const String& key) {
  int start = cartContent.indexOf(key);
  if (start < 0) {
    return "";
  }

  int lineEnd = cartContent.indexOf('\n', start);
  if (lineEnd < 0) {
    lineEnd = cartContent.length();
  }

  return cartContent.substring(start + key.length(), lineEnd);
}

/** Texto entre la linea siguiente a PALETTE: y el primer ---FILE: (opcional). */
String extractPaletteSection(const String& cart) {
  const char* tag = "PALETTE:";
  int p = cart.indexOf(tag);
  while (p >= 0) {
    if (p > 0) {
      const char prev = cart.charAt(static_cast<unsigned>(p - 1));
      if (prev != '\n' && prev != '\r') {
        p = cart.indexOf(tag, p + 1);
        continue;
      }
    }
    break;
  }
  if (p < 0) {
    return "";
  }
  const int afterTag = static_cast<int>(p + strlen(tag));
  int lineEnd = cart.indexOf('\n', afterTag);
  if (lineEnd < 0) {
    lineEnd = cart.length();
  }
  const int contentStart = lineEnd + 1;
  if (contentStart > cart.length()) {
    return "";
  }
  const int fileMark = cart.indexOf("---FILE:", contentStart);
  if (fileMark < 0) {
    return cart.substring(contentStart);
  }
  return cart.substring(contentStart, fileMark);
}

String extractEmbeddedFile(const String& cartContent, const String& filePath) {
  String markerStart = "---FILE:" + filePath + "---";
  int startMarkerPos = cartContent.indexOf(markerStart);
  if (startMarkerPos < 0) {
    return "";
  }

  int fileStart = cartContent.indexOf('\n', startMarkerPos);
  if (fileStart < 0) {
    return "";
  }
  fileStart += 1;

  int fileEnd = cartContent.indexOf("---END---", fileStart);
  if (fileEnd < 0) {
    return "";
  }

  return cartContent.substring(fileStart, fileEnd);
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

static bool runCartEntryLua(const String& source, const char* chunkName) {
  lua_State* L = luaL_newstate();
  if (!L) {
    Serial.println("Lua: luaL_newstate fallo");
    return false;
  }

  luaL_openlibs(L);
  lua_pushcfunction(L, l_serial_print);
  lua_setglobal(L, "print");

  turtle_gpu_register_lua(L);

  int st = luaL_loadbuffer(L, source.c_str(), source.length(), chunkName);
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

  // Preferencia: cartucho de arranque exportado por TurtleStudio (`build/main.turtlecart` -> raiz SD).
  // Compatibilidad: si no existe, intentar el demo antiguo.
  String cartContent = readFile("/main.turtlecart");
  const char* cartPath = "/main.turtlecart";
  if (cartContent.length() == 0) {
    cartContent = readFile("/demo.turtlecart");
    cartPath = "/demo.turtlecart";
  }
  if (cartContent.length() == 0) {
    Serial.println("Error: no se pudo leer /main.turtlecart ni /demo.turtlecart en la raiz de la SD");
    return;
  }

  Serial.print("Cartucho SD: ");
  Serial.println(cartPath);

  if (!cartContent.startsWith("TURTLECART:0")) {
    Serial.println("Error: header invalido (se esperaba TURTLECART:0)");
    return;
  }

  String entry = getHeaderValue(cartContent, "ENTRY:");
  entry.trim();
  if (entry.length() == 0) {
    Serial.println("Error: cartucho sin ENTRY");
    return;
  }

  String initialScene = getHeaderValue(cartContent, "INITIAL_SCENE:");
  initialScene.trim();
  if (initialScene.length() == 0) {
    initialScene = "intro";
  }

  String mainLua = extractEmbeddedFile(cartContent, entry);
  if (mainLua.length() == 0) {
    Serial.println("Error: no se encontro archivo ENTRY en cartucho");
    return;
  }

  mainLua.trim();

  const String palText = extractPaletteSection(cartContent);
  if (palText.length() > 0) {
    const int n = turtle_gpu_palette_from_hex_text(palText.c_str(), palText.length());
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
  }

  String bundleJson = extractEmbeddedFile(cartContent, "studio/project_bundle.json");
  bundleJson.trim();

  Serial.println("TurtleCart cargado correctamente");
  Serial.print("ENTRY: ");
  Serial.println(entry);
  Serial.print("INITIAL_SCENE: ");
  Serial.println(initialScene);
  Serial.println("Contenido del ENTRY:");
  Serial.println(mainLua);

  Serial.println("--- Lua ---");
  const bool lua_ok = runCartEntryLua(mainLua, entry.c_str());
  if (!lua_ok) {
    Serial.println("Lua fallo (revisa ENTRY / sintaxis).");
    turtle_gpu_flip();
    return;
  }
  Serial.println("--- Lua termino sin error ---");

  // Escena C++ despues del ENTRY: asi un cls()/flip() antiguo en el cartucho no deja la pantalla negra.
  if (bundleJson.length() > 0) {
    if (turtle_scene_draw_cart_bundle(bundleJson.c_str(), bundleJson.length(), initialScene.c_str())) {
      Serial.println("Escena inicial (C++ desde bundle) aplicada tras Lua.");
    } else {
      Serial.println("Aviso: bundle presente pero escena C++ no aplicada.");
    }
  } else {
    Serial.println("Sin studio/project_bundle.json: omitido dibujo de escena C++.");
  }

  turtle_gpu_flip();
}

void loop() {}
