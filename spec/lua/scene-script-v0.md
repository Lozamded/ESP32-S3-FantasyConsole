# Script de escena (v0)

Cada escena puede declarar un script Lua propio (`scripts/<stem>.lua`) que corre como una VM sin actor asociado, ademas de los `_update(dt)` por actor de `spec/lua/object-script-v0.md`. Sirve para logica de escena que no tiene un "cuerpo" natural: menus, transiciones (`goto_scene`), disparadores globales por tiempo, control de estado inter-actor, etc.

Antes de v0, el mismo patron se hacia con un actor "controlador" de sprite totalmente transparente (indice 31 en todos sus pixeles) — funcional, pero costaba un slot de placement y obligaba a autorar sprite+objeto+placement solo para hostear un `_update`. La VM de escena reemplaza ese patron sin costo.

## Como declarar el script

En el JSON de la escena (`scenes/<id>.json` o el mirror en `turtlestudio.json` cuando esta abierta):

```json
{
  "id": "intro",
  "script": "intro",
  "objects": [...],
  ...
}
```

- `"script"` es opcional. Si esta ausente, vacio, o no cumple con el shape de stem (`spec/scene-object-identity-v0.md` — letra inicial, luego letras/digitos/`_`/`-`, max 64 chars), no se carga ninguna VM de escena — no es error.
- El stem se resuelve a `scripts/<stem>.lua` en la raiz del proyecto/SD, exactamente como los scripts por actor.
- El editor (`scene_editor.py`, campo "Script (stem)") crea el archivo desde una plantilla si no existe (ver `_STARTER_SCENE_LUA` en `tools/turtlestudio/src/turtlestudio/project.py`).

Ejemplo vivo: `exampleprojects/demo_platformer/scenes/intro.json` + `scripts/intro.lua` — la escena `intro` no tiene actores y salta a `Lvl_1` cuando el jugador presiona `A/B/C/D`.

## Ciclo de vida

Firmware (`firmware/TurtleReader/turtle_scene.cpp` + `turtle_actor_lua.cpp`):

1. `turtle_scene_begin_runtime()` parsea el JSON de la escena y guarda `"script"` en `s_scene_script_stem` (via `json_extract_string_for_key`).
2. Despues de `turtle_actor_lua_bind_actors_from_scene()`, se llama a `turtle_actor_lua_bind_scene_script()`:
   - Si `turtle_scene_script_stem()` devuelve un stem, carga `/scripts/<stem>.lua` en la **misma** `lua_State` que los actores (`s_L`), ejecuta el chunk una vez, captura la global `_update` como `s_scene_update_ref`.
   - Se llama **despues** de bind_actors a proposito: ambos hacen `luaL_loadbuffer + pcall(0,0)` que setea `_update` como global, y cada actor pisa la global durante su carga; capturar la del script de escena al final evita colisiones.
3. Cada frame `turtle_scene_runtime_tick()` llama `turtle_actor_lua_tick_scene()` **antes** de `turtle_actor_lua_tick_all()`.
4. Al cambiar de escena (`goto_scene(id)` → `turtle_scene_begin_runtime()` de nuevo), `turtle_actor_lua_bind_scene_script()` libera la ref vieja y bindea la nueva (o limpia sin bindear si la escena entrante no declara script). Sin este paso, el `_update` de la escena vieja seguiria tickeando indefinidamente.

Play mode en TurtleStudio (`play_runtime.py` + `play_lua_bridge.py`) refleja el mismo ciclo: `PlaySession.scene_script_stem` se toma de `row["script"]` en `begin()`, y `ActorLuaBridge.bind_scene_script(stem)` corre despues de `bind_actors`. `play_widget._apply_pending_scene_switch` tambien re-bindea al cambiar de escena.

## Orden del tick

Cada frame (una vez que ninguna capa GUI marca `pauses_scene` — ver `spec/gui-layer-v0.md`):

1. `turtle_actor_lua_tick_scene(dt)` — script de escena.
2. `turtle_actor_lua_tick_all(dt)` — un `_update(dt)` por actor scriptado, en orden de indice.
3. Animacion de sprites + labels con blink + redibujo de actores.
4. `_hud_init` / `_hud(dt)` de la VM ENTRY (`spec/lua/entry-v0.md`).
5. Capas GUI (`spec/gui-layer-v0.md`).

Ir primero permite al script de escena fijar flags/estado global que los `_update(dt)` de actor lean en el **mismo** frame — patron "controlador" tradicional (ej. "todos los enemigos mueren al presionar START"). El script de escena tambien puede leer/escribir el store compartido de `spec/lua/state-v0.md` para comunicar con la VM ENTRY.

## API expuesta a la VM de escena

Comparte lua_State con los actores por decision de diseno (una sola VM, un solo `luaL_openlibs`, mismo alocador SPIRAM — ver comentario en `turtle_actor_lua.cpp`). Las funciones "de utilidad general" son las **recomendadas** para scripts de escena:

| Funcion                             | Origen (spec)                            |
|-------------------------------------|------------------------------------------|
| `print(...)`                        | `spec/lua/firmware-bridge-v0.md`         |
| `btn(i)`, `btnp(i)`, `axis(neg,pos)`| `spec/input-v0.md`                       |
| `goto_scene(scene_id)`              | `spec/lua/object-script-v0.md` "Cambio"  |
| `find_by_id(id)`, `find_by_tag(t)`  | `spec/scene-object-identity-v0.md`       |
| `obj_posx/posy/id/anim/has_tag/...` | `spec/scene-object-identity-v0.md`       |
| `state_get/set/add`                 | `spec/lua/state-v0.md`                   |

Los bindings **actor-scoped** (`posx/posy/move/on_ground/set_anim/play_anim/flip_h/flip_v/set_visible/set_pos/text/text_width/self_id`) **existen** en la VM de escena porque son globales del `lua_State` compartido, pero como no hay actor activo (el tick de escena hace `turtle_scene_actor_set_lua_target(-1)` antes de `lua_rawgeti`) todos degradan a no-op / `0` / `false`. No dependas de este comportamiento — son parte de la API de actores.

## Restricciones

- **Un script por escena**: `"script"` es un string, no una lista. Si necesitas dividir la logica, usa `require`-style organizacion desde el propio archivo Lua (aunque `require()` no esta habilitado por defecto — usar funciones auxiliares en el mismo archivo o compartir por globales).
- **Comparte globales con actores**: como usa la misma `lua_State`, un actor y el script de escena que definen la misma global se pisan entre si. Convencion: prefija las globales del script de escena con `scene_` (`scene_timer`, `scene_menu_index`) para evitar colisiones accidentales.
- **`math` disponible; sin `os`/`io`/`package`**: la VM ya arranca con `luaL_openlibs` acotado (ver `turtle_actor_lua_init`); mismo perfil que los scripts de actor.
- **Sin dibujo propio**: la VM de escena no tiene bindings de `pix`/`spix`/`cls`/`text` con coordenadas absolutas. Para HUD dinamico, usar la VM ENTRY (`_hud(dt)`, ver `spec/lua/entry-v0.md`) y comunicar via `spec/lua/state-v0.md`. Para texto estatico de escena (titulos, "Press to Start"), usar `text_labels[]` en el JSON (`spec/scene-text-labels-v0.md`), que soporta parpadeo (`spec/scene-text-blink-v0.md`).

## Fuera de alcance en v0

- **Callbacks de vida de la escena** (`_begin(scene_id)` / `_end()`): en v0 solo hay `_update(dt)`. Estado inicial se hace en el nivel top del chunk (corre una vez al cargar); cleanup no existe explicitamente — al cambiar de escena la ref se libera y el chunk se descarta.
- **Multiples scripts por escena**: ver "Restricciones".
- **API extendida especifica de escena**: bindings dedicados (`scene_timer_ms`, `scene_id`, etc.) se pueden agregar en versiones futuras si aparecen casos recurrentes; en v0 se resuelve con contadores propios en globales.
