#pragma once

#include <stdint.h>

struct lua_State;

/** Indices de boton (v0: 12 = D-pad + A-D + START/BACK + L/R). */
enum TurtleBtn : int {
  TURTLE_BTN_LEFT = 0,
  TURTLE_BTN_RIGHT = 1,
  TURTLE_BTN_UP = 2,
  TURTLE_BTN_DOWN = 3,
  TURTLE_BTN_A = 4,
  TURTLE_BTN_B = 5,
  TURTLE_BTN_C = 6,
  TURTLE_BTN_D = 7,
  TURTLE_BTN_START = 8,
  TURTLE_BTN_BACK = 9,
  TURTLE_BTN_L = 10,
  TURTLE_BTN_R = 11,
  TURTLE_BTN_COUNT = 12,
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
/*
 * START/BACK/L/R: GPIO libres y sin strapping (no 0/3/45/46), fuera de UART0 (43/44) y del
 * LED RGB de algunas placas N16R8 (48). Audio usa 14 y 42.
 */
#ifndef TURTLE_BTN_PIN_START
#define TURTLE_BTN_PIN_START 1
#endif
#ifndef TURTLE_BTN_PIN_BACK
#define TURTLE_BTN_PIN_BACK 2
#endif
#ifndef TURTLE_BTN_PIN_L
#define TURTLE_BTN_PIN_L 38
#endif
#ifndef TURTLE_BTN_PIN_R
#define TURTLE_BTN_PIN_R 39
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
uint16_t turtle_input_held_mask(void);

void turtle_input_register_lua(lua_State* L);

/**
 * spec/gui-layer-v0.md: variante para VMs de actor. Igual API que la version normal, pero
 * btn/btnp devuelven `false` mientras una capa GUI visible tenga `captures_input: true`.
 * La VM ENTRY sigue usando la version normal para poder navegar menus con input real.
 */
void turtle_input_register_lua_actor(lua_State* L);
