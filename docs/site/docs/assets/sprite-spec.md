---
id: sprite-spec
sidebar_position: 2
title: Sprite Spec
---

# Sprite Spec (v0)

Sprites in TurtleStudio are JSON assets stored in `objects/Sprites/<id>.json`. They define pixel art with optional multiple frames, a palette reference, an anchor origin, and a collision shape when attached to an object.

---

## Size: cells and pixels

| Field | Meaning |
|-------|---------|
| `cell_px` | Side of one design cell in pixels (integer `8..256`, multiple of 8). **Default: 8**. |
| `blocks_w`, `blocks_h` | Sprite size in cells (`1..32` per axis). |
| `pixel_w`, `pixel_h` | Size in pixels: `blocks_w × cell_px`, `blocks_h × cell_px`. |

The firmware always draws using `pixel_w × pixel_h`. `cell_px` is purely a grid/editor convention — two sprites can use different `cell_px` values. Sprites with legacy `cell_px: 4` remain valid; the editor only rewrites it when you explicitly use Resize.

The 8 px cell default matches the Game Boy / Game Gear VRAM tile convention.

---

## Sprite JSON format

```json
{
  "format_version": 1,
  "kind": "turtlestudio.sprite",
  "id": "hero",
  "notes": "",
  "palette": "palettes/palette.txt",
  "cell_px": 8,
  "blocks_w": 2,
  "blocks_h": 3,
  "pixel_w": 16,
  "pixel_h": 24,
  "origin_x": 8,
  "origin_y": 0,
  "render": { "mode": "indexed_pixels" },
  "image": {
    "format": "palette_rows",
    "rows": [
      [31, 31, 0, 1, 0, 31, 31, 31, 0, 31, 31, 31, 0, 1, 0, 31],
      ...
    ]
  },
  "frame_count": 3,
  "frames": [
    { "image": { "format": "palette_rows", "rows": [...] } },
    { "image": { "format": "palette_rows", "rows": [...] } }
  ]
}
```

| Field | Description |
|-------|-------------|
| `palette` | Project-relative path to a `#RRGGBB`-per-line palette file. Pixel indices in `image.rows` refer to this palette. |
| `frame_count` | Total frame count, `1..32`. Default `1`. |
| `image` | Frame 0 pixel data (always present for firmware compatibility). |
| `frames` | Frames 1..N−1. Each entry is `{ "image": { "format": "palette_rows", "rows": [...] } }`. |

---

## Render modes

### `solid_palette_index`

A solid rectangle filled with a single palette index. No `image` data needed.

```json
"render": { "mode": "solid_palette_index", "palette_index": 4 },
"image": null
```

### `indexed_pixels` *(recommended)*

A 2D array of palette indices. Row `0` is the **top** of the sprite (same row-0-top convention as the editor).

```json
"render": { "mode": "indexed_pixels" },
"image": {
  "format": "palette_rows",
  "rows": [
    [31, 31, 0, 1],
    [31,  0, 2, 1]
  ]
}
```

- Each row has `pixel_w` integers in range `0..31`.
- Index **31** is always **transparent** — pixels with this index are not drawn. Use it for the sprite's "holes."
- Incomplete rows are padded by tools on normalize/save.

The export pipeline also accepts `"palette_rows_rle"` (runs of `[index, count]`) for compactness; the firmware understands both.

---

## Origin (anchor point)

`origin_x` and `origin_y` define the sprite's **anchor** in sprite-local coordinates:
- `(0, 0)` = **bottom-left** corner of the `pixel_w × pixel_h` bounding box
- Y increases upward (same as scene space)
- Range: `0..pixel_w−1` for X, `0..pixel_h−1` for Y
- Default: `(0, 0)` — bottom-left is the anchor

When a scene places an object at `(x, y)`, the anchor lands exactly at that point. The top-left corner of the bounding box is drawn at `(x − origin_x, y − origin_y)`.

```
origin_x=8, origin_y=0 on a 16×24 sprite:
  → anchor at the horizontal center, feet level
  → bbox drawn at (object_x − 8, object_y)
```

TurtleStudio shows the anchor as a magenta crosshair on the sprite canvas.

---

## Object JSON

Objects are the game entities placed in scenes. Each object references one or more sprites via `sprite_id` and `animations`.

```json
{
  "format_version": 1,
  "kind": "turtlestudio.object",
  "id": "character",
  "name": "character",
  "sprite_id": "character_idle",
  "script": "character",
  "animations": [
    { "name": "idle", "sprite_id": "character_idle" },
    { "name": "walk", "sprite_id": "character_walk" },
    { "name": "jump", "sprite_id": "character_jump" }
  ],
  "collision": {
    "mode": "aabb",
    "x0": -7, "y0": 0,
    "x1": 6,  "y1": 23
  }
}
```

| Field | Description |
|-------|-------------|
| `sprite_id` | Default sprite (rest pose, scene placement). |
| `script` | Stem of `scripts/<stem>.lua` — the actor Lua script. Optional. |
| `animations` | List of `{ "name", "sprite_id" }`. Names must start with a letter, then letters/digits/`_`/`-`, max 32 chars. Max 32 animations per object. |
| `collision` | Collision shape in anchor-local space (see below). Optional. |

### Collision shapes

Coordinates are **local to the anchor** (`(0, 0)` = origin of the sprite in scene space, Y up).

**AABB (rectangle):**

```json
"collision": {
  "mode": "aabb",
  "x0": -7, "y0": 0,
  "x1": 6,  "y1": 23
}
```

`x0, y0` = bottom-left corner (inclusive); `x1, y1` = top-right corner.

**Triangle:**

```json
"collision": {
  "mode": "triangle",
  "points": [[-7, 0], [6, 0], [0, 23]]
}
```

3 vertices `[x, y]`.

**Hexagon:**

```json
"collision": {
  "mode": "hexagon",
  "points": [[-4,0],[-7,10],[−4,20],[4,20],[7,10],[4,0]]
}
```

6 vertices (clockwise or counter-clockwise).

:::note
The firmware approximates `triangle` and `hexagon` as AABB (bounding box of their vertices). TurtleStudio uses the actual shape for its editor preview; only the AABB is used for collision at runtime.
:::

If `collision` is absent, the firmware falls back to the sprite's bounding box from `origin`.

---

## Project bundle (`studio/project_bundle.json`)

When TurtleStudio exports `main.turtlecart`, it writes (or references) sprite data in the bundle:

| Field | Description |
|-------|-------------|
| `transparent_index` | Always `31`. |
| `target_fps` | Game loop FPS (default `30`, range `15–60`). Per-project default; each scene can override. |
| `default_anim_fps` | Sprite animation FPS at `speed=1` (default `8`, range `1–30`). Per-project default; each scene can override. |
| `sprites` | Map of `id` → inline sprite JSON **or** `{ "kind": "turtlestudio.sprite_ref", "file": "sprites/<id>.json" }` |
| `objects` | Map of `id` → inline object JSON **or** `{ "kind": "turtlestudio.object_ref", "file": "objects/<id>.json" }` |

All sprites referenced by default `sprite_id` and `animations` are embedded in the bundle at export time.

---

## Firmware draw sequence (boot)

If `studio/project_bundle.json` exists and `INITIAL_SCENE` matches a scene in the bundle, the firmware draws the scene **before** running the ENTRY Lua:

1. `cls(background_index)` — fill with the scene's background palette index
2. Draw the background asset at scene origin `(0, 0)` (if the scene declares one)
3. For each object in the scene's `objects[]`: resolve `sprite_id`, draw at `(x − origin_x, y − origin_y)`

### Draw modes

| Mode | Firmware behavior |
|------|------------------|
| `solid_palette_index` | `fill_rect` with `render.palette_index` |
| `indexed_pixels` | Blit `image.rows`; skip pixels where index = `transparent_index` (31) |

### Size resolution

The firmware prefers explicit `pixel_w`/`pixel_h`. If absent, it computes `blocks_w × cell_px` using `cell_px` from the JSON, or `kDefaultCellPx = 8` if that's also missing.

**Firmware limits:** sprite up to **128×128 px** in static RAM; background indexed image up to **164×124 px** (full scene); palette indices clamped to `0..31`.

---

## TurtleStudio sprite editor

- **Palette:** click an index to select it as the paint brush. Index 31 cannot be selected as a brush.
- **Right-click / right-drag:** erases (writes index 31).
- **Clear all:** fills the entire canvas with index 31.
- **Colors used:** row of indices currently present in the canvas; click to re-select.
- **Swap color:** replace all pixels of one index with another.
- **Frames:** `frame_count` field + F0, F1, … tabs above the canvas. Each tab edits a separate pixel matrix. Save writes all frames to JSON.
- **Reference image:** import a PNG/JPG scaled to `pixel_w × pixel_h`. Visible under the paint layer; **Convert to sprite** maps each pixel to the nearest palette index (alpha < 0.5 → index 31). Reference is not saved in the JSON.
- **Resize:** rewrites `cell_px` (must be a multiple of 8). Pixels outside the new bounds are kept in memory until save.
- **Canvas background:** preview-only color for transparent pixels; not part of the palette.

---

## Compatibility notes

| Case | Behavior |
|------|---------|
| `cell_px: 4` or other non-multiple of 8 | Valid; editor only rewrites it on explicit Resize. Runtime always uses `pixel_w`/`pixel_h`. |
| `solid_palette_index` sprites | Still work on hardware; saved as `indexed_pixels` after any edit. |
| Scene palette ≠ sprite palette | Allowed in data. The firmware uses the cart-level `PALETTE:` for all index→RGB lookups. Aligning palettes is the author's responsibility. |

---

## Implementation references

| File | Role |
|------|------|
| `tools/turtlestudio/src/turtlestudio/sprites.py` | Sprite serialization, `DEFAULT_CELL_PX`, editor constants |
| `tools/turtlestudio/src/turtlestudio/build.py` | Bundle export |
| `firmware/TurtleReader/turtle_scene.cpp` | Scene draw, sprite resolution, `kDefaultCellPx` |
| `firmware/TurtleReader/turtle_gpu.cpp` | `turtle_gpu_blit_indexed_scene` — pixel blit with transparent-index skip |

---

## Out of scope in v0

- In-firmware sprite animation playback (multi-frame data is stored; playback via actor scripts using `set_anim`/`play_anim` — see [Animation](/lua/animation))
- Hardware rotation / flip
- Pixel data compression in the JSON format
- Full background layer compositing at boot (v0 draws a single background + objects)
