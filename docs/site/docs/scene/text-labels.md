---
id: text-labels
sidebar_position: 2
title: Scene Text Labels
---

# Scene Text Labels (v0)

Scene text labels are static text strings baked directly into the scene JSON and drawn automatically by the firmware — no Lua code required. Use them for level names, tutorial hints, fixed UI text, or any string that doesn't need to change at runtime.

---

## Bundle format

`text_labels` is an array inside the scene object. Maximum **16 labels** per scene.

```json
{
  "id": "level_1",
  "text_labels": [
    {
      "id": "title",
      "text": "World 1-1",
      "x": 10,
      "y": 110,
      "font": "font8",
      "color_index": -1
    },
    {
      "id": "hint",
      "text": "Jump over gaps!",
      "x": 10,
      "y": 4,
      "font": "font8",
      "color_index": 5,
      "blink_ms": 800
    }
  ]
}
```

### Label fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | string | required | Unique identifier within this scene. Max 32 chars. |
| `text` | string | `""` | The string to draw. Max 63 chars. |
| `x` | int | `0` | Scene X coordinate of the left edge of the first glyph. |
| `y` | int | `0` | Scene Y coordinate of the **bottom** of the first glyph (scene space: origin bottom-left, Y upward). |
| `font` | string | required | Stem of a `.tfn` font asset in the bundle. Label is silently skipped if the font is missing. |
| `color_index` | int | `-1` | `-1` = use each glyph's own palette colors. `0..30` = flat tint applied to every non-transparent pixel in every glyph. Index 31 is transparent and has no effect as a tint. |
| `blink_ms` | int | `0` | Blink period in milliseconds. `0` = no blink (always visible). See [Blinking labels](#blinking-labels) below. |

**Supported charset:** space, `A–Z`, `a–z`, `0–9`, and `. , ! ? : ; ' -`. Characters outside this set are silently skipped (the character occupies no width).

---

## Coordinate system

`(x, y)` is in **scene space**: origin at the bottom-left of the effective playfield, Y increasing upward. The firmware converts to framebuffer coordinates internally.

```
scene (x=10, y=110) with hud_border.top=16, kSceneH=124:
  framebuffer_y = (kSceneH - 1) - y = 123 - 110 = 13
  framebuffer coords: (10 + L, 13 + T)
```

---

## Rendering

Labels are part of the scene's **static layer** — drawn by `paint_scene_static_layers` alongside the background and tile layer.

**Fixed camera (no scroll):**
Non-blinking labels are baked into `snapshot_static` during scene start. They cost zero per-frame repaint — the dirty-rect system preserves them automatically. Blinking labels are excluded from the snapshot and updated each frame using the dirty-rect system.

**Scrolling camera:**
All labels are repainted every frame as part of the full scene repaint. Blink timing works the same way.

Labels are drawn **before** actors, so actors always composite on top of text.

---

## Blinking labels

Setting `blink_ms` to a non-zero value makes the label blink symmetrically: the label is **visible** for `blink_ms / 2` ms, then **invisible** for `blink_ms / 2` ms, starting visible when the scene loads.

```json
{ "id": "press_start", "text": "Press Start", "blink_ms": 1000, ... }
```

- The blink timer is reset on scene load.
- Blink state is independent per label — two labels with the same `blink_ms` may drift out of phase if the scene was entered at different times.
- TurtleStudio caps `blink_ms` at **60000** (1 minute) on save.
- `blink_ms: 0` means always visible (default, no blink behavior, no timer overhead).

Blinking labels are **never** included in `snapshot_static`. On fixed-camera scenes they use the dirty-rect mechanism: only the cells they occupy are dirtied and restored each frame they change state.

:::tip
Blinking text is commonly used for "Press Start" title screens and countdown prompts. Keep blink periods at 500ms–1000ms for readability — faster than 200ms is generally unreadable on the small display.
:::

---

## Interaction with actors

Labels are part of the background layer — they do not interact with the physics or collision system. An actor can walk in front of a label (the actor sprite composites on top). There is no API to hide or update a label at runtime in v0; use [GUI layers](../gui/gui-layers) for dynamic text.

---

## TurtleStudio

- The scene editor shows text labels as overlays on the canvas at their scene coordinates.
- Font, color, and blink period are editable inline.
- Preview mode blinks labels at the configured period.

---

## Out of scope in v0

- Runtime mutation (`set_text`, `hide_label`) — use GUI layer `text_labels` for runtime-updatable text
- Scroll/marquee animation
- Per-character color
- Fonts larger than the canvas height
