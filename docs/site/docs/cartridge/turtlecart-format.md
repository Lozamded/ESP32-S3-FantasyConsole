---
id: turtlecart-format
sidebar_position: 1
title: .turtlecart Format
---

# .turtlecart Cartridge Format (v0)

A `.turtlecart` file is a **plain-text container** with an ordered set of sections. It's designed for simplicity: readable on any text editor, easy to parse on the ESP32.

## File structure

```
TURTLECART:0
ENTRY:scripts/global.lua
INITIAL_SCENE:intro
BUNDLE_FILE:studio/project_bundle.json
PALETTE:
#1a1a2e
#16213e
#0f3460
#e94560
...
---FILE:scripts/global.lua---
print("hello from entry")
cls(1)
flip()
---END---
```

## Rules (v0)

| # | Rule |
|---|------|
| 1 | First line must be exactly `TURTLECART:0` |
| 2 | `ENTRY:<path>` — Lua file to execute at boot (must be embedded below) |
| 3 | `INITIAL_SCENE:<id>` — optional; scene to load after ENTRY runs (default: `intro`). **`main` is a reserved id** — do not use as a scene id. |
| 4 | `BUNDLE_FILE:<path>` — optional; sidecar JSON bundle on the SD card. Do not embed the bundle in the cart — saves RAM on ESP32. |
| 5 | `PALETTE:` block — optional; one `#RRGGBB` or `#RGB` color per line. Up to 32 entries are applied to indices `0..31`. Fewer entries leave remaining indices as `#000000`. |
| 6 | Embedded files: content between `---FILE:<path>---` and `---END---` |
| 7 | The file named in `ENTRY` must exist as an embedded block |

**Recommended order:** `TURTLECART:` → `ENTRY:` → `INITIAL_SCENE:` → `BUNDLE_FILE:` → `PALETTE:` → `---FILE:<ENTRY>---`

## Palette

- `#RRGGBB` hex (upper or lowercase)
- `#RGB` shorthand is also accepted (each nibble is doubled)
- Blank lines and invalid lines are skipped
- Only the first 32 valid entries are applied at runtime; the rest are ignored
- Index **31** is always transparent — never paint with it

Default palette (when `PALETTE:` block is absent): a Genesis-style default is loaded by the firmware.

## SD package layout

TurtleStudio exports a `build/` folder that gets copied to the microSD root:

```
build/
├── main.turtlecart          # cart with embedded ENTRY Lua
├── studio/
│   └── project_bundle.json  # scene/object/sprite manifest
├── backgrounds/*.tbg        # baked background images
├── sprites/*.tsp            # baked sprite sheets
├── tiles/*.tts              # baked tilesets
├── fonts/*.tfn              # baked fonts
├── objects/*.json           # object definitions
├── scripts/*.lua            # game logic scripts
└── COPIAR_A_SD.txt          # instructions (copy all of build/ to SD root)
```

## Boot sequence

1. Mount microSD, load `main.turtlecart` (fallback: `demo.turtlecart`)
2. Load sidecar `studio/project_bundle.json`
3. Apply `PALETTE:` block to framebuffer (indices 0–31)
4. Execute embedded ENTRY Lua block (once, then destroy that VM)
5. `turtle_scene_begin_runtime` draws the `INITIAL_SCENE` (background, tiles, sprites)
6. `flip()` — display the first frame

:::note
A `cls()` or drawing done in ENTRY won't persist: the scene runtime repaints the framebuffer at step 5. ENTRY is for initialization, not rendering persistent content.
:::

## Scene coordinate system

Scene space: **164 × 124**, origin **(0, 0) at bottom-left**, **Y positive upward**. See [Intro](/intro) for the framebuffer conversion formula.

## Out of scope in v0

- Compression, checksums, digital signatures
- Sprites embedded in the cart binary (they go as sidecar `.tsp` files)
- Binary container format with a file table (planned for v1+)
