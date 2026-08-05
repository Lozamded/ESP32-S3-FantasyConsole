# Host-side verification harnesses

Small host-buildable (g++, not the Arduino toolchain) programs that compile a
handful of the real `firmware/TurtleReader/*.cpp` files as-is and cross-check
them against the Python encoder/decoder in `tools/turtlestudio/`, the same way
`test_asset_bin.py` cross-checks the Python export path against its own
decoder mirror. These do **not** touch actual hardware — they only prove the
C++ decoding logic agrees byte-for-byte with what the export pipeline
produces, given the same input.

Not part of the Arduino sketch: `TurtleReader.ino` never includes anything
from this directory. `arduino_shim/` (minimal stand-ins for `Arduino.h`,
`SPI.h`, `SD.h` — just enough of `Serial`/`String`/`SD`/`File`/`delay`/`millis`
to type-check, never talks to real hardware) only ever gets picked up here
because `-I arduino_shim` is passed on the host g++ command line, ahead of
the real Arduino core.

## `run_font_test.sh` (Phase 1 — `.tfn` / `turtle_font.cpp`)

```
./run_font_test.sh [path/to/font.json]
```

Defaults to `tools/turtlestudio/exampleprojects/demo1/objects/Fonts/default.json`,
a real authored font asset. Steps:

1. `gen_font_fixture.py` calls the real `font_json_to_tfn()` to produce a `.tfn`
   fixture, and the real `decode_font_blob()` to produce the expected decoded
   dump.
2. Compiles `test_turtle_font.cpp` + the actual `turtle_font.cpp` +
   `turtle_asset_bin.cpp` from `firmware/TurtleReader/`, unmodified.
3. Runs it against the fixture, dumping glyph pixels/advances in the same text
   format.
4. Diffs the two dumps. Also sanity-checks `turtle_font_charset_index()`
   against hand-computed expected indices, since the charset has no
   representation in the `.tfn` file itself (see `turtle_font.h`'s doc
   comment) and can't be cross-checked against the binary fixture the same
   way.
5. (Phase 2) Cross-checks `turtle_font_measure()` against `turtle_font_draw_scene()`'s
   returned width, and that out-of-charset characters (e.g. `\t`) advance
   without blitting. `turtle_gpu_blit_indexed_scene()` (defined in the much
   heavier `turtle_gpu.cpp`, never linked here) is faked locally in
   `test_turtle_font.cpp` — it just records call bounds, so the real glyph
   positioning/advance logic in `turtle_font_draw_scene()` gets exercised
   without pulling in the SPI/display driver.
6. (Phase 4) Cross-checks `turtle_font_draw_scene_tint()`: same width as the
   untinted draw, exactly one `turtle_gpu_fill_rect_scene()` call per
   non-transparent glyph pixel (counted independently from the raw pixel
   data), and every call uses the requested tint color. `fill_rect_scene` is
   faked the same way as the blit function above.

Requires `g++` and `python3` on `PATH`. Exits non-zero on any mismatch.

## `run_scene_syntax_check.sh` (Phase 3 — actor-VM `text()` / dirty-rect integration)

```
./run_scene_syntax_check.sh
```

`turtle_scene.cpp` (actor state, dirty-rect redraw) and `turtle_actor_lua.cpp`
(Lua bindings) are too entangled with the rest of the sketch to decode-and-diff
like `turtle_font.cpp` — there's no equivalent Python mirror to cross-check
against. This instead runs `g++ -fsyntax-only` (parse + full type-check, no
codegen/link) over the real, unmodified `turtle_font.cpp`, `turtle_scene.cpp`,
`turtle_actor_lua.cpp`, and `TurtleReader.ino`, using the real vendored Lua
headers (`firmware/libraries/lua54/src/`) plus the `arduino_shim/` stand-ins.

This is a real compiler, not a heuristic — it caught an actual bug during
development (a new Phase 3 helper called `font_cache_get()` before its
forward declaration existed, which only a compiler would catch reliably).
It does **not** prove the code links or runs correctly on hardware (it never
generates code), and it only covers these four files — other untouched
firmware files (`turtle_cart.cpp`, `turtle_input.cpp`, ...) won't pass
through this shim (they need `digitalRead`/`pinMode`/`File::size`/etc. that
aren't stubbed) — that's expected, not a regression.

## What this does and doesn't prove

Proves the decode logic is correct against real encoder output, on a host
compiler. Does **not** exercise PSRAM allocation (the `#if defined(ESP32) ||
defined(ESP_PLATFORM)` branches are compiled out on host, falling through to
plain `malloc`), ESP32-specific toolchain quirks, or anything on real
hardware — that still needs the user to flash a board.

A benign `-Wunused-parameter` warning on `free_bytes`'s `in_psram` argument is
expected on host builds: that parameter is only read inside the compiled-out
`#if defined(ESP32) || defined(ESP_PLATFORM)` branch (same shape as the
existing `turtle_tileset.cpp`'s `free_pixels`), not a real issue.
