# HUD por borde de camara (v0)

Documento **complementario a `spec/scene-v0.md`**: describe como un cartucho puede reservar bordes fijos del framebuffer para HUD (marcador, vidas, minimapa, temporizador) reduciendo el area util de la camara. Es el equivalente al split de la barra de status en NES/SNES: un jugador pierde algo de mundo visible a cambio de que la CPU no tenga que redibujar esa franja cada fotograma, y a cambio de tener un lugar "no jugable" garantizado donde poner el HUD.

Este es el **metodo 1** de GUI (`spec/hud-border-v0.md`, permanente durante el juego). El **metodo 2** — capas GUI apilables tipo `.tortuguilayer` para menus modales, pausa, inventario, dialogos — se describira aparte y compone limpiamente con este: la franja HUD por borde queda como "zona segura" que una capa modal puede ignorar o superponer.

## Campo del manifest (`scene`, dentro de `camera`)

```json
"camera": {
  "mode": "follow",
  "target": "player",
  "hud_border": {
    "top":    16,
    "bottom":  0,
    "left":    0,
    "right":   0,
    "bg_color_index": 3
  }
}
```

- Anidado bajo `camera` (misma familia de opciones que `mode`/`margin_x`/`margin_y`).
- Cuatro enteros en **pixeles del framebuffer** (no de escena logica): `top`, `bottom`, `left`, `right`. Cada uno indica **cuantos pixeles de ese borde se apartan del area de camara** para reservarlos como HUD.
- `bg_color_index` (opcional, default `-1`): indice de paleta con el que el firmware pinta la franja HUD **una vez** al comenzar la escena, ANTES de `_hud_init`. `-1` = no pintar (comportamiento previo, el HUD arranca con lo que dejo el `cls()`). `0..30` = color plano. `31` (transparente) se colapsa a `-1`. Ahorra a la mayoria de HUDs de escribir un `hud_clear(...)` manual en cada `_hud_init`.
- `overlay` (opcional, default `false`): cuando es `true`, el **mundo mantiene el tamano canonico completo** (`kSceneW × world_steps_x`, `kSceneH × world_steps_y`) en lugar de encogerse al playfield. El actor puede moverse a coords de escena que caen fuera del playfield visible; sus pixeles que caen en la region HUD **quedan invisibles** (el clip por playfield en los blits de escena los oculta), y el HUD se pinta encima. La camara se clampea contra el framebuffer completo en vez del playfield, asi no scrollea automaticamente para "revelar" al personaje que entro debajo del HUD (comportamiento tipo Metroid: el jugador salta arriba y desaparece detras de la franja HUD sin que la vista se corra). Default `false` conserva el comportamiento previo (mundo = playfield, actor rebota contra el borde interno).
- Ausente / `null` / cualquier campo ausente = **`0`** (comportamiento identico al de antes de este spec). Cartuchos ya exportados no se ven afectados y no requieren re-exportacion.
- Rangos validos:
  - `top`, `bottom` ∈ `[0, kSceneH/2 - 1]` (es decir 0..61 con `kSceneH=124`).
  - `left`, `right` ∈ `[0, kSceneW/2 - 1]` (0..81 con `kSceneW=164`).
  - Ademas `top + bottom ≤ kSceneH - 8` y `left + right ≤ kSceneW - 8` (deja al menos 8 px de camara util). El firmware clampea; TurtleStudio valida al guardar.
- Los bordes son **por escena**. Cada escena puede tener bordes distintos (menu sin HUD, gameplay con HUD, boss fight con HUD ancho, etc.).

## Playfield efectivo

Definiendo `T=top, B=bottom, L=left, R=right`, la **camara logica** de la escena pasa a operar sobre un playfield mas chico:

- `playfield_w = kSceneW - L - R`
- `playfield_h = kSceneH - T - B`
- Ancla en el framebuffer: esquina **superior izquierda del playfield = `(L, T)`** (framebuffer es Y-abajo).

El **mundo efectivo se dimensiona sobre el playfield**, no sobre el viewport canonico: `world_w = playfield_w × world_steps_x`, `world_h = playfield_h × world_steps_y`. Con `hud_border.top=16` y `world_steps_y=1` el mundo queda `164×108` — la fila 0 del mundo (piso) queda anclada al borde inferior del playfield, sin scroll automatico en Y. Las filas de scene y que quedarian sobre `playfield_h` sencillamente no existen para efectos de camara/mundo.

**Excepcion con `overlay=true`**: el mundo mantiene el tamano canonico (`kSceneW × world_steps_x`, `kSceneH × world_steps_y`) — como si `hud_border` no encogiera el mundo. La camara se clampea contra el framebuffer completo (`world - kSceneH`) en vez del playfield, asi `cam_y=0` fijo cuando `world_steps_y=1` (mundo = 124, viewport = 124). El actor puede posicionarse en filas `scene y > playfield_h` (por ejemplo saltar arriba del borde del HUD) y su sprite dibujado en la region HUD queda **invisible** por el clip de playfield que aplican los blits de escena (`blit_indexed_scene*`, `fill_rect_scene`). El HUD, pintado despues, no se ve afectado. Efecto visual: el personaje "desaparece detras" del HUD estilo Metroid.

- `W` y `H` expuestos a las VMs siguen valiendo `164` y `124` (dimensiones del framebuffer fisico). No se retocan por escena.
- El **playfield** es el subrectangulo del framebuffer donde pinta la camara: `(left, top)` a `(kSceneW - right, kSceneH - bottom)`, tamano `playfield_w × playfield_h`. La franja HUD es el complemento — jamas la toca ningun blit de escena.
- La conversion scene → framebuffer para la fila 0 es: `yfb = (kSceneH - bottom - 1) = playfield_oy + playfield_h - 1`. Es decir el piso siempre queda en el borde inferior del playfield, no en la ultima fila del framebuffer — lo que reduce la camara con `hud_border.top` se resta del TOPE del mundo, no del piso.
- Escenas sin `hud_border` y `world_steps_x = world_steps_y = 1` siguen siendo no-scrolling y usan `snapshot_static` (bajo coste). Escenas con `hud_border` reducen el mundo efectivo pero mantienen el mismo camino de dibujo: no hay coste extra por HUD si el mundo cabe en el playfield.
- **Rejilla de tiles**: se sigue autorando contra el viewport canonico (`kSceneW × kSceneH × steps`), independiente del `hud_border` — esto para no forzar a TurtleStudio a reordenar celdas cuando se cambia un HUD. Las celdas cuyo rango de scene y cae fuera del mundo efectivo (por ejemplo la fila superior de la rejilla cuando `hud_border.top > 0`) se recortan pixel a pixel al pintar; sus celdas visibles (parte de abajo) siguen dibujandose normalmente. El firmware (`tile_grid_dims`) y TurtleStudio (`scene_tile_grid_dimensions`) coinciden en el conteo de filas/columnas.
- Follow/clamp de camara, margen `margin_x/y`, tile-grid, `move()`, `posx()/posy()`, y el clip de sprites: todos miden contra el mundo efectivo (`playfield × steps`). Un actor no se puede colocar fuera del mundo efectivo (queda clampeado).
- Las coords de escena que llegan a los bindings Lua no cambian de convencion: siguen siendo (0,0) = esquina inferior-izquierda del mundo, Y hacia arriba.
- `spix(sx, sy, c)` (VM ENTRY): funciona en coords de escena Y-arriba contra el playfield (`sx` en `[0, playfield_w)`, `sy` en `[0, playfield_h)`). Fuera del playfield es no-op.

## Region HUD

Complemento del playfield: cualquier pixel del framebuffer `(x, y)` con `x < L`, `x ≥ kSceneW - R`, `y < T` o `y ≥ kSceneH - B`. Puede formar una **L, U, marco completo, franja simple o barra vertical** dependiendo de que bordes sean > 0.

Reglas:

- **La region HUD nunca es tocada por el redibujo de actores**. `draw_all_actors` clipea contra el playfield, no contra el framebuffer completo. Un actor que este cerca del borde del playfield tampoco se derrama a la region HUD.
- **La region HUD tampoco es tocada por la ventana horneada del mundo** (`s_world_bg`, tiles, capas 2-4 de fondo, bandas de parallax): todos los blits de escena estan clipeados al playfield.
- **La region HUD tampoco es afectada por `cls()`** aplicado por el firmware al comenzar una escena (`turtle_scene_begin_runtime` usa `turtle_gpu_cls` que rellena el framebuffer entero — pero inmediatamente despues se llama a `_hud_init` y el estado HUD queda tal como el cartucho lo definio). ENTRY VM que llame `cls()` explicitamente si limpia todo, incluida la HUD; documenta esto al desarrollador.
- **La franja HUD sobrevive a cambios de escena**: cada escena puede reconfigurar sus bordes; si dos escenas consecutivas tienen los mismos `hud_border`, y el HUD conceptualmente es el mismo, el desarrollador puede repintarlo en el `_hud_init` de la segunda para que se vea igual. No hay persistencia automatica entre escenas (evita cross-contamination de HUDs distintos).

## VM ENTRY: nuevos globales y ganchos

La VM ENTRY (`spec/lua/firmware-bridge-v0.md`) permanece **viva durante toda la ejecucion del cartucho** (antes se cerraba al terminar el script de arranque). Esta VM es la propietaria del HUD; los scripts de actor **no tienen acceso a los bindings HUD** — mantienen la separacion habitual (un actor no puede pintarse por afuera del playfield).

### Bindings de dibujo (framebuffer absoluto)

Todos usan coordenadas de **framebuffer** — `(0, 0)` = esquina superior-izquierda del framebuffer fisico, Y hacia abajo. Cualquier pixel que caiga **dentro del playfield actual es no-op** (proteccion contra pintar accidentalmente sobre el area de juego).

| Firma Lua                                            | Efecto                                                                 |
|------------------------------------------------------|------------------------------------------------------------------------|
| `hud_pix(x, y, color_index)`                         | Un pixel HUD.                                                          |
| `hud_rect(x, y, w, h, color_index)`                  | Relleno solido HUD.                                                    |
| `hud_clear([color_index])`                           | Rellena **toda la region HUD** con `color_index` (default 0 / negro).  |
| `hud_text(x, y, str, font_id [, color_index])`       | Dibuja `str` con la fuente `font_id`, misma convencion de tinte que `text` del ENTRY. Devuelve ancho dibujado (px). |
| `hud_text_width(str, font_id)`                       | Mismo `text_width` pero medido con la fuente HUD. Sin efecto lateral.  |

Notas:

- Las fuentes se resuelven contra el bundle del cartucho (`spec/asset-bin-v0.md` "Fuente `.tfn`"), igual que `text`/`text_width`. Un mismo `.tfn` sirve para HUD y para game text.
- `hud_pix`/`hud_rect` **no** clampean el color al indice 30 max; siguen la regla habitual (fuera de rango se ajusta al ultimo indice valido).
- No hay `hud_sprite` en v0. Repetir un sprite decorativo en la HUD se puede simular con `hud_rect`s y `hud_text` de una fuente de simbolos; el uso pesado de sprites HUD queda para el metodo 2 (capas GUI apilables).

### Ganchos de ejecucion

- **`function _hud_init()`** (opcional): se llama una unica vez cuando la escena arranca, despues de que el firmware pinto fondo/tiles/text_labels estaticos y **antes** del snapshot estatico. Si el cartucho lo define, su salida forma parte del snapshot estatico y sobrevive al mecanismo de dirty-rect de actores sin costo por fotograma.
- **`function _hud(dt)`** (opcional): se llama una vez por fotograma, **despues** de `draw_all_actors` y **antes** de `flip()`. `dt` en segundos (mismo que actores). Sirve para HUDs animados (blink, contadores, barras de vida). Si el cartucho **no** define esta funcion, la escena paga cero costo de HUD por fotograma. Documentar al desarrollador: no llamar `cls()`, `flip()` ni ninguna funcion de dibujo de escena aca — solo `hud_*`.

En ambos ganchos, la VM ENTRY tiene disponibles todos sus globales habituales (`btn`, `btnp`, `text`, `text_width`, `print`, `W`, `H`, `COLORS`) — `W` y `H` reflejan el playfield reducido. `hud_*` estan siempre disponibles aunque no haya escena activa (util para menu de titulo, splash, game over).

## Interaccion con el snapshot estatico y el redibujo por rects sucios

- Camara fija (sin scroll): el firmware usa `snapshot_static` + `restore_static_dirty` (ver `turtle_gpu.cpp`). `_hud_init` corre **antes** de `snapshot_static`, asi el HUD queda horneado en la capa estatica. Las llamadas de `hud_*` posteriores (dentro de `_hud`) actualizan **tanto el framebuffer como la capa estatica** (`s_static_fb`) y marcan el panel-dirty en las celdas HUD tocadas — para que `restore_static_dirty` no revierta el nuevo estado en frames siguientes y para que el flush a LCD envie los pixeles cambiados. Un actor en el borde del playfield cuyo rect sucio se derrame a HUD por la holgura de `dirty_mark_scene_rect` (±4 px) es indistinguible del rest: el restore copia HUD de `s_static_fb` (que refleja el estado actual del HUD), asi que no se corrompe.
- Camara con scroll: el firmware usa `paint_scene_static_layers` cada frame + `turtle_gpu_request_full_flip`. En este modo `_hud_init` corre despues del primer `paint_scene_static_layers`, pero como no hay snapshot estatico, el HUD **se sostiene solo mientras el codigo Lua no lo borre** (fondo/tiles nunca lo tocan, actores nunca lo tocan). El desarrollador tipico define `_hud(dt)` para animar y no toca `_hud_init` mas alla de dibujo inicial — o lo repinta cada frame si es puramente dinamico.

## TurtleStudio (autoria)

- El editor de escena expone `camera.hud_border` como cuatro inputs numericos (top/bottom/left/right, px) en el mismo grupo donde ya viven `mode`/`margin_x`/`margin_y` de camara.
- Preview en el canvas: un **marco semitransparente** dibuja las cuatro franjas HUD sobre la escena para que el autor vea que porcion del framebuffer queda como playfield.
- El simulador de play (`play_runtime.py`) aplica el mismo clip y offset que el firmware — el juego probado en el editor debe verse identico al hardware.
- Migracion: escenas ya guardadas sin `hud_border` se comportan igual que antes (defecto `{0,0,0,0}`, se omite del JSON al guardar si es todo cero para no ensuciar diffs).

## Errores comunes y sus modos de fallo

| Sintoma                                                | Causa tipica                                                       |
|--------------------------------------------------------|--------------------------------------------------------------------|
| HUD se ve un frame y despues desaparece.               | `_hud_init` corre antes del snapshot en camara fija — bien; pero la escena tiene camara `mode: "follow"` con scroll, sin snapshot: hay que repintar en `_hud` o llamar a `_hud_init` desde `_hud` una vez con estado guardado. |
| HUD parpadea entre valores viejos y nuevos.            | El script actualiza solo la parte cambiada pero no marca el borde suficiente — usar `hud_rect` para borrar el rect antes de repintarlo. |
| Sprite del jugador queda "cortado" en el borde superior. | Confusion entre coords de framebuffer (Y-abajo) y coords de escena (Y-arriba). `hud_border.top` reduce el playfield desde arriba en fb; en coords de escena eso significa que `posy()` maximo baja. El actor sigue completamente visible dentro del playfield. |
| Al cambiar de escena, el HUD anterior se queda pegado. | Falso: `turtle_gpu_cls` en `turtle_scene_begin_runtime` limpia todo, incluido HUD. Volver a pintar en `_hud_init` de la nueva escena si conceptualmente es el mismo HUD. |

## Fuera de alcance en v0

- `hud_sprite(x, y, sprite_id, frame)` — reservado para v1 si la practica lo pide; por ahora `hud_rect` + `hud_text` cubren el 90% de HUDs de plataformero/shmup.
- Blending / alpha en la region HUD — no hay concepto de alpha en el resto del firmware (indice 31 = transparente puro), tampoco aca.
- Multiples paletas activas simultaneamente (HUD con otra paleta que el juego) — sigue usando la paleta unica de la escena.
- Metodo 2 (capas GUI apilables tipo `.tortuguilayer`) — spec aparte cuando toque implementarlo. Ese metodo puede superponerse a la HUD; queda para v0 de ese spec definir la precedencia.
