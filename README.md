# FantasyConsole (ESP32-S3)

Primer objetivo del proyecto:
- Definir un formato minimo de cartucho `.turtlecart`.
- Leer ese cartucho desde microSD en ESP32-S3.
- Confirmar por Serial que se leyo el script del cartucho (ENTRY, p. ej. `scripts/global.lua` en el proyecto).

## Estado actual (MVP v0 + Lua 5.4 + framebuffer)

- Formato: texto plano `.turtlecart` con secciones.
- Firmware: sketch Arduino que:
  - monta SD por SPI (con reintentos),
  - abre `/main.turtlecart` en la SD (si no esta, `/demo.turtlecart`),
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
- `cart/demo.turtlecart`: cartucho de prueba (fallback en firmware si falta `main.turtlecart` en la SD).
- `firmware/libraries/lua54/`: Lua 5.4.6 empotrado (fuentes oficiales + parches minimos para ESP32).
- `firmware/TurtleReader/`: firmware principal (`TurtleReader.ino` + `turtle_gpu.*`).

## Prueba rapida

1. Instala la libreria **Lua54** como arriba.
2. Copia a la **raiz** de la microSD la **carpeta de exportacion** de TurtleStudio (p. ej. todo `build/`: `main.turtlecart`, `backgrounds/`, `sprites/`). El bundle del cartucho es delgado; los fondos y sprites pintados van en JSON aparte con las mismas rutas que en el proyecto. Si no tienes export, puedes copiar `cart/demo.turtlecart` como **`demo.turtlecart`** (todo embebido, pequeno) y el firmware lo cargara como respaldo.
3. Cartuchos grandes (fondos `indexed_pixels` embebidos, ~1 MB): en Arduino IDE activa **PSRAM** en la placa ESP32-S3 (`OPI PSRAM` / `Enabled`). Sin PSRAM el firmware puede reiniciarse al leer `main.turtlecart` y la pantalla queda negra; el monitor serial se corta justo despues de `microSD montada`.
4. Ajusta pines SPI/SD en el sketch segun tu cableado (alimenta el lector SD a **3V3**).
5. Flashea el sketch en tu ESP32-S3 (incluye `turtle_cart.cpp` junto al sketch).
6. Abre monitor serial a `115200`.

Comprueba el paquete en PC (sin placa):

```bash
cd tools/turtlestudio
PYTHONPATH=src python3 src/turtlestudio/verify_package.py /ruta/a/build
PYTHONPATH=src python3 src/turtlestudio/test_asset_bin.py /ruta/al/proyecto
```

Copia al sketch Arduino los archivos de `firmware/TurtleReader/` (incluye `turtle_asset_bin.cpp` y `turtle_tileset.cpp`).

Con **paquete SD** (carpeta `build/` copiada entera), el monitor serial deberia mostrar algo como:
- `SD: leyendo /main.turtlecart` (~5–50 KB, no ~1 MB)
- `Bundle embebido: … bytes`
- `turtle_scene: bin SD /backgrounds/cielo.tbg 264x198 mode 2 (... bytes)`
- `turtle_scene: fondo "cielo" indexed 264x198`
- `turtle_tileset: 10 tiles 16x16 (... bytes)` y `turtle_scene: N celdas tile pintadas`
- `turtle_scene: asset SD /objects/bloque.json` (por objeto)
- `turtle_scene: sprite "bloque_rojo" desde SD` o `asset SD /sprites/….json`
- `Escena inicial (C++ desde bundle) aplicada tras Lua.`

Si falta un sidecar veras `no pudo cargar asset SD /backgrounds/...`.

Si todo sale bien, veras la carga del cartucho y una linea en **Salida Lua** con el `print` real desde la VM, por ejemplo:
- `hola mundo desde turtlecart v0`
- `Lua termino sin error`

## Specs ideales para mi consola
- resolución: 264×198
- paleta: 32 colores
