---
id: intro
slug: /intro
sidebar_position: 1
title: Introduction
---

# TurtleReader Fantasy Console

**TurtleReader** is a fantasy console targeting the **ESP32-S3** microcontroller. Games are distributed as `.turtlecart` cartridges stored on a microSD card. Game logic runs on an embedded **Lua 5.4 VM**.

## Hardware spec

| Property | Value |
|----------|-------|
| Target chip | ESP32-S3 (S3N16R8) |
| Display | ILI9488 LCD via LovyanGFX |
| Resolution | **164 × 124** logical pixels |
| Colors | **32** palette indices (index 31 = always transparent) |
| Storage | microSD (FAT filesystem) |
| Input | 8 GPIO buttons (directional + 4 action) |
| Scripting | Lua 5.4.6 (two independent VMs) |

## Coordinate system

The console uses **scene space** as the primary coordinate convention:

- Origin **(0, 0)** is at the **bottom-left** corner
- **Y increases upward** (math convention)

The raw framebuffer is raster (row 0 = top, Y down). Conversion:

```
xfb = sx
yfb = (H − 1) − sy   where H = 124
```

Use `spix(sx, sy, color)` for scene-space drawing. Use `pix(xfb, yfb, color)` only for raw framebuffer access.

## Three packages

| Package | Language | Purpose |
|---------|----------|---------|
| `firmware/TurtleReader/` | C++ (Arduino) | Runs on ESP32-S3; reads cart, drives display, hosts Lua VMs |
| `firmware/libraries/lua54/` | C | Vendored Lua 5.4.6, installed as Arduino library |
| `tools/turtlestudio/` | Python | Authoring tool — CLI + Dear PyGui GUI for building projects |

## Quick start

1. Install the `Lua54` Arduino library from `firmware/libraries/lua54/`.
2. Flash `firmware/TurtleReader/TurtleReader.ino` to an ESP32-S3. Enable **OPI PSRAM**.
3. Build a project with TurtleStudio and copy the `build/` folder to the microSD root.
4. Insert the microSD and power on.

Serial monitor runs at **115200 baud** and outputs `print()` calls from Lua.

## Next steps

- [Cartridge format](/cartridge/turtlecart-format) — how `.turtlecart` files are structured
- [Lua API overview](/lua/overview) — ENTRY VM and actor script VMs
- [Asset binary formats](/assets/binary-formats) — `.tsp`, `.tbg`, `.tts`, `.tfn`
- [TurtleStudio guide](/turtlestudio/guide) — authoring tool reference
