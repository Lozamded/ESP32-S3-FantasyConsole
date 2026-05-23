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

/** Avanza animacion y redibuja solo sprites sobre la capa estatica. */
void turtle_scene_runtime_tick(uint32_t delta_ms);

bool turtle_scene_runtime_active(void);
int turtle_scene_target_fps(void);
