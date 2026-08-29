#pragma once

#include <stdint.h>

/**
 * spec/lua/state-v0.md: estado compartido clave-valor int32 accesible desde AMBAS VMs (ENTRY
 * y actores).
 *
 * Sirve como puente para que actor scripts empujen contadores/scores/HP que la VM ENTRY (via
 * `_hud(dt)`) lee para actualizar la HUD, sin romper la separacion "un actor no toca la UI"
 * (los bindings `gui_layer_*` siguen siendo ENTRY-only). Ejemplo: gear.lua hace `state_add
 * ("gears", 1)` al recolectar; global.lua hace `local n = state_get("gears") or 0; gui_layer_
 * set_text("hud","gears_lbl", tostring(n))` en `_hud(dt)`.
 *
 * Store: 16 slots fijos, claves hasta 31 chars + nul, valores int32. Persistente entre
 * escenas -- solo se limpia al cargar otro cart (`turtle_state_reset` desde setup()).
 */

struct lua_State;

/** Limpia todos los slots. Llamar al montar la SD / cargar cart nuevo. */
void turtle_state_reset(void);

/** Setea (o crea) `key`. false si key es null/vacio o si la tabla esta llena y `key` no existe. */
bool turtle_state_set(const char* key, int value);

/** Lee `key` en `*out_value`. false si key no existe o input invalido. */
bool turtle_state_get(const char* key, int* out_value);

/** Suma `delta` a `key` (crea con 0 si no existe). Devuelve el nuevo valor (0 si tabla llena). */
int turtle_state_add(const char* key, int delta);

/**
 * Registra `state_set`, `state_get`, `state_add` como globales en `L`. Se llama:
 *   - Una vez al inicializar cada actor VM (turtle_actor_lua.cpp).
 *   - Al inicializar la VM ENTRY (TurtleReader.ino runCartEntryLua).
 * El backing store es compartido (variables estaticas de esta unidad), asi que todos ven
 * los mismos valores independientemente de que VM lo escribio.
 */
void turtle_state_register_lua(struct lua_State* L);
