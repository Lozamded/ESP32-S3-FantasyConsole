#include "turtle_entry_lua.h"

#include <Arduino.h>

extern "C" {
#include <lauxlib.h>
#include <lua.h>
}

static lua_State* s_entry_L = nullptr;

void turtle_entry_lua_take(lua_State* L) {
  turtle_entry_lua_release();
  s_entry_L = L;
}

void turtle_entry_lua_release(void) {
  if (s_entry_L) {
    lua_close(s_entry_L);
    s_entry_L = nullptr;
  }
}

bool turtle_entry_lua_is_active(void) {
  return s_entry_L != nullptr;
}

// Empuja `global` en la cima de la pila; devuelve true si es una funcion. Si no lo es,
// desapila y devuelve false. Uso interno para _hud_init / _hud.
static bool push_global_function(const char* name) {
  if (!s_entry_L) {
    return false;
  }
  lua_getglobal(s_entry_L, name);
  if (lua_isfunction(s_entry_L, -1)) {
    return true;
  }
  lua_pop(s_entry_L, 1);
  return false;
}

void turtle_entry_lua_call_hud_init(void) {
  if (!push_global_function("_hud_init")) {
    return;
  }
  const int st = lua_pcall(s_entry_L, 0, 0, 0);
  if (st != LUA_OK) {
    Serial.print("Lua (_hud_init): ");
    Serial.println(lua_tostring(s_entry_L, -1));
    lua_pop(s_entry_L, 1);
  }
}

void turtle_entry_lua_call_hud(uint32_t delta_ms) {
  if (!push_global_function("_hud")) {
    return;
  }
  lua_pushnumber(s_entry_L, static_cast<lua_Number>(delta_ms) / 1000.0);
  const int st = lua_pcall(s_entry_L, 1, 0, 0);
  if (st != LUA_OK) {
    Serial.print("Lua (_hud): ");
    Serial.println(lua_tostring(s_entry_L, -1));
    lua_pop(s_entry_L, 1);
  }
}
