---
id: scene-format
sidebar_position: 1
title: Scene Format
---

# Scene Format (v0 / v1 / v2)

A scene defines the visual space where a game takes place: the coordinate system, camera, background layers, tile layers, and placed objects. Three incremental spec versions exist — each is **additive and backward-compatible** with `TURTLECART:0`; no field in any version is required.

---

## Coordinate system

The console uses **scene space** as the primary game coordinate convention:

| Property | Value |
|----------|-------|
| Viewport | **164 × 124** logical pixels |
| Origin (0, 0) | **Bottom-left** corner |
| X axis | Positive → right |
| Y axis | Positive → **up** (math convention) |
| Valid X | `0..163` |
| Valid Y | `0..123` |

The raw framebuffer is raster (Y down, row 0 = top). Conversion from scene to framebuffer coordinates:

```
xfb = sx
yfb = (H − 1) − sy    where H = 124
```

Use `spix(sx, sy, color)` in Lua for scene-space drawing. Use `pix(xfb, yfb, color)` only for raw framebuffer work.

**Transparency:** palette index **31** is always transparent. The runtime never copies pixels at index 31 when blitting sprites or backgrounds.

---

## World size

The world can be larger than the viewport. `world_steps_x` and `world_steps_y` (integers **1–8**) multiply the viewport dimensions:

- `world_steps_x: 8` → world width = **1312 px** (8 screens wide)
- Default: `1` on both axes → world = viewport (no scrolling)

### Resident window (how the firmware handles large worlds)

The firmware does **not** keep a pixel buffer for the entire world in RAM. Instead it maintains a **3×3-step resident window** (492×372 px, 183 024 bytes) centered on the camera. When the camera approaches the window edge, the firmware recenters and re-bakes the window — not every frame, approximately every ~164 px of scroll at normal game speed.

The tile grid (`uint8_t` per 16px cell) is kept fully resident for the entire world (≤~20 KB for 4 layers at 8×8 steps). Collision and `posx()`/`posy()` always operate against the full tile grid — the pixel window does not affect them.

:::note
Worlds of 1–2 steps fit entirely inside the 3-step window, so the initial bake is the only one needed for the life of the scene. The streaming mechanism is invisible for small scenes.
:::

---

## Camera

Configured in `scenes/<id>.json`, field `camera`:

| Field | Default | Description |
|-------|---------|-------------|
| `mode` | `"follow"` | `"follow"` or `"fixed"` |
| `target` | `""` | Id of object to follow. Falls back to `character`, then `player`, then the first object in `objects[]`. |
| `x`, `y` | — | Bottom-left corner of the viewport in scene space. Starting position for `follow`, fixed position for `fixed`. |
| `margin_x`, `margin_y` | — | Pixels from the viewport edge before the camera moves (`follow` only). |

---

## Background layers (`background_layers`)

A single array of **4 layers** controls all background imagery. **Layer 1** (index `0`) is special: its background image is baked together with tiles into the static world buffer once per scene. **Layers 2–4** (indices `1..3`) each live in their own buffer and are repainted every frame.

```json
"background_layers": [
  { "enabled": true,  "color_index": 1, "opacity": 255, "background": "sky_main" },
  { "enabled": true,  "color_index": 1, "opacity": 255, "background": "clouds_far",
    "parallax_x": 0.2, "repeat_x": true },
  { "enabled": true,  "color_index": 1, "opacity": 255, "background": "hills_mid",
    "parallax_x": 0.5, "repeat_x": true },
  { "enabled": false, "color_index": 1, "opacity": 255 }
]
```

| Field | Description |
|-------|-------------|
| `enabled` | Whether this layer is drawn |
| `background` | Id of a background asset (`backgrounds/<id>.tbg`). Empty = color-fill only. |
| `color_index` | Palette index for the `cls()` fill-color (used by TurtleStudio for preview; not mixed with the image in v0) |
| `opacity` | `0..255`. In v0, only `255` (opaque) and `0` (invisible) are distinct at runtime. v1 adds 4-level Bayer dither; v2 adds real alpha blend on capable hardware. |
| `parallax_x` | Horizontal scroll factor for layers 2–4 (`0.0..2.0`; `1.0` = same speed as camera). No effect on layer 1 — use `parallax_bands` instead. |
| `fixed` | `false` by default. If `true`, layer ignores camera entirely (offset always 0). |
| `repeat_x` | If `true`, the image wraps horizontally instead of clipping at its edge. Needed for slow-moving layers (`parallax_x < 1`) that would otherwise run out of source pixels. |

**Layer anchoring:** all layers are anchored at the world's bottom-left (`scene_y = 0`). Scene rows above the image's pixel height are not painted by that layer.

### Rendering cost (important)

- **Layer 1** — baked once into the static world buffer alongside tiles. Zero per-frame cost.
- **Layers 2–4** — each requires its own RAM buffer (`pixel_w × pixel_h` bytes in PSRAM) and a full repaint pass every frame.
- **Tile baking trade-off:** when any layer 2–4 is enabled, the firmware skips tile pre-baking and redraws tiles live every frame. The same applies when `parallax_bands` is present. This is an intentional architectural choice — decorative tiles in disabled-collision layers work correctly, but come with this CPU cost.

---

## Parallax bands (`parallax_bands`) — layer 1 only

`parallax_bands` divides the **layer 1** background into horizontal Y-ranges, each with its own independent scroll factor. Classic platformer parallax effect (clouds barely move, hills at medium speed, foreground at full speed).

```json
"parallax_bands": [
  { "y0": 88, "y1": 123, "parallax_x": 1.0 },
  { "y0": 44, "y1": 87,  "parallax_x": 0.5, "repeat_x": true },
  { "y0": 0,  "y1": 43,  "parallax_x": 0.15, "repeat_x": true }
]
```

| Field | Default | Description |
|-------|---------|-------------|
| `y0`, `y1` | — | Scene Y range (inclusive, Y up). Clamped to `[0, world_h−1]`; swapped if `y0 > y1`. |
| `parallax_x` | — | Horizontal scroll factor, `0.0..2.0`. `1.0` = camera speed. |
| `fixed` | `false` | Ignores camera; horizontal offset always 0. |
| `repeat_x` | `false` | Wraps source image column with `modulo image_width`. |

**Limit:** 8 bands per scene. Rows not in any active band use `parallax_x=1.0`, `fixed=false`, `repeat_x=false`.

:::caution
As soon as any `parallax_bands` entry is defined, the firmware disables tile baking for the whole scene (same CPU trade-off as enabling layers 2–4).
:::

---

## Tile layers (`tile_layers`)

Up to **4 tile layers** per scene. Each layer:

| Field | Description |
|-------|-------------|
| `enabled` | Whether the layer is drawn and its collision is evaluated |
| `tileset` | Stem of a tileset file (`tiles/<tileset>.tts`) |
| `cells` | Grid of tile indices. Empty cell = index **31** (transparent, no collision) |

**Collision layer:** only one tile layer blocks actors. Set with `collision_tile_layer` (integer `0–3`, default `0`) at the scene level. The other three layers are purely visual — their tiles' `collision` metadata is ignored by the firmware.

### Per-tile collision shapes

Defined in `tiles/<id>.json`, field `collision` per tile entry:

| Value | Meaning |
|-------|---------|
| omitted or `"solid"` | Full cell, solid (default) |
| `"none"` | Decoration — no blocking |
| `{ "mode": "aabb", "x0", "y0", "x1", "y1" }` | Axis-aligned box in tile-local space (origin bottom-left, Y up) |

Optional `oneway` (bool) + `oneway_direction` (`"up"` \| `"down"` \| `"left"` \| `"right"`) for one-way platforms. `triangle` and `hexagon` shapes are accepted in JSON but approximated as AABB by the firmware.

Tile size is a multiple of 8 px (default 8 px, same as Game Boy/Game Gear). TurtleStudio draws a tile grid overlay in the scene editor.

---

## Scene manifest fields (TurtleStudio)

Each scene in `turtlestudio.json` and `scenes/<id>.json`:

| Field | Description |
|-------|-------------|
| `id` | Unique scene identifier. **`main` is reserved** — do not use as a scene id. |
| `script` | Stem of `scripts/<stem>.lua` — the scene VM script (ticks before actors, no actor attached). |
| `palette` | Relative path to a palette file (`palettes/<name>.txt`). |
| `background_index` | Palette index for the `cls()` background fill (preview and runtime). |
| `world_steps_x` / `world_steps_y` | World size multiplier, `1..8`. |
| `camera` | Camera config object (see [Camera](#camera) above). |
| `background_layers` | Array of 4 layer configs (see above). |
| `parallax_bands` | Array of layer-1 parallax bands (see above). |
| `tile_layers` | Array of up to 4 tile layer configs. |
| `collision_tile_layer` | Index (0–3) of the tile layer that blocks actors. Default `0`. |
| `objects` | Array of placed object instances. Each has `object` (catalog id), `id` (instance id), `tags` (string array), `x`, `y` (scene-space). |
| `default_anim_fps` | Default animation frame rate for actors in this scene. |

The `active_scene` field in `turtlestudio.json` marks the scene shown in TurtleStudio for editing.

---

## v1 extensions — extended parallax

*(spec: `spec/scene-v1.md`)*  All fields are optional; absent fields reproduce v0 behavior exactly.

### Vertical parallax on layer-1 bands

Each `parallax_bands` entry gains:

| Field | Default | Description |
|-------|---------|-------------|
| `parallax_y` | `1.0` | Vertical scroll factor (`0.0..2.0`). `1.0` = follows camera Y at full speed. |
| `repeat_y` | `false` | Wraps source image row with `modulo image_height`. Needed when `parallax_y < 1`. |

`fixed: true` now suppresses both X and Y offsets (a fixed band is fixed on both axes).

### Per-band parallax on layers 2–4

Each layer 2–4 entry can declare its own `parallax_bands` array (same schema as the scene-level one, including the new `parallax_y`/`repeat_y` fields). If present and non-empty, it overrides the layer's uniform `parallax_x`/`fixed`/`repeat_x`.

```json
{ "enabled": true, "background": "hills_mid",
  "parallax_bands": [
    { "y0": 100, "y1": 123, "parallax_x": 0.6 },
    { "y0": 0,   "y1": 99,  "parallax_x": 0.4, "repeat_x": true }
  ]
}
```

Layer 1 (index 0) ignores an inline `parallax_bands` — it always uses the scene-level one.

### Vertical scroll / offset for layers 2–4

| Field | Default | Description |
|-------|---------|-------------|
| `parallax_y` | `1.0` | Vertical scroll factor for this layer |
| `repeat_y` | `false` | Wraps vertical sampling |
| `offset_y` | `0` | Fixed vertical offset in scene pixels, applied before `parallax_y`. Replaces the hard-coded bottom-left anchor of v0. |

### Layers in non-scrolling scenes

In v0, layers 2–4 were only rendered in scenes with scroll (`world_steps > 1`). v1 removes this restriction — an `enabled: true` layer renders in any scene. In a non-scrolling scene, offsets are computed with `cam_x = cam_y = 0`, producing a static overlay.

### Opacity (4-level Bayer dither)

v1 resolves `opacity` at runtime instead of ignoring non-255 values. The firmware maps `opacity` to 5 steps (`0`, `63`, `127`, `191`, `255`) and uses a Bayer 4×4 threshold pattern to paint only a fraction of pixels — classic indexed-palette pseudo-transparency, no framebuffer read required.

---

## v2 extensions — `GFX_TIER`

*(spec: `spec/scene-v2.md`)*  `GFX_TIER` is a **firmware compile-time constant** (`#define`), not a cartridge field.

| Tier | Hardware target | `opacity` rendering |
|------|----------------|---------------------|
| `0` | ESP32-S3 (current) | Bayer 4×4 dither (v1) |
| `1` | ESP32-P4 (planned) | Real alpha blend via PPA hardware |

### Compatibility rule

A cartridge authored for tier 1 must remain **fully playable** on tier 0 — with lower fidelity (dither instead of real blend) but never with broken collision, missing assets, or a scene that fails to load. Tier only affects visual fidelity and performance headroom, never game logic.

### `GFX_TIER` in Lua

The ENTRY VM exposes `GFX_TIER` as a read-only global integer (alongside `W`, `H`, `COLORS`):

```lua
if GFX_TIER >= 1 then
  -- enable a decorative effect that relies on real alpha blend
end
```

Use it only for optional visual enhancements — never to gate mechanics or content.

### `min_gfx_tier` field

A `background_layers` entry can declare `min_gfx_tier` (int, default `0`). If the running firmware's `GFX_TIER` is below this value, the layer is treated as `enabled: false` — a clean skip, not a failed load. No current feature requires `min_gfx_tier > 0`; the field is defined now so the cart format doesn't need to change when one appears.

### Quick-reference: new fields across all versions

| Version | Scope | Field | Type | Default |
|---------|-------|-------|------|---------|
| v1 | `parallax_bands[]` | `parallax_y` | float | `1.0` |
| v1 | `parallax_bands[]` | `repeat_y` | bool | `false` |
| v1 | `background_layers[]` (2–4) | `parallax_bands` | array | `[]` |
| v1 | `background_layers[]` (2–4) | `parallax_y` | float | `1.0` |
| v1 | `background_layers[]` (2–4) | `repeat_y` | bool | `false` |
| v1 | `background_layers[]` (2–4) | `offset_y` | int | `0` |
| v1 | `background_layers[]` (any) | `opacity` | u8 | `255` |
| v2 | ENTRY Lua global | `GFX_TIER` | int | `0` |
| v2 | `background_layers[]` (any) | `min_gfx_tier` | int | `0` |
| v2 | TurtleStudio manifest | `recommended_gfx_tier` | int | `0` |
