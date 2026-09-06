---
id: hud-border
sidebar_position: 2
title: HUD Border
---

# HUD Border (v0)

The HUD border reserves fixed pixel strips along the framebuffer edges for permanent on-screen UI — score, lives, minimap, timer — by shrinking the camera's playfield. This is **method 1** of GUI: always-visible during gameplay, zero per-frame cost when static. [GUI layers](./gui-layers) are **method 2**: transient overlays for menus, pause screens, and dialogues.

The two methods are independent and compose cleanly — a GUI layer can cover the HUD strip (e.g. a full-screen pause menu), but the HUD strip is otherwise a guaranteed "non-playable" zone that actors and background blits never touch.

---

## Configuration

`hud_border` is nested inside the scene's `camera` block:

```json
"camera": {
  "mode": "follow",
  "target": "player",
  "hud_border": {
    "top":    16,
    "bottom":  0,
    "left":    0,
    "right":   0,
    "bg_color_index": 3
  }
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `top` | int | `0` | Pixels reserved at the top of the framebuffer for HUD. |
| `bottom` | int | `0` | Pixels reserved at the bottom. |
| `left` | int | `0` | Pixels reserved on the left. |
| `right` | int | `0` | Pixels reserved on the right. |
| `bg_color_index` | int | `-1` | Palette index to fill the HUD strip **once** at scene start, before `_hud_init`. `-1` = don't fill (HUD starts with whatever `cls()` left). `31` collapses to `-1`. |
| `overlay` | bool | `false` | See [Overlay mode](#overlay-mode) below. |

**Valid ranges:**
- `top`, `bottom` ∈ `[0, 61]` (i.e. `kSceneH/2 − 1`)
- `left`, `right` ∈ `[0, 81]` (i.e. `kSceneW/2 − 1`)
- `top + bottom ≤ kSceneH − 8` and `left + right ≤ kSceneW − 8` (at least 8 px of usable camera)

The firmware clamps values to these ranges; TurtleStudio validates on save.

**Per-scene:** each scene has its own `hud_border`. A menu scene can have no HUD, a gameplay scene can have a top strip, a boss fight can have a wide border.

Absent or `null` fields default to `0` — no change in behavior for existing exported carts.

---

## Playfield

With `T=top, B=bottom, L=left, R=right`, the effective camera playfield is:

```
playfield_w = kSceneW − L − R     (kSceneW = 164)
playfield_h = kSceneH − T − B     (kSceneH = 124)

Playfield top-left in framebuffer: (L, T)
```

The world is sized against the playfield, not the full viewport:

```
world_w = playfield_w × world_steps_x
world_h = playfield_h × world_steps_y
```

Example: `hud_border.top = 16`, `world_steps_y = 1` → world is `164 × 108`. The scene floor (`y = 0`) anchors to the bottom edge of the playfield.

The HUD region is the complement of the playfield: any pixel with `x < L`, `x ≥ kSceneW − R`, `y < T`, or `y ≥ kSceneH − B`. It can be a top strip, an L-shape, a U-shape, or a full frame depending on which edges are non-zero.

:::note
`W` and `H` in Lua remain `164` and `124` (full framebuffer dimensions). They are not reduced per scene.
:::

### Tile grid

The tile grid is always authored against the canonical viewport (`kSceneW × kSceneH × steps`), regardless of `hud_border`. Tile cells whose scene-Y range falls outside the effective world are clipped pixel-by-pixel at draw time; their visible portion still draws normally. TurtleStudio and firmware agree on the row/column count.

### Camera, collision, and Lua coordinates

Follow/clamp, `margin_x/y`, `move()`, `posx()`/`posy()`, and sprite clip all operate against the effective world (`playfield × steps`). Actors cannot be positioned outside the effective world — they are clamped. Scene coordinates are unchanged: `(0, 0)` = bottom-left of the effective world, Y upward.

`spix(sx, sy, c)` in the ENTRY VM works in scene coordinates against the playfield (`sx` in `[0, playfield_w)`, `sy` in `[0, playfield_h)`). Out-of-playfield writes are no-ops.

---

## Overlay mode

When `overlay: true`:

- The world keeps its **canonical full size** (`kSceneW × world_steps_x`, `kSceneH × world_steps_y`) instead of shrinking to the playfield.
- The camera clamps against the full framebuffer rather than the playfield, so it does not auto-scroll to reveal an actor who walks into the HUD strip.
- An actor positioned in rows above `playfield_h` (e.g. jumping above the top HUD strip) has its sprite **invisibly clipped** by the playfield clip on scene blits — the actor disappears behind the HUD strip without the view scrolling, Metroid-style.
- The HUD, painted after actors, is unaffected.

`overlay: false` (the default) preserves the prior behavior: the world equals the playfield, and actors bounce against the inner playfield boundary.

---

## Lua API — ENTRY VM

The ENTRY VM stays **alive for the entire cart execution** (it is not destroyed after the boot script finishes). It owns the HUD; actor scripts have no access to `hud_*` bindings.

### Drawing functions

All coordinates are **framebuffer-space** — `(0, 0)` = top-left, Y downward. Any pixel that falls **inside the current playfield is a no-op** — this prevents accidentally painting over the game area.

| Function | Description |
|----------|-------------|
| `hud_pix(x, y, color_index)` | Draw one pixel in the HUD region. |
| `hud_rect(x, y, w, h, color_index)` | Fill a solid rectangle in the HUD region. |
| `hud_clear([color_index])` | Fill the **entire HUD region** with `color_index` (default `0`). |
| `hud_text(x, y, str, font_id [, color_index])` | Draw `str` using `font_id`. Same color-tint semantics as `text` in ENTRY. Returns width drawn in pixels. |
| `hud_text_width(str, font_id)` | Measure text width without drawing. |

Fonts resolve from the bundle's `.tfn` assets — the same font file works for both HUD and game text.

There is no `hud_sprite` in v0. Sprite-heavy HUDs (animated icons, portrait frames) belong in [GUI layers](./gui-layers).

### Lifecycle hooks

Both hooks are **optional**. If undefined, the cart pays zero HUD cost for them.

**`function _hud_init()`**

Called once when the scene starts, after static background/tiles/text labels are drawn and **before** the static snapshot is taken. Output becomes part of the static snapshot — it survives the actor dirty-rect mechanism with no per-frame repaint cost on fixed-camera scenes.

**`function _hud(dt)`**

Called once per frame, **after** `draw_all_actors` and **before** `flip()`. `dt` is seconds (same as actors). Use for animated HUDs: blinking text, live counters, health bars.

:::warning
Do not call `cls()`, `flip()`, or any scene-drawing function inside `_hud`. Only `hud_*` functions are safe here.
:::

Inside both hooks, all standard ENTRY globals are available: `btn`, `btnp`, `text`, `text_width`, `print`, `W`, `H`, `COLORS`, `gui_layer_*`, etc.

---

## Interaction with the static snapshot

**Fixed camera (no scroll):** the firmware uses `snapshot_static` + `restore_static_dirty`. `_hud_init` runs before the snapshot, so the HUD is baked into the static layer. Subsequent `hud_*` calls (in `_hud`) update both the live framebuffer and the static layer (`s_static_fb`) and mark those cells dirty — so `restore_static_dirty` never reverts the HUD state on the next frame.

**Scrolling camera:** the firmware repaints the scene every frame (`paint_scene_static_layers` + full flip). `_hud_init` runs after the first repaint. The HUD persists as long as Lua doesn't overwrite it — background/tile and actor blits never touch the HUD strip. Carts typically define `_hud(dt)` to animate and leave `_hud_init` for initial decoration.

---

## Per-frame compositing order

1. `paint_scene_static_layers` — background + tiles + scene text labels → **playfield only**
2. `draw_all_actors` — sprites → **playfield only**
3. **`_hud(dt)`** — HUD strip updates
4. GUI layers (method 2), sorted by `z`
5. `flip()` — display

---

## TurtleStudio authoring

- Scene editor exposes `top`, `bottom`, `left`, `right` as numeric inputs in the same camera group as `mode` and `margin_x/y`.
- Canvas preview draws a **semi-transparent overlay** over the HUD strips so authors see exactly what the playfield looks like.
- The Play simulator (`play_runtime.py`) applies the same clip and offset as the firmware — behavior in the editor matches hardware.
- Migration: existing scenes without `hud_border` behave as before (`{0,0,0,0}`). The field is omitted from the JSON when all values are zero to keep diffs clean.

---

## Common problems

| Symptom | Likely cause |
|---------|-------------|
| HUD visible for one frame then gone | Scene uses `follow` camera with scroll — no static snapshot. Repaint the HUD in `_hud` each frame, or call `_hud_init` logic from `_hud` once with a guard flag. |
| HUD flickers between old and new values | Only the changed part is updated but not cleared first — call `hud_rect` to erase the region before repainting it. |
| Player sprite clipped at the top of the playfield | Confusion between framebuffer-Y (down) and scene-Y (up). `hud_border.top` reserves rows at the **framebuffer top**, which lowers the maximum scene-Y actors can reach. The actor is still fully visible inside the playfield. |
| Previous scene's HUD persists after scene change | This shouldn't happen — `turtle_gpu_cls` in `turtle_scene_begin_runtime` clears the entire framebuffer including the HUD strip. Repaint in `_hud_init` of the new scene if you want the same HUD to continue. |

---

## Out of scope in v0

- `hud_sprite(x, y, sprite_id, frame)` — sprite blits in the HUD strip (planned for v1; use `hud_rect` + symbol fonts in the meantime)
- Alpha / blending in the HUD region (index 31 = transparent, same as everywhere else)
- Multiple simultaneous palettes (HUD shares the scene's single active palette)
- GUI layer method 2 interaction beyond covering the HUD strip — see [GUI Layers](./gui-layers)
