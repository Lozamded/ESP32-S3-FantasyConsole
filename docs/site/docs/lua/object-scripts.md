---
id: object-scripts
sidebar_position: 3
title: Object Scripts
---

# Object Scripts (v0)

Object scripts provide per-**instance** game logic: reading input, moving, and changing animations. Sprite drawing and the frame loop stay in C++ (`turtle_scene`); Lua decides behavior and position.

## Linking a script to an object

In the object's JSON (`objects/<id>.json` on the SD card):

```json
{
  "id": "character",
  "sprite_id": "character_idle",
  "script": "character"
}
```

- **`script`** — stem (no `.lua` extension). Optional. If absent, the actor has no Lua tick.
- File loaded from: `/scripts/<stem>.lua` on microSD
- Valid stem: starts with a letter, then letters/digits/`_`/`-`, max 64 chars

## Script contract

The runtime executes the whole file (local definitions, etc.) then calls `_update(dt)` every frame:

```lua
function _update(dt)
  -- dt: seconds since previous frame (e.g. ~0.033 at 30 FPS)
end
```

If `_update` is missing or the file isn't on the SD card, a warning is printed to Serial and the actor receives no Lua tick.

### Implicit context

There is no `self` in v0. All movement/position functions act on the **actor whose script is currently running**. Multiple objects can share the same script stem — they get separate instances with separate positions.

## Input

| Function | Description |
|----------|-------------|
| `btn(i)` | `true` if button `i` is held (sustained) |
| `btnp(i)` | `true` only on the frame it was first pressed |
| `axis(neg, pos)` | Returns **-1**, **0**, or **1**: subtracts 1 if `btn(neg)`, adds 1 if `btn(pos)` |

```lua
local dx = axis(0, 1)  -- BTN_LEFT=0, BTN_RIGHT=1 → -1, 0, or 1
local dy = axis(3, 2)  -- BTN_DOWN=3, BTN_UP=2
```

See [Input](/lua/input) for all button indices.

## Position & movement

Coordinates are in **scene space** (164×124, origin bottom-left, Y up).

| Function | Description |
|----------|-------------|
| `posx()` | Actor's current X position (integer) |
| `posy()` | Actor's current Y position (integer) |
| `move(dx, dy)` | Move with per-axis tile collision. Returns `ax, ay` — pixels actually moved. |
| `on_ground()` | `true` if the actor is resting on a solid tile or the scene floor |

See [Physics](/lua/physics) for `move` details, gravity, and jump patterns.

## Animation

Animations are defined in the object's `animations` JSON array.

| Function | Description |
|----------|-------------|
| `set_anim(name)` | Switch to named animation, loop, speed 1. Does **not** restart if already playing. |
| `play_anim(name, speed, repeat)` | Switch + set speed (float) + set repeat (bool). Always restarts at frame 0. |
| `flip_h(bool)` | Mirror sprite horizontally (`true` = face left). |

See [Animation](/lua/animation) for full details.

## Scene transitions

| Function | Description |
|----------|-------------|
| `goto_scene(scene_id)` | Request a scene change. **Deferred** — takes effect after the current frame ends. Calling it multiple times in one frame keeps only the last request. |

:::note
The ENTRY VM does **not** re-run on scene changes — it runs once at cart boot only.
:::

## Querying other actors

These functions are **read-only** in v0 — you can't move or animate another actor.

| Function | Description |
|----------|-------------|
| `self_id()` | Instance id of the actor currently running |
| `find_by_id(id)` | Handle (int) of the actor with that instance id, or `nil` |
| `find_by_tag(tag)` | Array of handles for all actors with that tag (1-based, may be empty) |
| `obj_posx(handle)` | X of actor at `handle`, or `nil` if invalid |
| `obj_posy(handle)` | Y of actor at `handle`, or `nil` if invalid |
| `obj_id(handle)` | Instance id of actor at `handle`, or `nil` |
| `obj_has_tag(handle, tag)` | `true` if actor at `handle` has the tag |

:::warning
Handles are invalidated on scene change — never cache them across `goto_scene`.
:::

```lua
-- Enemy approaching the player
function _update(dt)
  local player = find_by_id("player")
  if player then
    local dx = obj_posx(player) - posx()
    move((dx > 0 and 1 or -1) * 20 * dt, 0)
  end
end
```

## Scene script VM

A scene can declare `"script": "<stem>"` in its JSON. That script runs as a **scene VM** — it ticks before all actors each frame, with no actor attached. Useful for scene-level logic (e.g. listening for a button to transition scenes):

```lua
-- scripts/intro.lua
function _update(dt)
  if btnp(4) or btnp(5) then  -- A or B
    goto_scene("Lvl_1")
  end
end
```

## Platformer example skeleton

```lua
local walk_speed = 85
local jump_speed = 240
local gravity = 420
local vy = 0

function _update(dt)
  local dx = axis(0, 1)  -- LEFT / RIGHT

  -- Horizontal movement
  move(dx * walk_speed * dt, 0)
  flip_h(dx < 0)

  -- Gravity and jump
  if on_ground() then
    if vy < 0 then vy = 0 end
    if btnp(4) then vy = jump_speed end  -- BTN_A
  else
    vy = vy - gravity * dt
  end
  move(0, math.floor(vy * dt + (vy >= 0 and 0.5 or -0.5)))

  -- Animation
  if not on_ground() then
    set_anim(vy > 0 and "jump" or "fall")
  elseif dx ~= 0 then
    set_anim("walk")
  else
    set_anim("idle")
  end
end
```

## Debug

| Function | Description |
|----------|-------------|
| `print(...)` | Output to Serial (same as ENTRY) |

## Out of scope in v0

- `cls`, `pix`, `spix`, `flip` (ENTRY-only in v0)
- Actor-to-actor collision
- Remotely controlling another actor (handles are read-only)
