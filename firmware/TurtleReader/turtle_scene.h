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

/**
 * spec/lua/object-script-v0.md "Cambio de escena": un actor Lua pide el cambio via el
 * binding goto_scene(id) (turtle_actor_lua.cpp) -> turtle_scene_request_switch. El cambio
 * real NO se aplica aca ni dentro de turtle_actor_lua_tick_all -- reconstruir s_actors/
 * rebindear Lua mientras esa misma lista se esta iterando la corromperia. Se aplica una vez
 * por fotograma en TurtleReader.ino::loop(), despues de turtle_scene_runtime_tick, via
 * turtle_scene_consume_pending_switch.
 */
void turtle_scene_request_switch(const char* scene_id);

/** true + copia el id pendiente a out (y limpia el pedido) si turtle_scene_request_switch se
 *  llamo en el fotograma que acaba de terminar. Llamar una vez por iteracion de loop(). */
bool turtle_scene_consume_pending_switch(char* out, size_t out_cap);

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

/**
 * Overlay de texto del actor Lua actual: (dx, dy) offset desde (x, y) del actor, espacio
 * escena. `str`/`font_id` null o vacio borra el overlay. Persiste hasta el siguiente
 * set_text (no hace falta llamarlo cada frame para mantener el mismo valor visible).
 * El dibujo real ocurre en draw_actor_runtime, integrado con el redibujo por rects sucios
 * (ver draw_all_actors) — no es un blit inmediato.
 * `color_index` (0..30) tiñe cada pixel no transparente del glifo con ese color en vez de
 * usar el color propio del glifo (util para reusar una fuente en varios colores de HUD);
 * -1 (por defecto) = sin tinte, usa los colores tal como se pintaron en el editor.
 */
void turtle_scene_actor_set_text(const char* str, int dx, int dy, const char* font_id,
                                 int color_index = -1);

/** Ancho en px de `str` con `font_id`, usando la escena runtime activa (fuera de ella, 0). */
int turtle_scene_measure_text_active(const char* font_id, const char* str);

/**
 * Dibuja `str` con la fuente `font_id` (resuelta y cacheada desde `bundle_json`, ver
 * spec/asset-bin-v0.md "Fuente (.tfn)"). (sx, sy) = esquina inferior izquierda del primer
 * glifo, espacio escena (misma convencion que spix/fill_rect_scene). Una sola linea (v0).
 * `color_index` (0..30) tiñe el texto igual que en turtle_scene_actor_set_text; -1 = sin tinte.
 * Devuelve el ancho en px dibujado, o 0 si la fuente no se pudo resolver.
 */
int turtle_scene_draw_text(const char* bundle_json, size_t bundle_json_len, const char* font_id,
                           int sx, int sy, const char* str, int color_index = -1);

/** Ancho en px de `str` con `font_id`, sin dibujar. 0 si la fuente no se pudo resolver. */
int turtle_scene_measure_text(const char* bundle_json, size_t bundle_json_len,
                              const char* font_id, const char* str);
