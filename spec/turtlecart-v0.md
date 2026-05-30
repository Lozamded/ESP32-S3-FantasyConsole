# Especificacion TurtleCart v0 (texto plano)

Esta version prioriza simplicidad para validar lectura en hardware.

## Tamano del cartucho

No hay limite fijo en la especificacion: el tamano lo marcan la **microSD**, el **sistema de archivos** y la **RAM/tiempo** que el desarrollador acepte. Puedes meter listas largas (p. ej. muchas lineas de paleta) siempre que el firmware actual sepa que hacer con ellas (ver abajo).

## Extension

- `.turtlecart`

## Estructura del archivo

```txt
TURTLECART:0
ENTRY:scripts/global.lua
INITIAL_SCENE:intro
PALETTE:
#RRGGBB
#RRGGBB
...
---FILE:scripts/global.lua---
print("hola")
---END---
```

`PALETTE:` es **opcional**. Si falta, el firmware usa una paleta por defecto.

En TurtleStudio el arranque se edita como `scripts/global.lua` (`entry` en `turtlestudio.json`) y se embebe en **`main.turtlecart`** (`ENTRY:`). El paquete SD exportado incluye ademas **`scripts/*.lua`** (ENTRY, escenas y objetos con `"script"`); ver **`spec/lua/`**. El bundle `studio/project_bundle.json` referencia escenas, objetos y sprites (ver **`spec/sprite-v0.md`**).

## Reglas v0

1. Primera linea exacta: `TURTLECART:0`
2. Linea: `ENTRY:<ruta>` (archivo embebido que se ejecuta como Lua).
3. Opcional: linea `INITIAL_SCENE:<id>` — escena de arranque para datos embebidos / runtime (misma convencion que ids de escena en `turtlestudio.json`). Si falta, herramientas y firmware pueden asumir **`intro`**. El id de escena **`main` esta reservado** (nombre convencional del cartucho principal `main.turtlecart` en TurtleStudio; no debe usarse como `id` de escena en el manifest).
4. Opcional: linea `BUNDLE_FILE:<ruta>` — JSON del bundle en la SD (p. ej. `studio/project_bundle.json`). **No** embeber el bundle en `main.turtlecart` (ahorra RAM en ESP32). Si falta, el firmware intenta el sidecar por defecto o bundle embebido legacy.
5. Opcional: bloque `PALETTE:` **en su propia linea**, seguido de **una linea por color**:
   - Formato recomendado: `#RRGGBB` (hex, mayusculas o minusculas).
   - Tambien aceptado: `#RGB` (se expande a `#RRGGBB` duplicando cada nibble).
   - Lineas vacias se ignoran; lineas invalidas se saltan.
   - Puedes poner **mas de 32 lineas** en el archivo; el runtime actual solo aplica las **primeras 32 entradas validas** a los indices `0..31` de `pix`/`cls`. El resto se ignora (reserva para futuras versiones o herramientas).
   - Si hay **menos de 32** colores validos, los indices faltantes se rellenan con `#000000`.
   - El bloque de paleta termina donde empieza la primera linea `---FILE:` (debe haber al menos un archivo embebido despues en el cartucho normal).
6. Contenido de archivos embebidos (solo ENTRY Lua; el bundle va en sidecar) entre:
   - inicio: `---FILE:<ruta>---`
   - fin: `---END---`
7. Debe existir el archivo indicado en `ENTRY`.

Orden recomendado: `TURTLECART:` → `ENTRY:` → `INITIAL_SCENE:` → `BUNDLE_FILE:` → `PALETTE:` (si hay) → `---FILE:ENTRY---` ...

## Escena y coordenadas

El espacio logico del juego (tamano, origen, ejes) esta definido en **`spec/scene-v0.md`**: escena **264×198**, **(0,0) en la esquina inferior izquierda**, **Y positivo hacia arriba**. El cartucho v0 no exige un bloque `SCENE:`; se asume la escena canonica salvo extension futura.

## Objetivo tecnico de v0

- Cargar el cartucho desde SD.
- Aplicar paleta opcional antes de ejecutar el script.
- Extraer el archivo indicado en `ENTRY` (p. ej. `scripts/global.lua`).
- Opcional: si existe el archivo embebido `studio/project_bundle.json`, el firmware puede **dibujar en C++** la escena cuyo `id` coincide con **`INITIAL_SCENE:`** (fondo `background_index`, asset opcional `background`, objetos con sprites; ver **`spec/sprite-v0.md`**) antes de ejecutar el `ENTRY`.
- **Paquete en SD (recomendado):** TurtleStudio exporta una **carpeta** (p. ej. `build/`) con `main.turtlecart`, `backgrounds/*.tbg`, `sprites/*.tsp`, `objects/*.json`, opcionalmente **`scripts/*.lua`** (logica por objeto; ver **`spec/lua/object-script-v0.md`**) y `COPIAR_A_SD.txt`. El proyecto en PC sigue en JSON; solo la SD usa binario (ver **`spec/asset-bin-v0.md`**). Copia **toda la carpeta** a la raiz de la microSD.
- Ejecutar ese script en **Lua 5.4** en el firmware con API documentada en **`spec/lua/entry-v0.md`** (`print`, `cls`, `pix`, `spix`, `flip`, `W`, `H`, `COLORS`, `btn`/`btnp` con limitaciones de arranque).

## Fuera de alcance en v0

- Compresion.
- Checksums.
- Sprites en binario dedicado (`sprites.bin`); en v0 van como JSON dentro de `studio/project_bundle.json` (texto embebido).
- Firma digital.

## Evolucion sugerida (v1+)

- Pasar a contenedor binario con tabla de archivos.
- Agregar CRC32.
- Incluir assets (`sprites.bin`, `map.bin`, etc).
- Mas indices de color o paletas multiples si el hardware lo permite.
- API de juego (input, audio) encima de Lua.
