#pragma once

#include <stddef.h>

/**
 * Helpers de parsing JSON compartidos entre turtle_scene.cpp y turtle_gui_layer.cpp.
 * Historicamente vivian como `static` dentro de turtle_scene.cpp; se extrajeron a este
 * modulo cuando turtle_gui_layer.cpp los necesito para parsear el catalogo `guilayers` del
 * bundle. Definidos en turtle_json.cpp.
 *
 * No es un parser JSON completo -- son extractores por-clave sobre un buffer plano, no
 * recorren el arbol. Suficiente para los bundles chatos (single-level objects, arrays de
 * primitivos) que exporta TurtleStudio.
 */

const char* strstr_bounded(const char* s, const char* e, const char* needle);
const char* json_object_end(const char* p);
const char* json_array_end(const char* p);
bool parse_int_bounded(const char* p, const char* e, int* out);
bool json_extract_int_for_key(const char* s, const char* e, const char* key_name, int* outv);
bool json_extract_float_for_key(const char* s, const char* e, const char* key_name,
                                float* outv);
bool json_extract_string_for_key(const char* s, const char* e, const char* key_name, char* out,
                                 size_t outsz);
bool json_extract_bool_for_key(const char* s, const char* e, const char* key_name, bool* out);
