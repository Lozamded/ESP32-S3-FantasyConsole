---
id: physics
sidebar_position: 5
title: Physics
---

# Physics (v0)

Movement and collision for actors in scene. Inspired by Godot's `move_and_collide` — per-axis, no slope sliding.

## Responsibility split

| Layer | Handles |
|-------|---------|
| **Lua** | Velocity (`vx`, `vy`), gravity, jump impulse, input |
| **C++** | AABB vs solid tiles, scene bounds, `on_ground()` flag |

## `move(dx, dy)` → `ax, ay`

Moves the actor by `(dx, dy)` pixels with tile collision:

1. Resolves **X** in 1-px steps
2. Resolves **Y** in 1-px steps
3. If moving down (`dy < 0` in scene space) and it hits a tile → sets **grounded**
4. Clamps to scene bounds using the actor's collision AABB

Returns `ax, ay` — the pixels **actually moved**, which may be less than requested if a tile blocks the path.

## `on_ground()` → bool

`true` if the actor is resting on a solid tile just below its AABB, or at scene floor `y = 0`.

Reflects state after the **last `move()` in the current frame**.

## Collision AABB

Defined in the object JSON, field `collision`:

```json
"collision": {
  "mode": "aabb",
  "x0": -7,
  "y0": 0,
  "x1": 6,
  "y1": 16
}
```

Coordinates are **local to the sprite anchor** (feet at `(0, 0)`, Y up). If absent, the firmware derives a box from the sprite size and `origin`.

## Gravity pattern (Y up = positive)

```lua
if on_ground() then
  vy = 0
else
  vy = vy - gravity * dt  -- falling: vy decreases (goes negative)
end
move(0, math.floor(vy * dt + (vy >= 0 and 0.5 or -0.5)))
```

## Jump pattern

```lua
local jump_speed = 240  -- px/s upward
local gravity    = 420  -- px/s²

if on_ground() then
  if vy < 0 then vy = 0 end  -- reset downward velocity on landing
  if btnp(4) then             -- BTN_A
    vy = jump_speed
  end
else
  vy = vy - gravity * dt
end
```

Jump height ≈ `jump_speed² / (2 × gravity)` — with the values above: ~69 px.

## Common bugs and fixes

### Bug 1 — Stuck on ceiling after jump

**Cause:** `ay < my` when hitting a ceiling, but `vy` isn't reset so the actor keeps requesting upward motion.

**Fix:**
```lua
local my = math.floor(vy * dt + (vy >= 0 and 0.5 or -0.5))
local ax, ay = move(0, my)
if my > 0 and ay < my then
  vy = 0  -- hit ceiling; cut upward impulse immediately
end
```

### Bug 2 — Teleport when un-sticking from a wall

**Cause:** horizontal remainder accumulates while blocked, then fires all at once when the block clears.

**Fix:** discard the remainder on block:
```lua
local mx = math.floor(rem_x + 0.5)
local ax, ay = move(mx, 0)

if ax == mx then
  rem_x = rem_x - ax  -- applied, keep sub-pixel remainder
else
  rem_x = 0.0         -- blocked: discard, don't let it accumulate
end
```

## Full platformer example

```lua
local walk_speed = 85
local jump_speed = 240
local gravity    = 420
local vy         = 0
local rem_x      = 0.0

function _update(dt)
  local dx = axis(0, 1)  -- LEFT, RIGHT

  -- Horizontal with sub-pixel accumulator
  rem_x = rem_x + dx * walk_speed * dt
  local mx = math.floor(rem_x + 0.5)
  local ax = select(1, move(mx, 0))
  if ax == mx then rem_x = rem_x - ax else rem_x = 0.0 end
  flip_h(dx < 0)

  -- Gravity + jump
  if on_ground() then
    if vy < 0 then vy = 0 end
    if btnp(4) then vy = jump_speed end
  else
    vy = vy - gravity * dt
  end
  local my = math.floor(vy * dt + (vy >= 0 and 0.5 or -0.5))
  local _, ay = move(0, my)
  if my > 0 and ay < my then vy = 0 end  -- ceiling hit

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

## Out of scope in v0

- `move_and_slide` / surface normals
- One-way platforms (supported at tile level but not exposed to Lua separately)
- Actor-to-actor collision
- Knockback, bounce
