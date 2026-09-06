---
id: firmware-bridge
sidebar_position: 7
title: Firmware Bridge
---

# Firmware–Lua Bridge (v0)

This page documents how the C++ firmware exposes functionality to the two Lua VMs, what each VM can and cannot do, and where the code lives for each binding.

---

## Two independent VMs

The firmware creates **two completely separate** Lua states. They never share a `lua_State`, never share globals, and cannot call each other directly.

| Property | ENTRY VM | Actor VM |
|----------|----------|----------|
| `lua_State` | Dedicated | Shared across all actors in the scene |
| Lifetime | Entire cart execution | Created at scene start, destroyed at scene end |
| Ticked by | `TurtleReader.ino` `setup()` | `turtle_scene_runtime_tick` each frame |
| Script source | `ENTRY:<path>` in `.turtlecart` | `objects/<id>.json → "script"` |
| Drawing | Immediate (ENTRY globals, HUD) | Via actor overlay system |
| VM isolation | Runs first, completes before scene starts | Runs per-frame inside scene loop |

Communication between VMs goes through the **state store** (`state_get`/`state_set`/`state_add`) — 16 int32 slots that both VMs can read and write. See [State Store](./state).

---

## API surface by VM

### ENTRY VM bindings

Bound in `TurtleReader.ino` and `turtle_gpu.cpp`.

| Function | Description |
|----------|-------------|
| `cls(i)` | Fill framebuffer with palette index `i`. |
| `pix(xfb, yfb, i)` | Draw pixel at raw framebuffer coords (Y-down). |
| `spix(sx, sy, i)` | Draw pixel at scene coords (origin bottom-left, Y-up). |
| `flip()` | Push framebuffer to display. |
| `text(sx, sy, str, font_id [, color])` | Draw text immediately at scene coords. |
| `text_width(str, font_id)` | Measure text width in pixels without drawing. |
| `btn(i)` / `btnp(i)` | Read button state / pressed-this-frame. |
| `W`, `H`, `COLORS` | Constants: 164, 124, 32. |
| `hud_pix`, `hud_rect`, `hud_clear`, `hud_text`, `hud_text_width` | HUD-strip drawing (see [HUD Border](../gui/hud-border)). |
| `gui_layer_show`, `gui_layer_hide`, `gui_layer_set_text`, … | GUI layer control (see [GUI Layers](../gui/gui-layers)). |
| `state_get`, `state_set`, `state_add` | Cross-VM state store (see [State Store](./state)). |

`text()` in the ENTRY VM draws **immediately** at absolute scene coordinates. It is wiped as soon as the scene starts (`turtle_scene_begin_runtime` calls `cls`). Use it for splash screens and boot animations; for persistent in-game text use scene `text_labels` or GUI layers.

### Actor VM bindings

Bound in `turtle_actor_lua.cpp`.

| Function | Description |
|----------|-------------|
| `btn(i)` / `btnp(i)` / `axis(i)` | Input. |
| `posx()` / `posy()` | Actor position in scene coordinates. |
| `move(dx, dy)` | Move with tile collision; returns actual pixels moved. |
| `on_ground()` | True if grounded after the last `move`. |
| `set_anim(name)` / `play_anim(name [, speed])` | Animation control. |
| `flip_h(bool)` | Mirror sprite horizontally. |
| `text(str, font_id [, dx, dy, color])` | Persistent text overlay on this actor (different signature than ENTRY). |
| `text_width(str, font_id)` | Measure text width without drawing. |
| `goto_scene(id)` | Transition to a named scene. |
| `find_by_id(id)` / `find_by_tag(tag)` | Object identity queries. |
| `obj_posx(h)` / `obj_posy(h)` / `obj_id(h)` / `obj_has_tag(h, tag)` | Handle queries. |
| `state_get`, `state_set`, `state_add` | Cross-VM state store. |

---

## `text()` signature difference

The two VMs have different `text()` signatures because they have different drawing models:

**ENTRY `text(sx, sy, str, font_id [, color])`** — immediate blit at absolute scene position. The call draws and returns immediately. Suitable for splash screens.

**Actor `text(str, font_id [, dx, dy, color])`** — a **setter** that attaches a text overlay to the actor. The firmware redraws this overlay at the actor's current position every frame as part of the actor draw pass. `dx`/`dy` offset the overlay relative to the actor's anchor. Call with `""` to clear. This design is required for correct dirty-rect erasure: if the actor moves, the firmware knows exactly which cells to clear and repaint on the next frame.

---

## Font cache

Both VMs share a single font cache (max **4 fonts** simultaneously). A font is loaded from the bundle's `.tfn` assets the first time it is referenced and evicted by LRU if the cache is full. Keep the number of distinct fonts per scene to 4 or fewer to avoid repeated SD loads.

---

## Data origins

| Data | Source | Notes |
|------|--------|-------|
| ENTRY Lua script | Embedded in `.turtlecart` | Loaded into RAM at cart open |
| Actor Lua scripts | `/scripts/<stem>.lua` on SD | Loaded at scene start |
| Bundle JSON (sprites, objects, scenes, guilayers) | `/studio/project_bundle.json` on SD | Parsed at cart open |
| Sidecar binary assets (`.tbg`, `.tsp`, `.tts`, `.tfn`) | SD card | Loaded on demand per scene |
| Palette | `PALETTE:` block in `.turtlecart` | Applied once at cart open |
| State store | RAM | Zeroed at cart load; persists across scenes |

---

## Firmware source map

| File | Role |
|------|------|
| `TurtleReader.ino` | ENTRY VM setup, button polling, SDL loop |
| `turtle_gpu.cpp/.h` | Framebuffer primitives bound to ENTRY |
| `turtle_actor_lua.cpp/.h` | Actor VM lifecycle, all actor bindings |
| `turtle_scene.cpp/.h` | Scene runtime, actor position/animation/collision, `text` overlay |
| `turtle_font.cpp/.h` | Font loading, measuring, drawing (shared by both VMs) |
| `turtle_input.cpp/.h` | GPIO polling; `btn`/`btnp` state shared to both VMs |
