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

/**
 * spec/scene-object-identity-v0.md: buscar/consultar otros actores por id/tag unico de
 * instancia. `index` (para *_at) es 0-based, el mismo indice de s_actors que devuelve
 * turtle_scene_find_actor_by_id -- turtle_actor_lua.cpp suma/resta 1 al exponerlo a Lua como
 * find_by_id/find_by_tag/obj_posx/obj_posy/obj_id/obj_has_tag (convencion Lua 1-based). Los
 * indices son estables mientras no cambie la escena activa (goto_scene la reconstruye).
 */
bool turtle_scene_actor_id(char* out, size_t out_cap);
bool turtle_scene_find_actor_by_id(const char* id, int* out_index);
int turtle_scene_find_actors_by_tag(const char* tag, int* out_indices, int max_out);
bool turtle_scene_actor_pos_at(int index, int* x, int* y);
bool turtle_scene_actor_id_at(int index, char* out, size_t out_cap);
bool turtle_scene_actor_has_tag_at(int index, const char* tag);
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

/** spec/scene-object-visibility-v0.md: enciende/apaga el dibujo del actor Lua actual.
 *  El script sigue recibiendo _update(dt); solo el redibujo consulta `visible`. */
void turtle_scene_actor_set_visible(bool visible);

/** Reposiciona al actor Lua actual en (x, y) espacio escena. Sin colision ni clamp
 *  contra tiles -- teleport puro, pensado para hitboxes/overlays que siguen a otro actor
 *  (ver player_attack.lua). El redibujo por rects sucios detecta el cambio por a->x/y
 *  distintos de last_x/last_y (draw_all_actors) y borra el rect previo. */
void turtle_scene_actor_set_pos(int x, int y);

/** Lee el nombre de la animacion actual del actor en `index` (0-based, mismo indice que
 *  find_by_id/find_by_tag exponen +1). Devuelve false si el indice no es valido o el
 *  actor no tiene animacion activa. */
bool turtle_scene_actor_anim_at(int index, char* out, size_t out_cap);

/** true si el actor en `index` esta espejado horizontalmente (flip_h). Devuelve false
 *  si el indice no es valido (mismo valor que "no espejado" -- el llamador que necesite
 *  distinguir tiene que chequear con obj_posx u otro getter). */
bool turtle_scene_actor_flip_h_at(int index);

/** Espejo vertical del sprite del actor Lua actual. Util para "muerte" cabeza abajo sin
 *  necesidad de otra animacion (ver eneny_snake.lua). */
void turtle_scene_actor_set_flip_v(bool flip_v);

/** true si el actor en `index` esta espejado verticalmente (flip_v); false si no o si el
 *  handle no es valido. Sirve como senal ligera "esta derrotado" sin necesidad de tags
 *  mutables (ver eneny_snake.lua + character.lua). */
bool turtle_scene_actor_flip_v_at(int index);

/** true si el actor en `index` esta actualmente visible (Placement::visible en el JSON
 *  o cambiado en runtime por set_visible). */
bool turtle_scene_actor_visible_at(int index);

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

/**
 * spec/hud-border-v0.md: variante para bindings `hud_text`. `(xfb, yfb_top)` = esquina
 * superior-izquierda del primer glifo en coord de framebuffer (Y-abajo). Pixeles que caen
 * dentro del playfield actual son no-op (proteccion contra pintar la zona de juego); el
 * resto se escribe con turtle_gpu_pixel_absolute (mantiene s_static_fb en sync + marca
 * panel-dirty). Devuelve ancho dibujado (px).
 */
int turtle_scene_draw_text_absolute(const char* bundle_json, size_t bundle_json_len,
                                    const char* font_id, int xfb, int yfb_top, const char* str,
                                    int color_index = -1);

/**
 * spec/gui-layer-v0.md: variante para capas GUI apilables. Igual convencion que
 * turtle_scene_draw_text_absolute (coord de framebuffer top-left, `color_index >= 0` tinta)
 * pero SIN restriccion de playfield -- puede pintar sobre la zona de juego (menu de pausa,
 * dialogos). Usa turtle_font_draw_fb_raw internamente.
 */
int turtle_scene_draw_text_raw(const char* bundle_json, size_t bundle_json_len,
                               const char* font_id, int xfb, int yfb_top, const char* str,
                               int color_index = -1);

/**
 * spec/gui-layer-v0.md: variante compartida por barras de progreso (fill_mode="sprite") y
 * barras de pips. Decodifica los pixeles indexados del sprite `sprite_id` (frame 0 o
 * `frame_index`) del bundle actual en el buffer del llamador y devuelve el tamano real. Comparte
 * el cache interno de sprites (mismo que `draw_sprite_for_object` / actores) para no re-parsear.
 * Devuelve `false` si el bundle no esta activo, si `sprite_id` no existe, si `out_cap` es menor
 * que `pw*ph`, o si el sprite es "solido" (sin pixeles indexados; ver
 * extract_palette_index_sprite -- no soportado por capas GUI). Pixeles con indice de paleta 31
 * son transparentes.
 */
bool turtle_scene_load_sprite_pixels(const char* sprite_id, int frame_index, uint8_t* out_pixels,
                                     size_t out_cap, int* out_w, int* out_h);
