---
id: input
sidebar_position: 6
title: Input
---

# Input (v0)

## Button indices

12 buttons are supported in v0. Typical wiring: one side to a GPIO, other to GND. Firmware uses `INPUT_PULLUP` (released = HIGH, pressed = LOW).

| Index | Name | Common use |
|-------|------|------------|
| `0` | LEFT | Move left |
| `1` | RIGHT | Move right |
| `2` | UP | Move up / menu up |
| `3` | DOWN | Move down / menu down |
| `4` | A | Jump / confirm |
| `5` | B | Action 2 / cancel |
| `6` | C | Action 3 |
| `7` | D | Action 4 |
| `8` | START | Pause / confirm in menus |
| `9` | BACK | Go back / select |
| `10` | L | Left shoulder |
| `11` | R | Right shoulder |

In TurtleStudio's Play mode: arrows = D-pad, `Z/X/C/V` = A/B/C/D, `Enter` = START, `Backspace` = BACK, `A/S` = L/R.

## API

### `btn(i)` → bool

`true` if button `i` is currently **held down**.

### `btnp(i)` → bool

`true` only on the **frame it was first pressed** (rising edge). The firmware retains the edge until Lua reads it — so even at 30 FPS you won't miss a fast tap.

### `axis(neg, pos)` → int *(actor scripts only)*

Convenience helper: returns **-1** if `btn(neg)`, **+1** if `btn(pos)`, **0** otherwise.

```lua
local dx = axis(0, 1)  -- -1=left, 0=neutral, +1=right
local dy = axis(3, 2)  -- -1=down (scene Y down), +1=up
```

`axis` is not available in the ENTRY VM.

:::warning
An invalid button index (`< 0` or `> 11`) causes a **Lua error** (unlike color clamping which is silent).
:::

## Where input is available

| Context | Available |
|---------|-----------|
| ENTRY VM | `btn`, `btnp` — but `turtle_input_poll()` hasn't run yet; state is usually all-released |
| Actor scripts `_update(dt)` | `btn`, `btnp`, `axis` — polled every frame |
| Scene scripts `_update(dt)` | `btn`, `btnp`, `axis` — same as actor scripts |

## Pin configuration

Button GPIO pins are defined in `firmware/TurtleReader/turtle_input.h` (`TURTLE_BTN_PIN_*`). Set a pin to **-1** to disable that button. Defaults: D-pad 4–7, A–D 15–18, START/BACK 1/2, L/R 40/39. Avoid SD (19, 20, 21, 47), display (8–13), audio (14, 42), octal PSRAM (33–37), strapping pins (0, 3, 45, 46), UART0 (43/44) and the on-board RGB LED (IO38 on DevKitC-1 v1.1, IO48 on v1.0).
