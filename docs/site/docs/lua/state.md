---
id: state
sidebar_position: 9
title: State Store
---

# State Store (v0)

The state store is a small key–value memory shared across **all Lua VMs** (ENTRY and all actor scripts). It is the canonical way for actors to communicate with the HUD, to persist progress between scenes, and to coordinate between actor scripts.

---

## Characteristics

| Property | Value |
|----------|-------|
| Slots | 16 simultaneous keys |
| Key type | String, max 31 chars |
| Value type | `int32` (signed 32-bit integer) |
| Lifetime | Persists across scene transitions; **reset to all-zero on cart load** |
| Visibility | Every VM sees writes immediately within the same frame |

The 16-slot limit is per cart. Choose short, descriptive keys — they are the only documentation of what a slot means.

---

## API

### `state_set(key, value)`

Write `value` (integer) to `key`. Creates the slot if it doesn't exist; overwrites if it does.

```lua
state_set("score", 0)
state_set("lives", 3)
```

Returns nothing. If the store is full (16 keys) and `key` is new, the write is a silent no-op — check Serial output during development.

### `state_get(key)` → int | nil

Read the current value for `key`. Returns `nil` if the key has never been written.

```lua
local score = state_get("score") or 0
```

Use `or 0` (or another default) to guard against the first-run `nil`.

### `state_add(key, delta)` → int

Atomically add `delta` to the value at `key` and return the new value. If `key` doesn't exist, it is treated as `0` before the add.

```lua
local new_score = state_add("score", 100)
```

Equivalent to `state_set(key, (state_get(key) or 0) + delta)`, but in a single call. Useful for counters that multiple actors may increment independently.

---

## Cross-VM visibility

State writes from actor scripts are visible to ENTRY's `_hud(dt)` within the **same frame**, because the per-frame order is:

1. Actor VM: scene script `_update(dt)` → actor `_update(dt)` calls
2. ENTRY VM: `_hud(dt)`
3. GUI layers
4. `flip()`

An actor that calls `state_add("score", 100)` in step 1 will have the HUD read the new value in step 2, on the same frame. No one-frame lag.

---

## Common patterns

### Score counter

```lua
-- actor script (e.g. coin.lua)
function _update(dt)
  local px = find_by_tag("player")[1]
  if px and math.abs(obj_posx(px) - posx()) < 8 then
    state_add("score", 10)
    goto_scene("level_1")  -- respawn / collect
  end
end
```

```lua
-- ENTRY VM (_hud function)
function _hud(dt)
  hud_clear(0)
  hud_text(4, 4, "SCORE " .. (state_get("score") or 0), "font8")
end
```

### Lives / retry loop

```lua
-- scene script
function _update(dt)
  if state_get("lives") ~= nil and state_get("lives") <= 0 then
    goto_scene("game_over")
  end
end
```

```lua
-- player actor script, on death:
state_add("lives", -1)
goto_scene("level_1")  -- restart
```

### Cross-scene persistent flag

```lua
-- level_1 scene script
state_set("boss_defeated", 0)

-- boss actor, on death:
state_set("boss_defeated", 1)

-- level_2 scene script (read flag set in level_1):
function _update(dt)
  if state_get("boss_defeated") == 1 then
    -- skip intro cutscene
  end
end
```

---

## Key naming guidelines

- Use lowercase `snake_case`: `"score"`, `"lives"`, `"gears_collected"`.
- Stay under 16 total keys for the whole cart — treat the store as a tight global register file, not a database.
- Document your key names in the ENTRY script or a comment in your scene script — there is no introspection API.

---

## Limits and edge cases

| Situation | Behavior |
|-----------|----------|
| `state_get` on an unset key | Returns `nil` |
| `state_add` on an unset key | Treats existing value as `0`, creates key |
| 17th unique key written | Silent no-op; value is not stored |
| Integer overflow (exceeding int32 range) | Wraps (C signed overflow semantics) |
| Scene change | State is preserved |
| Cart reload / power cycle | State is reset to zero |
