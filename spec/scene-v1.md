# Especificacion de escena y coordenadas (v1) — parallax extendido

Extiende **`spec/scene-v0.md`** (que sigue vigente: viewport 264×198, mundo via `world_steps_x/y`,
camara, sistema de coordenadas, transparencia, y el modelo de 4 capas de fondo con **capa 1**
como capa base/horneada). Este documento **no** reemplaza v0, solo cierra los puntos que v0 dejaba
explicitamente en su "Fuera de alcance": scroll vertical de parallax, bandas en capas 2-4, y
renderizado de esas capas fuera de escenas con scroll.

## No hace falta subir `TURTLECART:1`

Igual que `parallax_bands` y `background_layers` en v0, todos los campos de este documento son
**opcionales y aditivos** en el bloque de escena (`scenes/<id>.json` / bundle). Una escena sin
estos campos se comporta exactamente igual que con v0 — no hay regresion posible ni cambio en el
contenedor `.turtlecart`. `TURTLECART:0` sigue siendo la cabecera correcta.

## Que cierra v1 (referencia a los "Fuera de alcance" de v0)

| Gap listado en v0 | Seccion de este documento |
|---|---|
| `parallax_y` (bandas de capa 1, `background_layers[0]`) | [Scroll vertical en `parallax_bands`](#scroll-vertical-en-parallax_bands) |
| `repeat_y` por banda | [Scroll vertical en `parallax_bands`](#scroll-vertical-en-parallax_bands) |
| Bandas por fila en capas 2-4 (hoy solo capa 1 via `parallax_bands`) | [Bandas propias por capas 2-4](#bandas-propias-por-capas-2-4) |
| Offset vertical / `parallax_y` por capa (capas 2-4) | [Scroll y offset vertical por capa](#scroll-y-offset-vertical-por-capa) |
| Capas con imagen en escenas sin scroll | [Capas sin scroll (`world_steps` 1×1)](#capas-sin-scroll-world_steps-1×1) |
| Mezcla alfa / opacidad real entre capas | [Transparencia aproximada (dither)](#transparencia-aproximada-dither) |

Explicitamente **fuera de alcance de v1** tambien (no se tocan en este documento):

- Capas de GUI (`gui_layers` al estilo TortuMecha) — es un sistema aparte (HUD, texto, barras),
  no parallax de escena; si se hace, spec propio.
- Bandas / parallax por columna (parallax vertical distinto por rango de X) — no hay caso de uso
  claro todavia.
- Mezcla alfa real en espacio RGB (requiere leer el framebuffer destino y volver a cuantizar a
  paleta por pixel; ver la seccion de dither mas abajo para la alternativa barata que si entra en
  v1).

## Scroll vertical en `parallax_bands`

Cada entrada de `parallax_bands` (bandas de **capa 1**, `spec/scene-v0.md` § "Bandas de parallax
horizontal") gana dos campos opcionales:

```json
"parallax_bands": [
  { "y0": 140, "y1": 197, "parallax_x": 1.0,  "parallax_y": 1.0 },
  { "y0": 70,  "y1": 139, "parallax_x": 0.5,  "parallax_y": 0.6, "repeat_x": true },
  { "y0": 0,   "y1": 69,  "parallax_x": 0.15, "parallax_y": 0.2, "repeat_x": true, "repeat_y": true }
]
```

- **`parallax_y`** (float, default **`1.0`**, acotado **0.0..2.0** igual que `parallax_x`): factor
  de scroll vertical de esa banda respecto a la camara. `1.0` = comportamiento de hoy (la banda
  sigue verticalmente igual que `cam_y`, que es como se comporta v0 porque hoy `vis_y0/vis_y1`
  vienen directo de `cam_y` sin factor). Con `parallax_y < 1.0` la banda se desplaza mas lento en
  vertical que la camara (fondo lejano tambien "respira" menos con saltos/scroll vertical).
- **`fixed`** (ya existente en v0) sigue anulando el offset horizontal a 0; con `parallax_y`
  presente, `fixed` **tambien** anula el offset vertical a 0 — una banda fija lo es en ambos ejes,
  no solo en X (evita el caso raro de una banda "fija en X pero flotando en Y").
- **`repeat_y`** (bool, default `false`): igual que `repeat_x` pero para el muestreo vertical —
  la fila de origen se envuelve (`modulo` la altura del bitmap de fondo) en vez de recortarse.
  Necesaria para bandas con `parallax_y < 1.0` que si no se quedarian sin filas de origen antes de
  que la camara llegue al borde vertical del mundo (mismo razonamiento que `repeat_x` en v0).
- Filas de escena sin banda activa, o bandas sin estos campos: `parallax_y=1.0`, `repeat_y=false`
  — igual que hoy, cero regresion.

### Firmware

- `ParallaxBand` (`turtle_scene.cpp`, ~linea 67) gana `float parallax_y;` y `bool repeat_y;`.
- `parse_scene_parallax_bands()` (~linea 1826) lee las dos claves nuevas con los mismos helpers
  `json_extract_float_for_key` / `json_extract_bool_for_key` ya usados para `parallax_x`/`repeat_x`,
  mismo clamp `0.0..2.0`.
- `paint_world_background_banded()` (la funcion que hoy resuelve `find_parallax_band` por fila,
  ~linea 1247) pasa a calcular tambien un `y_offset = static_cast<int>(cam_y * band->parallax_y)`
  por banda (en vez de usar `scene_y` directo como fila de muestreo) y aplica `repeat_y` con el
  mismo patron de `modulo` que ya existe para `repeat_x` en `turtle_gpu_blit_indexed_row_banded`.

## Bandas propias por capas 2-4

Hoy (`spec/scene-v0.md` § "Capas de fondo con imagen") capas 2-4 solo admiten un factor de scroll
horizontal **uniforme** — toda la imagen a la misma velocidad; solo capa 1 tiene banding, via el
`parallax_bands` de nivel de escena. v1 permite que una entrada de capas 2-4 declare su **propio**
array `parallax_bands` (mismo esquema que el de capa 1, incluyendo los campos nuevos de la seccion
anterior) para el parallax clasico de "varias franjas dentro de la misma imagen de capa" (p. ej.
una sola imagen de "colinas" donde la cresta se mueve mas rapido que la base). Capa 1 **no**
necesita esto — ya tiene banding completo via el `parallax_bands` de escena.

```json
"background_layers": [
  { "enabled": true, "background": "sky_main" },
  { "enabled": true, "background": "hills_mid",
    "parallax_bands": [
      { "y0": 100, "y1": 197, "parallax_x": 0.6 },
      { "y0": 0,   "y1": 99,  "parallax_x": 0.4, "repeat_x": true }
    ]
  }
]
```

- Si `parallax_bands` esta presente y no vacio en una entrada de capas 2-4, **anula** los campos
  uniformes `parallax_x`/`fixed`/`repeat_x` de esa misma entrada (se ignoran; la capa se comporta
  banda por banda, igual que capa 1). Sin `parallax_bands` (o vacio), la capa sigue el
  comportamiento uniforme de v0 sin cambios. Un `parallax_bands` dentro de la entrada de **capa 1**
  (indice 0) se ignora: esa capa ya usa el `parallax_bands` de escena descrito arriba.
- Limite: igual que capa 1, **8 bandas** por entrada (`kMaxParallaxBands`); siguen habiendo como
  maximo 3 entradas de capas 2-4 en `s_bg_image_layers` (`kMaxBgImageLayers`, ver
  `spec/scene-v0.md`) — esto **no** agrega mas capas, solo mas control dentro de cada una.
- Costo: banding por capa significa resolver `find_parallax_band` una vez por fila **por capa**
  en vez de una vez por fila total — mismo tipo de costo que ya paga capa 1, multiplicado por
  capas habilitadas con bandas. Ver tambien el aviso de RAM/tiempo de v0 (§ "Costo real, no
  gratis"): esto sigue sin ser gratis, solo mas flexible.

### Firmware

- `BgImageLayer` (~linea 79) gana `ParallaxBand bands[kMaxParallaxBands]; int band_count;` (o un
  puntero a un pool compartido si el presupuesto de RAM estatica aprieta — a decidir en
  implementacion, no cambia el spec). Recordar que `s_bg_image_layers` ya no incluye la entrada de
  indice 0 (capa base, horneada por separado) — solo capas 2-4.
- `parse_scene_bg_image_layers()` (~linea 1975) intenta parsear `"parallax_bands"` dentro del
  objeto de cada capa **antes** de leer los campos uniformes (saltando la primera entrada del
  array, como ya hace hoy); si encuentra el array no vacio, reusa la misma logica interna de
  `parse_scene_parallax_bands()` (refactorizada a una funcion compartida que tome un
  `sc_start/sc_end` y un buffer de salida) en vez de duplicar el parser.
- `paint_bg_image_layers()` (~linea 1321): si `ly->band_count > 0`, resuelve banda por fila con
  `find_parallax_band`-equivalente sobre `ly->bands` en vez de usar `ly->parallax_x`/`fixed`
  directo.

## Scroll y offset vertical por capa

Hoy cada capa 2-4 se **ancla siempre en la esquina inferior del mundo** (`scene_y=0`); no hay
forma de moverla en vertical ni de que responda a la camara en Y (capa 1 ya puede, via
`parallax_bands`). v1 agrega, solo para entradas de capas 2-4:

```json
{ "enabled": true, "background": "clouds_far",
  "parallax_x": 0.2, "repeat_x": true,
  "parallax_y": 0.3, "repeat_y": true, "offset_y": 40 }
```

- **`parallax_y`** (float, default `1.0`, acotado `0.0..2.0`): mismo significado que en
  `parallax_bands` — factor de scroll vertical respecto a `cam_y`. `1.0` en una capa cuya imagen
  no cubre todo el alto del mundo simplemente hace que esa capa se desplace en vertical igual de
  rapido que la camara ademas de en horizontal.
- **`repeat_y`** (bool, default `false`): envuelve el muestreo vertical (`modulo` `ph` de la capa).
- **`offset_y`** (int, default `0`): desplazamiento vertical fijo en pixeles de escena, aplicado
  **antes** de `parallax_y`/camara — sube o baja el punto de anclaje de la capa respecto al piso
  del mundo. Reemplaza el anclaje fijo-siempre-abajo de v0 por un anclaje configurable; `0` es
  identico al comportamiento de hoy (ancla abajo).
- Si `parallax_y`/`repeat_y`/`offset_y` estan ausentes: comportamiento identico a v0 (capa fija
  verticalmente, anclada abajo, sin scroll en Y). Sin efecto en capa 1 (indice 0): esa capa usa
  `parallax_bands` de escena para todo su scroll, vertical incluido.

### Firmware

- `BgImageLayer` gana `float parallax_y; bool repeat_y; int offset_y;`.
- `paint_bg_image_layers()`: el bucle que hoy usa `scene_y` directo como `row_top = (ly->ph-1) -
  scene_y` pasa a calcular `sample_y = offset_y_layer + static_cast<int>(cam_y * ly->parallax_y) +
  scene_y_local` (formula exacta a afinar en implementacion contra el mismo criterio que
  `paint_world_background_banded` usa para X) y aplica `repeat_y` con `modulo ly->ph` o recorta
  (deja de pintar esa fila) igual que hoy hace para filas fuera de `ly->ph`.

## Capas sin scroll (`world_steps` 1×1)

v0 solo renderiza capas 2-4 cuando la escena tiene camara con scroll (`world_steps_x` o
`world_steps_y` > 1). v1 quita esa restriccion: una capa habilitada se dibuja siempre que
`enabled=true`, tenga o no la escena scroll. En una escena sin scroll el resultado es simplemente
una capa estatica superpuesta (offsets calculados con `cam_x=cam_y=0`, que es el valor real de la
camara en una escena `world_steps` 1×1) — util para decoracion en capas sin tener que fingir una
camara con scroll para poder usar capas 2-4.

### Firmware

- El chequeo que hoy hace `paint_bg_image_layers()` (o quien la llama) para saltarse capas en
  escenas sin scroll se elimina; la funcion ya es segura con `cam_x=cam_y=0` (offsets quedan en 0
  salvo `offset_y` explicito).

## Transparencia aproximada (dither)

Alfa blending real (mezclar RGB de dos indices de paleta y recuantizar al indice mas cercano) no
entra en v1: el motor no lee el framebuffer destino en ningun otro punto del pipeline y agregar
esa lectura por pixel en cada capa habilitada es un costo de tiempo de frame que no se puede medir
sin hardware real primero (mismo espiritu que el aviso de RAM de v0). En su lugar, v1 resuelve
el campo `opacity` (ya existente en el manifest de `background_layers`, hoy solo usado por
TurtleStudio para el `cls()` de respaldo) como una **aproximacion por patron** al pintar en
firmware:

- `opacity` se cuantiza a **5 escalones**: `255` (opaco, sin cambio), `191`, `127`, `63`, `0`
  (capa invisible, no se pinta — ya es el comportamiento de `enabled=false`).
- Para escalones intermedios, el pixel de la capa se pinta solo en una fraccion de las celdas
  segun un patron fijo tipo Bayer 4×4 (umbral por `(x mod 4, y mod 4)` contra el escalon de
  opacidad) — el pixel "no pintado" deja ver lo que ya esta debajo (capa 1 / capa previa), igual
  que hace hoy `enabled=false` pero por-pixel en vez de por-capa completa. Es el mismo truco que
  las consolas de 8/16 bits con paleta indexada usaban para pseudo-transparencia. Aplica a
  cualquier capa (1-4) que use el color plano de respaldo, no solo a capas 2-4.
- No requiere leer el framebuffer destino ni tabla de mezcla RGB: sigue siendo "pintar o no pintar
  ese pixel de la capa", solo que la decision depende de `(x, y, opacity)` en vez de ser binaria
  por capa.

### Fuera de alcance (revisar si un objetivo futuro tiene mas musculo)

Mezcla RGB real por pixel queda para un documento aparte si algun objetivo de hardware (p. ej. uno
con mas CPU/RAM disponible que el ESP32-S3 actual) justifica el costo de leer+recuantizar el
framebuffer por pixel — no se descarta, solo no es parte de v1.

### Firmware

- `paint_bg_image_layers()` gana el chequeo de patron Bayer antes de escribir cada pixel cuando
  `ly->opacity < 255` (nuevo campo `uint8_t opacity;` en `BgImageLayer`, hoy el campo existe solo
  en el manifest/TurtleStudio, no se guarda en la struct de firmware).
- `parse_scene_bg_image_layers()` lee `"opacity"` (u8, default `255`) igual que ya lee
  `color_index` indirectamente hoy via TurtleStudio.

## Resumen de campos nuevos (referencia rapida)

| Bloque | Campo | Tipo | Default | Rango/nota |
|---|---|---|---|---|
| `parallax_bands[]` (capa 1) | `parallax_y` | float | `1.0` | `0.0..2.0` |
| `parallax_bands[]` (capa 1) | `repeat_y` | bool | `false` | — |
| `background_layers[]` (capas 2-4) | `parallax_bands` | array | `[]` (ausente) | mismo esquema que arriba; si no vacio, anula `parallax_x`/`fixed`/`repeat_x` de esa capa; sin efecto en capa 1 |
| `background_layers[]` (capas 2-4) | `parallax_y` | float | `1.0` | `0.0..2.0` |
| `background_layers[]` (capas 2-4) | `repeat_y` | bool | `false` | — |
| `background_layers[]` (capas 2-4) | `offset_y` | int | `0` | pixeles de escena, aplicado antes de `parallax_y` |
| `background_layers[]` (cualquier capa) | `opacity` | u8 | `255` | cuantizado a 5 escalones en firmware, dither Bayer 4×4 |

Todos los campos son opcionales; su ausencia reproduce exactamente el comportamiento de
`spec/scene-v0.md`.
