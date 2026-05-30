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

/** Indices 0..31; rellena framebuffer con indice de color. */
void turtle_gpu_cls(uint8_t color_index);
/** Rectangulo en coordenadas de escena (spec/scene-v0.md): esquina inferior izquierda (x0,y0), Y hacia arriba. */
void turtle_gpu_fill_rect_scene(int x0, int y0, int w, int h, uint8_t color_index);
/**
 * Pixeles indexados (fila 0 = arriba del sprite). (x0,y0) = esquina inferior izquierda del bbox.
 * Omite indice `transparent_index` (p. ej. 31).
 */
void turtle_gpu_blit_indexed_scene(int x0, int y0, int w, int h, const uint8_t* rows_top_first,
                                   int row_stride, uint8_t transparent_index);
/** Igual que blit_indexed_scene pero espejo horizontal alrededor del ancla (origin_x, origin_y). */
void turtle_gpu_blit_indexed_scene_anchor(int anchor_x, int anchor_y, int w, int h,
                                          const uint8_t* rows_top_first, int row_stride,
                                          uint8_t transparent_index, int origin_x, int origin_y,
                                          bool flip_h);
void turtle_gpu_flip(void);

/** Marca region sucia (coords escena: esquina inf-izq del blit, Y arriba). */
void turtle_gpu_dirty_reset(void);
void turtle_gpu_dirty_mark_scene_rect(int x0, int y0, int w, int h);
/** Restaura solo la union de rects sucios desde la capa estatica. */
void turtle_gpu_restore_static_dirty(void);
/** Proximo flip envia framebuffer completo (tras cls, snapshot, ENTRY). */
void turtle_gpu_request_full_flip(void);

/** Copia el framebuffer actual a capa estatica (fondo + tiles sin sprites). */
void turtle_gpu_snapshot_static(void);
/** Restaura capa estatica sobre el framebuffer (antes de redibujar sprites). */
void turtle_gpu_restore_static(void);
bool turtle_gpu_has_static_snapshot(void);
