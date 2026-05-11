# FantasyConsole (ESP32-S3)

Primer objetivo del proyecto:
- Definir un formato minimo de cartucho `.turtlecart`.
- Leer ese cartucho desde microSD en ESP32-S3.
- Confirmar por Serial que se leyo un "hola mundo" desde `main.lua`.

## Estado actual (MVP v0 + Lua 5.4 + framebuffer)

- Formato: texto plano `.turtlecart` con secciones.
- Firmware: sketch Arduino que:
  - monta SD por SPI (con reintentos),
  - abre `/demo.turtlecart`,
  - extrae el script indicado en `ENTRY`,
  - **ejecuta Lua 5.4** con `print` a Serial,
  - API de consola: **`cls(i)`**, **`pix(x,y,i)`** (raster), **`spix(sx,sy,i)`** (escena, ver `spec/scene-v0.md`), **`flip()`**, constantes **`W`**, **`H`**, **`COLORS`** (264x198, 32 indices de color).
- **Paleta por juego**: bloque opcional **`PALETTE:`** en el `.turtlecart` con lineas **`#RRGGBB`** (lista larga permitida; el firmware usa las primeras 32 entradas validas). Sin bloque, paleta Genesis-like por defecto.
- **Sin tope de tamano de cartucho en spec**: lo limitan SD y el desarrollador; el runtime actual solo interpreta el formato v0.

### Pantalla ILI9488 (opcional)

1. Instala la libreria **LovyanGFX** en Arduino IDE.
2. En `firmware/TurtleReader/turtle_gpu.h` deja **`TURTLE_USE_DISPLAY 1`** y ajusta pines `TURTLE_DISP_PIN_*`.
3. `flip()` escala de 264x198 al panel (240x320 fisico, normalmente rotado a 320x240 para juego).

Sin pantalla, `flip()` no hace falta para probar logica; el buffer igual se rellena en RAM.

## Dependencia: libreria Lua54 (en este repo)

1. Copia la carpeta `firmware/libraries/lua54` dentro del directorio de librerias de Arduino, por ejemplo:
   - `~/Arduino/libraries/lua54`
2. Reinicia Arduino IDE si hace falta. Deberia aparecer como libreria **Lua54**.

## Estructura

- `tools/turtlestudio/`: **TurtleStudio** (Python) — CLI y utilidades para armar `.turtlecart`.
- `spec/scene-v0.md`: escena canonica (264×198) y sistema de coordenadas.
- `spec/turtlecart-v0.md`: especificacion inicial.
- `cart/demo.turtlecart`: cartucho de prueba.
- `firmware/libraries/lua54/`: Lua 5.4.6 empotrado (fuentes oficiales + parches minimos para ESP32).
- `firmware/TurtleReader/`: firmware principal (`TurtleReader.ino` + `turtle_gpu.*`).

## Prueba rapida

1. Instala la libreria **Lua54** como arriba.
2. Copia `cart/demo.turtlecart` a la raiz de la microSD con nombre `demo.turtlecart`.
3. Ajusta pines SPI/SD en el sketch segun tu cableado (alimenta el lector SD a **3V3**).
4. Flashea el sketch en tu ESP32-S3.
5. Abre monitor serial a `115200`.

Si todo sale bien, veras la carga del cartucho y una linea en **Salida Lua** con el `print` real desde la VM, por ejemplo:
- `hola mundo desde turtlecart v0`
- `Lua termino sin error`

## Specs ideales para mi consola
- resolución: 264×198
- paleta: 32 colores
