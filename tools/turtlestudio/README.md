# TurtleStudio

Python authoring tool (GUI + CLI) for creating `.turtlecart` cartridges for the FantasyConsole ESP32-S3.

---

## Requirements

- Python **3.10+**
- `g++` and `python3` on PATH (only for host tests)

---

## Installation

```bash
cd tools/turtlestudio
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -U pip setuptools
pip install -e .
```

This installs **turtlestudio** and **dearpygui** (the GUI backend).

> If you see `No module named turtlestudio`, run `pip install -e .` inside the active venv from the `tools/turtlestudio` directory.

---

## GUI

```bash
source .venv/bin/activate
python -m turtlestudio gui
# or:
turtlestudio gui
```

The GUI window has two panels:

- **Left panel:** export folder, initial scene selector, optional palette, and the **Export SD package** button.
- **Right panel:** 164×124 canvas editor and Lua editor for the ENTRY script (`scripts/global.lua`).

**Export** writes the full `build/` folder — `main.turtlecart`, binary assets (`.tbg`, `.tsp`, `.tts`, `.tfn`), `objects/`, `scripts/`, and `COPIAR_A_SD.txt`. Copy the entire `build/` to the root of the microSD.

---

## CLI

### Build a cartridge

```bash
cd tools/turtlestudio
PYTHONPATH=src python3 -m turtlestudio build path/to/main.lua -o out.turtlecart
```

With a custom palette (one `#RRGGBB` per line; lines starting with `#` that aren't valid hex are treated as comments):

```bash
PYTHONPATH=src python3 -m turtlestudio build main.lua -o cart.turtlecart --palette palette.txt
```

With a different logical entry name from the file name:

```bash
PYTHONPATH=src python3 -m turtlestudio build src/game.lua --entry main.lua -o cart.turtlecart
```

> **Warning:** if the Lua source contains the literal string `---END---`, the firmware will truncate the script. The builder emits a `warnings.warn` in that case.

### Initialize a project

```bash
PYTHONPATH=src python3 -m turtlestudio project init path/to/project [--name X] [--force]
```

### Help

```bash
PYTHONPATH=src python3 -m turtlestudio --help
```

---

## Play tab (live playtest, optional)

The **Play** tab in the GUI runs the full project logic — actor/ENTRY Lua scripts, collision, camera — directly in memory, without building or flashing a board. It requires `lupa` compiled against the vendored Lua 5.4.6 sources (see below). If `lupa` is not available the tab is disabled with an explanation; the rest of TurtleStudio still works normally.

### Installing lupa (Lua 5.4.6, 32-bit, matching the firmware)

`pip install lupa` alone **will not work** — the PyPI wheel ships Lua 5.5, which is incompatible with the actor scripts written for 5.4. You must build `lupa` from source against the vendored Lua 5.4.6:

```bash
cd tools/turtlestudio
source .venv/bin/activate

# Step 1: compile the vendored Lua 5.4.6 as a static host library.
# -DESP_PLATFORM is REQUIRED: it enables LUA_32BITS in luaconf.h (32-bit
# integers and floats), matching what runs on the ESP32-S3.
LUA_SRC=../../firmware/libraries/lua54/src
mkdir -p /tmp/liblua54 && cd /tmp/liblua54
gcc -std=c99 -O1 -DESP_PLATFORM -c "$LUA_SRC"/*.c
ar rcs liblua54.a *.o
cd -

# Step 2: download the lupa sdist (not the wheel) and build it against that library.
pip download --no-binary lupa --no-deps -d /tmp/lupa_src lupa
cd /tmp/lupa_src && tar xf lupa-*.tar.gz && cd lupa-*/
python3 setup.py build_ext \
  --lua-lib=/tmp/liblua54/liblua54.a \
  --lua-includes="$LUA_SRC" \
  install
```

Verify the result (must say `Lua 5.4` and `LUA_32BITS: True`):

```bash
python3 -c "
import lupa
rt = lupa.LuaRuntime()
print(rt.lua_implementation)
print('LUA_32BITS:', rt.eval('math.maxinteger') == 2**31 - 1)
"
```

If `LUA_32BITS: False`, `-DESP_PLATFORM` was missing from Step 1 — recompile `liblua54.a`.

When `lupa` is correctly installed, the **Play** tab is enabled, and the CLI `build` command can also export actor scripts as pre-compiled Lua 5.4 bytecode (smaller, not human-readable) instead of plain text. The firmware accepts both transparently via `luaL_loadbuffer`.

---

## Verification (no board needed)

```bash
cd tools/turtlestudio

# Sanity-check an exported SD package (build/ folder):
PYTHONPATH=src python3 src/turtlestudio/verify_package.py /path/to/build

# Build + verify a full project (defaults to exampleprojects/demo1):
PYTHONPATH=src python3 src/turtlestudio/test_asset_bin.py [/path/to/project]

# Tile collision unit tests:
PYTHONPATH=src python3 src/turtlestudio/test_tile_collision.py
```

---

## Conventions

| Convention | Detail |
|---|---|
| Scene space | 164×124, origin bottom-left, Y up (see `spec/scene-v0.md`) |
| Palette index 31 | Always transparent — not selectable as a brush or fill color |
| Cell size | 4 px default (`cell_px` in sprite/tile definitions) |
| Object/asset IDs | Leading letter, then letters/digits/`_`/`-`, max 64 chars |
| ENTRY script | `scripts/global.lua` — embedded in `main.turtlecart`, also exported to `scripts/` |
| Actor scripts | `scripts/<stem>.lua` — referenced by `objects/<id>.json` via `"script"` field |
| Binary assets | `backgrounds/*.tbg`, `sprites/*.tsp`, `tiles/*.tts`, `fonts/*.tfn` |
