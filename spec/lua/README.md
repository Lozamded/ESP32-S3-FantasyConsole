# Lua Scripting — FantasyConsole / TurtleReader

Documentation for the **Lua 5.4** runtime embedded in the firmware and the scripts exported by TurtleStudio.

| Document | Scope |
|---|---|
| [entry-v0.md](entry-v0.md) | **ENTRY script** — `cls`, `pix`, `spix`, `flip`, runs once at boot |
| [object-script-v0.md](object-script-v0.md) | **Actor scripts** — `_update(dt)`, input, movement in scene space |
| [physics-v0.md](physics-v0.md) | Platformer physics: `move` with tile collision, `on_ground()`, gravity in Lua |
| [animation-v0.md](animation-v0.md) | `set_anim` / `play_anim` driven by the object's `animations` definition |
| [firmware-bridge-v0.md](firmware-bridge-v0.md) | C++ / Lua execution order in TurtleReader (two VMs, frame loop, `move`) |
| [../input-v0.md](../input-v0.md) | `btn` / `btnp` button API (shared by ENTRY and actor VMs) |
| [../scene-v0.md](../scene-v0.md) | 164×124 scene space and coordinate system (`move` / `posx` space) |
| [../turtlecart-v0.md](../turtlecart-v0.md) | Cartridge format, `ENTRY` field, SD package layout |

## Two Lua VMs

The firmware runs two **independent** Lua contexts — they do not share state:

**1. ENTRY VM** (`scripts/global.lua` or the path in `ENTRY:`)
- Runs **once** during `setup()`, before the scene starts.
- Has access to graphics primitives and `print`.
- See [entry-v0.md](entry-v0.md) for the full API.

**2. Actor VM** (one per scene object that has a `"script"` field)
- Loaded from `scripts/<stem>.lua` on the SD card.
- Persists for the lifetime of the scene; `_update(dt)` is called every frame.
- Has access to input, movement, animation, and text overlay.
- See [object-script-v0.md](object-script-v0.md) for the full API.
