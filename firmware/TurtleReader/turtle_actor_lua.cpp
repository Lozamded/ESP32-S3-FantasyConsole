#include "turtle_actor_lua.h"

#include "turtle_input.h"
#include "turtle_scene.h"

#include <Arduino.h>
#include <SD.h>
#include <stdlib.h>
#include <string.h>

extern "C" {
#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>
}

namespace {

constexpr int kMaxActors = 96;
constexpr int kMaxScriptStem = 40;

static lua_State* s_L = nullptr;
static int s_update_ref[kMaxActors];
static char s_script_stem[kMaxActors][kMaxScriptStem];
static int s_script_actor_count = 0;

static int l_serial_print(lua_State* L) {
  int n = lua_gettop(L);
  for (int i = 1; i <= n; i++) {
    if (i > 1) {
      Serial.print('\t');
    }
    const char* msg = luaL_tolstring(L, i, nullptr);
    Serial.print(msg);
    lua_pop(L, 1);
  }
  Serial.println();
  return 0;
}

static int l_axis(lua_State* L) {
  const int neg_btn = static_cast<int>(luaL_checkinteger(L, 1));
  const int pos_btn = static_cast<int>(luaL_checkinteger(L, 2));
  int v = 0;
  if (turtle_input_held(neg_btn)) {
    v -= 1;
  }
  if (turtle_input_held(pos_btn)) {
    v += 1;
  }
  lua_pushinteger(L, v);
  return 1;
}

static int l_posx(lua_State* L) {
  int x = 0;
  int y = 0;
  if (!turtle_scene_actor_pos(&x, &y)) {
    lua_pushinteger(L, 0);
    return 1;
  }
  lua_pushinteger(L, x);
  return 1;
}

static int l_posy(lua_State* L) {
  int x = 0;
  int y = 0;
  if (!turtle_scene_actor_pos(&x, &y)) {
    lua_pushinteger(L, 0);
    return 1;
  }
  lua_pushinteger(L, y);
  return 1;
}

static int lua_round_to_int(lua_Number v) {
  if (v >= 0.0) {
    return static_cast<int>(v + 0.5);
  }
  return static_cast<int>(v - 0.5);
}

static int l_move(lua_State* L) {
  const lua_Number mx = luaL_checknumber(L, 1);
  const lua_Number my = luaL_checknumber(L, 2);
  const int dx = lua_round_to_int(mx);
  const int dy = lua_round_to_int(my);
  int ax = 0;
  int ay = 0;
  turtle_scene_actor_move(dx, dy, &ax, &ay);
  lua_pushinteger(L, ax);
  lua_pushinteger(L, ay);
  return 2;
}

static int l_on_ground(lua_State* L) {
  lua_pushboolean(L, turtle_scene_actor_on_ground());
  return 1;
}

static int l_set_anim(lua_State* L) {
  const char* name = luaL_checkstring(L, 1);
  turtle_scene_actor_set_anim(name);
  return 0;
}

static int l_play_anim(lua_State* L) {
  const char* name = luaL_checkstring(L, 1);
  const lua_Number speed_n = luaL_optnumber(L, 2, 1.0);
  const bool repeat = lua_gettop(L) >= 3 ? lua_toboolean(L, 3) : true;
  turtle_scene_actor_play_anim(name, static_cast<float>(speed_n), repeat);
  return 0;
}

static int l_flip_h(lua_State* L) {
  turtle_scene_actor_set_flip_h(lua_toboolean(L, 1));
  return 0;
}

/** spec/lua/object-script-v0.md "Cambio de escena": pide el cambio a `scene_id` -- no se
 *  aplica de inmediato (ver turtle_scene_request_switch), asi que el resto de los actores
 *  siguen recibiendo _update(dt) de la escena VIEJA hasta que termine este fotograma. */
static int l_goto_scene(lua_State* L) {
  const char* scene_id = luaL_checkstring(L, 1);
  turtle_scene_request_switch(scene_id);
  return 0;
}

/**
 * text(str, font_id [, dx, dy, color_index]) — overlay de texto del actor actual,
 * persistente hasta el siguiente text(). text("") lo borra. (dx, dy) offset opcional
 * (0,0 = ancla del actor). `color_index` (0..30) opcional tiñe el texto en vez de usar
 * los colores propios del glifo.
 * NOTA: firma distinta a la de la VM ENTRY (text(sx, sy, str, font_id, color_index),
 * coords absolutas escena) — aqui es relativo al actor, como flip_h/set_anim.
 * Ver spec/lua/firmware-bridge-v0.md.
 */
static int l_text(lua_State* L) {
  const char* str = luaL_checkstring(L, 1);
  const char* font_id = luaL_optstring(L, 2, "");
  const int dx = static_cast<int>(luaL_optinteger(L, 3, 0));
  const int dy = static_cast<int>(luaL_optinteger(L, 4, 0));
  const int color_index = static_cast<int>(luaL_optinteger(L, 5, -1));
  turtle_scene_actor_set_text(str, dx, dy, font_id, color_index);
  return 0;
}

/** text_width(str, font_id) -> ancho en px, sin dibujar. */
static int l_text_width(lua_State* L) {
  const char* str = luaL_checkstring(L, 1);
  const char* font_id = luaL_checkstring(L, 2);
  lua_pushinteger(L, turtle_scene_measure_text_active(font_id, str));
  return 1;
}

// spec/scene-object-identity-v0.md: buscar/consultar otros actores por id/tag unico de
// instancia. Handle = indice 1-based (convencion Lua) devuelto por find_by_id/find_by_tag;
// las funciones obj_* lo convierten de vuelta a 0-based antes de llamar a turtle_scene.cpp.

/** self_id() -> id de la instancia cuyo script se esta ejecutando este fotograma. */
static int l_self_id(lua_State* L) {
  char buf[40];
  if (!turtle_scene_actor_id(buf, sizeof buf)) {
    lua_pushnil(L);
    return 1;
  }
  lua_pushstring(L, buf);
  return 1;
}

/** find_by_id(id) -> handle (entero) o nil si no hay ningun actor con ese id en la escena. */
static int l_find_by_id(lua_State* L) {
  const char* id = luaL_checkstring(L, 1);
  int idx = -1;
  if (!turtle_scene_find_actor_by_id(id, &idx)) {
    lua_pushnil(L);
    return 1;
  }
  lua_pushinteger(L, idx + 1);
  return 1;
}

/** find_by_tag(tag) -> tabla (array) de handles, vacia si ninguno matchea. */
static int l_find_by_tag(lua_State* L) {
  const char* tag = luaL_checkstring(L, 1);
  int idxs[kMaxActors];
  const int n = turtle_scene_find_actors_by_tag(tag, idxs, kMaxActors);
  lua_createtable(L, n, 0);
  for (int i = 0; i < n; ++i) {
    lua_pushinteger(L, idxs[i] + 1);
    lua_rawseti(L, -2, i + 1);
  }
  return 1;
}

/** obj_posx(handle) -> X del actor en `handle`, o nil si el handle no es valido. */
static int l_obj_posx(lua_State* L) {
  const int handle = static_cast<int>(luaL_checkinteger(L, 1));
  int x = 0;
  int y = 0;
  if (!turtle_scene_actor_pos_at(handle - 1, &x, &y)) {
    lua_pushnil(L);
    return 1;
  }
  lua_pushinteger(L, x);
  return 1;
}

/** obj_posy(handle) -> Y del actor en `handle`, o nil si el handle no es valido. */
static int l_obj_posy(lua_State* L) {
  const int handle = static_cast<int>(luaL_checkinteger(L, 1));
  int x = 0;
  int y = 0;
  if (!turtle_scene_actor_pos_at(handle - 1, &x, &y)) {
    lua_pushnil(L);
    return 1;
  }
  lua_pushinteger(L, y);
  return 1;
}

/** obj_id(handle) -> id de instancia del actor en `handle`, o nil si el handle no es valido. */
static int l_obj_id(lua_State* L) {
  const int handle = static_cast<int>(luaL_checkinteger(L, 1));
  char buf[40];
  if (!turtle_scene_actor_id_at(handle - 1, buf, sizeof buf)) {
    lua_pushnil(L);
    return 1;
  }
  lua_pushstring(L, buf);
  return 1;
}

/** obj_has_tag(handle, tag) -> true si el actor en `handle` tiene `tag`. */
static int l_obj_has_tag(lua_State* L) {
  const int handle = static_cast<int>(luaL_checkinteger(L, 1));
  const char* tag = luaL_checkstring(L, 2);
  lua_pushboolean(L, turtle_scene_actor_has_tag_at(handle - 1, tag));
  return 1;
}

static void register_api(lua_State* L) {
  lua_pushcfunction(L, l_serial_print);
  lua_setglobal(L, "print");

  turtle_input_register_lua(L);

  lua_pushcfunction(L, l_axis);
  lua_setglobal(L, "axis");

  lua_pushcfunction(L, l_posx);
  lua_setglobal(L, "posx");

  lua_pushcfunction(L, l_posy);
  lua_setglobal(L, "posy");

  lua_pushcfunction(L, l_move);
  lua_setglobal(L, "move");

  lua_pushcfunction(L, l_on_ground);
  lua_setglobal(L, "on_ground");

  lua_pushcfunction(L, l_set_anim);
  lua_setglobal(L, "set_anim");

  lua_pushcfunction(L, l_play_anim);
  lua_setglobal(L, "play_anim");

  lua_pushcfunction(L, l_flip_h);
  lua_setglobal(L, "flip_h");

  lua_pushcfunction(L, l_text);
  lua_setglobal(L, "text");

  lua_pushcfunction(L, l_text_width);
  lua_setglobal(L, "text_width");

  lua_pushcfunction(L, l_goto_scene);
  lua_setglobal(L, "goto_scene");

  lua_pushcfunction(L, l_self_id);
  lua_setglobal(L, "self_id");

  lua_pushcfunction(L, l_find_by_id);
  lua_setglobal(L, "find_by_id");

  lua_pushcfunction(L, l_find_by_tag);
  lua_setglobal(L, "find_by_tag");

  lua_pushcfunction(L, l_obj_posx);
  lua_setglobal(L, "obj_posx");

  lua_pushcfunction(L, l_obj_posy);
  lua_setglobal(L, "obj_posy");

  lua_pushcfunction(L, l_obj_id);
  lua_setglobal(L, "obj_id");

  lua_pushcfunction(L, l_obj_has_tag);
  lua_setglobal(L, "obj_has_tag");
}

static bool load_script_update_ref(int actor_index, const char* stem) {
  if (!s_L || !stem || !stem[0] || actor_index < 0 || actor_index >= kMaxActors) {
    return false;
  }

  char path[64];
  snprintf(path, sizeof path, "/scripts/%s.lua", stem);

  if (!SD.exists(path)) {
    Serial.printf("turtle_actor_lua: falta %s\n", path);
    return false;
  }

  File f = SD.open(path, FILE_READ);
  if (!f) {
    Serial.printf("turtle_actor_lua: no abrio %s\n", path);
    return false;
  }

  // Lectura de un solo golpe a un buffer propio (no un String): scripts/<stem>.lua puede
  // ser texto Lua o bytecode Lua 5.4 precompilado (TurtleStudio exporta bytecode cuando
  // puede, ver tools/turtlestudio/lua_bytecode.py) -- el bytecode trae bytes arbitrarios,
  // incluido \0, que un String armado caracter a caracter no esta pensado para cargar.
  // luaL_loadbuffer ya toma un largo explicito, no depende de terminador nulo.
  const size_t len = f.size();
  uint8_t* buf = static_cast<uint8_t*>(malloc(len > 0 ? len : 1));
  if (!buf) {
    Serial.printf("turtle_actor_lua: sin RAM para %s (%u bytes)\n", path,
                  static_cast<unsigned>(len));
    f.close();
    return false;
  }
  const size_t got = f.read(buf, len);
  f.close();
  if (got != len) {
    Serial.printf("turtle_actor_lua: lectura incompleta %s (%u/%u bytes)\n", path,
                  static_cast<unsigned>(got), static_cast<unsigned>(len));
    free(buf);
    return false;
  }

  const char* chunk_name = path;
  int st = luaL_loadbuffer(s_L, reinterpret_cast<const char*>(buf), len, chunk_name);
  free(buf);
  if (st != LUA_OK) {
    Serial.printf("turtle_actor_lua: carga %s: %s\n", path, lua_tostring(s_L, -1));
    lua_pop(s_L, 1);
    return false;
  }

  st = lua_pcall(s_L, 0, 0, 0);
  if (st != LUA_OK) {
    Serial.printf("turtle_actor_lua: init %s: %s\n", path, lua_tostring(s_L, -1));
    lua_pop(s_L, 1);
    return false;
  }

  lua_getglobal(s_L, "_update");
  if (!lua_isfunction(s_L, -1)) {
    Serial.printf("turtle_actor_lua: %s sin funcion _update(dt)\n", path);
    lua_pop(s_L, 1);
    return false;
  }

  s_update_ref[actor_index] = luaL_ref(s_L, LUA_REGISTRYINDEX);
  return true;
}

}  // namespace

void turtle_actor_lua_init(void) {
  if (s_L) {
    return;
  }

  s_L = luaL_newstate();
  if (!s_L) {
    Serial.println("turtle_actor_lua: luaL_newstate fallo");
    return;
  }

  luaL_openlibs(s_L);
  // GC generacional: mejor ajustado que el incremental por defecto para el patron de
  // asignacion tipico de _update(dt) por actor (muchas tablas/closures chicas de vida
  // corta por frame); evita picos de tiempo de frame por pausas del incremental.
  lua_gc(s_L, LUA_GCGEN, 0, 0);
  lua_getglobal(s_L, "math");
  if (!lua_istable(s_L, -1)) {
    lua_pop(s_L, 1);
    luaL_requiref(s_L, LUA_MATHLIBNAME, luaopen_math, 1);
    lua_pop(s_L, 1);
  } else {
    lua_pop(s_L, 1);
  }
  register_api(s_L);

  for (int i = 0; i < kMaxActors; ++i) {
    s_update_ref[i] = LUA_NOREF;
    s_script_stem[i][0] = '\0';
  }
  s_script_actor_count = 0;
}

void turtle_actor_lua_shutdown(void) {
  if (!s_L) {
    return;
  }

  for (int i = 0; i < kMaxActors; ++i) {
    if (s_update_ref[i] != LUA_NOREF) {
      luaL_unref(s_L, LUA_REGISTRYINDEX, s_update_ref[i]);
      s_update_ref[i] = LUA_NOREF;
    }
  }

  lua_close(s_L);
  s_L = nullptr;
  s_script_actor_count = 0;
}

void turtle_actor_lua_bind_actors_from_scene(void) {
  if (!s_L) {
    return;
  }

  for (int i = 0; i < kMaxActors; ++i) {
    if (s_update_ref[i] != LUA_NOREF) {
      luaL_unref(s_L, LUA_REGISTRYINDEX, s_update_ref[i]);
      s_update_ref[i] = LUA_NOREF;
    }
    s_script_stem[i][0] = '\0';
  }

  s_script_actor_count = turtle_scene_actor_count();
  if (s_script_actor_count > kMaxActors) {
    s_script_actor_count = kMaxActors;
  }

  for (int i = 0; i < s_script_actor_count; ++i) {
    char stem[kMaxScriptStem];
    if (!turtle_scene_actor_script_stem(i, stem, sizeof stem)) {
      continue;
    }
    snprintf(s_script_stem[i], sizeof s_script_stem[i], "%s", stem);
    load_script_update_ref(i, stem);
  }
}

void turtle_actor_lua_tick_all(uint32_t delta_ms) {
  if (!s_L || delta_ms == 0 || s_script_actor_count <= 0) {
    return;
  }

  const float dt = static_cast<float>(delta_ms) / 1000.0f;

  for (int i = 0; i < s_script_actor_count; ++i) {
    if (s_update_ref[i] == LUA_NOREF) {
      continue;
    }

    turtle_scene_actor_set_lua_target(i);

    lua_rawgeti(s_L, LUA_REGISTRYINDEX, s_update_ref[i]);
    if (!lua_isfunction(s_L, -1)) {
      lua_pop(s_L, 1);
      continue;
    }

    lua_pushnumber(s_L, static_cast<lua_Number>(dt));
    const int st = lua_pcall(s_L, 1, 0, 0);
    if (st != LUA_OK) {
      const char* err = lua_tostring(s_L, -1);
      Serial.printf("turtle_actor_lua: _update actor %d: %s\n", i, err ? err : "?");
      lua_pop(s_L, 1);
    }
  }

  turtle_scene_actor_set_lua_target(-1);
}
