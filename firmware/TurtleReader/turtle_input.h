#pragma once

#include <stdint.h>

struct lua_State;

/** Indices de boton (v0: 8; futuro hasta 11). */
enum TurtleBtn : int {
  TURTLE_BTN_LEFT = 0,
  TURTLE_BTN_RIGHT = 1,
  TURTLE_BTN_UP = 2,
  TURTLE_BTN_DOWN = 3,
  TURTLE_BTN_A = 4,
  TURTLE_BTN_B = 5,
  TURTLE_BTN_C = 6,
  TURTLE_BTN_D = 7,
  TURTLE_BTN_COUNT = 8,
};

/*
 * Pines por defecto (ESP32-S3 + PSRAM OPI): evitan TFT 8-13 y SD 19/20/21/41.
 * No uses GPIO 33-37 (bus octal PSRAM). Un extremo del pulsador -> GPIO, otro -> GND (LOW).
 * Cambia con -DTURTLE_BTN_PIN_LEFT=... al compilar o edita aqui.
 */
#ifndef TURTLE_BTN_PIN_LEFT
#define TURTLE_BTN_PIN_LEFT 4
#endif
#ifndef TURTLE_BTN_PIN_RIGHT
#define TURTLE_BTN_PIN_RIGHT 5
#endif
#ifndef TURTLE_BTN_PIN_UP
#define TURTLE_BTN_PIN_UP 6
#endif
#ifndef TURTLE_BTN_PIN_DOWN
#define TURTLE_BTN_PIN_DOWN 7
#endif
#ifndef TURTLE_BTN_PIN_A
#define TURTLE_BTN_PIN_A 15
#endif
#ifndef TURTLE_BTN_PIN_B
#define TURTLE_BTN_PIN_B 16
#endif
#ifndef TURTLE_BTN_PIN_C
#define TURTLE_BTN_PIN_C 17
#endif
#ifndef TURTLE_BTN_PIN_D
#define TURTLE_BTN_PIN_D 18
#endif

/** Antirebote: lecturas consecutivas iguales antes de cambiar estado (1 = sin filtro extra). */
#ifndef TURTLE_BTN_DEBOUNCE_SAMPLES
#define TURTLE_BTN_DEBOUNCE_SAMPLES 1
#endif

void turtle_input_init(void);
/** Llamar una vez por fotograma (p. ej. al inicio de loop). */
void turtle_input_poll(void);

bool turtle_input_held(int btn);
bool turtle_input_pressed(int btn);
bool turtle_input_released(int btn);
uint8_t turtle_input_held_mask(void);

void turtle_input_register_lua(lua_State* L);
