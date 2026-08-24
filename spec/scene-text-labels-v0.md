# Especificacion de escena — etiquetas de texto estaticas (v0)

Extiende **`spec/scene-v0.md`** (que sigue vigente: viewport 164×124, mundo via `world_steps_x/y`,
camara, sistema de coordenadas Y-arriba con origen inferior-izquierdo, paleta de 32 colores con
indice 31 transparente). Este documento cierra el punto que `spec/scene-v1.md` dejaba
explicitamente fuera ("Capas de GUI (`gui_layers` al estilo TortuMecha)... es un sistema aparte
(HUD, texto, barras)... si se hace, spec propio") solo para el caso mas simple: texto **estatico**
declarado en la escena, sin script.

## No hace falta subir `TURTLECART:1`

Igual que v1/v2, todo lo de este documento es **aditivo y opcional**. Una escena sin
`text_labels` se comporta exactamente igual que hoy. `TURTLECART:0` sigue siendo la cabecera
correcta.

## Por que no alcanza con lo que ya existe

- `text()` de la ENTRY VM (`spec/lua/firmware-bridge-v0.md` § "Texto") dibuja inmediato pero se
  borra en cuanto arranca una escena (`turtle_scene_begin_runtime` hace `cls()`+`snapshot_static`)
  — solo sirve para splash/no-bundle.
- `text()` de un actor es un overlay persistente, pero requiere un actor con `"script"` — un
  VM Lua completo solo para mostrar un titulo fijo es desperdicio de RAM/CPU y de autoria.

`text_labels` es la pieza que faltaba: texto fijo, sin Lua, declarado junto a `objects`/
`tile_layers` en la escena.

## Campo `text_labels`

Array opcional en el bloque de la escena (`scenes/<id>.json` / bundle), mismo nivel que
`objects`/`tile_layers`/`camera`:

```json
"text_labels": [
  { "id": "title", "text": "LEVEL 1", "x": 40, "y": 100, "font": "main", "color_index": -1 }
]
```

| Campo | Tipo | Default | Nota |
|---|---|---|---|
| `id` | string | — (requerido) | Estilo stem (`spec` de IDs de objeto/sprite/tile: letra inicial, luego letras/digitos/`_`/`-`, hasta 64 chars). Solo para listar/editar en TurtleStudio — el firmware no lo usa para dibujar. |
| `text` | string | — (requerido) | Una sola linea. Mismo charset que `.tfn`/`text()` hoy: espacio, `A-Z`, `a-z`, `0-9`, `` .,!?:;'- `` (`LATIN_CHARSET` en `turtlestudio/fonts.py`, `kCharset` en `turtle_font.cpp`). Caracteres fuera del charset no tienen glifo y el firmware los salta igual que ya hace `text()` (ver `spec/asset-bin-v0.md`). |
| `x`, `y` | int | — (requeridos) | Posicion en espacio escena (origen inferior-izquierdo, Y hacia arriba) del **origen del texto** — misma esquina que usa `turtle_font_draw_scene` para el overlay de actor: `x` es el borde izquierdo de la primera letra, `y` es el borde inferior de la linea. Mismo sistema que `objects[].x/y` y `camera`. |
| `font` | string | — (requerido) | Stem de una fuente `fonts/<font>.tfn` del proyecto. Una entrada cuya fuente no se puede resolver en tiempo de carga se salta (no rompe la escena) y se registra un aviso por Serial, igual que `text()`. |
| `color_index` | int | `-1` | `-1` = usar los colores propios horneados de cada glifo (comportamiento normal de la fuente). `0..31` = tiñe cada pixel no-transparente del glifo con ese indice de paleta, igual que el `color_index` opcional de `text()` en ambas VMs — util para reusar una fuente en varios colores de HUD. |

Entradas invalidas (falta `text`, `font` no resuelve, o mas de `kMaxTextLabels` etiquetas en una
escena) se saltan individualmente; el resto de la escena carga igual.

## Orden de pintado

Una etiqueta es **estatica** (nunca se mueve ni cambia en tiempo de ejecucion — para texto que un
script necesita actualizar, sigue siendo el `text()` de actor). Por eso se pinta como parte de la
misma capa "de fondo horneada" que el background + los tiles, **encima** de ambos y **debajo** de
los actores/sprites — nunca hace falta redibujarla por separado con logica de dirty-rect propia:

- **Escena sin scroll** (`scene_uses_scrolling()` falso, el caso comun): se pinta una sola vez en
  `turtle_scene_begin_runtime`, justo despues de `draw_tile_layers_for_scene()` y antes de
  `turtle_gpu_snapshot_static()` — queda horneada en el snapshot estatico, asi que
  `turtle_gpu_restore_static_dirty()` ya la restaura gratis cuando un actor se mueve por encima o
  se aleja, sin costo por fotograma.
- **Escena con scroll** (`world_steps_x/y` > 1): `paint_scene_static_layers()` ya repinta
  background + capas de imagen + tiles **cada fotograma** (los tres caminos de esa funcion, ver
  `spec/scene-v1.md` § "Bandas propias por capas 2-4" para el porque del camino en vivo de tiles);
  las etiquetas se pintan al final de esa misma funcion, en los tres caminos, para quedar siempre
  encima de tiles y por debajo de los actores que se dibujan despues en `draw_all_actors()`.

## Fuera de alcance de v0

- Texto multilinea / wrap / alineacion — una sola linea, igual que `text()` hoy.
- Etiquetas mutables en tiempo de ejecucion desde un script — para eso ya existe `text()` de actor.
- Colocacion por arrastre en el canvas de TurtleStudio — v0 edita posicion por lista + spinbox
  X/Y, igual que el panel de Camara; arrastre en canvas puede agregarse despues sin tocar este
  spec (es UX del editor, no del formato).

## Firmware (`turtle_scene.cpp`)

- `kMaxTextLabels` (16) + `struct SceneTextLabel { char id[40]; char text[64]; int x, y;
  char font_id[48]; int color_index; }`, array estatico `s_text_labels`/`s_text_label_count`
  (mismo patron que `s_placements`/`kMaxPlacements`).
- `parse_scene_text_labels(sc_start, sc_end)`: mismo shape que `parse_placements` — busca
  `"text_labels"`, recorre el array, `json_extract_string_for_key`/`json_extract_int_for_key` por
  objeto, `color_index` default `-1` si falta.
- `draw_scene_text_labels(uint8_t transparent_index)`: por etiqueta, `font_cache_get(...)` +
  `turtle_font_draw_scene_tint(...)` (si `color_index >= 0`) o `turtle_font_draw_scene(...)` —
  las mismas dos llamadas que ya usa `draw_actor_runtime` para el overlay de texto de actor.
- Se invoca desde `turtle_scene_begin_runtime()` (camino sin scroll, antes de
  `turtle_gpu_snapshot_static()`) y desde `paint_scene_static_layers()` (camino con scroll, al
  final de sus tres ramas) — ver "Orden de pintado" arriba.

## TurtleStudio

`text_labels` viaja en el bundle exportado exactamente igual que `objects`/`tile_layers`: el
`build.py` de TurtleStudio ya embebe cada fila de `scenes` del manifest tal cual dentro de
`studio/project_bundle.json` (no hay allow-list de campos de escena), asi que no hace falta tocar
el exportador — alcanza con que el editor escriba el campo en la fila de escena. El simulador
**Play** (`play_runtime.py`) dibuja las etiquetas con la misma logica de blit de glifos que ya usa
para el overlay de texto de actor, en el mismo punto relativo (despues de fondo/tiles, antes de
actores) para que la previsualizacion coincida con el firmware.
