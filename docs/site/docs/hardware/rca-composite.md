---
id: rca-composite
sidebar_position: 2
title: RCA Composite Driver (P4)
---

# RCA Composite Video Driver (v0)

This page covers the v0 design for the **ESP32-P4** composite video output driver. The P4 target outputs NTSC monochrome video over an RCA connector — no LCD, no SPI display. This is a separate firmware sketch (`TurtleReaderP4/`) and a distinct hardware platform from the ESP32-S3 TurtleReader.

:::note
The composite driver design has not yet been tested against real ESP32-P4 hardware as of v0. All timing and level values are derived from NTSC spec and the PARLIO+GDMA API documentation.
:::

---

## Architecture overview

```
ESP32-P4
  PARLIO TX peripheral  ←── DMA ring buffer (framebuffer lines)
        │
        ▼
  8-bit R-2R DAC  ──────►  RCA jack (composite out)
```

The **PARLIO TX** peripheral clocks out parallel data at a fixed rate. The output pins are wired to an **R-2R resistor ladder** (8-bit DAC) to produce the analog voltage levels required by composite video. A **GDMA ring** feeds the PARLIO TX with scanline data — each DMA entry contains the samples for one TV line.

---

## Signal parameters

| Parameter | Value |
|-----------|-------|
| Video standard | NTSC (first target) |
| Output | Monochrome (luminance only) |
| Clock | 5 MHz |
| Samples per line | 320 (64 µs / 200 ns) |
| Active video samples | 264 (matches canonical scene width) |
| Lines per frame | 262 |
| Frame rate | ~59.6 Hz |
| Sync tip | 0 V |
| Black level | ~0.3 V |
| White level | ~1.0 V |

Active video spans 264 samples per line — matching the engine's 264-wide framebuffer — leaving the remaining samples for blanking and sync.

### PAL support

`TURTLE_VIDEO_STD` is an enum in `turtle_gpu_p4.h`:

```cpp
enum TurtleVideoStd { TURTLE_VIDEO_NTSC, TURTLE_VIDEO_PAL };
```

PAL timing (312 lines, 50 Hz, 5.5 MHz clock) is reserved for v1. The driver architecture accommodates it without hardware changes.

---

## R-2R DAC wiring

8 ESP32-P4 PARLIO output pins are wired as an R-2R resistor ladder to produce the composite signal. Each bit position doubles the resistor value toward the MSB:

```
D7 (MSB) ─── R ─────┬──── composite out
D6       ─── R ─────┤
D5       ─── R ─────┤
D4       ─── R ─────┤
D3       ─── R ─────┤
D2       ─── R ─────┤
D1       ─── R ─────┤
D0 (LSB) ─── R ─────┤
                    │
GND ─── 2R ─────────┘ (one per bit)
```

Exact resistor values depend on the target voltage swing and output impedance required by the TV's 75 Ω input. Refer to `spec/rca-composite-driver-v0.md` for the full resistor table.

---

## DMA ring buffer

Each DMA descriptor covers one TV line (320 bytes). The ring contains:

- **Sync lines** (vertical blanking): samples set to sync tip (0x00)
- **Blanking + active** lines: left blanking, active video region (264 bytes from framebuffer row), right blanking
- **Sync pulse** embedded at the start of each line for horizontal sync

The GDMA DMA-chain is set up as a linked list of descriptors that loops continuously. The CPU (or a background task) updates the framebuffer region of each descriptor's buffer for the next frame while the current frame is transmitting.

---

## Bringup stages

### Stage 1 — Sync only

Output sync pulses with flat black active area. A TV should lock and show a stable black screen.

```
PARLIO_TX + GDMA → fixed sync pattern → RCA out
Verify: TV shows black, stable sync lock
```

### Stage 2 — Solid gray

Set all active video samples to a mid-gray value (e.g. 0x7F). TV shows stable gray field.

```
Verify: uniform gray, no tearing, correct aspect ratio
```

### Stage 3 — Framebuffer output

Wire the framebuffer scanlines into the DMA ring. Each active video line reads from `framebuffer[row]`. This stage maps the 264×198 scene to the TV scanlines.

:::note
Stage 3 is **not** in the v0 driver — framebuffer integration is planned for v1.
:::

---

## Bringup sketch

`firmware/TurtleReaderP4/TurtleReaderP4_CompositeBringup.ino` runs Stage 1 and Stage 2 in sequence:

1. Init PARLIO TX at 5 MHz, 8-bit parallel
2. Allocate DMA ring in PSRAM (262 descriptors × 320 bytes)
3. Fill ring with NTSC sync pattern
4. Start DMA → TV should lock
5. After 3 seconds, fill active area with gray
6. Report sync status to Serial

Expected Serial output:

```
P4 composite bringup
PARLIO TX init OK
GDMA ring alloc OK (83840 bytes)
Stage 1: sync only — check TV for lock
Stage 2: gray field
Bringup complete
```

---

## Shared cartridge format

The ESP32-P4 target uses the same `.turtlecart` format and `GFX_TIER` compile-time constant as the ESP32-S3 target:

| `GFX_TIER` | Target | Display |
|------------|--------|---------|
| `0` | ESP32-S3 | ILI9488 SPI LCD |
| `1` | ESP32-P4 | NTSC composite RCA |

A cartridge must never *require* a tier to load — tiers only change rendering fidelity and performance ceiling. Game logic and Lua scripts are identical across tiers.

---

## Out of scope in v0

- PAL timing
- Color (chroma sub-carrier) — NTSC color requires a 3.58 MHz burst and QAM encoding; out of scope until monochrome is stable
- Framebuffer DMA integration (Stage 3)
- Audio over RCA (composite audio is a separate connector)
- Interlaced output (480i)
