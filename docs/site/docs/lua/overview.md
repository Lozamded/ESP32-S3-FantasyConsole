---
id: overview
sidebar_position: 1
title: Lua API Overview
---

# Lua API Overview

TurtleReader runs **two independent Lua VMs** that do not share state. Each has a distinct lifecycle and API surface.

## The two VMs

| | ENTRY VM | Actor VM |
|-|----------|----------|
| **When it runs** | Once during `setup()` at boot | Every frame via `_update(dt)` |
| **Source** | Embedded in `main.turtlecart` | `/scripts/<stem>.lua` on microSD |
| **Lifecycle** | Created → runs → destroyed | Created per scene actor, persists until scene change |
| **Graphics** | `cls`, `pix`, `spix`, `flip` | ✗ (no direct drawing in v0) |
| **Movement** | ✗ | `move`, `posx`, `posy`, `on_ground` |
| **Input** | `btn`, `btnp` (limited) | `btn`, `btnp`, `axis` |
| **Animation** | ✗ | `set_anim`, `play_anim`, `flip_h` |

## Shared API

Both VMs have:
- `print(...)` — outputs tab-separated args to Serial (115200 baud)
- `btn(i)` / `btnp(i)` — button state ([button indices](/lua/input))

## Boot order

```
Mount SD
  └─ Load main.turtlecart + bundle JSON
       └─ Apply PALETTE:
            └─ Run ENTRY Lua (once)
                 └─ turtle_scene_begin_runtime
                      ├─ Draw background + tiles
                      ├─ Create actors, load actor scripts from SD
                      └─ flip() → first frame visible
                           └─ Per-frame loop:
                                ├─ turtle_input_poll()
                                ├─ actor _update(dt) × N
                                ├─ C++ sprite/animation tick
                                └─ turtle_gpu_flip()
```

## Lua standard library

`luaL_openlibs` is available in both VMs, but only the documented API is guaranteed portable across cart builds.

## Pages in this section

- [ENTRY VM](/lua/entry-vm) — boot script API: graphics, constants, input
- [Object Scripts](/lua/object-scripts) — per-actor `_update(dt)` API
- [Animation](/lua/animation) — `set_anim`, `play_anim`, `flip_h`
- [Physics](/lua/physics) — `move`, `on_ground`, gravity patterns
- [Input](/lua/input) — button indices and axis helper
