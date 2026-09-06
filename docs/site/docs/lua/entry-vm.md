---
id: entry-vm
sidebar_position: 2
title: ENTRY VM
---

# ENTRY VM (v0)

The ENTRY script is declared in the `ENTRY:` line of the cartridge (TurtleStudio convention: `scripts/global.lua`). The firmware executes it **once** during `setup()`, before the scene runtime starts.

## Constants

| Name | Value | Meaning |
|------|-------|---------|
| `W` | `164` | Logical framebuffer width |
| `H` | `124` | Logical framebuffer height |
| `COLORS` | `32` | Valid color indices `0..31` |

## Graphics API

Color indices are integers **`0..31`**. Out-of-range values are clamped (`< 0` → `0`, `>= 32` → `31`). No alpha in v0.

### `cls(color_index)`

Fills the entire framebuffer with the given palette index.

### `pix(x, y, color_index)`

Draws a pixel in **framebuffer (raster) coordinates**:
- `(0, 0)` = **top-left**
- Y increases **downward**
- `x` ∈ `0..W-1`, `y` ∈ `0..H-1`
- Out-of-range coordinates are silently ignored

Use `pix` for raw screen-space operations. For game content that must align with the scene and `move()`, use `spix`.

### `spix(sx, sy, color_index)`

Draws a pixel in **scene space** (same convention as object positions):
- `(0, 0)` = **bottom-left**
- Y increases **upward**
- `sx` ∈ `0..163`, `sy` ∈ `0..123`

Internal conversion: `yfb = (H − 1) − sy`, `xfb = sx`.

### `flip()`

Copies the framebuffer to the display (if `TURTLE_USE_DISPLAY` is enabled). No arguments.

:::warning
After ENTRY, the firmware calls `flip()` again when the scene runtime finishes drawing. Any content drawn in ENTRY will be **overwritten** by the scene — ENTRY drawing only persists for carts without a bundle/scene.
:::

## Input

Input state is available but `turtle_input_poll()` hasn't been called before ENTRY runs (it runs only in `loop()`). `btn`/`btnp` will typically read all-released. Don't rely on button state in ENTRY for gameplay.

| Function | Description |
|----------|-------------|
| `btn(i)` | `true` if button `i` is held |
| `btnp(i)` | `true` on the press edge |

`axis()` is not available in ENTRY (actor scripts only).

See [Input](/lua/input) for button index reference.

## Palette

If the cart includes a `PALETTE:` block, colors are applied **before** ENTRY runs. Indices in `cls`/`pix`/`spix` refer to that table, not raw RGB.

## Debug

### `print(...)`

Prints tab-separated arguments followed by a newline to **Serial** (115200 baud).

## Minimal example

```lua
-- scripts/global.lua embedded in main.turtlecart
print("TurtleReader boot")
cls(1)
flip()
```

With `INITIAL_SCENE:intro` and a bundle on the SD card, the `intro` scene overrides this drawing at step 6 of boot.

## Drawing in scene space

```lua
cls(0)
for sx = 10, 50 do
  spix(sx, 20, 7)  -- horizontal line at scene y=20
end
flip()
```

## Out of scope in v0

- Game loop in Lua (the VM is destroyed after the script ends)
- `move`, `posx`, `posy`, `axis`
- Scene changes or sprite control
- Audio, text rendering, tile tables
