---
id: gui-layers
sidebar_position: 1
title: GUI Layers
---

# GUI Layers (v0)

GUI layers are stackable overlays defined in the cart bundle and shown/hidden at runtime from Lua. They handle menus, dialogues, inventory screens, title cards, game-over screens, and non-modal popups — any transient UI that doesn't fit in the permanent HUD strip.

:::tip Relation to the HUD border
The HUD border strip is always visible during gameplay. GUI layers are transient and hidden when the game runs alone. A GUI layer **can** cover the HUD strip (e.g. a full-screen pause menu covers everything) — each layer decides its own rectangle. The two systems are independent.
:::

---

## Capabilities in v0

| Feature | Support |
|---------|---------|
| **Content** | Solid rectangles, text labels (`.tfn` font, optional palette tint), progress bars, pip bars, sprite icons |
| **Tiles** | Not in v0 |
| **Transparency** | `transparent_bg` skips the background fill; index 31 is transparent in glyphs and sprites |
| **Animation** | Not built-in — update text/values from Lua each frame |
| **Max visible simultaneously** | 8 layers |
| **Z-order** | `z` field (higher = drawn on top); ties resolved by manifest order |
| **Persistence** | Reset to hidden at every scene start; restored via `gui_layers_autoshow` or Lua calls |

---

## Bundle format

GUI layers live outside the `scenes` block — they form a global catalogue that any scene can reference by id.

```json
{
  "guilayers": [
    {
      "id": "pause_menu",
      "x": 0, "y": 0, "w": 164, "h": 124,
      "bg_color_index": 0,
      "transparent_bg": false,
      "pauses_scene": true,
      "captures_input": true,
      "z": 100,
      "rects": [...],
      "text_labels": [...],
      "progress_bars": [...],
      "pip_bars": [...],
      "sprites": [...]
    }
  ]
}
```

### Layer fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | string | required | Unique id in the catalogue. Start with a letter, then letters/digits/`_`/`-`, max 32 chars. |
| `x`, `y` | int | `0`, `0` | Top-left corner in **framebuffer coordinates** (Y down, `(0,0)` = top-left). |
| `w`, `h` | int | `164`, `124` | Size in pixels. Clamped to `[1, kSceneW]` / `[1, kSceneH]`. |
| `bg_color_index` | int | `0` | Palette index for the background fill. Ignored when `transparent_bg=true`. |
| `transparent_bg` | bool | `false` | Skip the background fill — the scene beneath shows through. |
| `pauses_scene` | bool | `false` | While any visible layer has this set, actor `_update(dt)` and `move()` are suspended. See [Pause](#pause). |
| `captures_input` | bool | `false` | While any visible layer has this set, `btn`/`btnp` return `false` in actor VMs. See [Input capture](#input-capture). |
| `z` | int | `0` | Paint order. Higher = drawn on top. |
| `rects` | array | `[]` | Solid filled rectangles. Max 16 per layer. |
| `text_labels` | array | `[]` | Text labels with font and optional color tint. Max 16 per layer. |
| `progress_bars` | array | `[]` | Fractional fill bars. Max 4 per layer. |
| `pip_bars` | array | `[]` | Discrete icon bars. Max 4 per layer. |
| `sprites` | array | `[]` | Static sprite icons. Max 4 per layer. |

---

## Content elements

### Rectangles (`rects`)

Solid filled rectangles inside the layer. Painted in array order (index 0 first, last index on top).

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `x`, `y` | int | `0` | Relative to the layer's `(x, y)`. Clamped to layer bounds. |
| `w`, `h` | int | `1` | Size in pixels. Clamped to remaining space from `(x, y)`. |
| `color_index` | int | `0` | Palette index. Index 31 is a no-op (transparent). |

### Text labels (`text_labels`)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | string | required | Identifier within this layer, used by `gui_layer_set_text`. Max 32 chars. |
| `x`, `y` | int | `0`, `0` | Relative to the layer's `(x, y)`. Top-left of the first glyph (Y down). |
| `font` | string | required | Stem of a `.tfn` font in the bundle. If missing, the label is skipped with a Serial warning. |
| `text` | string | `""` | Initial content. Runtime buffer: 63 chars max (64 bytes including nul). |
| `color_index` | int | `-1` | `-1` = no tint (glyph's own palette colors). `0..30` = flat tint applied to every non-transparent glyph pixel. |

### Progress bars (`progress_bars`)

Fractional fill in one direction. Value is expressed as `value_num / value_den` (integers, no floats in firmware). The filled area is `round(fill_dim × fraction)` where `fill_dim` is `w` for horizontal directions or `h` for vertical.

Drawn **after** rects and **before** text labels (so text can overlay the bar as a visible value label).

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | string | required | Unique within this layer. Used by `gui_layer_set_progress`. |
| `x`, `y` | int | `0`, `0` | Relative to the layer's `(x, y)`. |
| `w`, `h` | int | `1`, `1` | Bar rectangle size in pixels. |
| `direction` | string | `left_to_right` | One of: `left_to_right`, `right_to_left`, `top_to_bottom`, `bottom_to_top`. |
| `fill_mode` | string | `color` | `color` (solid fill) or `sprite` (tiled sprite fill). |
| `fill_color_index` | int | `11` | Palette index for the fill when `fill_mode="color"`. Index 31 = no-op. |
| `fill_sprite_id` | string | `""` | Sprite stem when `fill_mode="sprite"`. Tiled across the filled area; partial tiles are clipped. Index 31 pixels are transparent. |
| `bg_color_index` | int | `3` | Palette index for the empty part of the bar. Use `31` to let the scene beneath show through. |
| `border_color_index` | int | `-1` | `-1` = no border. `0..30` = 1 px outline around the full bar rectangle. |
| `value_num` | int | `0` | Numerator of the current value. Range `[-32768, 32767]`. |
| `value_den` | int | `1` | Denominator (maximum). Range `[1, 32767]`. Zero or negative collapses to `1`. |
| `ranges` | array | `[]` | Value-range color/sprite overrides. Max 3 per bar. See [Value ranges](#value-ranges). |

### Pip bars (`pip_bars`)

N discrete icons showing an integer value — HP hearts, keys, medals. Each "on" pip (index `< value`) blits `sprite_full_id`. "Off" pips are **not drawn** (the background shows through), so you can place a static sprite or rect in `rects` to render the empty-pip look.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | string | required | Unique within this layer. Used by `gui_layer_set_pips`. |
| `x`, `y` | int | `0`, `0` | Relative to the layer's `(x, y)`. Top-left of the first pip. |
| `sprite_full_id` | string | required | Sprite stem for the "on" state. Its pixel dimensions set the pip width/height. Index 31 = transparent. |
| `direction` | string | `horizontal` | `horizontal` (pips grow toward +x) or `vertical` (toward +y). |
| `gap_px` | int | `0` | Spacing between consecutive pips. Range `[0, 32]`. |
| `value` | int | `0` | Number of "on" pips to draw. Clamped to `[0, max_value]`. |
| `max_value` | int | `1` | Total pip count. Range `[1, 32]`. |
| `ranges` | array | `[]` | Value-range sprite overrides. Max 3 per bar. See [Value ranges](#value-ranges). |

### Sprite icons (`sprites`)

A 1:1 blit of a single sprite at a fixed position. Intended for HUD iconography — a gear icon next to a counter, a player face next to the lives display, a status icon next to a timer. The layer does not animate the sprite; Lua can rotate frames via `gui_layer_set_sprite`.

Drawn **after** pip bars and **before** text labels.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | string | required | Unique within this layer. Used by `gui_layer_set_sprite`. |
| `x`, `y` | int | `0`, `0` | Relative to the layer's `(x, y)`. Top-left of the blit. |
| `sprite_id` | string | required | Sprite stem in the bundle. |
| `frame_index` | int | `0` | Which frame of a multi-frame sprite to draw. |
| `flip_h` | bool | `false` | Horizontal mirror at blit time. |
| `flip_v` | bool | `false` | Vertical mirror at blit time. |

---

## Value ranges (`ranges`)

Both progress bars and pip bars accept a `ranges` array (max 3 entries) that **overrides** the base color or sprite when the current value fraction falls inside `[min_pct, max_pct)`. Classic pattern: green above 50%, yellow 25–50%, red below 25%.

```json
"ranges": [
  { "min_pct": 0,  "max_pct": 25, "alt_color_index": 8 },
  { "min_pct": 25, "max_pct": 50, "alt_color_index": 9 }
]
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `min_pct` | int | `0` | Inclusive lower bound. Range `[0, 100]`. |
| `max_pct` | int | `100` | Exclusive upper bound (inclusive when `max_pct=100`, so 100% is never orphaned). |
| `alt_color_index` | int | `-1` | Progress bars with `fill_mode="color"` only. `-1` = don't override. |
| `alt_sprite_id` | string | `""` | Progress with `fill_mode="sprite"`: replaces `fill_sprite_id`. Pip bar: replaces `sprite_full_id`. `""` = don't override. |

Ranges are evaluated in array order — the **first** match wins. If no range matches, the bar's base color/sprite is used. Ranges with `min_pct >= max_pct` are discarded at parse time.

---

## Lua API

All functions operate on the catalogue loaded from the current bundle. An unknown `id` or sub-id is a **silent no-op** (the cart can call without existence checks). The first failure per id is logged to Serial for debugging.

| Function | Description |
|----------|-------------|
| `gui_layer_show(id [, z])` | Mark the layer visible. Optional `z` overrides the manifest `z` for this show only. |
| `gui_layer_hide(id)` | Mark the layer hidden. No-op if already hidden. |
| `gui_layer_visible(id)` → bool | Query visibility. |
| `gui_layer_set_text(id, label_id, str)` | Update a text label. Truncated to 63 chars. Persists until next call. |
| `gui_layer_set_progress(id, bar_id, num [, den])` | Update `value_num` of a progress bar. Optional `den` also replaces `value_den` (useful when the maximum changes at runtime, e.g. a level-up raises max HP). |
| `gui_layer_set_pips(id, bar_id, val [, max])` | Update `value` of a pip bar. Optional `max` replaces `max_value`. `val` is clamped to `[0, max_value]` after the update. |
| `gui_layer_set_sprite(id, icon_id, sprite_id [, frame])` | Replace the `sprite_id` (and optionally `frame_index`) of a sprite icon. Useful for dynamic iconography (key present/absent, player face by state). |
| `gui_layer_hide_all()` | Hide all currently visible layers. Useful for transitions and state changes. |

---

## Auto-show per scene

Each scene can declare a `gui_layers_autoshow` array of layer ids to show automatically when the scene starts — without any Lua code. Intended for persistent level HUDs (score, lives, radar). Modal layers like pause menus or dialogues should still be Lua-triggered and should **not** appear here.

```json
{
  "id": "level_1",
  "gui_layers_autoshow": ["hud_score", "hud_lives"],
  ...
}
```

- Applied **after** the scene visibility reset and **before** the first `_hud(dt)` tick.
- Equivalent to calling `gui_layer_show(id)` without a `z` override.
- The cart can call `gui_layer_hide(id)` at any time to hide an auto-shown layer (e.g. hide the HUD during a cutscene).
- Unknown ids: no-op with a Serial warning. Duplicate ids: silently ignored.
- Scenes without this field default to `[]` (no auto-shown layers).

In TurtleStudio, the scene editor shows a checkbox per layer in the `guilayers` catalogue; checking it adds the id to `gui_layers_autoshow`.

---

## Pause

When any visible layer has `pauses_scene: true`, on the next tick:

- Actor `_update(dt)` calls are **skipped**.
- Actor sprite animation **continues** (frames still advance). To fully freeze a sprite, call `play_anim(..., speed=0)` before showing the layer.
- `move()` does not run (nothing calls it without `_update`).
- Scene text label blinking continues.
- `_hud(dt)` in the ENTRY VM **continues** — so the cart can navigate the menu and update the HUD.

---

## Input capture

When any visible layer has `captures_input: true`:

- `btn(k)` / `btnp(k)` return `false` for all buttons in **actor VMs** — actors see no input.
- The **ENTRY VM** still receives normal `btn`/`btnp` — `_hud(dt)` can navigate the menu.

Set `captures_input: false` (the default) for non-blocking popups like "Achievement unlocked!" where the player should keep moving.

---

## Compositing order (per frame)

1. `paint_scene_static_layers` — world background + tiles + scene text labels → playfield
2. `draw_all_actors` — sprites inside the playfield
3. `_hud(dt)` — HUD strip (method 1)
4. **GUI layers**, sorted by `z` ascending
5. `flip()` — send framebuffer to display

GUI layers use `turtle_gpu_pixel_raw` internally, which bypasses the playfield write guard that protects the game area from HUD bindings. This is what allows a layer to cover the playfield with a pause menu.

---

## Common problems

| Symptom | Likely cause |
|---------|-------------|
| `gui_layer_show("pause")` shows nothing | The id doesn't match — typo, or the layer isn't in the bundle. Check Serial output at boot. |
| Layer appears for one frame then vanishes | Something else is calling `gui_layer_hide` or `hide_all` in the same tick. |
| HUD strip invisible under a layer | Expected — the layer covers it. Set `transparent_bg: true` to let the HUD show through. |
| Actor keeps moving with the pause menu up | The layer doesn't have `pauses_scene: true`. Update the manifest and re-export. |
| Popup freezes the player | The layer has `pauses_scene` or `captures_input` set to `true`. Set both to `false`. |
| `gui_layer_set_text` has no effect | `label_id` doesn't match any label in that layer. Check for typos. |

---

## Out of scope in v0

- Direct Lua sprite blits (`gui_layer_blit_sprite`) — sprite icons are declarative; the cart can swap sprite/frame via `gui_layer_set_sprite`
- Tile layers inside GUI layers (planned for v2)
- Built-in text blink or sprite animation — simulate from `_hud(dt)` with `gui_layer_set_text` / `gui_layer_set_sprite`
- Layer fade/transition effects
- Dynamic layout (center, padding) — all positions are fixed in the manifest
- Full-stop pause including sprite animation — call `play_anim(..., speed=0)` before showing the layer
