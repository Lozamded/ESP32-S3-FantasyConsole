#pragma once

#include <stdint.h>

struct lua_State;

/* Pon a 1 cuando instales LovyanGFX y cablees ILI9488 (SPI aparte de la SD). */
#ifndef FANTASY_USE_DISPLAY
#define FANTASY_USE_DISPLAY 0
#endif

#if FANTASY_USE_DISPLAY
#include <SPI.h>
#ifndef FANTASY_DISP_SPI_HOST
#define FANTASY_DISP_SPI_HOST SPI3_HOST
#endif
#ifndef FANTASY_DISP_PIN_SCK
#define FANTASY_DISP_PIN_SCK 12
#endif
#ifndef FANTASY_DISP_PIN_MISO
#define FANTASY_DISP_PIN_MISO 13
#endif
#ifndef FANTASY_DISP_PIN_MOSI
#define FANTASY_DISP_PIN_MOSI 11
#endif
#ifndef FANTASY_DISP_PIN_DC
#define FANTASY_DISP_PIN_DC 10
#endif
#ifndef FANTASY_DISP_PIN_CS
#define FANTASY_DISP_PIN_CS 9
#endif
#ifndef FANTASY_DISP_PIN_RST
#define FANTASY_DISP_PIN_RST 8
#endif
#endif

void fantasy_gpu_init(void);
void fantasy_gpu_register_lua(struct lua_State* L);

/** Restaura la paleta Genesis por defecto del firmware. */
void fantasy_gpu_palette_reset_default(void);

/**
 * Parsea texto con una linea #RRGGBB por color (opcional #, permite #RGB).
 * Rellena indices 0..COLORS-1; sobrantes ignoradas. Huecos con negro.
 * @return cantidad de colores validos leidos (0 si ninguno).
 */
int fantasy_gpu_palette_from_hex_text(const char* text, size_t text_len);
