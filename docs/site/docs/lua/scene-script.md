---
id: scene-script
sidebar_position: 8
title: Scene Script
---

# Scene Script (v0)

A scene script is an optional Lua file that runs inside the **Actor VM** alongside all actor scripts. It is ideal for scene-level coordination: checking conditions that span multiple actors, triggering transitions, managing global game state within a scene.

---

## Declaration

Add a `"script"` field to the scene object in the bundle:

```json
{
  "id": "level_1",
  "script": "level1",
  ...
}
```

The firmware loads `/scripts/level1.lua` from the SD card at scene start. If the file is missing, the firmware logs a Serial warning and the scene runs without a scene script.

---

## Execution model

The scene script runs in the **same `lua_State`** as all actor scripts. It shares the Lua global table with actors.

**Tick order per frame:**
1. Scene script `_update(dt)` — called **before** any actor's `_update(dt)`
2. All actor `_update(dt)` calls (in manifest order)

This ordering means the scene script can set globals that actors read within the same frame.

---

## Available API

The scene script has access to the same actor VM bindings — **minus** the self-referential actor functions:

| Available | Not available |
|-----------|---------------|
| `btn(i)` / `btnp(i)` / `axis(i)` | `posx()` / `posy()` (no self) |
| `goto_scene(id)` | `move(dx, dy)` / `on_ground()` |
| `find_by_id(id)` / `find_by_tag(tag)` | `set_anim` / `play_anim` / `flip_h` |
| `obj_posx/posy/id/has_tag(handle)` | `text(str, ...)` as actor overlay |
| `state_get(key)` / `state_set(key, val)` / `state_add(key, delta)` | — |
| `print(...)` | — |

---

## Naming convention

Because scene script globals live in the same namespace as all actor globals, use a consistent prefix to avoid collisions:

```lua
-- level1.lua — scene script
scene_timer = 0
scene_enemies_left = 5

function _update(dt)
  scene_timer = scene_timer + dt

  if scene_enemies_left <= 0 then
    goto_scene("level_2")
  end
end
```

Actor scripts can read `scene_enemies_left` directly; an enemy actor that dies can decrement it:

```lua
-- enemy.lua — actor script
function _update(dt)
  -- ... enemy logic ...
  if hp <= 0 then
    scene_enemies_left = scene_enemies_left - 1
    -- self-destruct or freeze
  end
end
```

:::warning
Global names beginning with `_` are reserved for firmware lifecycle hooks (`_update`, `_hud`, `_hud_init`). Use alphabetic prefixes like `scene_` or `g_` for scene-level globals.
:::

---

## Common patterns

### Scene timer / countdown

```lua
-- scene script
scene_countdown = 60  -- seconds

function _update(dt)
  scene_countdown = scene_countdown - dt
  if scene_countdown <= 0 then
    goto_scene("game_over")
  end
end
```

### Boss gate

```lua
-- scene script
function _update(dt)
  local boss = find_by_id("boss")
  if boss == nil then
    -- boss was destroyed; transition after a brief pause
    scene_win_timer = (scene_win_timer or 0) + dt
    if scene_win_timer > 2.0 then
      goto_scene("credits")
    end
  end
end
```

### Persistent progress via state store

```lua
-- scene script: save checkpoint on reaching a flag
function _update(dt)
  local flag = find_by_id("checkpoint_1")
  local player = find_by_tag("player")[1]
  if flag and player then
    local dx = obj_posx(player) - obj_posx(flag)
    if math.abs(dx) < 8 then
      state_set("last_checkpoint", 1)
    end
  end
end
```

---

## Interaction with `_hud` (ENTRY VM)

The scene script runs in the Actor VM; `_hud(dt)` runs in the ENTRY VM. They cannot call each other directly. Coordination goes through the **state store**: the scene script writes `state_set("score", n)`, and `_hud(dt)` reads `state_get("score")` to display it.

Actor writes to state are visible to ENTRY's `_hud(dt)` within the **same frame** because the frame ordering is:

1. Scene script `_update` → actor `_update` calls (Actor VM ticks)
2. `_hud(dt)` (ENTRY VM tick)
3. GUI layers
4. `flip()`

---

## TurtleStudio

- The scene inspector has a "Scene script" field accepting a bare stem (no `.lua` extension).
- The Lua editor tab shows the scene script file alongside actor scripts.
- The Play simulator loads the scene script from the project's `scripts/` directory.
