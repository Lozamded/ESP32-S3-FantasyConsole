# Puente C++ / Lua en TurtleReader (v0)

## Dos máquinas Lua separadas

| VM | Cuándo | Archivo fuente | API |
|----|--------|----------------|-----|
| **ENTRY** | Una vez en `setup()` | Bloque embebido en `main.turtlecart` | `print`, `cls`, `pix`, `spix`, `flip`, `W`, `H`, `COLORS`, `btn`, `btnp`, `text`, `text_width` |
| **Actores** | Cada fotograma del juego | `/scripts/<stem>.lua` en la SD | `print`, `btn`, `btnp`, `axis`, `posx`, `posy`, `move`, `on_ground`, `set_anim`, `play_anim`, `flip_h`, `text`, `text_width` |

No comparten `lua_State`: el ENTRY termina antes de arrancar la escena en C++.

## Orden en `setup()`

```text
montar SD
  → cargar main.turtlecart + studio/project_bundle.json (RAM)
  → paleta opcional (C++)
  → runCartEntryLua()          [Lua ENTRY]
  → turtle_scene_begin_runtime [C++: fondo, tiles, actores]
       → turtle_actor_lua_init + bind (carga scripts/*.lua)
  → flip()
```

## Bucle `loop()` (juego)

```text
turtle_input_poll()                    // C++: GPIO → btn/btnp
  → (acumulador FPS del bundle)
  → turtle_scene_runtime_tick(dt_ms):
       1. turtle_actor_lua_tick_all   // Lua: _update(dt) por actor con "script" (puede llamar text())
       2. tick_actors                 // C++: animación de sprites
       3. draw_all_actors             // C++: sprites + overlay de texto sobre capa estática
  → turtle_gpu_flip()
```

`dt` en `_update(dt)` son **segundos** (`delta_ms / 1000`).

## Cómo Lua mueve un actor

1. `turtle_scene_actor_set_lua_target(i)` — contexto del actor `i` (interno, antes de `_update`).
2. Lua llama `move(dx, dy)` → devuelve **`ax, ay`** (pixeles realmente movidos tras colision). `turtle_scene_actor_move` resuelve por ejes contra tiles solidos, actualiza `grounded` y hace **clamp** al borde de escena (AABB de colision). Ver **`spec/lua/physics-v0.md`**.
3. Lua llama `on_ground()` → lee `grounded` del actor activo (tras el ultimo `move` del mismo frame).
4. C++ redibuja el sprite en la nueva posicion; la capa de fondo/tiles no se repinta.

`posx()` / `posy()` leen la misma instancia.

## Texto

Fuentes bitmap (`.tfn`, ver `spec/asset-bin-v0.md`) se resuelven por `font_id` desde
`fonts` del bundle (mismo mecanismo que `sprites`/`tilesets`/`backgrounds`), se decodifican
una sola vez y quedan cacheadas en RAM (`turtle_scene.cpp`, cache fija de 4 fuentes,
compartida entre ambas VMs). Caracteres fuera del charset fijo v0 avanzan como un glifo en
blanco (`glyph_px` px) en vez de cortar la cadena. Una sola linea: ningun `text()` soporta
`\n` ni wrap automatico (v0).

**`text` en ENTRY — `text(sx, sy, str, font_id [, color_index])`, dibujo inmediato.**

- `(sx, sy)` en **espacio escena** (`spec/scene-v0.md`), misma convencion que `spix`: esquina **inferior izquierda del primer glifo**, no la linea base. Devuelve el ancho en px dibujado.
- **Se borra en cuanto empieza una escena**: `turtle_scene_begin_runtime` hace `cls` + `snapshot_static` antes de que la escena se muestre, igual que con `pix`/`spix`. Solo persiste en el caso sin bundle/escena (cartucho de solo splash).

**`text` en Actores — `text(str, font_id [, dx, dy, color_index])`, overlay persistente por actor.**

- Firma distinta a la de ENTRY a proposito: aqui es un **setter** sobre el actor activo (`turtle_scene_actor_set_lua_target`), como `set_anim`/`flip_h`, no una coordenada absoluta. `(dx, dy)` es un offset opcional (por defecto `0,0`) desde `(x, y)` del actor, espacio escena.
- **Persiste** hasta el siguiente `text()` del mismo actor — no hace falta llamarlo cada `_update` para mantener visible el mismo valor (p. ej. un contador de vida que no cambio). `text("")` borra el overlay.
- El dibujo real ocurre en `draw_actor_runtime`, justo despues del sprite del actor, integrado en el mismo paso de `draw_all_actors` que ya redibuja sprites — **no** es una llamada inmediata como en ENTRY. Esto importa porque la camara fija de `draw_all_actors` solo repinta la **union de rects sucios** (rect previo ∪ rect actual) de cada actor por eficiencia (ver `turtle_gpu_dirty_mark_scene_rect`); el rect del texto (`text_prev_blit_*`/bounds actuales via `turtle_font_measure`) se une a esa misma pasada, con contabilidad propia independiente de `prev_blit_*` del sprite (no coinciden). Un `text()` implementado como blit inmediato durante `_update` habria quedado fuera de esa union (fantasma sin borrar) o habria sido borrado por el `restore_static_dirty()` del siguiente actor antes de llegar a verse — de ahi el diseño como setter.
- En camara con scroll, `draw_all_actors` repinta todo el frame igual que los sprites (sin optimizacion de rects sucios ahi).

**Ambas** `text_width(str, font_id)` miden sin dibujar (util para centrar antes de llamar a `text()`). Si `font_id` no se pudo resolver, ambas funciones (ENTRY o Actor) devuelven `0` y no dibujan nada; se registra un aviso por Serial.

**Tinte de color** (`color_index`, ambas VM, opcional, ultimo argumento): 0..30 pinta cada pixel no transparente del glifo con ese indice de paleta en vez del color con el que se pinto en el editor — util para reusar una fuente en varios colores de HUD (p. ej. "GAME OVER" en rojo) sin duplicar el asset. Sin argumento (o `-1` desde C), usa los colores propios del glifo, igual que antes. Implementado pixel a pixel via `turtle_gpu_fill_rect_scene` (no existe un blit indexado con tinte en `turtle_gpu`), no cambia el ancho dibujado ni la logica de rect sucio — mismas posiciones de pixel que sin tinte.

## Datos que vienen del bundle / SD

| Dato | Origen |
|------|--------|
| Colocación inicial `(x, y)` | `objects` en la escena del bundle |
| `"script": "character"` | `objects/character.json` (sidecar SD) |
| Cuerpo Lua | `/scripts/character.lua` |
| Colision AABB | `objects/<id>.json` campo `"collision"` (sidecar SD) |
| Tiles solidos | Capas `tile_layers` de la escena (indice ≠ `transparent_index`) |
| Sprites / fondo | C++ lee `.tsp` / `.tbg` según refs del bundle |
| Fuente (`font_id` en `text`/`text_width`) | C++ lee `.tfn` según ref en `fonts` del bundle (o `/fonts/<id>.tfn` en SD), cacheada en RAM |

El bundle en RAM (`g_bundle`) no se vuelve a parsear cada frame; los actores guardan estado en `s_actors[]`.

## Serial de arranque (referencia)

- `turtle_actor_lua: VM lista`
- `turtle_actor_lua: script OK /scripts/....lua (actor N)`
- `turtle_actor_lua: enlazados M/K actores con script`
- Errores: falta `.lua`, sin `_update`, error en `pcall`

## Implementación

| Módulo | Rol |
|--------|-----|
| `TurtleReader.ino` | ENTRY Lua, loop, SD |
| `turtle_actor_lua.cpp` | VM de actores, carga SD, `_update` |
| `turtle_scene.cpp` | Actores, dibujo, colision, `move`, animaciones; resolucion/cache de fuentes (`resolve_font_tfn`, `font_cache_get`); texto ENTRY (`turtle_scene_draw_text`/`turtle_scene_measure_text`) y overlay por actor (`turtle_scene_actor_set_text`/`turtle_scene_measure_text_active`, dibujado en `draw_actor_runtime`, integrado en el rect sucio de `draw_all_actors`) |
| `turtle_font.cpp` | Decodifica `.tfn`, mide y dibuja texto (`turtle_font_measure`/`turtle_font_draw_scene`) sobre `turtle_gpu_blit_indexed_scene` |
| `turtle_input.cpp` | `btn` / `btnp` (ambas VM) |
| `turtle_gpu.cpp` | Solo ENTRY |

## Fuera de alcance v0

- Scripts por escena en el loop (solo objetos).
- `btnp` útil en ENTRY (no hay `poll` antes del ENTRY).
- Una sola VM unificada.
- Texto multilinea / wrap automatico / alineacion — una sola linea, el llamador hace el layout.
- Orden Z entre el overlay de texto y el sprite de otros actores (el texto de un actor siempre se dibuja despues de su propio sprite, pero el orden entre actores distintos sigue el de `s_actors[]`, no hay z-index explicito).
- Cultivo por camara con scroll del overlay de texto por bounds propios (usa el mismo bounds-check del sprite del actor, que puede no coincidir exactamente con el rect de texto si `dx`/`dy` es grande).
- Charset personalizable (el `.tfn` no lo guarda; ver `spec/asset-bin-v0.md` "Fuente (.tfn)").
