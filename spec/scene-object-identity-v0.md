# Especificacion de escena — identidad de objetos: id unico + tags (v0)

Extiende **`spec/scene-v0.md`** (viewport 164×124, mundo via `world_steps_x/y`, camara, Y hacia
arriba con origen inferior-izquierdo) y **`spec/lua/object-script-v0.md`** (scripts de objeto,
un actor Lua por entrada de `objects[]`). Antes de este documento, cada entrada de `objects[]`
solo tenia un campo `"id"` que en realidad era la referencia al **catalogo** (`objects/Objects/
<id>.json`, define sprite/script) — varias instancias en la misma escena comparten esa
referencia (ej. varios `"gear"` en `demo_platformer/Lvl_1`), asi que no habia forma de nombrar
o encontrar UNA instancia en particular desde un script.

## No hace falta subir `TURTLECART:1`

Aditivo y opcional, igual que v1/v2/text-labels/text-blink. Una escena sin `tags` en sus
objetos se comporta igual que hoy; el campo `id` de instancia, si falta, cae automaticamente al
valor de `object` (ver "Compatibilidad hacia atras" abajo). `TURTLECART:0` sigue siendo la
cabecera correcta.

## Campos de `objects[]`

```json
"objects": [
  { "object": "gear", "id": "gear", "x": 40, "y": 20, "tags": [] },
  { "object": "gear", "id": "gear_2", "x": 60, "y": 20, "tags": ["hazard"] },
  { "object": "eneny_snake", "id": "boss_snake", "x": 100, "y": 30, "tags": ["enemy", "boss"] }
]
```

| Campo | Tipo | Default | Nota |
|---|---|---|---|
| `object` | string | — (requerido) | Referencia de catalogo: `objects/Objects/<object>.json` define `sprite_id`/`script`/animaciones. Varias instancias pueden compartir el mismo `object`. |
| `id` | string | = `object` si falta/invalido/repetido | Identificador **unico** de esta instancia dentro de la escena. Mismo criterio de stem que otros ids del proyecto (letra inicial, luego letras/digitos/`_`/`-`, hasta 64 chars). TurtleStudio garantiza unicidad al guardar/exportar (ver "TurtleStudio" abajo); el firmware **no** deduplica en runtime, confia en el bundle ya limpio. |
| `x`, `y` | int | — (requeridos) | Igual que hoy: posicion inicial en espacio escena. |
| `tags` | array de string | `[]` | Etiquetas libres para `find_by_tag`. Cada tag: letra inicial, luego letras/digitos/`_`/`-`, hasta 20 chars; hasta 6 tags por instancia (topes de autoria en TurtleStudio — el firmware solo trunca si no entran en el buffer CSV). |

`camera.target` (`spec/scene-v0.md`) y el fallback sin target explicito (busca una instancia de
`id` literal `"player"` o `"character"`) ahora matchean contra el **`id`** de instancia, no
contra `object` — antes eran el mismo campo asi que no habia diferencia observable.

## Compatibilidad hacia atras

Una escena con el formato viejo (`{"id": "gear", "x":.., "y":..}`, sin `"object"`) se sigue
leyendo: tanto TurtleStudio (`_parse_one_scene_object` en `project.py`) como el firmware
(`parse_placements` en `turtle_scene.cpp`) tratan un dict sin `"object"` como legado — usan su
`"id"` como referencia de catalogo, y el `id` de instancia queda igual a esa referencia (sin
sufijo) hasta que TurtleStudio le asigne uno unico. La deduplicacion (`next_unique_placement_id`
en `project.py`) pasa **solo** por TurtleStudio, al normalizar para guardar/exportar: primer
candidato libre es el propio `object` sin sufijo (asi una escena con una sola instancia de
`"player"` sigue teniendo `id == "player"`, preservando el fallback de camera de arriba);
instancias siguientes del mismo `object` reciben `object_2`, `object_3`, etc.

## API Lua — buscar y consultar otros actores

Ver tabla completa (con `self_id`) en **`spec/lua/object-script-v0.md`** § "Buscar y consultar
otros actores". Resumen: `find_by_id(id)` / `find_by_tag(tag)` devuelven un **handle** (entero,
`nil` o tabla de enteros); `obj_posx(h)` / `obj_posy(h)` / `obj_id(h)` / `obj_has_tag(h, tag)`
leen el estado de la instancia en `h`. Son de **solo lectura** — v0 no expone forma de mover o
animar un actor distinto al que esta corriendo su propio `_update(dt)` (deliberado, ver "Fuera
de alcance" abajo).

## Fuera de alcance de v0

- Control remoto: mover/animar/cambiar estado de OTRO actor desde el script de un actor distinto
  (`obj_move`, `obj_set_anim`, etc.) — v0 es de solo lectura a proposito, evita el caso de dos
  scripts moviendo al mismo actor en el mismo fotograma sin ningun orden definido.
  `find_by_id`/`find_by_tag` + las lecturas alcanzan para el caso comun (saber si un enemigo
  con cierto tag sigue vivo/cerca, encontrar al jugador por id fijo, etc.).
- Colision entre actores (sigue fuera de alcance segun `object-script-v0.md`).
- Tags jerarquicos o con namespace — lista plana de strings.

## Firmware (`turtle_scene.cpp` / `turtle_actor_lua.cpp`)

- `struct Placement`/`struct SceneActor` ganan `char instance_id[40]` y `char tags[128]` (CSV
  sin espacios, ver `json_extract_string_array_as_csv`/`tags_csv_has`) junto al `obj_id[32]`
  que ya tenian.
- `parse_placements`: lee `"object"` (fallback a `"id"` si falta = escena legado) y `"id"`
  (fallback a `obj_id` si falta); `"tags"` opcional via `json_extract_string_array_as_csv`.
- `init_actor_from_placement` copia `instance_id`/`tags` del `Placement` al `SceneActor`.
- `resolve_player_actor_index` (camera follow) matchea contra `instance_id`, no `obj_id`.
- Accesores nuevos en `turtle_scene.h`: `turtle_scene_actor_id` (self, via
  `s_lua_actor_target`), `turtle_scene_find_actor_by_id`, `turtle_scene_find_actors_by_tag`,
  `turtle_scene_actor_pos_at`/`_id_at`/`_has_tag_at` (por indice explicito, 0-based).
- `turtle_actor_lua.cpp` expone `self_id`, `find_by_id`, `find_by_tag`, `obj_posx`, `obj_posy`,
  `obj_id`, `obj_has_tag` como funciones globales Lua (handle = indice+1, convencion Lua
  1-based); ver tabla en `object-script-v0.md`.

## TurtleStudio

- `project.py`: `SceneObjectPlacement` gana `object_id`/`tags` (y `id` ahora es la instancia,
  no el catalogo); `validate_placement_instance_id`, `validate_object_tags`,
  `next_unique_placement_id`. `_parse_one_scene_object`/`parse_scene_objects_raw` migran
  transparentemente el formato legado (ver "Compatibilidad hacia atras"); todos los saves
  (`normalize_scene_objects_for_save`, usado tanto por `save_project` como por `_normalize_row`
  del editor) escriben siempre `{"object", "id", "x", "y", "tags"}`.
- `scene_editor.py`: la lista de objetos de la escena muestra icono (preview del sprite,
  resuelto por `object`) + `id [object] (x, y) #tags`; el panel de edicion agrega campos **Id**
  (unico, valida contra el resto de instancias de la escena) y **Tags** (coma-separado) junto a
  X/Y. Arrastrar/soltar y "Añadir" desde el catalogo asignan un `id` unico automatico via
  `next_unique_placement_id`.
- `build.py` sigue embebiendo cada fila de `scenes` del manifest tal cual dentro del bundle
  exportado (sin allow-list de campos) — la unica pieza que SI necesitaba tocarse es la
  recoleccion de `objects/Objects/<id>.json` a incluir en el paquete SD, que ahora lee
  `"object"` (con el mismo fallback a `"id"` para proyectos sin migrar) en vez de `"id"`.
- **Play** (`play_runtime.py`/`play_lua_bridge.py`): `ActorRuntimeState` gana `object_id`/`tags`
  (el `id` existente pasa a significar instancia, igual que en el firmware); `ActorLuaBridge`
  implementa `self_id`/`find_by_id`/`find_by_tag`/`obj_posx`/`obj_posy`/`obj_id`/`obj_has_tag`
  contra `session.actors` para poder probar scripts que usan estas funciones sin hardware.
