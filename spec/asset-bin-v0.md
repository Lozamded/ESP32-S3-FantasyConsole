# Assets binarios en SD (exportacion v0)

TurtleStudio **sigue editando JSON** en el proyecto (`backgrounds/*.json`, `sprites/*.json`).

Al **exportar el paquete SD**, los pixeles indexados se convierten a binario:

| Extension | Uso |
|-----------|-----|
| `.tbg` | Fondo (`TBG\0`) |
| `.tsp` | Sprite (`TSP\0`) |
| `.tts` | Tileset (`TTS\0`) |
| `.tfn` | Fuente (`TFN\0`) |
| `.json` | Objetos (pequenos, legibles) |

## Cabecera (little-endian)

| Offset | Campo |
|--------|--------|
| 0 | Magic `TBG\0` o `TSP\0` |
| 4 | `version` u8 (=0) |
| 5 | `flags` u8 (=0) |
| 6 | `pixel_w` u16 |
| 8 | `pixel_h` u16 |
| 10 | `mode` u8 (solo v0 mono-fotograma) |

### Sprite multi-fotograma (`.tsp` version 1)

| Offset | Campo |
|--------|--------|
| 4 | `version` u8 (=1) |
| 6 | `pixel_w` u16 |
| 8 | `pixel_h` u16 |
| 10 | `frame_count` u16 |
| 12+ | Por fotograma: `chunk_len` u32 + `[mode u8][payload…]` (mismo payload que v0 tras `mode`) |

`version` 0 = un solo fotograma (layout anterior). El exportador usa v1 si `frame_count > 1` en el JSON del sprite.

## Modos (`mode`)

| Valor | Nombre | Payload |
|-------|--------|---------|
| 0 | SOLID | 1 byte: indice de paleta |
| 1 | RAW | `pixel_w * pixel_h` bytes (fila 0 = arriba) |
| 2 | ROW_RLE | Por fila: `nruns` u16, luego `nruns` × (`idx` u8, `count` u16) |

El exportador elige el modo mas pequeno (solid &lt; RLE &lt; RAW segun imagen).

## Tileset (`.tts`)

Cabecera igual a la tabla general (magic `TTS\0`), con `version` 0 o 1:

| Offset | Campo |
|--------|--------|
| 4 | `version` u8 (0 = sin colision embebida; 1 = con bloque de colision) |
| 6 | `tile_px` u16 |
| 8 | `tile_count` u16 |
| 10+ | Por tile: `chunk_len` u32 + blob indexado (mismo payload que `.tsp`, `tile_px`×`tile_px`) |

### Bloque de colision (solo `version` 1)

Inmediatamente despues del ultimo chunk de tile, `tile_count` registros fijos de **10 bytes** cada uno (alineados 1:1 con el orden de `tiles[]`):

| Offset (rel.) | Campo |
|---------------|--------|
| 0 | `kind` u8 (0=solid, 1=none, 2=shape/aabb) |
| 1 | `flags` u8: bit0 = oneway; bits1-2 = direccion (0=up, 1=down, 2=left, 3=right) |
| 2 | `x0` i16 LE (solo `kind`=2; caja en espacio tile, Y arriba) |
| 4 | `y0` i16 LE |
| 6 | `x1` i16 LE |
| 8 | `y1` i16 LE |

Tiles sin dato de colision explicito en el proyecto exportan `kind`=0 (solid), igual que el default histórico del firmware (`entry_defaults` en `turtle_tile_collision.cpp`).

Firmware: `turtle_tileset_load_tts` en `turtle_tileset.cpp` decodifica este bloque si `version`=1; en `version`=0 (binarios legacy) usa el fallback por JSON (`tileset_load_collision_meta` en `turtle_scene.cpp`, que ya no aplica cuando hay bloque embebido). Tool: `tileset_json_to_tts` / `_encode_tile_collision_block` en `tools/turtlestudio/src/turtlestudio/asset_bin.py`.

## Fuente (`.tfn`)

Cabecera de 14 bytes (little-endian), distinta de la tabla general (no reutiliza `pixel_w`/`pixel_h`/`mode`, ya que una fuente es N glifos cuadrados, no una sola imagen):

| Offset | Campo |
|--------|--------|
| 0 | Magic `TFN\0` |
| 4 | `version` u8 (=0) |
| 5 | `flags` u8 (=0) |
| 6 | `glyph_px` u16 (glifo cuadrado, mismo tamano para todos) |
| 8 | `line_height` u16 |
| 10 | `baseline` u16 |
| 12 | `glyph_count` u16 |

### Glifos

Inmediatamente tras la cabecera, `glyph_count` registros de tamano variable, uno por caracter:

| Campo | Tamano |
|-------|--------|
| `advance` u8 | 1 (px de avance horizontal; 1..255) |
| `chunk_len` u32 LE | 4 |
| chunk | `chunk_len` bytes: blob indexado `glyph_px`×`glyph_px` (mismo formato que `.tsp`, magic forzado a `TSP\0`) |

**El `.tfn` no guarda que caracter corresponde a cada glifo.** El orden de los registros es el mismo que el campo `charset` del JSON de la fuente en el momento de exportar (`font_json_to_tfn` en `tools/turtlestudio/src/turtlestudio/asset_bin.py`). Hoy ningun flujo del editor permite un `charset` distinto al `LATIN_CHARSET` por defecto (`tools/turtlestudio/src/turtlestudio/fonts.py`: espacio, A-Z, a-z, 0-9, `.,!?:;'-`), asi que el firmware asume ese orden fijo (`turtle_font_charset_index` en `turtle_font.cpp`) en vez de leer un charset embebido. **Si el editor alguna vez permite personalizar el charset, este formato debe subir a `version`=1 con el charset embebido**, para no descuadrar glifos en firmware antiguo.

Glifos ausentes en el JSON exportan con relleno solido (indice de paleta 1), no transparente — ver `parse_font_glyphs(..., fill_index=1)`.

Firmware: `turtle_font_load_tfn` en `turtle_font.cpp` (decodifica igual que `turtle_tileset_load_tts` decodifica tiles, reutilizando `turtle_asset_bin_decode_indexed` por glifo). Tool: `font_json_to_tfn` en `tools/turtlestudio/src/turtlestudio/asset_bin.py`. Verificacion sin hardware: `firmware/host_tests/run_font_test.sh` decodifica un `.tfn` real con el firmware compilado en host y lo compara byte a byte contra `decode_font_blob` (Python).

## Bundle

Referencias en `studio/project_bundle.json`:

```json
"backgrounds": {
  "cielo": { "kind": "turtlestudio.background_ref", "file": "backgrounds/cielo.tbg" }
},
"fonts": {
  "default": { "kind": "turtlestudio.font_ref", "file": "fonts/default.tfn" }
}
```

Firmware: `turtle_asset_bin.cpp` + JSON legacy (`.json` en SD si hace falta).
