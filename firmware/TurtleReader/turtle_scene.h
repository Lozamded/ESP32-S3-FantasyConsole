#pragma once

#include <stddef.h>
#include <stdint.h>

/**
 * Dibuja en el framebuffer la escena `scene_id` del bundle TurtleStudio embebido
 * (`studio/project_bundle.json`): fondo `background_index`, asset `background` (inline o
 * `"file"` en SD bajo `backgrounds/`) y objetos con sprites (inline o `sprites/` en SD)
 * Sprites por `pixel_w` x `pixel_h` (independiente de `cell_px`, default 4 en herramientas):
 * `solid_palette_index` (rectangulo) o `indexed_pixels` + `image.rows` (indice 31 = transparente).
 *
 * Requiere paleta del cartucho ya cargada. Solo actualiza RAM; el host llama turtle_gpu_flip()
 * despues (en TurtleReader: tras el ENTRY Lua, para que cls() en cartuchos viejos no deje negro).
 *
 * @return true si encontro la escena y dibujo al menos el fondo (puede no haber objetos).
 */
bool turtle_scene_draw_cart_bundle(const char* json, size_t json_len, const char* scene_id);
