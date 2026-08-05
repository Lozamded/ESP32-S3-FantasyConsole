// Etapa 1/2 de bring-up del driver de video compuesto RCA (ESP32-P4).
// spec/rca-composite-driver-v0.md. NO lee cartucho ni corre Lua todavia --
// unico objetivo: confirmar que la TV engancha una imagen estable (Etapa 1,
// campo negro) y que los niveles/letterboxing se ven bien (Etapa 2, gris
// medio) antes de integrar con el resto del firmware.
//
// Placa: ESP32-P4 (Arduino-ESP32 3.3.x ya trae soporte P4). Cablear la
// escalera R-2R de 8 bits + atenuador/acople + salida 75 ohm segun
// spec/rca-composite-driver-v0.md antes de conectar a una TV real.

#include "turtle_gpu_composite.h"

// Cambiar a false para volver a la Etapa 1 (campo negro solido) si hace
// falta aislar si un problema es de sync o de nivel de gris.
static const bool kStage2SolidGray = true;

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("TurtleReaderP4 composite bring-up");
  Serial.printf("TURTLE_VIDEO_STD=%d (0=NTSC,1=PAL; solo NTSC implementado en v0)\n",
                TURTLE_VIDEO_STD);

  if (!turtle_gpu_composite_init()) {
    Serial.println("turtle_gpu_composite_init fallo -- revisar log anterior");
    return;
  }

  const uint8_t level =
      kStage2SolidGray ? TURTLE_COMPOSITE_LEVEL_MID_GRAY : TURTLE_COMPOSITE_LEVEL_BLACK;
  if (!turtle_gpu_composite_start_solid_field(level)) {
    Serial.println("turtle_gpu_composite_start_solid_field fallo");
    return;
  }
  Serial.println("Campo en loop por DMA -- deberia verse estable en la TV (sin roll).");
}

void loop() {
  // Todo el trabajo lo hace PARLIO por DMA; el CPU queda libre.
  delay(1000);
}
