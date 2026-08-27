#pragma once

#include <stddef.h>
#include <stdint.h>

/**
 * spec/gui-layer-v0.md: capas GUI apilables (menus, dialogos, HUD popups).
 *
 * El firmware guarda un catalogo de capas parseado desde el bundle en `turtle_scene_begin_
 * runtime`. Cada capa arranca oculta; el codigo del cart la activa via bindings ENTRY VM
 * (`gui_layer_show(id)`, ver TurtleReader.ino).
 *
 * El paint de las capas se hace desde `turtle_scene_runtime_tick` DESPUES de draw_all_actors
 * y DESPUES de `_hud(dt)`. Ver `turtle_gui_layer_paint_all`.
 */

/**
 * Parsea el catalogo `guilayers` del bundle. Se llama una vez por escena en
 * turtle_scene_begin_runtime. `bundle_json` puede ser el mismo puntero que se guarda como
 * s_runtime_json en turtle_scene (asset live durante toda la escena). Al parsear, la
 * visibilidad de todas las capas queda RESETEADA a oculto.
 */
void turtle_gui_layer_begin_scene(const char* bundle_json, size_t bundle_json_len);

/** Libera estado interno. Se llama en cambio de cart. */
void turtle_gui_layer_release(void);

/**
 * true si al menos una capa visible tiene `pauses_scene: true`. turtle_scene_runtime_tick
 * consulta esto antes de invocar `_update` de actores.
 */
bool turtle_gui_layer_any_pauses(void);

/**
 * true si al menos una capa visible tiene `captures_input: true`. turtle_input consulta
 * esto para devolver `false` a btn/btnp desde VMs de ACTOR (la VM ENTRY sigue viendo
 * input normal para navegar menus).
 */
bool turtle_gui_layer_any_captures_input(void);

/** Pinta todas las capas visibles ordenadas por z ascendente. No-op si no hay activas. */
void turtle_gui_layer_paint_all(void);

/* --- API llamada desde bindings Lua de la VM ENTRY (TurtleReader.ino) --- */

/** true si `id` matchea una capa del catalogo (encontrada, no necesariamente visible). */
bool turtle_gui_layer_show(const char* id, bool has_z_override, int z_override);
bool turtle_gui_layer_hide(const char* id);
bool turtle_gui_layer_is_visible(const char* id);
void turtle_gui_layer_hide_all(void);
bool turtle_gui_layer_set_text(const char* id, const char* label_id, const char* str);
