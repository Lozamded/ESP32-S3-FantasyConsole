# Especificacion de escena — visibilidad inicial de objetos (v0)

Extiende **`spec/scene-object-identity-v0.md`** (campos `object`/`id`/`tags` de `objects[]`).
Agrega un cuarto campo opcional: `visible`.

## No hace falta subir `TURTLECART:1`

Aditivo y opcional, igual que el resto de la familia `scene-*-v0.md`. Una entrada de `objects[]`
sin `"visible"` se comporta igual que hoy (visible). `TURTLECART:0` sigue siendo la cabecera
correcta.

## Campo `objects[].visible`

```json
{ "object": "scene_controller", "id": "scene_controller", "x": 0, "y": 0, "visible": false }
```

| Campo | Tipo | Default | Nota |
|---|---|---|---|
| `visible` | bool | `true` | Si el actor se **dibuja** al arrancar la escena. `false` no lo excluye de nada mas: sigue recibiendo `_update(dt)` (si tiene `"script"`), sigue moviendose/colisionando via `move()`, sigue siendo encontrable por `find_by_id`/`find_by_tag` (`spec/scene-object-identity-v0.md`). Solo afecta el paso de dibujado. |

Es deliberadamente **estatico** en v0 (fijado al colocar el objeto en TurtleStudio, no
modificable desde Lua) — generaliza el truco de "sprite totalmente transparente" que ya usaba
`scene_controller` (`demo_platformer/objects/Objects/scene_controller.json` +
`objects/Sprites/invisible.json`, ver `spec/lua/object-script-v0.md` § "Cambio de escena") a
**cualquier** objeto con **cualquier** sprite, sin necesitar un sprite dedicado transparente:
ahora alcanza con destildar la casilla de visibilidad en el editor.

## Fuera de alcance de v0

- Alternar visibilidad en tiempo de ejecucion desde un script (`set_visible(bool)`/`show()`/
  `hide()`) — v0 es solo el estado inicial declarado en la escena. Si se agrega despues, debe
  respetar el mismo contrato de dibujado (no afecta tick/colision/find_by_*) documentado arriba.
- Ocultar el overlay de texto de un actor de forma independiente al sprite — mientras
  `visible == false` no se dibuja NADA del actor (ni sprite ni `text()`), igual que un actor
  fuera de camara hoy.

## Firmware (`turtle_scene.cpp`)

- `struct Placement`/`struct SceneActor` ganan `bool visible` (default `true` si `"visible"`
  falta en el JSON, via `json_extract_bool_for_key`).
- `init_actor_from_placement` copia `pl->visible` a `actor->visible`.
- `draw_all_actors()`: un actor invisible se trata igual que uno fuera de la ventana de camara
  — nunca se carga/blittea su sprite (ni su overlay de texto, que depende del mismo camino de
  dibujado). Camino con scroll: `continue` temprano junto al chequeo de superposicion con la
  ventana de camara. Camino de camara fija: `in_view = a->visible && rects_overlap(...)`, asi
  que reusa la limpieza de `prev_blit`/`text_prev_blit` y `skip_draw` que ya existia para "salio
  de camara" — sin logica nueva de dirty-rect.
- `tick_actors` (animacion) y el tick de Lua de objeto (`turtle_actor_lua_tick_all`) **no**
  consultan `visible` — un actor invisible sigue animando/moviendose/corriendo su script
  normalmente, simplemente no se pinta.

## TurtleStudio

- `project.py`: `SceneObjectPlacement.visible: bool = True`; `_parse_one_scene_object` lo lee
  (`raw.get("visible", True)`, tolerante a cualquier valor no-bool via `bool(...)`);
  `normalize_scene_objects_for_save` siempre escribe `"visible"` en la salida.
- `scene_editor.py`: cada fila de `list_objects` (panel de escena) tiene su propio checkbox
  nativo del item (`ItemIsUserCheckable`) ademas del icono de preview — destildarlo pone
  `visible: false` en la instancia y refresca el lienzo. La vista previa del canvas
  (`_paint_scene_objects`) no blittea el sprite de un objeto invisible pero SI deja la cruz de
  origen, para que siga siendo ubicable/clickeable en el editor aunque no se vea el sprite.
- **Play** (`play_runtime.py`): `ActorRuntimeState.visible: bool = True`, poblado por
  `build_actor_states`; `render_rgba()` salta el blit de sprite+texto de un actor invisible (el
  tick de animacion/Lua sigue corriendo igual, sin chequear `visible`).
