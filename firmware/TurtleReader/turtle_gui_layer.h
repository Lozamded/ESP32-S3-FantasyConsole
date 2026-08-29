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

/**
 * Actualiza el valor de una barra de progreso. `value_num` reemplaza siempre; si `has_max`
 * es true, `value_den` se reemplaza tambien (util cuando el maximo cambia en runtime, por
 * ejemplo un nivel-up que sube el HP maximo). Devuelve false si la capa o el bar no existen.
 */
bool turtle_gui_layer_set_progress(const char* id, const char* bar_id, int value_num,
                                   bool has_max, int value_den);

/**
 * Actualiza el valor de un pip bar. `value` se clampea a [0, max_value] final. Si `has_max`,
 * `max_value` tambien se reemplaza (clampeado a [1, 32]).
 */
bool turtle_gui_layer_set_pips(const char* id, const char* bar_id, int value, bool has_max,
                               int max_value);

/**
 * Actualiza el `sprite_id` (y opcionalmente el `frame_index`) de un icono sprite estatico.
 * `sprite_id` null o vacio deja el sprite actual sin cambio (util para cambiar solo el frame).
 * `has_frame` false deja el frame actual. Devuelve false si la capa o el icono no existen.
 */
bool turtle_gui_layer_set_sprite(const char* id, const char* icon_id, const char* sprite_id,
                                 bool has_frame, int frame_index);
