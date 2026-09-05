#pragma once

#include <stddef.h>
#include <stdint.h>

struct lua_State;

// 0 = framebuffer solo en RAM; 1 = salida por panel ILI9488.
#ifndef TURTLE_USE_DISPLAY
#define TURTLE_USE_DISPLAY 1
#endif

#if TURTLE_USE_DISPLAY
#include <SPI.h>
#ifndef TURTLE_DISP_SPI_HOST
#define TURTLE_DISP_SPI_HOST SPI3_HOST
#endif
#ifndef TURTLE_DISP_PIN_SCK
#define TURTLE_DISP_PIN_SCK 12
#endif
#ifndef TURTLE_DISP_PIN_MISO
#define TURTLE_DISP_PIN_MISO 13
#endif
#ifndef TURTLE_DISP_PIN_MOSI
#define TURTLE_DISP_PIN_MOSI 11
#endif
#ifndef TURTLE_DISP_PIN_DC
#define TURTLE_DISP_PIN_DC 10
#endif
#ifndef TURTLE_DISP_PIN_CS
#define TURTLE_DISP_PIN_CS 9
#endif
#ifndef TURTLE_DISP_PIN_RST
#define TURTLE_DISP_PIN_RST 8
#endif
#ifndef TURTLE_PANEL_ROTATION
#define TURTLE_PANEL_ROTATION 1
#endif
#endif

// LovyanGFX Panel_LCD: MADCTL |= (rgb_order ? MAD_RGB : MAD_BGR). false = BGR (habitual ILI9488).
#ifndef TURTLE_ILI9488_RGB_ORDER
#define TURTLE_ILI9488_RGB_ORDER false
#endif

// pushImage(uint16_t*): con swap false Lovyan interpreta el buffer como swap565_t, no como RGB565
// canonico. Nuestra paleta usa rgb565() estandar -> activar swap bytes en el LGFX_Device.
#ifndef TURTLE_LGFX_SWAP565_BYTES
#define TURTLE_LGFX_SWAP565_BYTES 1
#endif

// INVON (video invertido). Muchos ILI9488 SPI / IPS se ven bien asi; 0 si tu panel ya va derecho.
#ifndef TURTLE_PANEL_INVERT
#define TURTLE_PANEL_INVERT 1
#endif

void turtle_gpu_init(void);
void turtle_gpu_register_lua(struct lua_State* L);
void turtle_gpu_palette_reset_default(void);
int turtle_gpu_palette_from_hex_text(const char* text, size_t text_len);
/** Aplica paleta desde array JSON de strings "#RRGGBB" (sin corchetes). */
int turtle_gpu_palette_from_json_array(const char* arr_inner, size_t arr_len);

/** Indices 0..31; rellena framebuffer con indice de color. */
void turtle_gpu_cls(uint8_t color_index);
/**
 * spec/hud-border-v0.md: rellena SOLO la region del playfield con `color_index`, ignorando
 * la camara (a diferencia de fill_rect_scene, que trabaja en espacio escena y se desplaza
 * con la camara). La region HUD queda intacta. Usado por paint_scene_static_layers para
 * limpiar el area de juego cada frame en camara con scroll, sin borrar el HUD y sin
 * depender del origen actual de la camara.
 */
void turtle_gpu_playfield_clear(uint8_t color_index);
/** Rectangulo en coordenadas de escena (spec/scene-v0.md): esquina inferior izquierda (x0,y0), Y hacia arriba. */
void turtle_gpu_fill_rect_scene(int x0, int y0, int w, int h, uint8_t color_index);
/**
 * Pixeles indexados (fila 0 = arriba del sprite). (x0,y0) = esquina inferior izquierda del bbox.
 * Omite indice `transparent_index` (p. ej. 31).
 */
void turtle_gpu_blit_indexed_scene(int x0, int y0, int w, int h, const uint8_t* rows_top_first,
                                   int row_stride, uint8_t transparent_index);
/**
 * Igual que blit_indexed_scene pero en vez de usar el color propio de cada pixel fuente,
 * pinta todo pixel no-transparente con `tint_color_index` fijo (glifos de texto con tinte,
 * ver turtle_font_draw_scene_tint). Evita el costo de un fill_rect_scene(1,1) por pixel.
 */
void turtle_gpu_blit_indexed_scene_tint(int x0, int y0, int w, int h,
                                        const uint8_t* rows_top_first, int row_stride,
                                        uint8_t transparent_index, uint8_t tint_color_index);
/** Igual que blit_indexed_scene pero espejo horizontal y/o vertical alrededor del ancla
 *  (origin_x, origin_y). flip_v invierte el orden de las filas fuente en su lugar (no cambia
 *  el rect que ocupa el sprite, solo su contenido queda cabeza abajo). */
void turtle_gpu_blit_indexed_scene_anchor(int anchor_x, int anchor_y, int w, int h,
                                          const uint8_t* rows_top_first, int row_stride,
                                          uint8_t transparent_index, int origin_x, int origin_y,
                                          bool flip_h, bool flip_v = false);
/**
 * Una fila del framebuffer con su propio offset horizontal de muestreo (spec/scene-v0.md,
 * bandas de parallax). `scene_y` ubica la fila en espacio escena (Y arriba) para el mapeo
 * camara->pantalla habitual (igual que blit_indexed_scene). `sample_row`/`sample_row_len` es
 * la fila fuente completa (ancho de esa fila del bitmap origen, no del viewport). Cada columna
 * de pantalla `vx` (0..ancho viewport-1) muestrea `sample_row[vx + x_offset]`; si `wrap_x` es
 * true esa columna se ajusta modulo `sample_row_len` (bandas lentas que deben repetirse), si no
 * las columnas fuera de rango quedan transparentes.
 */
void turtle_gpu_blit_indexed_row_banded(int scene_y, const uint8_t* sample_row,
                                        int sample_row_len, int x_offset, bool wrap_x,
                                        uint8_t transparent_index);
void turtle_gpu_flip(void);

/** Origen de camara en espacio escena (esquina inf-izq del viewport). Por defecto (0,0). */
void turtle_gpu_set_camera(int cam_x, int cam_y);
void turtle_gpu_get_camera(int* cam_x, int* cam_y);

/**
 * spec/hud-border-v0.md: reserva franjas HUD en los bordes del framebuffer. `ox, oy` =
 * esquina superior-izquierda del playfield dentro del framebuffer (Y-abajo, raster). `pw, ph`
 * = tamano del playfield. Todos los blits de escena (fill_rect_scene, blit_indexed_scene*,
 * blit_indexed_row_banded) clipean y aplican offset contra este rectangulo; el area fuera
 * del playfield queda como region HUD, jamas tocada por dibujo de escena.
 *
 * Defecto tras turtle_gpu_init: `(0, 0, 164, 124)` = playfield = framebuffer completo
 * (sin HUD, comportamiento pre-v0). turtle_scene.cpp llama a set_playfield al comenzar cada
 * escena con los valores derivados de `camera.hud_border` del manifest.
 */
void turtle_gpu_set_playfield(int ox, int oy, int pw, int ph);
void turtle_gpu_get_playfield(int* ox, int* oy, int* pw, int* ph);
/** true si (x, y) — coord de framebuffer, Y-abajo — cae dentro del playfield. */
bool turtle_gpu_playfield_contains(int x, int y);

/**
 * Escribe un pixel HUD en coord de framebuffer (Y-abajo, origen top-left del framebuffer
 * fisico). NO-OP si (x, y) cae dentro del playfield (proteccion contra pintar la zona de
 * juego desde bindings hud_*). Ademas de escribir en `s_fb`, actualiza `s_static_fb` (si
 * hay snapshot) para que restore_static_dirty no revierta el nuevo estado, y marca la
 * celda como panel-dirty para el proximo flush.
 */
void turtle_gpu_pixel_absolute(int x, int y, uint8_t color_index);
/** Relleno solido HUD en coord de framebuffer. Cada pixel fuera del playfield sigue la
 *  misma semantica que turtle_gpu_pixel_absolute; los que caigan dentro del playfield son
 *  no-op silencioso (el rect puede cruzar bordes sin efectos colaterales). */
void turtle_gpu_fill_rect_absolute(int x, int y, int w, int h, uint8_t color_index);

/**
 * spec/gui-layer-v0.md: escritura sin restriccion de playfield. Escribe `s_fb` en (x, y) si
 * cae en el framebuffer, sin importar si es zona HUD o playfield. Marca la celda como
 * panel-dirty para el proximo flush. NO escribe a `s_static_fb`: las capas GUI se re-pintan
 * cada frame (paint_all al final del tick), asi que hornear su contenido en la capa estatica
 * causaria acumulacion de pixeles cuando el contenido dinamico cambia (p. ej. labels con
 * texto variable dejaban un rastro de tinta del valor anterior). NO USAR desde bindings de
 * HUD (`hud_pix`/`hud_text`/etc) — esos delegan en `_absolute` justamente para proteger el
 * playfield de escrituras accidentales.
 */
void turtle_gpu_pixel_raw(int x, int y, uint8_t color_index);
/** Relleno solido sin restriccion de playfield. Ver turtle_gpu_pixel_raw. */
void turtle_gpu_fill_rect_raw(int x, int y, int w, int h, uint8_t color_index);
/**
 * Copia una region rectangular (coords framebuffer, Y-abajo) desde `s_static_fb` a `s_fb`.
 * No-op si no hay snapshot. Usado por el pintado de capas GUI (paint_one_layer en
 * turtle_gui_layer.cpp) para borrar el rastro de labels dinamicos antes de repintar cada
 * frame: sin este restore, un label sobre `transparent_bg` acumula pixeles del texto previo
 * porque nada limpia la region entre frames.
 */
void turtle_gpu_restore_static_rect_fb(int x, int y, int w, int h);

/** Marca region sucia (coords escena: esquina inf-izq del blit, Y arriba). */
void turtle_gpu_dirty_reset(void);
void turtle_gpu_dirty_mark_scene_rect(int x0, int y0, int w, int h);
/**
 * No-op: la holgura de 1px por redondeo fb->panel ahora se aplica dentro de cada
 * turtle_gpu_dirty_mark_scene_rect(). Se mantiene por compatibilidad de API/orden de
 * llamada (llamar tras marcar rects, como antes).
 */
void turtle_gpu_dirty_slack_for_scale(void);
bool turtle_gpu_dirty_valid(void);
/** Marca todo el framebuffer logico como sucio. */
void turtle_gpu_dirty_mark_fb_full(void);
/** Restaura solo la union de rects sucios desde la capa estatica. */
void turtle_gpu_restore_static_dirty(void);
/** Proximo flip envia framebuffer completo (tras cls, snapshot, ENTRY). */
void turtle_gpu_request_full_flip(void);

/** Copia el framebuffer actual a capa estatica (fondo + tiles sin sprites). */
void turtle_gpu_snapshot_static(void);
/** Restaura capa estatica sobre el framebuffer (antes de redibujar sprites). */
void turtle_gpu_restore_static(void);
bool turtle_gpu_has_static_snapshot(void);
