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

En TurtleStudio el arranque se edita como `scripts/global.lua` en el proyecto y se exporta convencionalmente al cartucho inicial **`main.turtlecart`**: el `ENTRY:` en el archivo es la ruta del bloque embebido de ese script (p. ej. `scripts/global.lua`). Opcionalmente el mismo cartucho incluye `studio/project_bundle.json` con escenas, objetos y sprites (ver **`spec/sprite-v0.md`**); **no** incluye por defecto los Lua de cada escena (pueden ir en otros archivos).

## Reglas v0

1. Primera linea exacta: `TURTLECART:0`
2. Linea: `ENTRY:<ruta>` (archivo embebido que se ejecuta como Lua).
3. Opcional: linea `INITIAL_SCENE:<id>` — escena de arranque para datos embebidos / runtime (misma convencion que ids de escena en `turtlestudio.json`). Si falta, herramientas y firmware pueden asumir **`intro`**. El id de escena **`main` esta reservado** (nombre convencional del cartucho principal `main.turtlecart` en TurtleStudio; no debe usarse como `id` de escena en el manifest).
4. Opcional: bloque `PALETTE:` **en su propia linea**, seguido de **una linea por color**:
   - Formato recomendado: `#RRGGBB` (hex, mayusculas o minusculas).
   - Tambien aceptado: `#RGB` (se expande a `#RRGGBB` duplicando cada nibble).
   - Lineas vacias se ignoran; lineas invalidas se saltan.
   - Puedes poner **mas de 32 lineas** en el archivo; el runtime actual solo aplica las **primeras 32 entradas validas** a los indices `0..31` de `pix`/`cls`. El resto se ignora (reserva para futuras versiones o herramientas).
   - Si hay **menos de 32** colores validos, los indices faltantes se rellenan con `#000000`.
   - El bloque de paleta termina donde empieza la primera linea `---FILE:` (debe haber al menos un archivo embebido despues en el cartucho normal).
5. Contenido de archivos embebidos entre:
   - inicio: `---FILE:<ruta>---`
   - fin: `---END---`
6. Debe existir el archivo indicado en `ENTRY`.

Orden recomendado: `TURTLECART:` → `ENTRY:` → `INITIAL_SCENE:` → `PALETTE:` (si hay) → `---FILE:...---` ...

## Escena y coordenadas

El espacio logico del juego (tamano, origen, ejes) esta definido en **`spec/scene-v0.md`**: escena **264×198**, **(0,0) en la esquina inferior izquierda**, **Y positivo hacia arriba**. El cartucho v0 no exige un bloque `SCENE:`; se asume la escena canonica salvo extension futura.

## Objetivo tecnico de v0

- Cargar el cartucho desde SD.
- Aplicar paleta opcional antes de ejecutar el script.
- Extraer el archivo indicado en `ENTRY` (p. ej. `scripts/global.lua`).
- Opcional: si existe el archivo embebido `studio/project_bundle.json`, el firmware puede **dibujar en C++** la escena cuyo `id` coincide con **`INITIAL_SCENE:`** (fondo `background_index`, asset opcional `background`, objetos con sprites; ver **`spec/sprite-v0.md`**) antes de ejecutar el `ENTRY`.
- **Paquete en SD (recomendado):** TurtleStudio exporta una **carpeta** (p. ej. `build/`) con `main.turtlecart`, `backgrounds/*.tbg`, `sprites/*.tsp`, `objects/*.json` y `COPIAR_A_SD.txt`. El proyecto en PC sigue en JSON; solo la SD usa binario (ver **`spec/asset-bin-v0.md`**). Copia **toda la carpeta** a la raiz de la microSD.
- Ejecutar ese script en **Lua 5.4** en el firmware con API minima:
  - `print` → Serial
  - `cls(color)`, `pix(x,y,color)` (framebuffer), **`spix(sx,sy,color)`** (escena: abajo-izquierda, Y arriba), `flip()` → framebuffer 264×198 (**32 indices** de color)
  - `W`, `H`, `COLORS` en Lua (`COLORS` == 32)

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
