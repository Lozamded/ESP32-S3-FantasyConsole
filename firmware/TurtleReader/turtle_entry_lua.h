#pragma once

#include <stdint.h>

struct lua_State;

/**
 * spec/hud-border-v0.md: la VM ENTRY sobrevive al script de arranque del cartucho para
 * poder pintar HUD (via bindings hud_*) desde ganchos por-escena y por-fotograma. Modelo:
 *
 *  - turtle_entry_lua_take(L) toma ownership de la VM recien inicializada y con el script
 *    de arranque ya ejecutado; a partir de ese punto la VM queda viva hasta un release()
 *    explicito. TurtleReader.ino la crea y la pasa aca.
 *  - turtle_scene_begin_runtime() llama a call_hud_init() antes del snapshot estatico,
 *    y a call_hud(dt) por fotograma tras draw_all_actors. Ambos son no-ops silenciosos si
 *    el script no define la funcion global correspondiente.
 *  - turtle_entry_lua_release() cierra la VM (al cargar otro cartucho / reboot).
 *  - turtle_entry_lua_is_active() sirve para saber si la VM sigue viva sin exponer L.
 */
void turtle_entry_lua_take(lua_State* L);
void turtle_entry_lua_release(void);
bool turtle_entry_lua_is_active(void);

/** Llama `_hud_init()` global si esta definida en la VM ENTRY. No-op silencioso si no. */
void turtle_entry_lua_call_hud_init(void);

/** Llama `_hud(dt)` (dt en segundos) global si esta definida. No-op silencioso si no. */
void turtle_entry_lua_call_hud(uint32_t delta_ms);
