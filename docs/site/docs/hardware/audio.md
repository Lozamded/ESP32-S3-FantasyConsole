---
id: audio
sidebar_position: 1
title: Audio (M0 Bringup)
---

# Audio — M0 Hardware Bringup

This page covers the M0 (initial) hardware bring-up for audio on the ESP32-S3 target. It documents the signal chain, component selection, and verification sketch. Full Lua API integration is out of scope for M0.

---

## Signal chain

```
ESP32-S3 GPIO14
    │
    ├─── 1 kΩ resistor ───┬─── PAM8403 IN+
    │                     │
    │                  100 nF cap
    │                     │
    └─────────────────────┴─── GND
                              PAM8403 OUT → 8 Ω speaker
```

| Component | Value / Part | Notes |
|-----------|-------------|-------|
| RC filter resistor | 1 kΩ | Between GPIO and cap |
| RC filter cap | 100 nF | To GND; sets cutoff ~1.6 kHz |
| Amplifier | PAM8403 | Filterless class-D, 3 W per channel @ 4 Ω |
| Speaker | 8 Ω | Typical small panel speaker |
| Mute pin | GPIO42 (optional) | Active-low; tie HIGH to enable always |

The RC low-pass filter (fc ≈ 1/(2π·R·C) = 1.6 kHz) attenuates PWM carrier harmonics before they reach the amplifier. Game audio typically sits below 4 kHz so this cutoff is acceptable for M0 bringup; a wider filter can be used once the full audio pipeline is defined.

---

## PWM generation

The firmware uses the ESP32-S3 **LEDC** peripheral (LED Control, repurposed as general PWM) to generate the audio signal on GPIO14.

| Parameter | Value |
|-----------|-------|
| GPIO | 14 |
| LEDC channel | 0 |
| Timer | LEDC_TIMER_0 |
| Resolution | 8-bit (256 duty levels) |
| Carrier frequency | Configurable; audio-range sample rate |
| Mute GPIO | 42 (active-low, optional) |

---

## Bringup sketch

`firmware/TurtleReader/AudioBringup.ino` plays a sequence to verify the chain without needing a full cartridge:

1. **440 Hz tone** — concert A, ~1 second
2. **880 Hz tone** — one octave up, ~1 second
3. **C major scale** — C4, D4, E4, F4, G4, A4, B4, C5, ~300 ms each
4. **100 Hz → 4 kHz sweep** — linear frequency sweep over ~3 seconds

If all four steps produce audible sound without distortion the signal chain is verified.

### Running the sketch

```bash
# Open in Arduino IDE — same board settings as TurtleReader.ino
# Board: ESP32S3 Dev Module
# PSRAM: OPI PSRAM → Enabled
# Serial: 115200
```

Flash and open the serial monitor. Expected output:

```
AudioBringup: starting
Playing 440 Hz...
Playing 880 Hz...
Playing C major scale...
Sweeping 100 Hz → 4000 Hz...
AudioBringup: done
```

---

## Troubleshooting

| Symptom | Likely cause |
|---------|-------------|
| No sound, amplifier powered | GPIO14 not generating PWM — check LEDC init |
| Loud buzz, no tone | RC filter missing or wrong value |
| Distortion at all volumes | PAM8403 supply voltage too low (needs 2.5–5 V) |
| Sound only on one channel | Single-ended wiring — PAM8403 expects differential input for stereo; wire mono to IN+ with IN− to ground |
| Mute pin has no effect | GPIO42 left floating; pull down or tie to GND explicitly |

---

## Out of scope in M0

- Lua `sfx()` / `music()` API bindings
- Wavetable or sample playback
- Stereo output (M0 is mono)
- Volume control from Lua
- Audio mixing with background music
