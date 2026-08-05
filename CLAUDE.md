# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

FantasyConsole: a fantasy-console game system targeting an ESP32-S3. Cartridges (`.turtlecart`) are read from a microSD card, and game logic runs on an embedded Lua 5.4 VM. The repo has three main pieces:

- `firmware/TurtleReader/` — Arduino sketch (C++) that runs on the ESP32-S3: reads the cartridge, drives the display/framebuffer, and hosts the two Lua VMs.
- `firmware/libraries/lua54/` — vendored Lua 5.4.6 (official sources + minimal ESP32 patches), installed as an Arduino library.
- `tools/turtlestudio/` — Python authoring tool (CLI + Dear PyGui GUI) for building projects and exporting the SD package.
- `spec/` — the source of truth for file formats and coordinate conventions. When in doubt about behavior, check the spec doc before guessing.

Most in-repo documentation and commit-adjacent docs are written in Spanish; match that when editing `spec/` or code comments in `firmware/`.

## Commands

### TurtleStudio (Python tool, `tools/turtlestudio/`)

Editable install (recommended for the GUI, needs `dearpygui`):
```bash
cd tools/turtlestudio
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m turtlestudio gui          # or: turtlestudio gui
```

Run without installing (CLI/build only):
```bash
cd tools/turtlestudio
PYTHONPATH=src python3 -m turtlestudio --help
PYTHONPATH=src python3 -m turtlestudio build path/to/main.lua -o out.turtlecart [--palette pal.txt] [--entry name.lua]
PYTHONPATH=src python3 -m turtlestudio project init path/to/project [--name X] [--force]
```

### Tests / verification (no pytest — plain unittest / script-style, run directly)

```bash
cd tools/turtlestudio
PYTHONPATH=src python3 src/turtlestudio/test_tile_collision.py      # unittest suite, tile collision parsing
PYTHONPATH=src python3 src/turtlestudio/test_asset_bin.py [project_dir]   # builds+verifies a project (defaults to exampleprojects/demo1)
PYTHONPATH=src python3 src/turtlestudio/verify_package.py path/to/build  # sanity-checks an exported SD package (build/ folder)
```

To run a single test case from the unittest file: `PYTHONPATH=src python3 -m unittest turtlestudio.test_tile_collision.<TestClass>.<test_method>` (run from `tools/turtlestudio/src`, or keep `PYTHONPATH=src` from `tools/turtlestudio`).

### Firmware

No CLI build — flash `firmware/TurtleReader/TurtleReader.ino` (with the other `.cpp`/`.h` files alongside it) via Arduino IDE onto an ESP32-S3. The `Lua54` Arduino library must be installed first by copying `firmware/libraries/lua54` into the Arduino libraries folder. Enable PSRAM (`OPI PSRAM` / `Enabled`) for large cartridges with embedded indexed-pixel backgrounds, or the board can crash on load. Serial monitor runs at `115200`.

## Architecture

### Cartridge format (`.turtlecart`, spec: `spec/turtlecart-v0.md`)

Plain-text container: `TURTLECART:0` header, `ENTRY:<path>` (the boot Lua file), optional `INITIAL_SCENE:`, optional `BUNDLE_FILE:` (path to a sidecar `studio/project_bundle.json`), optional `PALETTE:` block (up to 32 `#RRGGBB` lines, index 31 always transparent), then one or more `---FILE:<path>---` ... `---END---` embedded files (only the ENTRY Lua is embedded here — the bundle/assets are sidecar files on the SD card, not embedded, to save RAM on the ESP32).

The recommended distribution unit is a whole exported `build/` folder copied to the SD root: `main.turtlecart` + `backgrounds/*.tbg` + `sprites/*.tsp` + `tiles/*.tts` + `fonts/*.tfn` + `objects/*.json` + `scripts/*.lua` + `COPIAR_A_SD.txt`. See `spec/asset-bin-v0.md` for the binary asset formats. `.tfn` fonts are decodable and drawable via `text()`/`text_width()` from both Lua VMs (see the two-Lua-VMs section below), with different call signatures — ENTRY draws immediately at absolute coords, actors set a persistent per-actor overlay.

### Scene / coordinate system (spec: `spec/scene-v0.md`)

Canonical viewport is **264×198**. Scene space has origin **(0,0) at bottom-left**, **Y up** (math convention). The runtime framebuffer is raster (row 0 = top, Y down), so scene→framebuffer conversion is `xfb = sx`, `yfb = (H-1) - sy` (`H=198`). New game code should use `spix(sx, sy, c)` (applies the conversion); `pix(xfb, yfb, c)` is the raw framebuffer primitive kept for legacy/internal use. Palette index **31 is always transparent** for indexed sprites/backgrounds, project-wide, regardless of how many colors a given palette file defines.

A "world" can be up to 2x the viewport per axis (`world_steps_x/y` in the scene manifest), clipped through a `camera` (`follow`/`fixed`) config.

### Two separate Lua VMs (spec: `spec/lua/firmware-bridge-v0.md`)

They do **not** share a `lua_state`:

1. **ENTRY VM** — runs once in `setup()`, from the Lua block embedded in `main.turtlecart` (conventionally `scripts/global.lua`). API: `print, cls, pix, spix, flip, W, H, COLORS, btn, btnp, text, text_width`. `text(sx, sy, str, font_id [, color_index])` draws immediately at absolute scene coords — but gets wiped the instant a scene begins (`turtle_scene_begin_runtime` does `cls`+`snapshot_static`), so it only persists for no-bundle/splash carts. Implemented in `TurtleReader.ino` + `turtle_gpu.cpp` (+ `turtle_scene.cpp`/`turtle_font.cpp` for `text`/`text_width`).
2. **Actor VM(s)** — one per scene actor with a `"script"` field, ticked every frame via `_update(dt)` (`dt` in seconds). Scripts live at `/scripts/<stem>.lua` on the SD card, referenced by `objects/<id>.json`. API: `print, btn, btnp, axis, posx, posy, move, on_ground, set_anim, play_anim, flip_h, text, text_width`. `text(str, font_id [, dx, dy, color_index])` has a different signature than ENTRY's — it's a setter on the active actor (like `set_anim`), persists until the next `text()` call, and its redraw is integrated into the actor dirty-rect pass rather than an immediate blit (required for correct erasure — see `spec/lua/firmware-bridge-v0.md`'s "Texto" section for why). Optional `color_index` (both VMs) tints every non-transparent glyph pixel with that palette index instead of the glyph's own baked color, e.g. for reusing one font in multiple HUD colors. Implemented in `turtle_actor_lua.cpp` (VM lifecycle) + `turtle_scene.cpp` (actor state, drawing, collision, `move`, text overlay).

Boot order: mount SD → load `main.turtlecart` + bundle into RAM → apply palette → run ENTRY Lua → `turtle_scene_begin_runtime` (C++ draws background/tiles, creates actors, `turtle_actor_lua_init` loads/binds actor scripts) → `flip()`.

Per-frame loop: `turtle_input_poll()` → `turtle_scene_runtime_tick(dt_ms)` (1. actor `_update(dt)` calls, 2. C++ sprite animation tick, 3. C++ redraw of actors + text overlays over the static background/tile layer) → `turtle_gpu_flip()`. The background/tile layer is drawn once and not repainted; only sprites (and any actor text) redraw per frame.

`move(dx, dy)` resolves per-axis collision against solid tiles (and one-way platforms) and scene bounds, updates `grounded`, and returns actual pixels moved; see `spec/lua/physics-v0.md` and `turtle_tile_collision.cpp`/`.h` for the tile collision shapes (`solid`, `none`, `aabb`/`triangle`/`hexagon` approximated as AABB, optional one-way direction).

### Firmware module map (`firmware/TurtleReader/`)

| File | Responsibility |
|------|----------------|
| `TurtleReader.ino` | Setup/loop, SD mount, ENTRY Lua execution |
| `turtle_cart.cpp/.h` | `.turtlecart` text-format parsing |
| `turtle_asset_bin.cpp/.h` | Binary asset (`.tbg`/`.tsp`) decoding |
| `turtle_tileset.cpp/.h` | Tileset (`.tts`) loading |
| `turtle_font.cpp/.h` | Font (`.tfn`) loading, measuring, drawing (`text`/`text_width` in both VMs) |
| `turtle_tile_collision.cpp/.h` | Per-tile collision metadata/shapes |
| `turtle_scene.cpp/.h` | Scene runtime: actors, drawing, collision, animation, camera (largest file, ~3.2k lines) |
| `turtle_actor_lua.cpp/.h` | Per-actor Lua VM lifecycle and C-function bindings |
| `turtle_input.cpp/.h` | GPIO polling, `btn`/`btnp` (shared by both VMs) |
| `turtle_gpu.cpp/.h` | Framebuffer + display driver (ILI9488 via LovyanGFX), ENTRY-only primitives |

### TurtleStudio project layout (`tools/turtlestudio/src/turtlestudio/`)

A project on disk is JSON-based (`turtlestudio.json` manifest + `scenes/`, `objects/Objects/`, `objects/Sprites/`, `tiles/`, `scripts/`, `palettes/`). `turtlestudio.json` is the source of truth when the project is open; `scenes/<id>.json` files are a mirror for external review, not authoritative. Exporting ("build") converts this project into the SD-ready binary package (`build/`): JSON sprites/backgrounds become `.tsp`/`.tbg`, and `main.turtlecart` embeds only the ENTRY script + references the sidecar bundle.

Key modules: `project.py`/`project_runtime.py` (manifest + in-memory project state), `build.py` (writes `.turtlecart`), `asset_bin.py`/`asset_bin_decode.py` (binary asset codec), `sprites.py`/`backgrounds.py`/`tiles.py`/`tile_collision.py` (per-asset-type serialization), `scene_camera.py`/`scene_tiles.py` (scene editing logic), `gui.py` (Dear PyGui window/editor), `cli.py` (argparse entry point).

Object/sprite/tile IDs share one stem-naming rule across the tool and firmware: leading letter, then letters/digits/`_`/`-`, max 64 chars.
