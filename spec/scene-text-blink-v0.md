# Especificacion de escena — parpadeo de etiquetas de texto (v0)

Extiende **`spec/scene-text-labels-v0.md`** (que sigue vigente: campo `text_labels`, coordenadas,
charset, `color_index`). Este documento agrega el unico campo nuevo que hacia falta para el caso
de uso mas comun de UI retro ("PRESS START" parpadeando, indicador de vida bajo, etc.): parpadeo
puramente declarativo, sin script.

## Por que no un script por etiqueta

`spec/scene-text-labels-v0.md` ya descarto deliberadamente dar scripts a las etiquetas ("para eso
ya existe `text()` de actor") porque un VM Lua completo solo para alternar visible/oculto es el
mismo costo que el sistema de etiquetas estaticas nacio para evitar. Parpadear es, como la
animacion de sprites (`anim_fps`), un efecto puramente temporizado — el firmware ya resuelve eso
sin Lua para sprites, asi que `text_labels` sigue el mismo patron.

## Campo `blink_ms`

Nuevo campo opcional por entrada de `text_labels` (junto a `id`/`text`/`x`/`y`/`font`/`color_index`):

```json
{ "id": "start_prompt", "text": "PRESS START", "x": 40, "y": 20, "font": "main",
  "color_index": -1, "blink_ms": 500 }
```

- **`blink_ms`** (int, default **`0`**): `0` = sin parpadeo, la etiqueta es siempre visible
  (comportamiento identico a `spec/scene-text-labels-v0.md`, cero regresion). `> 0` = la
  etiqueta alterna visible/oculta cada `blink_ms` milisegundos de escena (medidos con el mismo
  reloj que ya usan `dt`/animacion de sprites) — arranca **visible** al comenzar la escena, la
  primera transicion a oculta ocurre a los `blink_ms` ms.
- Sin `repeat`/`duty cycle` distinto: el ciclo es siempre simetrico (mismo tiempo visible que
  oculto). Si hace falta un patron asimetrico o mas complejo en el futuro, es candidato a
  `blink_on_ms`/`blink_off_ms` como extension aditiva, no a scripts.

## Por que una etiqueta con blink no puede ir horneada

`spec/scene-text-labels-v0.md` hornea las etiquetas SIN blink como parte de la misma capa
estatica que fondo/tiles (una vez para escenas fijas, cada fotograma para escenas con scroll)
precisamente porque nunca cambian. Una etiqueta con `blink_ms > 0` viola esa premisa — su
visibilidad cambia con el tiempo aunque su posicion no se mueva — asi que queda **excluida** del
horneado y se resuelve por separado:

- **Escena con scroll**: sin cambios de arquitectura. `paint_scene_static_layers()` ya repinta
  fondo+tiles+etiquetas **cada fotograma** (`spec/scene-text-labels-v0.md`); alcanza con evaluar
  `blink_visible` en cada llamada, ya que la funcion entera se ejecuta por fotograma de todos
  modos.
- **Escena fija (sin scroll)**: aca si hace falta trabajo nuevo, porque el snapshot estatico
  normalmente se hornea **una sola vez**. Una etiqueta con blink se trata en cambio como
  "siempre activa" dentro del mismo sistema de dirty-rect que ya usa `draw_all_actors()` para
  actores: se marca su rect sucio **todos los fotogramas** (no solo cuando cambia de estado —
  mas simple que rastrear transiciones, y necesario para que un actor que pase por encima la
  tape/restaure bien, mismo motivo que existe la "Fase 2" de promocion de actores quietos), se
  restaura el fondo/tiles debajo via el mecanismo existente, y se redibuja solo si
  `blink_visible` es verdadero ese fotograma. Costo: proporcional a la cantidad de etiquetas
  parpadeantes (tipicamente 1-3 en una pantalla de titulo/HUD), no a la escena entera.

## Firmware (`turtle_scene.cpp`)

- `SceneTextLabel` gana `int blink_ms` (parseado, default `0`, negativo se trata como `0`) mas
  estado de runtime no persistido en JSON: `bool blink_visible` (arranca en `true` al parsear la
  escena) y `uint32_t blink_accum_ms`.
- `tick_text_labels(uint32_t delta_ms)` (llamada desde `turtle_scene_runtime_tick`, junto a
  `tick_actors`): mismo patron acumulador que `tick_actors` usa para avanzar frames de
  animacion — `blink_accum_ms += delta_ms`, un `while (blink_accum_ms >= blink_ms)` togglea
  `blink_visible` y resta `blink_ms`, tantas veces como periodos completos hayan pasado (cubre
  un `delta_ms` grande por un frame lento sin quedar desincronizado).
- `draw_scene_text_labels()` gana un parametro `include_blinking`: `false` en el horneado unico
  de escena fija (etiquetas con blink se saltan ahi por completo), `true` en
  `paint_scene_static_layers()` (repintado por fotograma de escena con scroll, evalua
  `blink_visible` cada vez).
- `draw_all_actors()` (camino de camara fija) gana, entre la Fase 1 y la Fase 2 de actores, un
  paso que marca dirty el rect de cada etiqueta con `blink_ms > 0` (usando
  `turtle_font_measure` para el ancho, igual que `actor_text_scene_bounds`) y lo agrega a
  `s_active_rects` para que la Fase 2 tambien la considere; despues del
  `turtle_gpu_restore_static_dirty()` existente, redibuja cada etiqueta parpadeante cuyo
  `blink_visible` sea verdadero ese fotograma.

## TurtleStudio

- `project.py`: `SceneTextLabelPlacement.blink_ms` (default `0`), clamp `[0, TEXT_LABEL_BLINK_MS_MAX]`
  (`60000` ms — tope de autoria, el firmware no impone limite). Viaja por los mismos tres puntos
  de guardado que el resto de los campos de `text_labels`
  (`_normalize_scenes_for_save`/`_write_mirror_scene_json_files` en `project.py`, `_normalize_row`
  en `scene_editor.py` — ver nota en memoria de proyecto sobre por que hace falta tocar los tres).
- Editor de escena: spinbox "Parpadeo (ms)" en el panel de etiquetas (`0` = sin parpadeo, texto
  especial "Sin parpadeo" en ese valor). La previsualizacion estatica del canvas del editor
  **ignora** `blink_ms` a proposito (siempre dibuja la etiqueta) — es una vista de diseño, no una
  simulacion en vivo, igual que no anima sprites cuadro a cuadro.
- **Play** (`play_runtime.py`, `PlaySession`): SI simula el parpadeo en vivo, porque Play corre
  un loop real con `dt`. `begin()` separa `text_labels` en estaticas (siguen horneadas en
  `_static_rgba`, igual que antes) y parpadeantes (`_blinking_labels`, excluidas del horneado);
  `tick()` avanza su acumulador con el mismo patron que el firmware; `render_rgba()` las dibuja
  en vivo cada fotograma (antes de los actores, mismo orden relativo que el firmware) cuando
  estan visibles.

## Nota de correctitud sobre `color_index` (no especifica de blink, pero relevante aca)

Al implementar el camino de dibujo en vivo de etiquetas parpadeantes se detecto que
`color_index >= 0` debe resolverse contra la **paleta activa de la escena**, no contra la paleta
propia de la fuente — en el firmware solo existe una paleta activa a la vez (`.tfn` no lleva
paleta embebida, ver `turtle_font.cpp`), asi que el selector de color de TurtleStudio (que
muestra los colores de la escena) tiene que coincidir con lo que se ve en hardware. Se corrigio
en el mismo cambio tanto la previsualizacion estatica (`scene_editor.py`) como el dibujo en vivo
de Play (`play_runtime.py`) para las etiquetas; el overlay de texto de **actor** (`text()` desde
un script) queda fuera de este documento y no se toco.

## Fuera de alcance de v0

- `blink_on_ms`/`blink_off_ms` asimetricos — ver seccion "Campo `blink_ms`" arriba.
- Fade/transicion suave entre visible y oculto — parpadeo binario, igual que el resto de la
  consola no tiene mezcla alfa en tier 0 (`spec/scene-v1.md`).
- Sincronizar el parpadeo entre varias etiquetas con offsets de fase distintos — cada etiqueta
  arranca su propio acumulador en `blink_visible = true` al comenzar la escena; dos etiquetas con
  el mismo `blink_ms` ya parpadean sincronizadas por construccion, no hace falta un campo aparte.
