# Puente C++ / Lua en TurtleReader (v0)

## Dos máquinas Lua separadas

| VM | Cuándo | Archivo fuente | API |
|----|--------|----------------|-----|
| **ENTRY** | Una vez en `setup()` | Bloque embebido en `main.turtlecart` | `print`, `cls`, `pix`, `spix`, `flip`, `W`, `H`, `COLORS`, `btn`, `btnp` |
| **Actores** | Cada fotograma del juego | `/scripts/<stem>.lua` en la SD | `print`, `btn`, `btnp`, `axis`, `posx`, `posy`, `move`, `on_ground`, `set_anim`, `play_anim`, `flip_h` |

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
       1. turtle_actor_lua_tick_all   // Lua: _update(dt) por actor con "script"
       2. tick_actors                 // C++: animación de sprites
       3. draw_all_actors             // C++: sprites sobre capa estática
  → turtle_gpu_flip()
```

`dt` en `_update(dt)` son **segundos** (`delta_ms / 1000`).

## Cómo Lua mueve un actor

1. `turtle_scene_actor_set_lua_target(i)` — contexto del actor `i` (interno, antes de `_update`).
2. Lua llama `move(dx, dy)` → devuelve **`ax, ay`** (pixeles realmente movidos tras colision). `turtle_scene_actor_move` resuelve por ejes contra tiles solidos, actualiza `grounded` y hace **clamp** al borde de escena (AABB de colision). Ver **`spec/lua/physics-v0.md`**.
3. Lua llama `on_ground()` → lee `grounded` del actor activo (tras el ultimo `move` del mismo frame).
4. C++ redibuja el sprite en la nueva posicion; la capa de fondo/tiles no se repinta.

`posx()` / `posy()` leen la misma instancia.

## Datos que vienen del bundle / SD

| Dato | Origen |
|------|--------|
| Colocación inicial `(x, y)` | `objects` en la escena del bundle |
| `"script": "character"` | `objects/character.json` (sidecar SD) |
| Cuerpo Lua | `/scripts/character.lua` |
| Colision AABB | `objects/<id>.json` campo `"collision"` (sidecar SD) |
| Tiles solidos | Capas `tile_layers` de la escena (indice ≠ `transparent_index`) |
| Sprites / fondo | C++ lee `.tsp` / `.tbg` según refs del bundle |

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
| `turtle_scene.cpp` | Actores, dibujo, colision, `move`, animaciones |
| `turtle_input.cpp` | `btn` / `btnp` (ambas VM) |
| `turtle_gpu.cpp` | Solo ENTRY |

## Fuera de alcance v0

- Scripts por escena en el loop (solo objetos).
- `btnp` útil en ENTRY (no hay `poll` antes del ENTRY).
- Una sola VM unificada.
