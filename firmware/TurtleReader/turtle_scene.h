#pragma once

#include <stddef.h>
#include <stdint.h>

/**
 * Dibuja en el framebuffer la escena `scene_id` del bundle (un solo fotograma, sin loop).
 * Ver turtle_scene_begin_runtime() para animacion continua.
 */
bool turtle_scene_draw_cart_bundle(const char* json, size_t json_len, const char* scene_id);

/**
 * Dibuja fondo + tiles, guarda capa estatica, inicializa actores (sprite por defecto,
 * fotogramas en loop a default_anim_fps * speed 1). Requiere turtle_scene_runtime_tick().
 */
bool turtle_scene_begin_runtime(const char* json, size_t json_len, const char* scene_id);

/**
 * Un fotograma de juego: Lua (_update en actores con script) → animacion sprites → redibujo.
 * Llamar tras turtle_input_poll() en el mismo ciclo.
 */
void turtle_scene_runtime_tick(uint32_t delta_ms);

bool turtle_scene_runtime_active(void);
int turtle_scene_target_fps(void);

/** Actores en runtime (para scripts Lua por objeto). */
int turtle_scene_actor_count(void);
bool turtle_scene_actor_script_stem(int index, char* out, size_t out_cap);
void turtle_scene_actor_set_lua_target(int index);
bool turtle_scene_actor_pos(int* x, int* y);
/** Mueve el actor Lua; si out_dx/out_dy no son null, devuelve pixeles realmente movidos. */
void turtle_scene_actor_move(int dx, int dy, int* out_dx, int* out_dy);
/** true si el actor Lua actual apoya sobre tile solido o el borde inferior de escena. */
bool turtle_scene_actor_on_ground(void);

/** Cambia al sprite de la animacion nombrada (loop, velocidad 1). No reinicia si ya esta activa. */
bool turtle_scene_actor_set_anim(const char* name);

/** Igual que set_anim pero con velocidad y repetir; reinicia siempre desde el fotograma 0. */
bool turtle_scene_actor_play_anim(const char* name, float speed, bool repeat);

/** Espejo horizontal del sprite del actor Lua actual (alrededor del ancla del sprite). */
void turtle_scene_actor_set_flip_h(bool flip_h);
