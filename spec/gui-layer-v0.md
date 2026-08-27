# Capas GUI apilables (v0)

Documento **complementario a `spec/scene-v0.md` y `spec/hud-border-v0.md`**: describe el segundo metodo de GUI, capas modales/superponibles que un cartucho define en el bundle y muestra u oculta en runtime. Sirve para menus de pausa, dialogos, inventario, pantalla de titulo, game over, popups no modales ("+1 vida", flash de dano) — cualquier UI transitoria que no encaje en la franja HUD permanente del metodo 1.

**Relacion con `hud-border-v0.md`**: las dos son ortogonales. La franja HUD es SIEMPRE visible durante el juego; las capas GUI son transitorias y se ocultan cuando el juego debe correr solo. Una capa GUI **puede** tapar la franja HUD (por ejemplo, el menu de pausa cubre todo el framebuffer, incluyendo el HUD del score) — cada capa decide su rectangulo. Ambas coexisten sin dependencias mutuas.

## Alcance v0

- **Contenido**: solo **rectangulos solidos** (fondo, marcos) y **etiquetas de texto** (fuente `.tfn` del bundle, con opcional tinte por color de paleta). Sin sprites, sin tiles.
- **Posicion/tamano**: rectangulo axis-aligned en coord de framebuffer (Y-abajo, top-left = `(0,0)`), independiente de la camara y del playfield. Una capa puede ir sobre el playfield, sobre la region HUD, o cubrir el framebuffer entero.
- **Apilamiento**: hasta **8 capas simultaneamente visibles** en el firmware. Cada capa tiene un `z` (default 0); las capas con `z` mayor se pintan encima. Empate por orden de aparicion en el manifest.
- **Persistencia entre escenas**: la visibilidad se **resetea a "oculto" al comenzar cada escena** (`turtle_scene_begin_runtime` limpia la lista de capas visibles). Un cartucho que quiere el mismo HUD/menu en dos escenas vuelve a llamar `gui_layer_show(id)` en el `_hud_init` o `_update` correspondiente.
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
| `gui_layer_hide_all()`                             | Oculta todas las capas activas (util para transiciones/cambios de estado).          |

`id`/`label_id` que no existan: no-op silencioso (para que el cart pueda usar `gui_layer_show` sin chequear existencia). En Serial se loguea la primera falla por id/label para debug.

Fuera de estas 5 funciones no hay API nueva de GUI en v0. El compositing lo hace el firmware — el cart solo cambia texto y visibilidad.

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

- **Sprites en capas**: reservado para v1 (probablemente `gui_layer_sprite(id, sprite_id, x, y, frame)`).
- **Tiles en capas**: reservado — patron muy usado en Semi (`.tortuguilayer` tiene un tile layer completo). Aca queda para v2 si aparece necesidad concreta.
- **Animaciones dentro de la capa** (blink de texto, sprites animados): el cart lo puede simular con `gui_layer_set_text` desde el `_hud(dt)`.
- **Transiciones/fade** de capa: fuera de scope. Cart lo puede simular tinteando texto o cambiando `bg_color_index` via campos futuros.
- **Anchoring/layout dinamico**: todas las posiciones son fijas al momento del manifest. Sin "center_horizontal" o wrapper de padding.
- **Modales que "detienen" completamente** (incluyendo animacion de sprites): en v0 la animacion de sprite sigue tickeando bajo pausa; si se necesita full-stop, cart llama `play_anim(..., speed=0)` antes de mostrar la capa.
