---
id: binary-formats
sidebar_position: 1
title: Asset Binary Formats
---

# Asset Binary Formats (v0)

TurtleStudio edits assets as **JSON** on disk. When **exporting** to the SD package (`build/`), pixel data is baked into compact binary files.

| Extension | Type | Magic |
|-----------|------|-------|
| `.tbg` | Background image | `TBG\0` |
| `.tsp` | Sprite sheet | `TSP\0` |
| `.tts` | Tileset | `TTS\0` |
| `.tfn` | Font | `TFN\0` |
| `.json` | Object definitions | (plain text, small) |

All binary formats are **little-endian**.

---

## Sprite / Background common header

Applies to `.tsp` (v0) and `.tbg`:

| Offset | Field | Size |
|--------|-------|------|
| 0 | Magic (`TBG\0` or `TSP\0`) | 4 bytes |
| 4 | `version` | u8 |
| 5 | `flags` | u8 (= 0) |
| 6 | `pixel_w` | u16 |
| 8 | `pixel_h` | u16 |
| 10 | `mode` | u8 |

### Sprite multi-frame (`.tsp` version 1)

Used when a sprite has more than one frame:

| Offset | Field | Size |
|--------|-------|------|
| 4 | `version` = 1 | u8 |
| 6 | `pixel_w` | u16 |
| 8 | `pixel_h` | u16 |
| 10 | `frame_count` | u16 |
| 12+ | Per frame: `chunk_len` u32 + `[mode u8][payload…]` | variable |

The exporter uses version 1 when `frame_count > 1`.

---

## Pixel modes

| Value | Name | Payload |
|-------|------|---------|
| `0` | `SOLID` | 1 byte: single palette index (whole image one color) |
| `1` | `RAW` | `pixel_w × pixel_h` bytes (row 0 = top) |
| `2` | `ROW_RLE` | Per row: `nruns` u16, then `nruns × (idx u8, count u16)` |

The exporter automatically chooses the smallest mode: `SOLID < RLE < RAW`.

Palette index **31** is always transparent — pixels with that index are not drawn.

---

## Tileset (`.tts`)

Header (same magic convention, `TTS\0`):

| Offset | Field | Size |
|--------|-------|------|
| 4 | `version` (0 = no collision, 1 = with collision) | u8 |
| 6 | `tile_px` (tile size in pixels, square) | u16 |
| 8 | `tile_count` | u16 |
| 10+ | Per tile: `chunk_len` u32 + indexed blob (`tile_px × tile_px`) | variable |

### Collision block (version 1 only)

Immediately after the last tile chunk, `tile_count` records of **10 bytes** each (1:1 with the `tiles[]` order):

| Offset | Field | Size |
|--------|-------|------|
| 0 | `kind`: `0`=solid, `1`=none, `2`=AABB shape | u8 |
| 1 | `flags`: bit0=one-way; bits1-2=direction (0=up,1=down,2=left,3=right) | u8 |
| 2 | `x0` (tile-local, Y up, only for `kind=2`) | i16 LE |
| 4 | `y0` | i16 LE |
| 6 | `x1` | i16 LE |
| 8 | `y1` | i16 LE |

Tiles without explicit collision data export with `kind=0` (solid) — same as the firmware default.

---

## Font (`.tfn`)

Header is **14 bytes** (distinct from the sprite/bg header — fonts are N square glyphs, not a single image):

| Offset | Field | Size |
|--------|-------|------|
| 0 | Magic `TFN\0` | 4 bytes |
| 4 | `version` = 0 | u8 |
| 5 | `flags` = 0 | u8 |
| 6 | `glyph_px` (square glyph size, same for all) | u16 |
| 8 | `line_height` | u16 |
| 10 | `baseline` | u16 |
| 12 | `glyph_count` | u16 |

### Glyph records

Immediately after the header, `glyph_count` variable-size records:

| Field | Size |
|-------|------|
| `advance` (horizontal advance in px, 1..255) | u8 |
| `chunk_len` | u32 LE |
| chunk blob (indexed `glyph_px × glyph_px`, same format as `.tsp`) | `chunk_len` bytes |

:::warning
The `.tfn` format does **not** embed which character maps to which glyph. Glyph order matches the `charset` field of the font JSON at export time. The firmware assumes the fixed `LATIN_CHARSET` order (space, A-Z, a-z, 0-9, `.,!?:;'-`). If the editor ever supports custom charsets, the format must bump to version 1 with an embedded charset.
:::

Glyphs absent from the JSON are exported with solid fill (palette index 1), not transparent.

---

## Bundle manifest (`studio/project_bundle.json`)

The bundle references baked assets by path:

```json
{
  "backgrounds": {
    "sky": { "kind": "turtlestudio.background_ref", "file": "backgrounds/sky.tbg" }
  },
  "fonts": {
    "default": { "kind": "turtlestudio.font_ref", "file": "fonts/default.tfn" }
  }
}
```

---

## Implementation references

| File | Role |
|------|------|
| `firmware/TurtleReader/turtle_asset_bin.cpp` | Decoder (`.tsp`, `.tbg`) |
| `firmware/TurtleReader/turtle_tileset.cpp` | Tileset decoder (`.tts`) |
| `firmware/TurtleReader/turtle_font.cpp` | Font decoder (`.tfn`) |
| `tools/turtlestudio/src/turtlestudio/asset_bin.py` | Encoder (export pipeline) |
| `firmware/host_tests/run_font_test.sh` | Round-trip verification for `.tfn` |
