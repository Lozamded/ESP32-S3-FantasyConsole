# FantasyConsole — ESP32-S3

A fantasy game console running on the **ESP32-S3**. Games are distributed as `.turtlecart` cartridge files on a microSD card and run a full **Lua 5.4** VM on-device. Scenes, sprites, backgrounds, tilemaps, and input are all handled by the C++ firmware; game logic lives entirely in Lua scripts.

---

## Features

| Feature | Detail |
|---|---|
| Resolution | **164 × 124** canonical pixels |
| Color palette | **32 colors** (index 31 = transparent), per-game palette via `PALETTE:` block |
| Display | ILI9488 driven by LovyanGFX, scaled to 320 × 240 |
| Scripting | Lua 5.4.6 — two independent VMs (ENTRY + per-actor) |
| Input | 8 buttons: 4 directional + 4 action (`btn` / `btnp`) |
| Assets | Sprites `.tsp`, backgrounds `.tbg`, tilemaps `.tts`, fonts `.tfn` |
| Physics | Per-axis tile collision with AABB, one-way platforms |
| Camera | Follow or fixed, world up to 2× the viewport per axis |
| Scene layers | Up to 3 scrolling background layers + tile layer |
| Authoring tool | **TurtleStudio** (Python + Dear PyGui) — GUI editor and CLI builder |

---

## Hardware requirements

- **Board:** ESP32-S3 (variant S3N16R8 recommended)
- **PSRAM:** Enable `OPI PSRAM` in Arduino IDE (required for cartridges with large backgrounds)
- **Display:** ILI9488 SPI panel (optional — logic works without it, serial output still runs)
- **Storage:** microSD reader wired via SPI, powered at **3.3 V**
- **Input:** 8 push-buttons (pin mapping in `firmware/TurtleReader/turtle_input.h`)

---

## Firmware installation

### 1. Install the Lua54 Arduino library

Copy `firmware/libraries/lua54` into your Arduino libraries folder:

```
~/Arduino/libraries/lua54
```

Restart Arduino IDE — it should appear as **Lua54**.

### 2. Install LovyanGFX

Install **LovyanGFX** from Arduino IDE's Library Manager (required for the display driver).

### 3. Configure display pins

In `firmware/TurtleReader/turtle_gpu.h`:

```cpp
#define TURTLE_USE_DISPLAY 1
// adjust TURTLE_DISP_PIN_* to match your wiring
```

### 4. Flash the firmware

Open `firmware/TurtleReader/TurtleReader.ino` in Arduino IDE. Make sure all sibling `.cpp`/`.h` files are in the same folder:

```
TurtleReader.ino
turtle_cart.cpp / .h
turtle_gpu.cpp / .h
turtle_input.cpp / .h
turtle_asset_bin.cpp / .h
turtle_tileset.cpp / .h
turtle_font.cpp / .h
turtle_scene.cpp / .h
turtle_actor_lua.cpp / .h
turtle_tile_collision.cpp / .h
```

Board settings:
- Board: **ESP32S3 Dev Module**
- PSRAM: **OPI PSRAM → Enabled**
- Serial: **115200 baud**

Flash and open the serial monitor.

---

## TurtleStudio — authoring tool

TurtleStudio is a Python GUI + CLI for creating cartridges. It exports a ready-to-copy `build/` folder for the microSD.

### Requirements

- Python **3.10+**

### Install

```bash
cd tools/turtlestudio
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -U pip setuptools
pip install -e .
```

### Launch the GUI

```bash
python -m turtlestudio gui
# or simply:
turtlestudio gui
```

The GUI provides:
- **Scene editor** — place sprites, tiles, and backgrounds on the 164 × 124 canvas
- **Sprite / tile painter** — draw with the 32-color palette, cell size 4 px default
- **Lua editor** — write the ENTRY script (`scripts/global.lua`) directly in the tool
- **Export** — writes `build/` with `main.turtlecart`, binary assets, and all scripts

### CLI build (no GUI needed)

```bash
cd tools/turtlestudio
PYTHONPATH=src python3 -m turtlestudio build path/to/main.lua -o out.turtlecart
PYTHONPATH=src python3 -m turtlestudio build main.lua -o cart.turtlecart --palette palette.txt
```

---

## Running a cartridge

### Copy to microSD

Copy the entire exported `build/` folder to the **root** of the microSD:

```
/main.turtlecart
/backgrounds/sky.tbg
/sprites/player.tsp
/tiles/terrain.tts
/scripts/actor.lua
...
```

If no `main.turtlecart` is found, the firmware falls back to `/demo.turtlecart`.

### Serial output (expected on success)

```
SD: reading /main.turtlecart
Bundle: N bytes
turtle_scene: bin SD /backgrounds/sky.tbg 164x124 mode 2
turtle_scene: sprite "player" loaded from SD
Initial scene applied.
-- Lua output --
hello from turtlecart
Lua finished OK
```

If a sidecar asset is missing you will see `could not load asset SD /backgrounds/...`.

### Verify a package on PC (no board needed)

```bash
cd tools/turtlestudio
PYTHONPATH=src python3 src/turtlestudio/verify_package.py /path/to/build
PYTHONPATH=src python3 src/turtlestudio/test_asset_bin.py /path/to/project
```

---

## Lua scripting API

### ENTRY script (`scripts/global.lua`)

Runs once at boot in its own VM.

| Function | Description |
|---|---|
| `cls(i)` | Clear framebuffer to palette index `i` |
| `pix(x, y, i)` | Draw pixel at raw framebuffer coords |
| `spix(sx, sy, i)` | Draw pixel at scene coords (origin bottom-left, Y up) |
| `flip()` | Push framebuffer to display |
| `btn(i)` / `btnp(i)` | Read button state / pressed-this-frame |
| `text(sx, sy, str, font_id [, color])` | Draw text at scene coords |
| `text_width(str, font_id)` | Measure text width in pixels |
| `W`, `H`, `COLORS` | Constants: 164, 124, 32 |

### Actor scripts (`scripts/<name>.lua`)

One Lua VM per actor, ticked every frame via `_update(dt)` (dt in seconds).

| Function | Description |
|---|---|
| `btn(i)` / `btnp(i)` / `axis(i)` | Input |
| `posx()` / `posy()` | Actor position in scene coords |
| `move(dx, dy)` | Move with tile collision, returns actual pixels moved |
| `on_ground()` | True if grounded after last `move` |
| `set_anim(name)` / `play_anim(name)` | Set/play sprite animation |
| `flip_h(bool)` | Mirror sprite horizontally |
| `text(str, font_id [, dx, dy, color])` | Persistent text overlay on this actor |

---

## Project structure

```
firmware/
  TurtleReader/        # Main Arduino sketch + all C++ modules
  libraries/lua54/     # Vendored Lua 5.4.6 (ESP32-patched)
tools/
  turtlestudio/        # Python authoring tool (GUI + CLI)
spec/
  turtlecart-v0.md     # Cartridge format spec
  scene-v0.md          # Scene coordinate system and layers
  asset-bin-v0.md      # Binary asset formats (.tbg, .tsp, .tts, .tfn)
  lua/                 # Lua VM API specs
cart/
  demo.turtlecart      # Minimal demo cartridge (firmware fallback)
```

---

## Console specs

| Spec | Value |
|---|---|
| Resolution | 164 × 124 |
| Palette | 32 colors per game |
| Max world size | 328 × 248 (2× viewport) |
| Lua VM | 5.4.6 (32-bit integers and floats) |
| Cartridge format | `.turtlecart` (plain-text container) |
| Asset formats | `.tbg` `.tsp` `.tts` `.tfn` |
