# Animaciones de objeto (v0)

Control desde Lua del **sprite** que muestra un actor, segun la tabla **`animations`** del JSON del objeto (`objects/<id>.json`).

Ver [sprite-v0.md](../sprite-v0.md) (campo `animations`) y [object-script-v0.md](object-script-v0.md).

## Definicion en el objeto

```json
"animations": [
  { "name": "walk", "sprite_id": "character_walk" },
  { "name": "idle", "sprite_id": "character_idle" }
]
```

- **`name`**: identificador logico (string) usado en Lua.
- **`sprite_id`**: stem del sprite en `sprites/<stem>.tsp` (o embebido en el bundle).

El firmware carga la lista al crear el actor en escena (desde el sidecar en SD o el JSON embebido).

En runtime, `set_anim` / `play_anim` **buscan el nombre en ese JSON** (bundle o `/objects/<id>.json` en SD); no hay tabla grande en RAM por actor.

## API Lua

| Funcion | Descripcion |
|---------|-------------|
| `set_anim(anim)` | Cambia al sprite de `anim`. **Loop** infinito, velocidad **1.0** (relativa a `default_anim_fps` de la escena). Si ya estaba en esa animacion, **no** reinicia el fotograma (el ciclo sigue). |
| `play_anim(anim, speed, repeat)` | Cambia sprite, aplica **`speed`** (`float`, 0.25–16, factor sobre `default_anim_fps`) y **`repeat`** (`boolean`). **Siempre** reinicia en el fotograma 0. |

Si `anim` no existe en el objeto, el firmware escribe aviso en Serial y no cambia el sprite.

### Velocidad de fotogramas

Internamente: `ms_por_fotograma = 1000 * 16 / (default_anim_fps * speed * 16)`.

- `speed = 1.0` → un fotograma cada `1000 / default_anim_fps` ms (p. ej. 8 FPS de escena → 125 ms).
- `speed = 2.0` → el doble de rapido.

### Repeticion

- `repeat = true`: al llegar al ultimo fotograma del sprite, vuelve al 0.
- `repeat = false`: se queda en el **ultimo** fotograma (util para `damage`, cutscenes, etc.).

## Ejemplo (demo1)

```lua
if not on_ground() then
  if vy > 0 then
    set_anim("jump")
  else
    set_anim("fall")
  end
elseif mx ~= 0 then
  set_anim("walk")
else
  set_anim("idle")
end

-- Una sola vez, mas lento, sin loop:
play_anim("damage", 0.75, false)
```

## Notas

- `move()` ya **no** altera la velocidad de animacion; Lua la controla con `set_anim` / `play_anim`.
- El avance de fotogramas lo hace C++ en `tick_actors` tras `_update`.
- Cambiar animacion invalida la cache de pixeles del actor (sin releer SD cada frame salvo cambio de sprite/fotograma).

### Rendimiento (firmware)

- **`set_anim`**: si el actor ya usa ese nombre, no repite la busqueda en JSON ni recarga el sprite.
- **Lua**: conviene llamar `set_anim` solo cuando cambie el estado (p. ej. `cur_anim` local).
- **Sprites `.tsp`**: el firmware guarda en **PSRAM** hasta 48 blobs por `sprite_id` al arrancar la escena (precalentado con sprites del actor y sus `animations`); los cambios de fotograma leen de RAM, no de SD.

## Implementacion

- `firmware/TurtleReader/turtle_scene.cpp` — parseo `animations`, `set_anim` / `play_anim`
- `firmware/TurtleReader/turtle_actor_lua.cpp` — globals Lua
