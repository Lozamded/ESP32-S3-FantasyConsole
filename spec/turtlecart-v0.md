# Especificacion TurtleCart v0 (texto plano)

Esta version prioriza simplicidad para validar lectura en hardware.

## Tamano del cartucho

No hay limite fijo en la especificacion: el tamano lo marcan la **microSD**, el **sistema de archivos** y la **RAM/tiempo** que el desarrollador acepte. Puedes meter listas largas (p. ej. muchas lineas de paleta) siempre que el firmware actual sepa que hacer con ellas (ver abajo).

## Extension

- `.turtlecart`

## Estructura del archivo

```txt
TURTLECART:0
ENTRY:main.lua
PALETTE:
#RRGGBB
#RRGGBB
...
---FILE:main.lua---
print("hola")
---END---
```

`PALETTE:` es **opcional**. Si falta, el firmware usa una paleta por defecto.

## Reglas v0

1. Primera linea exacta: `TURTLECART:0`
2. Linea: `ENTRY:<ruta>` (archivo embebido que se ejecuta como Lua).
3. Opcional: bloque `PALETTE:` **en su propia linea**, seguido de **una linea por color**:
   - Formato recomendado: `#RRGGBB` (hex, mayusculas o minusculas).
   - Tambien aceptado: `#RGB` (se expande a `#RRGGBB` duplicando cada nibble).
   - Lineas vacias se ignoran; lineas invalidas se saltan.
   - Puedes poner **mas de 32 lineas** en el archivo; el runtime actual solo aplica las **primeras 32 entradas validas** a los indices `0..31` de `pix`/`cls`. El resto se ignora (reserva para futuras versiones o herramientas).
   - Si hay **menos de 32** colores validos, los indices faltantes se rellenan con `#000000`.
   - El bloque de paleta termina donde empieza la primera linea `---FILE:` (debe haber al menos un archivo embebido despues en el cartucho normal).
4. Contenido de archivos embebidos entre:
   - inicio: `---FILE:<ruta>---`
   - fin: `---END---`
5. Debe existir el archivo indicado en `ENTRY`.

Orden recomendado: `TURTLECART:` → `ENTRY:` → `PALETTE:` (si hay) → `---FILE:...---` ...

## Objetivo tecnico de v0

- Cargar el cartucho desde SD.
- Aplicar paleta opcional antes de ejecutar el script.
- Extraer el archivo indicado en `ENTRY` (p. ej. `main.lua`).
- Ejecutar ese script en **Lua 5.4** en el firmware con API minima:
  - `print` → Serial
  - `cls(color)`, `pix(x,y,color)`, `flip()` → framebuffer 240×180 (**32 indices** de color)
  - `W`, `H`, `COLORS` en Lua (`COLORS` == 32)

## Fuera de alcance en v0

- Compresion.
- Checksums.
- Sprites/binarios embebidos (salvo texto en secciones FILE).
- Firma digital.

## Evolucion sugerida (v1+)

- Pasar a contenedor binario con tabla de archivos.
- Agregar CRC32.
- Incluir assets (`sprites.bin`, `map.bin`, etc).
- Mas indices de color o paletas multiples si el hardware lo permite.
- API de juego (input, audio) encima de Lua.
