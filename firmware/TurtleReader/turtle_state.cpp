#include "turtle_state.h"

#include <string.h>

extern "C" {
#include <lua.h>
#include <lauxlib.h>
}

namespace {

constexpr int kStateMaxSlots = 16;
constexpr int kStateKeyCap = 32;  // 31 chars + nul

struct Slot {
  char key[kStateKeyCap];
  int32_t value;
  bool used;
};

Slot s_slots[kStateMaxSlots];

int find_slot(const char* key) {
  for (int i = 0; i < kStateMaxSlots; ++i) {
    if (s_slots[i].used && strcmp(s_slots[i].key, key) == 0) return i;
  }
  return -1;
}

int alloc_slot(const char* key) {
  for (int i = 0; i < kStateMaxSlots; ++i) {
    if (!s_slots[i].used) {
      s_slots[i].used = true;
      strncpy(s_slots[i].key, key, kStateKeyCap - 1);
      s_slots[i].key[kStateKeyCap - 1] = '\0';
      s_slots[i].value = 0;
      return i;
    }
  }
  return -1;  // tabla llena, no se puede crear la clave
}

int l_state_set(lua_State* L) {
  const char* key = luaL_checkstring(L, 1);
  const int value = static_cast<int>(luaL_checkinteger(L, 2));
  turtle_state_set(key, value);
  lua_pushinteger(L, value);
  return 1;
}

int l_state_get(lua_State* L) {
  const char* key = luaL_checkstring(L, 1);
  int value = 0;
  if (turtle_state_get(key, &value)) {
    lua_pushinteger(L, value);
  } else {
    lua_pushnil(L);
  }
  return 1;
}

int l_state_add(lua_State* L) {
  const char* key = luaL_checkstring(L, 1);
  const int delta = static_cast<int>(luaL_checkinteger(L, 2));
  const int new_value = turtle_state_add(key, delta);
  lua_pushinteger(L, new_value);
  return 1;
}

}  // namespace

void turtle_state_reset(void) {
  memset(s_slots, 0, sizeof s_slots);
}

bool turtle_state_set(const char* key, int value) {
  if (!key || !*key) return false;
  int idx = find_slot(key);
  if (idx < 0) idx = alloc_slot(key);
  if (idx < 0) return false;
  s_slots[idx].value = value;
  return true;
}

bool turtle_state_get(const char* key, int* out_value) {
  if (!key || !*key) return false;
  int idx = find_slot(key);
  if (idx < 0) return false;
  if (out_value) *out_value = s_slots[idx].value;
  return true;
}

int turtle_state_add(const char* key, int delta) {
  if (!key || !*key) return 0;
  int idx = find_slot(key);
  if (idx < 0) idx = alloc_slot(key);
  if (idx < 0) return 0;
  s_slots[idx].value += delta;
  return s_slots[idx].value;
}

void turtle_state_register_lua(lua_State* L) {
  lua_pushcfunction(L, l_state_set);
  lua_setglobal(L, "state_set");
  lua_pushcfunction(L, l_state_get);
  lua_setglobal(L, "state_get");
  lua_pushcfunction(L, l_state_add);
  lua_setglobal(L, "state_add");
}
