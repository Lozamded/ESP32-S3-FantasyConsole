#include "turtle_input.h"

#include <Arduino.h>

extern "C" {
#include <lua.h>
#include <lauxlib.h>
}

namespace {

struct BtnPin {
  int8_t gpio;
};

static const BtnPin k_pins[TURTLE_BTN_COUNT] = {
    {static_cast<int8_t>(TURTLE_BTN_PIN_LEFT)},
    {static_cast<int8_t>(TURTLE_BTN_PIN_RIGHT)},
    {static_cast<int8_t>(TURTLE_BTN_PIN_UP)},
    {static_cast<int8_t>(TURTLE_BTN_PIN_DOWN)},
    {static_cast<int8_t>(TURTLE_BTN_PIN_A)},
    {static_cast<int8_t>(TURTLE_BTN_PIN_B)},
    {static_cast<int8_t>(TURTLE_BTN_PIN_C)},
    {static_cast<int8_t>(TURTLE_BTN_PIN_D)},
};

static uint8_t s_stable = 0;
static uint8_t s_prev_stable = 0;
static uint8_t s_pressed = 0;
static uint8_t s_released = 0;
/** Flancos de pulsacion retenidos hasta que Lua llama btnp (sobreviven polls extra). */
static uint8_t s_pressed_latch = 0;
static uint8_t s_debounce_count[TURTLE_BTN_COUNT];
static uint8_t s_debounce_candidate[TURTLE_BTN_COUNT];

static bool valid_btn(int btn) {
  return btn >= 0 && btn < TURTLE_BTN_COUNT;
}

static uint8_t read_raw_mask(void) {
  uint8_t mask = 0;
  for (int i = 0; i < TURTLE_BTN_COUNT; ++i) {
    const int pin = k_pins[i].gpio;
    if (pin < 0) {
      continue;
    }
    if (digitalRead(pin) == LOW) {
      mask |= static_cast<uint8_t>(1u << i);
    }
  }
  return mask;
}

static void debounce_update(uint8_t raw) {
  for (int i = 0; i < TURTLE_BTN_COUNT; ++i) {
    const uint8_t bit = static_cast<uint8_t>(1u << i);
    const bool raw_on = (raw & bit) != 0;
    const bool stable_on = (s_stable & bit) != 0;

    if (raw_on == stable_on) {
      s_debounce_count[i] = 0;
      continue;
    }

    if (raw_on == ((s_debounce_candidate[i] & bit) != 0)) {
      if (s_debounce_count[i] < 255) {
        ++s_debounce_count[i];
      }
    } else {
      s_debounce_candidate[i] = raw_on ? bit : 0;
      s_debounce_count[i] = 1;
    }

    if (s_debounce_count[i] >= TURTLE_BTN_DEBOUNCE_SAMPLES) {
      if (raw_on) {
        s_stable |= bit;
      } else {
        s_stable &= static_cast<uint8_t>(~bit);
      }
      s_debounce_count[i] = 0;
    }
  }
}

static int lua_btn_index(lua_State* L, int arg) {
  const lua_Integer v = luaL_checkinteger(L, arg);
  if (v < 0 || v >= TURTLE_BTN_COUNT) {
    return luaL_error(L, "btn index out of range (0..%d)", TURTLE_BTN_COUNT - 1);
  }
  return static_cast<int>(v);
}

static int l_btn(lua_State* L) {
  const int i = lua_btn_index(L, 1);
  lua_pushboolean(L, turtle_input_held(i));
  return 1;
}

static int l_btnp(lua_State* L) {
  const int i = lua_btn_index(L, 1);
  lua_pushboolean(L, turtle_input_pressed(i));
  return 1;
}

}  // namespace

void turtle_input_init(void) {
  s_stable = 0;
  s_prev_stable = 0;
  s_pressed = 0;
  s_released = 0;
  s_pressed_latch = 0;
  memset(s_debounce_count, 0, sizeof s_debounce_count);
  memset(s_debounce_candidate, 0, sizeof s_debounce_candidate);

  for (int i = 0; i < TURTLE_BTN_COUNT; ++i) {
    const int pin = k_pins[i].gpio;
    if (pin < 0) {
      continue;
    }
    pinMode(pin, INPUT_PULLUP);
  }

  const uint8_t raw = read_raw_mask();
  s_stable = raw;
  s_prev_stable = raw;
}

void turtle_input_poll(void) {
  const uint8_t raw = read_raw_mask();
  debounce_update(raw);
  s_pressed = static_cast<uint8_t>(s_stable & ~s_prev_stable);
  s_pressed_latch |= s_pressed;
  s_released = static_cast<uint8_t>(~s_stable & s_prev_stable);
  s_prev_stable = s_stable;
}

bool turtle_input_held(int btn) {
  if (!valid_btn(btn)) {
    return false;
  }
  return (s_stable & static_cast<uint8_t>(1u << btn)) != 0;
}

bool turtle_input_pressed(int btn) {
  if (!valid_btn(btn)) {
    return false;
  }
  const uint8_t bit = static_cast<uint8_t>(1u << btn);
  if ((s_pressed_latch & bit) == 0) {
    return false;
  }
  s_pressed_latch &= static_cast<uint8_t>(~bit);
  return true;
}

bool turtle_input_released(int btn) {
  if (!valid_btn(btn)) {
    return false;
  }
  return (s_released & static_cast<uint8_t>(1u << btn)) != 0;
}

uint8_t turtle_input_held_mask(void) {
  return s_stable;
}

void turtle_input_register_lua(lua_State* L) {
  lua_pushcfunction(L, l_btn);
  lua_setglobal(L, "btn");

  lua_pushcfunction(L, l_btnp);
  lua_setglobal(L, "btnp");
}
