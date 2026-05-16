# Especificacion de sprites (v0)

Sprites en **TurtleStudio** y su uso en el **cartucho** / **firmware**. Complementa `spec/scene-v0.md` (coordenadas) y `spec/turtlecart-v0.md` (contenedor).

## Ubicacion en el proyecto

- Un sprite = un archivo JSON en `objects/Sprites/<id>.json`.
- Un **objeto** de juego (`objects/Objects/<id>.json`) referencia un sprite por `sprite_id` (mismo stem que el `.json` del sprite).
- La escena coloca **objetos** (no sprites directamente) con posicion `(x, y)` en espacio escena.

## Tamano logico: celdas y pixeles

| Campo | Significado |
|--------|-------------|
| `cell_px` | Lado de una **celda** de diseno en pixeles (entero `1..256`). **Default en herramientas: 4**. |
| `blocks_w`, `blocks_h` | Ancho y alto del sprite en **celdas** (`1..32` por eje). |
| `pixel_w`, `pixel_h` | Tamano en pixeles: `blocks_w * cell_px`, `blocks_h * cell_px`. |

El **runtime (firmware) dibuja por `pixel_w` × `pixel_h`**, no por `cell_px`. `cell_px` es convencion de rejilla y editor; dos sprites pueden usar distinto `cell_px` si el JSON lo declara.

### Por que 4 px por celda (default)

Con escena **264×198**, celdas de **8 px** dejan pocos “tiles” utiles; **4 px** da mas detalle en pixel art sin cambiar la resolucion de salida. Sigue alineando con rejillas **4 / 8 / 16** en el editor.

Sprites antiguos con `cell_px: 8` siguen siendo validos si `pixel_w` / `pixel_h` son correctos.

## Archivo `turtlestudio.sprite` (v0)

```json
{
  "format_version": 1,
  "kind": "turtlestudio.sprite",
  "id": "hero",
  "notes": "",
  "palette": "palettes/palette.txt",
  "cell_px": 4,
  "blocks_w": 4,
  "blocks_h": 6,
  "pixel_w": 16,
  "pixel_h": 24,
  "render": { "mode": "..." },
  "image": null,
  "frames": []
}
```

- **`palette`**: ruta relativa al proyecto (`#RRGGBB` por linea). Los indices en `render` / `image` son respecto a **esa** paleta (la escena puede usar otra; validacion cruzada es responsabilidad de herramientas).
- **`frames`**: reservado (animacion futura).

## Modos de render (`render.mode`)

### `solid_palette_index`

Rectangulo uniforme del tamano `pixel_w` × `pixel_h`.

```json
"render": {
  "mode": "solid_palette_index",
  "palette_index": 4
},
"image": null
```

### `indexed_pixels` (recomendado desde el editor)

Matriz de indices de paleta; fila **0 = arriba** del sprite (como en el editor).

```json
"render": {
  "mode": "indexed_pixels"
},
"image": {
  "format": "palette_rows",
  "rows": [
    [31, 31, 0, 1],
    [31, 0, 2, 1]
  ]
}
```

- Cada fila tiene `pixel_w` enteros `0..31` (paleta de consola de 32 indices).
- **Indice 31**: siempre **transparente** al dibujar (convencion global; ver `spec/scene-v0.md`). Puede aparecer en `rows` como hueco del arte; no se elige como pincel en TurtleStudio.
- Filas incompletas: las herramientas rellenan al normalizar.

## TurtleStudio (editor)

- Pestana **Sprites**: paleta propia del sprite, celdas W/H, lienzo con pincel (clic en la paleta = indice de pincel). **Clic derecho** (o arrastrar con boton derecho) borra con indice **31**. **Borrar todo** vacia el lienzo (todo transparente). Debajo del lienzo, **colores usados** (clic para volver a elegir ese indice); **Intercambiar color** sustituye todos los pixeles de un indice por otro (origen resaltado con borde). Al **reducir** W/H el estudio conserva en memoria el arte fuera del lienzo para recuperarlo si se **agranda** de nuevo; al **guardar**, el JSON solo lleva el tamano activo (sin datos fuera de `pixel_w`×`pixel_h`).
- **Guardar sprite** escribe siempre `indexed_pixels` + `image.rows` (no sobrescribe con un solo color plano).
- **Crear JSON sprite** crea un sprite indexado relleno con el pincel actual.
- Rejilla del lienzo: paso configurable (1 px o multiplos de 4).
- Escala de vista: ampliacion por vecino mas cercano (pixeles nítidos).
- **Referencia visual** (PNG/JPG/…): importar imagen escalada al lienzo (`pixel_w`×`pixel_h`); visible bajo el relleno del lienzo (indice 1 por defecto), tapada al pintar. **Convertir en sprite** rellena `image.rows` con el color de paleta mas cercano por pixel (escala vecino mas cercano; alpha &lt; 0.5 → indice 31). Opacidad de referencia y de la **capa pintada** ajustables en la vista previa (no afectan al JSON exportado). La referencia **no** se guarda en el JSON del sprite.

Sprites cargados en modo `solid_palette_index` se muestran en el editor como lienzo relleno; al guardar pasan a `indexed_pixels`.

## Objetos (`turtlestudio.object`)

```json
{
  "format_version": 1,
  "kind": "turtlestudio.object",
  "id": "bloque",
  "name": "bloque",
  "sprite_id": "bloque_rojo"
}
```

## Cartucho: `studio/project_bundle.json`

Al exportar `main.turtlecart`, TurtleStudio puede embeber un JSON con:

| Campo | Uso |
|--------|-----|
| `kind` | `"turtlestudio.cart_bundle"` |
| `transparent_index` | Siempre **31** (reservado; no copiar al blitear `indexed_pixels`) |
| `active_scene` / escenas en `scenes` | Lista de escenas con `id`, `palette`, `background_index`, `objects[]` con `{ "id", "x", "y" }` |
| `objects` | Mapa `id` → definicion de objeto |
| `sprites` | Mapa `id` → JSON completo del sprite (copia de disco) |

El cartucho referencia la escena inicial con `INITIAL_SCENE:<id>` en el header (ver `spec/turtlecart-v0.md`).

## Firmware (TurtleReader, v0)

Si existe `studio/project_bundle.json` y `INITIAL_SCENE` coincide con una escena del bundle, **antes del `ENTRY` Lua** el firmware:

1. Rellena el framebuffer con `background_index` de esa escena (`cls`).
2. Para cada objeto en la lista de la escena, resuelve `sprite_id` y dibuja en `(x, y)` (**esquina inferior izquierda** del bbox del sprite, espacio escena).

### Resolucion de tamano

- Preferido: `pixel_w`, `pixel_h` del sprite.
- Si faltan: `blocks_w * cell_px`, `blocks_h * cell_px` con **`cell_px` default 4** en firmware si no viene en JSON.

### Dibujo segun modo

| Modo | Comportamiento |
|------|----------------|
| `solid_palette_index` | `fill_rect` con `render.palette_index` |
| `indexed_pixels` | Blit de `image.rows`; omite pixeles con indice `transparent_index` del bundle |

Limites actuales en firmware: sprite hasta **128×128** px en RAM estatica; indices acotados a **0..31** (paleta del cartucho).

### Transparencia

Ver `spec/scene-v0.md`: indice **31** fijo en todas las paletas. En el editor, los pixeles con indice 31 se muestran como hueco (color de relleno del lienzo) para ver referencias importadas debajo.

## Compatibilidad y migracion

| Origen | Notas |
|--------|--------|
| `cell_px: 8`, `blocks 2×2`, `16×16` px | Valid; solo cambia la rejilla logica si se reexporta con `cell_px: 4` manteniendo `pixel_w`/`pixel_h` (p. ej. `blocks 4×4`). |
| Solo `solid_palette_index` | Sigue funcionando en hardware; el editor guarda como indexado al editar. |
| Paleta distinta escena vs sprite | Permitido en datos; el firmware usa la **paleta del cartucho** (`PALETTE:`) para los indices. Alinear paletas es responsabilidad del autor. |

## Fuera de alcance (v0)

- Animacion (`frames[]`).
- Rotacion / flip en hardware.
- Compresion de matrices.
- Tilemaps y capas de fondo multiples en firmware (parcial en manifest; dibujo simple de fondo + objetos).

## Referencias en codigo

- TurtleStudio: `tools/turtlestudio/src/turtlestudio/sprites.py` (`DEFAULT_CELL_PX = 4`).
- Bundle: `tools/turtlestudio/src/turtlestudio/build.py`.
- Firmware: `firmware/TurtleReader/turtle_scene.cpp`, `turtle_gpu_blit_indexed_scene` en `turtle_gpu.cpp`.
