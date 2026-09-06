---
id: animation
sidebar_position: 4
title: Animation
---

# Animation (v0)

Sprite animation is controlled from Lua via the `animations` list defined in the object's JSON. C++ advances frames automatically after `_update(dt)` runs.

## Defining animations in the object JSON

```json
{
  "id": "character",
  "animations": [
    { "name": "idle", "sprite_id": "character_idle" },
    { "name": "walk", "sprite_id": "character_walk" },
    { "name": "jump", "sprite_id": "character_jump" },
    { "name": "fall", "sprite_id": "character_fall" }
  ]
}
```

- **`name`** — logical identifier used in Lua
- **`sprite_id`** — stem of the sprite file (`sprites/<stem>.tsp`)

## API

| Function | Description |
|----------|-------------|
| `set_anim(name)` | Switch to `name`. Loops infinitely at speed 1. **Does not restart** if already playing that animation. |
| `play_anim(name, speed, repeat)` | Switch to `name`. Always **restarts at frame 0**. `speed` is a float; `repeat` is a boolean. |
| `flip_h(bool)` | Horizontal mirror (`true` = face left). Flips around the sprite anchor in scene space. |

### Frame rate

`speed = 1.0` → one frame every `1000 / default_anim_fps` ms (e.g. 8 FPS → 125 ms/frame).

`speed = 2.0` → twice as fast. Valid range: `0.25..16`.

### Repeat

- `true` — loops back to frame 0 after the last frame
- `false` — holds on the last frame (useful for `damage`, cutscenes)

## Performance

- `set_anim` is a no-op if the actor is already on that animation — safe to call every frame.
- Sprites are pre-loaded into PSRAM at scene start (up to 48 blobs per `sprite_id`). Frame advances read from RAM, not SD.
- Changing animation invalidates the actor's pixel cache; C++ redraws it on the next frame.

## Example

```lua
if not on_ground() then
  if vy > 0 then
    set_anim("jump")
  else
    set_anim("fall")
  end
elseif dx ~= 0 then
  set_anim("walk")
  flip_h(dx < 0)
else
  set_anim("idle")
end

-- One-shot damage animation (slower, no loop):
-- play_anim("damage", 0.75, false)
```

## Notes

- `move()` no longer affects animation speed (it did in early firmware). Lua has full control.
- Frame advance is performed by C++ in `tick_actors`, after `_update` returns.
- If `name` doesn't exist in the object's animation list, the firmware logs a warning to Serial and keeps the current sprite.
