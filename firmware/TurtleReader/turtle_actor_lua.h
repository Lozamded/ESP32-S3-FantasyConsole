#pragma once

#include <stdint.h>

/** Crea la VM Lua de actores y registra btn/pos/move. Idempotente. */
void turtle_actor_lua_init(void);

void turtle_actor_lua_shutdown(void);

/** Tras turtle_scene_begin_runtime: carga scripts/<stem>.lua y enlaza _update. */
void turtle_actor_lua_bind_actors_from_scene(void);

/**
 * spec/lua/scene-script-v0.md: si la escena declara "script": "<stem>" en su JSON,
 * carga scripts/<stem>.lua en la MISMA lua_State que los actores y captura su _update.
 * No-op si la escena no declara script. Llamar DESPUES de bind_actors_from_scene (los
 * chunks de actor ejecutados ahi pisan el global _update; guardamos la ref del script de
 * escena inmediatamente al final para no colisionar).
 */
void turtle_actor_lua_bind_scene_script(void);

/**
 * Llama _update(dt) en cada actor con campo script (scripts/<stem>.lua en SD).
 * Requiere turtle_input_poll() antes en el mismo fotograma.
 */
void turtle_actor_lua_tick_all(uint32_t delta_ms);

/**
 * spec/lua/scene-script-v0.md: llama _update(dt) del script de escena (si hay). Correr
 * ANTES de turtle_actor_lua_tick_all() -- el script de escena puede fijar flags/estado
 * globales que los actores lean en el mismo frame ("controlador"). No-op sin script.
 * Requiere turtle_input_poll() antes en el mismo fotograma.
 */
void turtle_actor_lua_tick_scene(uint32_t delta_ms);
