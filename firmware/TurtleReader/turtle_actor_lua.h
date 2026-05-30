#pragma once

#include <stdint.h>

/** Crea la VM Lua de actores y registra btn/pos/move. Idempotente. */
void turtle_actor_lua_init(void);

void turtle_actor_lua_shutdown(void);

/** Tras turtle_scene_begin_runtime: carga scripts/<stem>.lua y enlaza _update. */
void turtle_actor_lua_bind_actors_from_scene(void);

/**
 * Llama _update(dt) en cada actor con campo script (scripts/<stem>.lua en SD).
 * Requiere turtle_input_poll() antes en el mismo fotograma.
 */
void turtle_actor_lua_tick_all(uint32_t delta_ms);
