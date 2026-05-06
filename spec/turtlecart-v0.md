# Especificacion TurtleCart v0 (texto plano)

Esta version prioriza simplicidad para validar lectura en hardware.

## Extension

- `.turtlecart`

## Estructura del archivo

```txt
TURTLECART:0
ENTRY:main.lua
---FILE:main.lua---
print("hola mundo desde turtlecart v0")
---END---
```

## Reglas v0

1. Primera linea exacta: `TURTLECART:0`
2. Segunda linea: `ENTRY:<ruta>`
3. Contenido de archivos embebidos entre:
   - inicio: `---FILE:<ruta>---`
   - fin: `---END---`
4. Debe existir el archivo indicado en `ENTRY`.

## Objetivo tecnico de v0

- Cargar el cartucho desde SD.
- Extraer `main.lua`.
- Confirmar que se puede leer su contenido.

## Fuera de alcance en v0

- Compresion.
- Checksums.
- Binarios/sprites embebidos.
- Firma digital.
- Ejecucion real de Lua.

## Evolucion sugerida (v1+)

- Pasar a contenedor binario con tabla de archivos.
- Agregar CRC32.
- Incluir assets (`sprites.bin`, `map.bin`, etc).
- Integrar runtime Lua en C++.
