# Variables exportadas por instancia — `prop()` (v0)

Permite que un **mismo script** se reutilice en varias instancias del mismo objeto con valores distintos, sin editar el `.lua`. El autor declara la variable con `prop(key, default)` en el script; el valor concreto se configura **por instancia** en TurtleStudio, en el panel Props de la escena.

Equivalente conceptual a `export var` de Godot o campos `[SerializeField]` de Unity.

## Uso en Lua

```lua
-- a nivel de modulo (antes de _update); prop() se evalua al cargar el script
local sceneToChange = prop("sceneToChange", "Lvl_2")
local speed         = prop("speed", 80.0)
local enabled       = prop("enabled", true)

function _update(dt)
  -- usa sceneToChange, speed, enabled como locales normales
end
```

### Firma

```
prop(key, default) → valor
```

| Argumento | Tipo | Descripcion |
|-----------|------|-------------|
| `key` | string | Nombre de la variable exportada (case-sensitive). |
| `default` | string \| number \| nil | Valor de reserva si la instancia no declara esa clave. El **tipo** del default determina el tipo de retorno. |

### Inferencia de tipo

El tipo del `default` decide cómo se lee el JSON de la instancia:

| Tipo de `default` | Lectura |
|-------------------|---------|
| `number` | Se extrae como `float` (usa `json_extract_float_for_key`). |
| `string` o `nil` | Se extrae como string (usa `json_extract_string_for_key`). |

Si la clave no existe en la instancia, se devuelve `default` sin conversion.

### Cuando se evalua

`prop()` se llama en el **cuerpo del modulo**, antes de que `_update` exista. En ese momento el firmware ya ha fijado el actor activo (`s_lua_actor_target`), por lo que la lectura del buffer `s_props_store[i]` es correcta. El valor queda en una `local` de Lua — no hay lookup por frame.

## Configurar en TurtleStudio

En la pestaña **Escenas**, selecciona la instancia en la lista **Objetos**. Bajo el campo de tags aparece el panel **Props**:

```
Props                              [+]
 ┌──────────────┐ : ┌──────────────┐  [−]
 │ sceneToChange│   │ Lvl_2        │
 └──────────────┘   └──────────────┘
 ┌──────────────┐ : ┌──────────────┐  [−]
 │ speed        │   │ 120          │
 └──────────────┘   └──────────────┘
```

- **`+`**: agrega una nueva fila vacía.
- **`−`**: elimina esa fila.
- Los cambios se guardan junto con la escena al pulsar **Guardar**.

### Inferencia de tipo al guardar

TurtleStudio guarda el valor como JSON con inferencia de tipo sobre el texto escrito en el campo valor:

| Texto en el campo | Tipo en JSON |
|-------------------|--------------|
| `42` | `int` |
| `3.14` | `float` |
| `true` / `false` | `boolean` |
| Cualquier otra cadena | `string` |

El firmware lee el número como `float` o el string sin más conversion — los `boolean` JSON se tratan como string en la ruta `prop(key, "")`.

## Formato en el JSON de escena

```json
{
  "object": "finish_PC",
  "id": "finish_pc",
  "x": 1300,
  "y": 16,
  "tags": [],
  "visible": true,
  "z_index": 0,
  "props": {
    "sceneToChange": "Lvl_2"
  }
}
```

El objeto `"props"` se omite cuando está vacío (sin claves).

## Implementacion (firmware)

El JSON crudo de `"props"` por instancia vive en `s_props_store[i]` (PSRAM via `heap_caps_malloc`, `kPropsBufSize = 256` bytes por slot, paralelo a `s_placements[]`). `EXT_RAM_ATTR` no alcanza a arrays dentro del namespace anonimo en el toolchain Xtensa — mismo patron que `s_tile_cells`.

| Funcion C | Uso |
|-----------|-----|
| `turtle_scene_actor_prop_str(key, out, outsz)` | Extrae string; devuelve `false` si no existe la clave. |
| `turtle_scene_actor_prop_num(key, out)` | Extrae float; devuelve `false` si no existe la clave. |

Ambas leen de `s_props_store[s_lua_actor_target]`.

El binding Lua (`l_prop` en `turtle_actor_lua.cpp`) despacha segun el tipo del segundo argumento: si es numero llama `_prop_num`, si es string/nil llama `_prop_str`.

`sort_actors_by_z_index` (llamado al final de `turtle_scene_begin_runtime`) mantiene `s_props_store[i]` en sincronía con `s_placements[i]` / `s_actors[i]` durante el ordenamiento por insertion sort.

## Limitaciones en v0

- **Tamaño del JSON de props**: 255 bytes utiles por instancia (buffer `kPropsBufSize = 256`). Suficiente para decenas de pares clave-valor cortos; valores muy largos se truncan silenciosamente.
- **Tipos disponibles**: string y numero (float). No arrays, no objetos anidados.
- **Claves duplicadas**: si el JSON de la instancia tiene la misma clave dos veces, `json_extract_*` devuelve la **primera** ocurrencia.
- **`prop()` fuera del actor VM**: no disponible en ENTRY (`scripts/global.lua`); esa VM no tiene actor activo.

## Archivos relacionados

- `firmware/TurtleReader/turtle_scene.cpp` — `s_props_store`, `parse_placements`, `turtle_scene_actor_prop_str/num`
- `firmware/TurtleReader/turtle_scene.h` — declaraciones publicas
- `firmware/TurtleReader/turtle_actor_lua.cpp` — `l_prop`
- `tools/turtlestudio/src/turtlestudio/scene_editor.py` — `_PropsWidget`, `_on_object_props_edited`
- `tools/turtlestudio/src/turtlestudio/project.py` — `_extract_props`, `normalize_scene_objects_for_save`
