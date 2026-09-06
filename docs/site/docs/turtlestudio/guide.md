---
id: guide
sidebar_position: 1
title: TurtleStudio Guide
---

# TurtleStudio

TurtleStudio is the Python authoring tool for TurtleReader projects. It ships a CLI and a **Dear PyGui** GUI editor.

## Installation

```bash
cd tools/turtlestudio
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Launching the GUI

```bash
python -m turtlestudio gui
# or, after editable install:
turtlestudio gui
```

## CLI reference

```bash
# Show help
PYTHONPATH=src python3 -m turtlestudio --help

# Build a project into a .turtlecart + SD package
PYTHONPATH=src python3 -m turtlestudio build path/to/main.lua \
  -o out.turtlecart [--palette pal.txt] [--entry name.lua]

# Initialize a new project directory
PYTHONPATH=src python3 -m turtlestudio project init path/to/project \
  [--name MyGame] [--force]
```

## Project layout on disk

A TurtleStudio project is a directory with:

```
turtlestudio.json           # master manifest (source of truth when open)
palettes/                   # .pal files (palette definitions)
scenes/<id>.json            # scene data (mirrors of manifest, for review)
objects/
  Objects/<id>.json         # object definitions (animations, collision, script)
  Sprites/<id>.json         # sprite frame data (JSON, pre-export)
tiles/<id>.json             # tileset definitions
scripts/
  global.lua                # ENTRY script (embedded in main.turtlecart)
  <stem>.lua                # actor/scene scripts
```

:::note
`turtlestudio.json` is authoritative while the project is open. `scenes/*.json` are mirrors for external review — do not edit them directly.
:::

## Export (build)

Exporting bakes the project into the microSD-ready `build/` folder:

1. Scans all scene assets
2. Renders sprites, tilesets, and backgrounds to binary (`asset_bin.py` via numpy)
3. Writes `main.turtlecart` (embeds ENTRY Lua, references sidecar bundle)
4. Writes `studio/project_bundle.json` manifest
5. Copies `scripts/*.lua` and `objects/*.json`

Copy the entire `build/` folder to the **root** of the microSD card.

## Verification scripts

```bash
# Unit tests — tile collision parsing
PYTHONPATH=src python3 src/turtlestudio/test_tile_collision.py

# Build + verify a project (defaults to exampleprojects/demo1)
PYTHONPATH=src python3 src/turtlestudio/test_asset_bin.py [project_dir]

# Sanity-check an exported SD package
PYTHONPATH=src python3 src/turtlestudio/verify_package.py path/to/build
```

## Key modules

| Module | Purpose |
|--------|---------|
| `project.py` / `project_runtime.py` | Manifest loading + in-memory project state |
| `build.py` | Writes `main.turtlecart` |
| `asset_bin.py` / `asset_bin_decode.py` | Binary asset encoder/decoder |
| `sprites.py` / `backgrounds.py` / `tiles.py` | Per-asset-type JSON serialization |
| `tile_collision.py` | Tile collision shape serialization |
| `scene_camera.py` / `scene_tiles.py` | Scene editing logic |
| `gui.py` | Dear PyGui window and editor panels |
| `cli.py` | argparse CLI entry point |
| `fonts.py` | Font handling (`LATIN_CHARSET` definition) |

## Asset naming rules

IDs and script stems share one naming rule across the tool and firmware:
- Starts with a **letter**
- Then letters, digits, `_`, or `-`
- Max **64 characters**

## Starter Lua template

When you initialize a project or create a script in the Objects tab, TurtleStudio generates a starter `global.lua`:

```lua
-- scripts/global.lua — runs once at boot (ENTRY VM)
print("TurtleReader: cart loaded")
cls(0)
flip()
```

## Object script template

From the **Objects tab → Create .lua in scripts/**:

```lua
-- scripts/<stem>.lua — runs every frame (Actor VM)
function _update(dt)
  -- dt: seconds since previous frame
end
```

## Architecture notes

- TurtleStudio (PyQt6 + Dear PyGui) is **fully independent** from the pygame runtime
- Both share only the `tortoisengine` data layer *(Note: TurtleStudio is for the ESP32 cart; TortoiseMecha/`tortoisengine` is the separate SBC console — do not mix)*
- `watchdog` is a listed dependency for future hot-reload support but is not yet wired up
