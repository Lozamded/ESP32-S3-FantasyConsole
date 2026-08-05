#pragma once

#include <stddef.h>
#include <stdint.h>

// Driver de video compuesto (RCA) para ESP32-P4 via PARLIO TX + GDMA.
// Diseno: spec/rca-composite-driver-v0.md. Etapa 1 de bring-up: solo genera
// sync + un campo solido (negro o gris) para verificar que la TV engancha
// una imagen estable, sin framebuffer real todavia (ver Etapa 3 en el spec).

// PAL declarado para no tener que tocar esta interfaz cuando se implemente
// (spec/rca-composite-driver-v0.md "TURTLE_VIDEO_STD"); v0 solo llena NTSC.
enum TurtleVideoStd {
  TURTLE_VIDEO_NTSC = 0,
  TURTLE_VIDEO_PAL = 1,
};

#ifndef TURTLE_VIDEO_STD
#define TURTLE_VIDEO_STD TURTLE_VIDEO_NTSC
#endif

// --- Pines (ajustar segun cableado real; ver spec para la escalera R-2R) ---
#ifndef TURTLE_COMPOSITE_PIN_D0
#define TURTLE_COMPOSITE_PIN_D0 10
#endif
#ifndef TURTLE_COMPOSITE_PIN_D1
#define TURTLE_COMPOSITE_PIN_D1 11
#endif
#ifndef TURTLE_COMPOSITE_PIN_D2
#define TURTLE_COMPOSITE_PIN_D2 12
#endif
#ifndef TURTLE_COMPOSITE_PIN_D3
#define TURTLE_COMPOSITE_PIN_D3 13
#endif
#ifndef TURTLE_COMPOSITE_PIN_D4
#define TURTLE_COMPOSITE_PIN_D4 14
#endif
#ifndef TURTLE_COMPOSITE_PIN_D5
#define TURTLE_COMPOSITE_PIN_D5 15
#endif
#ifndef TURTLE_COMPOSITE_PIN_D6
#define TURTLE_COMPOSITE_PIN_D6 16
#endif
#ifndef TURTLE_COMPOSITE_PIN_D7
#define TURTLE_COMPOSITE_PIN_D7 17
#endif
#ifndef TURTLE_COMPOSITE_PIN_CLK_OUT
#define TURTLE_COMPOSITE_PIN_CLK_OUT 18
#endif

// Reloj de muestreo objetivo (spec: 5 MHz -> 264 muestras exactas en video
// activo, 1:1 con el ancho de escena). PARLIO puede redondear a la frecuencia
// alcanzable mas cercana -- verificar con osciloscopio antes de confiar en
// las cuentas de muestras derivadas de esto.
#ifndef TURTLE_COMPOSITE_SAMPLE_HZ
#define TURTLE_COMPOSITE_SAMPLE_HZ 5000000
#endif

// Niveles de luma de 8 bits (0..255) para los tres niveles de voltaje del
// spec (0.0V / 0.3V / 1.0V sobre una salida R-2R de 0..3.3V, antes del
// atenuador+acople de la etapa analogica). Ajustar segun calibracion real.
#ifndef TURTLE_COMPOSITE_LEVEL_SYNC
#define TURTLE_COMPOSITE_LEVEL_SYNC 0
#endif
#ifndef TURTLE_COMPOSITE_LEVEL_BLACK
#define TURTLE_COMPOSITE_LEVEL_BLACK 25
#endif
#ifndef TURTLE_COMPOSITE_LEVEL_WHITE
#define TURTLE_COMPOSITE_LEVEL_WHITE 84
#endif
// Etapa 2 (spec): gris medio en la zona activa para verificar niveles y
// letterboxing antes de tener framebuffer real.
#ifndef TURTLE_COMPOSITE_LEVEL_MID_GRAY
#define TURTLE_COMPOSITE_LEVEL_MID_GRAY 54
#endif

// Inicializa PARLIO TX y arma la unidad (no empieza a transmitir).
// Devuelve false si la unidad PARLIO no se pudo crear/habilitar.
bool turtle_gpu_composite_init(void);

// Arma el campo estatico (Etapa 1: negro; Etapa 2: gris medio en zona
// activa) y arranca la transmision en loop por DMA. No vuelve a tocar CPU
// hasta que se llame turtle_gpu_composite_stop().
bool turtle_gpu_composite_start_solid_field(uint8_t active_level);

void turtle_gpu_composite_stop(void);
