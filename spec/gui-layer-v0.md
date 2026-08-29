# Capas GUI apilables (v0)

Documento **complementario a `spec/scene-v0.md` y `spec/hud-border-v0.md`**: describe el segundo metodo de GUI, capas modales/superponibles que un cartucho define en el bundle y muestra u oculta en runtime. Sirve para menus de pausa, dialogos, inventario, pantalla de titulo, game over, popups no modales ("+1 vida", flash de dano) — cualquier UI transitoria que no encaje en la franja HUD permanente del metodo 1.

**Relacion con `hud-border-v0.md`**: las dos son ortogonales. La franja HUD es SIEMPRE visible durante el juego; las capas GUI son transitorias y se ocultan cuando el juego debe correr solo. Una capa GUI **puede** tapar la franja HUD (por ejemplo, el menu de pausa cubre todo el framebuffer, incluyendo el HUD del score) — cada capa decide su rectangulo. Ambas coexisten sin dependencias mutuas.

## Alcance v0

- **Contenido**: **rectangulos solidos** (fondo, marcos), **etiquetas de texto** (fuente `.tfn` del bundle, con opcional tinte por color de paleta), **barras de progreso** (relleno fraccional en una direccion, con color solido o sprite tileado + marco opcional de 1 px + bandas de valor que cambian color/sprite) y **barras de pips** (N iconos discretos que muestran un valor entero, con opcional swap de sprite por bandas de valor). Sin tiles.
- **Posicion/tamano**: rectangulo axis-aligned en coord de framebuffer (Y-abajo, top-left = `(0,0)`), independiente de la camara y del playfield. Una capa puede ir sobre el playfield, sobre la region HUD, o cubrir el framebuffer entero.
- **Apilamiento**: hasta **8 capas simultaneamente visibles** en el firmware. Cada capa tiene un `z` (default 0); las capas con `z` mayor se pintan encima. Empate por orden de aparicion en el manifest.
- **Persistencia entre escenas**: la visibilidad se **resetea a "oculto" al comenzar cada escena** (`turtle_scene_begin_runtime` limpia la lista de capas visibles) y luego se aplica el campo `gui_layers_autoshow` de la escena (ver seccion "Auto-show por escena"). Un cartucho que quiere el mismo HUD/menu en dos escenas puede listarlas en `gui_layers_autoshow` (declarativo, sin codigo Lua) o llamar `gui_layer_show(id)` desde `_hud_init` / `_update`.
- **Sin animacion/blink** de contenido en v0: para actualizar dinamicamente un texto (contador, timer, tiempo restante), el codigo del cart usa `gui_layer_set_text(id, label_id, str)` cada fotograma (o cuando cambie).
- **Sin transparencia por-pixel** dentro del contenido de la capa: el "fondo transparente" (`transparent_bg`) simplemente no pinta el rectangulo de fondo — deja pasar la escena de abajo. Los rectangulos y texto pintados dentro sobrescriben (con transparencia solo por indice, indice 31 = transparente en glifos).

## Bundle: campo `guilayers` (top-level)

Las capas viven fuera del bloque `scenes`: son un catalogo global que cualquier escena puede referenciar por id.

```json
{
  "scenes": [...],
  "objects": [...],
  "guilayers": [
    {
      "id": "pause_menu",
      "x": 0, "y": 0, "w": 164, "h": 124,
      "bg_color_index": 0,
      "transparent_bg": false,
      "pauses_scene": true,
      "captures_input": true,
      "z": 100,
      "rects": [
        { "x": 20, "y": 40, "w": 124, "h": 44, "color_index": 5 }
      ],
      "text_labels": [
        { "id": "title", "x": 40, "y": 50, "font": "font_main",
          "text": "PAUSED", "color_index": 7 },
        { "id": "hint",  "x": 30, "y": 70, "font": "font_main",
          "text": "PRESS A TO RESUME" }
      ],
      "progress_bars": [
        { "id": "hp", "x": 6, "y": 6, "w": 60, "h": 6,
          "direction": "left_to_right", "fill_mode": "color",
          "fill_color_index": 11, "bg_color_index": 3,
          "border_color_index": 0, "value_num": 8, "value_den": 10,
          "ranges": [
            { "min_pct": 0, "max_pct": 25, "alt_color_index": 8 },
            { "min_pct": 25, "max_pct": 50, "alt_color_index": 9 }
          ]
        }
      ],
      "pip_bars": [
        { "id": "lives", "x": 6, "y": 16,
          "sprite_full_id": "heart_full", "direction": "horizontal",
          "gap_px": 1, "value": 3, "max_value": 5 }
      ]
    }
  ]
}
```

### Campos de la capa

| Campo             | Tipo      | Default          | Nota                                                                                            |
|-------------------|-----------|------------------|-------------------------------------------------------------------------------------------------|
| `id`              | string    | (obligatorio)    | Stem-name (letra + letras/digitos/`_`/`-`, max 32 char). Unico en el catalogo.                  |
| `x`, `y`          | int       | `0`, `0`         | Esquina superior-izquierda en coord de framebuffer.                                             |
| `w`, `h`          | int       | `164`, `124`     | Tamano en px. Se clampea a `[1, kSceneW]` / `[1, kSceneH]`.                                     |
| `bg_color_index`  | int       | `0`              | Indice de paleta (0..30) para el rectangulo de fondo. Ignorado si `transparent_bg=true`.        |
| `transparent_bg`  | bool      | `false`          | Si es `true`, no pinta el rectangulo de fondo (la escena debajo se ve).                         |
| `pauses_scene`    | bool      | `false`          | Ver "Pausa" mas abajo.                                                                          |
| `captures_input`  | bool      | `false`          | Ver "Input" mas abajo.                                                                          |
| `z`               | int       | `0`              | Orden de pintado. Mayor = mas arriba. Empate resuelve por orden de aparicion en el manifest.    |
| `rects`           | array     | `[]`             | Ver "Rectangulos" abajo.                                                                        |
| `text_labels`     | array     | `[]`             | Ver "Etiquetas de texto" abajo.                                                                 |
| `progress_bars`   | array     | `[]`             | Ver "Barras de progreso" abajo.                                                                 |
| `pip_bars`        | array     | `[]`             | Ver "Barras de pips" abajo.                                                                     |
| `sprites`         | array     | `[]`             | Ver "Iconos sprite" abajo.                                                                      |

### Rectangulos (`rects`)

Rellenos solidos dentro del rectangulo de la capa. Se pintan en el ORDEN del array (indice 0 primero, indice N-1 encima).

| Campo         | Tipo | Default | Nota                                                                                     |
|---------------|------|---------|------------------------------------------------------------------------------------------|
| `x`, `y`      | int  | `0`     | Relativos al `(x, y)` de la capa. Clampeados a los bordes de la capa.                    |
| `w`, `h`      | int  | `1`     | En px. Se clampea a `[1, capa.w]` / `[1, capa.h]` y al espacio restante desde `(x, y)`.  |
| `color_index` | int  | `0`     | Indice de paleta. 31 (transparente) es no-op — usar `transparent_bg` para dejar pasar.   |

Maximo por capa: **16 rects**. Rects excedentes se descartan al parsear con un aviso en Serial.

### Etiquetas de texto (`text_labels`)

Igual espiritu que las `scene.text_labels` (`spec/scene-text-labels-v0.md`) pero simplificadas — sin `blink_ms`, sin autoresize.

| Campo         | Tipo    | Default        | Nota                                                                                         |
|---------------|---------|----------------|----------------------------------------------------------------------------------------------|
| `id`          | string  | (obligatorio)  | Identificador dentro de la capa (para `gui_layer_set_text`). Stem-name, max 32 char.         |
| `x`, `y`      | int     | `0`, `0`       | Relativos al `(x, y)` de la capa; esquina superior-izquierda del PRIMER glifo (Y-abajo).     |
| `font`        | string  | (obligatorio)  | Stem del `.tfn` del bundle. Debe existir; si no, la etiqueta no se pinta con aviso.          |
| `text`        | string  | `""`           | Contenido inicial. Max 63 caracteres en runtime (buffer fijo por etiqueta).                  |
| `color_index` | int     | `-1`           | `-1` = sin tinte (colores del glifo). `0..30` = tinte plano (misma semantica que `hud_text`).|

Maximo por capa: **16 text labels**. Texto en runtime: buffer de 64 bytes (63 chars + nul) por etiqueta.

### Barras de progreso (`progress_bars`)

Relleno fraccional en una direccion. El valor se expresa como `value_num / value_den` (dos enteros para evitar coma flotante en el firmware); la fraccion resultante se clampea a `[0.0, 1.0]`. El area rellena es `round(fill_dim * fraction)`, donde `fill_dim` es `w` para direcciones horizontales o `h` para verticales.

Se pintan **despues** de `rects` y **antes** de `text_labels` (asi el texto puede quedar encima del bar como etiqueta visible del valor).

| Campo                | Tipo    | Default        | Nota                                                                                              |
|----------------------|---------|----------------|---------------------------------------------------------------------------------------------------|
| `id`                 | string  | (obligatorio)  | Stem-name, max 32 char. Unico dentro de la capa. Usado por `gui_layer_set_progress`.              |
| `x`, `y`             | int     | `0`, `0`       | Relativos al `(x, y)` de la capa. Clampeados al rect de la capa.                                  |
| `w`, `h`             | int     | `1`, `1`       | Tamano del rect del bar en px.                                                                    |
| `direction`          | string  | `left_to_right`| Uno de: `left_to_right`, `right_to_left`, `top_to_bottom`, `bottom_to_top`.                       |
| `fill_mode`          | string  | `color`        | `color` (fill_color_index) o `sprite` (tiled fill_sprite_id).                                     |
| `fill_color_index`   | int     | `11`           | Indice de paleta (0..30) del relleno cuando `fill_mode="color"`. `31` (transparente) es no-op.    |
| `fill_sprite_id`     | string  | `""`           | Stem del sprite del bundle cuando `fill_mode="sprite"`. El sprite se **tilea** sobre el rect rellenado (repetido tanto horizontal como verticalmente); las porciones parciales del ultimo tile se recortan al borde del area rellenada. Pixeles con indice de paleta 31 son transparentes. |
| `bg_color_index`     | int     | `3`            | Indice de paleta del fondo del bar (parte "vacia"). Usar `31` para dejar la escena/capa debajo visible en el area no rellenada. |
| `border_color_index` | int     | `-1`           | `-1` = sin marco. `0..30` = pinta un contorno de 1 px alrededor del rect completo del bar.        |
| `value_num`          | int     | `0`            | Numerador del valor actual. Runtime lo actualiza via `gui_layer_set_progress`. `[-32768, 32767]`. |
| `value_den`          | int     | `1`            | Denominador (valor maximo del bar). `[1, 32767]`. `0` o negativo se colapsa a `1`.                |
| `ranges`             | array   | `[]`           | Ver "Bandas de valor" abajo. Max 3 por bar.                                                       |

Maximo por capa: **4 progress bars**.

### Barras de pips (`pip_bars`)

N iconos discretos que muestran un valor entero — corazones de HP, llaves, medallas. Cada pip visible es el `sprite_full_id` completo; los pips "vacios" (posiciones `>= value`) **no se pintan** (la escena/capa debajo se ve), asi el autor puede usar un rect o sprite estatico en `rects` para simular la version apagada, o simplemente dejar el fondo.

| Campo             | Tipo    | Default        | Nota                                                                                              |
|-------------------|---------|----------------|---------------------------------------------------------------------------------------------------|
| `id`              | string  | (obligatorio)  | Stem-name, max 32 char. Unico dentro de la capa. Usado por `gui_layer_set_pips`.                  |
| `x`, `y`          | int     | `0`, `0`       | Relativos al `(x, y)` de la capa. Esquina superior-izquierda del PRIMER pip.                      |
| `sprite_full_id`  | string  | (obligatorio)  | Stem del sprite del bundle para el estado "encendido". Sus dimensiones determinan el ancho/alto de cada pip. Pixeles con indice 31 son transparentes. |
| `direction`       | string  | `horizontal`   | `horizontal` (pips crecen hacia +x) o `vertical` (pips crecen hacia +y).                          |
| `gap_px`          | int     | `0`            | Separacion en px entre pips consecutivos. Rango `[0, 32]`.                                        |
| `value`           | int     | `0`            | Cantidad de pips "encendidos" a pintar. Se clampea a `[0, max_value]`.                            |
| `max_value`       | int     | `1`            | Total de pips del bar. Rango `[1, 32]`. Solo se pintan los primeros `value`; los demas quedan invisibles. |
| `ranges`          | array   | `[]`           | Ver "Bandas de valor" abajo. Cuando aplica, el rango puede reemplazar el `sprite_full_id` via `alt_sprite_id`. Max 3 por bar. |

Maximo por capa: **4 pip bars**.

### Iconos sprite (`sprites`)

Un blit 1:1 de un sprite del bundle en una posicion fija. Pensado como *iconografia* del HUD (engranaje al lado de un contador, cabeza del jugador junto a las vidas, icono de estado junto a un timer) — no como pip repetido ni como relleno tileado. El sprite comparte la paleta de la escena (no hay paleta separada por capa GUI); pixeles con indice 31 son transparentes. Se pintan **despues** de `pip_bars` y **antes** de `text_labels`.

| Campo          | Tipo    | Default        | Nota                                                                                              |
|----------------|---------|----------------|---------------------------------------------------------------------------------------------------|
| `id`           | string  | (obligatorio)  | Stem-name, max 32 char. Unico dentro de la capa. Usado por `gui_layer_set_sprite`.                |
| `x`, `y`       | int     | `0`, `0`       | Relativos al `(x, y)` de la capa. Esquina superior-izquierda del blit.                            |
| `sprite_id`    | string  | (obligatorio)  | Stem del sprite del bundle. Sus dimensiones y frame determinan lo dibujado.                       |
| `frame_index`  | int     | `0`            | Fotograma del sprite (para sprites animados, la capa no anima — el cart puede rotar frames desde Lua). |
| `flip_h`       | bool    | `false`        | Espejo horizontal en el momento del blit (util para reusar el mismo sprite mirando a otro lado).  |
| `flip_v`       | bool    | `false`        | Espejo vertical.                                                                                  |

Maximo por capa: **4 iconos sprite**.

### Bandas de valor (`ranges`)

Ambos tipos de bar admiten un array `ranges` de hasta 3 elementos que **reemplazan** el color/sprite base cuando la fraccion actual (`value_num / value_den` para progress, `value / max_value` para pips) cae dentro de `[min_pct, max_pct)`. Sirve para el patron clasico "verde >50%, amarillo 25-50%, rojo <25%".

| Campo              | Tipo   | Default | Nota                                                                                              |
|--------------------|--------|---------|---------------------------------------------------------------------------------------------------|
| `min_pct`          | int    | `0`     | Inclusivo. `[0, 100]`.                                                                            |
| `max_pct`          | int    | `100`   | Exclusivo (salvo cuando `max_pct=100`, entonces inclusivo — asi el rango 100 nunca queda huerfano). |
| `alt_color_index`  | int    | `-1`    | Solo aplica a progress bars con `fill_mode="color"`. `-1` = no reemplazar. `0..30` = usar este color. |
| `alt_sprite_id`    | string | `""`    | Progress con `fill_mode="sprite"`: reemplaza `fill_sprite_id`. Pip bar: reemplaza `sprite_full_id`. `""` = no reemplazar. |

Ordenamiento: los rangos se evaluan en el orden del array; el **primer** rango cuyo intervalo cubre la fraccion actual gana. Si ningun rango matchea, se usa el color/sprite base del bar. Rangos con `min_pct >= max_pct` se descartan al parsear.

## Runtime (VM ENTRY)

Estado global mantenido por el firmware (`turtle_gui_layer.h/.cpp`):
- Al comenzar una escena (`turtle_scene_begin_runtime`), se parsean todas las capas del bundle y su visibilidad queda **oculta**.
- Cada fotograma, DESPUES del redibujo de actores y DESPUES de `_hud(dt)`, el firmware pinta las capas visibles en orden de `z` ascendente. La franja HUD ya esta pintada por metodo 1; una capa GUI con `x=0 y=0 w=kSceneW h=kSceneH` la cubre.

### Bindings Lua (VM ENTRY)

Todos actuan sobre el catalogo cargado del bundle actual. `id` es siempre el `id` del manifest.

| Firma Lua                                          | Efecto                                                                              |
|----------------------------------------------------|-------------------------------------------------------------------------------------|
| `gui_layer_show(id [, z])`                         | Marca visible. `z` opcional overridea el `z` del manifest en este show.             |
| `gui_layer_hide(id)`                               | Marca oculta. Sin efecto si ya lo estaba.                                           |
| `gui_layer_visible(id)` → bool                     | Consulta.                                                                           |
| `gui_layer_set_text(id, label_id, str)`            | Actualiza el texto de una etiqueta. Se trunca a 63 chars. Persiste hasta el proximo set. |
| `gui_layer_set_progress(id, bar_id, num [, den])`  | Actualiza `value_num` de una progress bar. Si se pasa `den`, tambien reemplaza `value_den` (util cuando el maximo cambia en runtime — nivel-up sube HP max). Sin `den` solo se actualiza el numerador. |
| `gui_layer_set_pips(id, bar_id, val [, max])`      | Actualiza `value` de un pip bar. `max` opcional reemplaza `max_value`. `val` se clampea a `[0, max_value]` despues.  |
| `gui_layer_set_sprite(id, icon_id, sprite_id [, frame])` | Reemplaza el `sprite_id` (y opcionalmente el `frame_index`) de un icono sprite. Util para cambiar iconografia dinamica (llave sin/con, cara del jugador segun estado). |
| `gui_layer_hide_all()`                             | Oculta todas las capas activas (util para transiciones/cambios de estado).          |

`id`/`label_id`/`bar_id`/`icon_id` que no existan: no-op silencioso (para que el cart pueda llamar sin chequear existencia). En Serial se loguea la primera falla por id/label para debug.

Fuera de estas 8 funciones no hay API nueva de GUI en v0. El compositing lo hace el firmware — el cart solo cambia texto, valores de bars, iconos y visibilidad.

## Auto-show por escena (`gui_layers_autoshow`)

Cada escena puede declarar en su manifest un array de ids de capas GUI que el firmware debe
mostrar automaticamente al comenzar la escena — sin necesidad de codigo Lua. Pensado para
HUDs de nivel (score, vidas, radar) que **siempre** estan arriba en esa escena. Los menus
tipo pausa/dialogo siguen siendo Lua-triggered y NO se listan aca.

```json
{
  "scenes": [
    {
      "id": "level_1",
      "gui_layers_autoshow": ["hud_score", "hud_lives"],
      ...
    }
  ]
}
```

Semantica:

- Se aplica **despues** del reset de visibilidad de `turtle_scene_begin_runtime`, y **antes** del primer `_hud(dt)`. Efecto identico a haber llamado `gui_layer_show(id)` desde ENTRY VM sin `z` override.
- El z-order es el propio del manifest de cada capa. No hay override por escena (mantener el modelo simple; si se necesita, editar el `z` de la capa).
- Ids repetidos en el array se ignoran silenciosamente. Ids que no existen en el catalogo `guilayers` del bundle: no-op y aviso en Serial (mismo comportamiento que `gui_layer_show` con id invalido).
- Compatibilidad: escenas antiguas sin el campo se comportan como antes (ninguna capa auto-mostrada). Default: `[]`.
- El cart puede llamar `gui_layer_hide(id)` en cualquier momento para ocultar una capa auto-mostrada (por ejemplo esconder el HUD durante una cutscene).

Autor: el editor de escenas de TurtleStudio muestra un checkbox por cada `guilayers/*.json` del proyecto; marcar = incluir el id en `gui_layers_autoshow` de la escena.

## Pausa

Cuando cualquier capa visible tiene `pauses_scene: true`, en el proximo tick:
- Los `_update(dt)` de los actores **no se llaman**.
- La animacion de sprites de actor **si sigue** (frames avanzan) — pensado para que un sprite quede en su animacion idle bajo un menu; el cart que quiera congelarlo tambien puede llamar `play_anim` con velocidad 0.
- `move()` de actores no se ejecuta (no hay `_update` que lo llame).
- `tick_text_labels` de la escena (blink) **si sigue** — hacer parpadear el texto de escena bajo un menu es raro pero valido.

El `_hud(dt)` de ENTRY VM **si se sigue llamando** (para que el cart mantenga vivo el HUD y navegue el menu). El cart puede reflejar la pausa cambiando el HUD (por ejemplo iconos grises) desde dentro del `_hud(dt)`.

## Input

Cuando cualquier capa visible tiene `captures_input: true`:
- Las llamadas `btn(k)` / `btnp(k)` desde **VMs de actor** devuelven `false` para toda tecla en ese tick — como si el jugador no estuviera tocando nada. El actor no siente input.
- La VM ENTRY sigue recibiendo `btn/btnp` normales — el `_hud(dt)` puede navegar el menu.
- Pensado para menus modales: la logica del juego (actores) queda "fuera del bucle de input" mientras el menu esta arriba.

Si `captures_input=false` (default), los actores siguen recibiendo input aunque la capa este arriba — util para popups no bloqueantes ("Achievement unlocked").

## Compositing y hud_border

- Las capas ignoran el rect del playfield: pueden pintar en cualquier pixel del framebuffer, incluyendo la franja HUD del metodo 1.
- El pintado usa `turtle_gpu_pixel_absolute` / `turtle_gpu_fill_rect_absolute` internamente... con una excepcion clave: **`turtle_gpu_pixel_absolute` normalmente rechaza escrituras dentro del playfield** (para proteger la zona de juego de bindings HUD). Las capas GUI usan un camino paralelo (`turtle_gpu_pixel_raw`, agregado por este spec) que **si** escribe en playfield — necesario para pintar un menu que cubra la accion del juego.
- Orden por fotograma:
  1. `paint_scene_static_layers` (mundo + tiles + labels) → playfield.
  2. `draw_all_actors` → actores dentro del playfield.
  3. `_hud(dt)` → HUD del metodo 1 (fuera del playfield).
  4. Capas GUI visibles, ordenadas por `z` ascendente.
  5. `flip()`.

## Errores comunes y modos de fallo

| Sintoma                                              | Causa tipica                                                                              |
|------------------------------------------------------|-------------------------------------------------------------------------------------------|
| `gui_layer_show("pause")` no muestra nada.           | El `id` no matchea (typo, o la capa no esta en el bundle). Chequear Serial al arrancar.   |
| La capa se ve un frame y desaparece.                 | Otro codigo esta llamando `gui_layer_hide` u `hide_all` en el mismo tick.                 |
| El HUD del metodo 1 no se ve bajo la capa.           | Esperado — la capa cubre el framebuffer. Si esta con `transparent_bg=true`, el HUD si se ve. |
| El actor sigue moviendose con el menu de pausa arriba. | La capa no tiene `pauses_scene: true`. Update del manifest y re-exportar.                |
| Un popup ("+1 vida") congela al jugador.             | La capa tiene `pauses_scene` y/o `captures_input` en true. Poner ambos en false.          |
| El texto no cambia con `gui_layer_set_text`.         | El `label_id` no existe en esa capa. Ojo con typos.                                        |

## Fuera de alcance en v0

- **Sprites completamente dinamicos con blit directo desde Lua** (`gui_layer_blit_sprite(x, y, sprite_id)`): reservado. En v0 los sprites son declarativos: `sprites` en el manifest para iconos estaticos (posicion fija, cambio de sprite/frame desde Lua via `gui_layer_set_sprite`), `progress_bars` con `fill_mode="sprite"` para tileado, `pip_bars` para repetidos discretos.
- **Tiles en capas**: reservado — patron muy usado en Semi (`.tortuguilayer` tiene un tile layer completo). Aca queda para v2 si aparece necesidad concreta.
- **Animaciones dentro de la capa** (blink de texto, sprites animados): el cart lo puede simular con `gui_layer_set_text` desde el `_hud(dt)`.
- **Transiciones/fade** de capa: fuera de scope. Cart lo puede simular tinteando texto o cambiando `bg_color_index` via campos futuros.
- **Anchoring/layout dinamico**: todas las posiciones son fijas al momento del manifest. Sin "center_horizontal" o wrapper de padding.
- **Modales que "detienen" completamente** (incluyendo animacion de sprites): en v0 la animacion de sprite sigue tickeando bajo pausa; si se necesita full-stop, cart llama `play_anim(..., speed=0)` antes de mostrar la capa.
