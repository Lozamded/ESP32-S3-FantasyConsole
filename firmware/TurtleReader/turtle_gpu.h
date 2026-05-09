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

// Si rojo/azul salen cruzados, cambia a true.
#ifndef TURTLE_ILI9488_RGB_ORDER
#define TURTLE_ILI9488_RGB_ORDER false
#endif

void turtle_gpu_init(void);
void turtle_gpu_register_lua(struct lua_State* L);
void turtle_gpu_palette_reset_default(void);
int turtle_gpu_palette_from_hex_text(const char* text, size_t text_len);
