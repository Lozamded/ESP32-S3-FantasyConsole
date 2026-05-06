#include <Arduino.h>
#include <SPI.h>
#include <SD.h>

// Ajusta estos pines a tu cableado real de microSD.
// Los valores de ejemplo son comunes en ESP32-S3 DevKit.
static const int SD_SCK_PIN = 36;
static const int SD_MISO_PIN = 37;
static const int SD_MOSI_PIN = 35;
static const int SD_CS_PIN = 34;

SPIClass sdSPI(FSPI);

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

String extractPrintMessage(const String& luaSource) {
  int printPos = luaSource.indexOf("print(");
  if (printPos < 0) {
    return "";
  }

  int firstQuote = luaSource.indexOf('"', printPos);
  if (firstQuote < 0) {
    return "";
  }

  int secondQuote = luaSource.indexOf('"', firstQuote + 1);
  if (secondQuote < 0) {
    return "";
  }

  return luaSource.substring(firstQuote + 1, secondQuote);
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println("== FantasyConsole TurtleCart Loader v0 ==");

  sdSPI.begin(SD_SCK_PIN, SD_MISO_PIN, SD_MOSI_PIN, SD_CS_PIN);
  if (!SD.begin(SD_CS_PIN, sdSPI)) {
    Serial.println("Error: no se pudo montar microSD");
    return;
  }

  Serial.println("microSD montada");

  const String cartContent = readFile("/demo.turtlecart");
  if (cartContent.length() == 0) {
    Serial.println("Error: no se pudo leer /demo.turtlecart");
    return;
  }

  if (!cartContent.startsWith("TURTLECART:0")) {
    Serial.println("Error: header invalido (se esperaba TURTLECART:0)");
    return;
  }

  const String entry = getHeaderValue(cartContent, "ENTRY:");
  if (entry.length() == 0) {
    Serial.println("Error: cartucho sin ENTRY");
    return;
  }

  String mainLua = extractEmbeddedFile(cartContent, entry);
  if (mainLua.length() == 0) {
    Serial.println("Error: no se encontro archivo ENTRY en cartucho");
    return;
  }

  mainLua.trim();

  Serial.println("TurtleCart cargado correctamente");
  Serial.print("ENTRY: ");
  Serial.println(entry);
  Serial.println("Contenido de main.lua:");
  Serial.println(mainLua);

  const String msg = extractPrintMessage(mainLua);
  if (msg.length() > 0) {
    Serial.print("Mensaje en main.lua: ");
    Serial.println(msg);
  } else {
    Serial.println("No se encontro print(\"...\") en main.lua");
  }
}

void loop() {
  // MVP: sin loop de juego todavia.
}
