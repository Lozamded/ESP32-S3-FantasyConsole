# Host-side verification harnesses

Small programs that compile real firmware C++ files (`firmware/TurtleReader/*.cpp`) with `g++` (not the Arduino toolchain) and cross-check their decoding logic against the Python encoder/decoder in `tools/turtlestudio/`. No hardware required — these only verify that the C++ decoding produces byte-for-byte identical output to the Python export pipeline.

Not part of the Arduino sketch: `TurtleReader.ino` never includes anything from this directory. `arduino_shim/` provides minimal stand-ins for `Arduino.h`, `SPI.h`, and `SD.h` (just enough `Serial`/`String`/`SD`/`File`/`delay`/`millis` to type-check) — picked up via `-I arduino_shim` on the host `g++` command line only.

---

## `run_font_test.sh` — `.tfn` / `turtle_font.cpp`

```bash
./run_font_test.sh [path/to/font.json]
```

Defaults to `tools/turtlestudio/exampleprojects/demo1/objects/Fonts/default.json`.

**What it does:**

1. `gen_font_fixture.py` calls the real `font_json_to_tfn()` to produce a `.tfn` fixture, and `decode_font_blob()` to produce the expected decoded dump.
2. Compiles `test_turtle_font.cpp` + the real `turtle_font.cpp` + `turtle_asset_bin.cpp` from `firmware/TurtleReader/`, unmodified.
3. Runs the compiled binary against the fixture, dumping glyph pixels and advances in the same text format.
4. Diffs the two dumps. Also checks `turtle_font_charset_index()` against hand-computed expected indices (the charset has no representation in the `.tfn` binary, so it can't be cross-checked via the fixture alone).
5. Cross-checks `turtle_font_measure()` against `turtle_font_draw_scene()`'s returned width, and verifies that out-of-charset characters (e.g. `\t`) advance without blitting. `turtle_gpu_blit_indexed_scene()` is faked locally in `test_turtle_font.cpp` — it just records call bounds so the positioning/advance logic is exercised without pulling in the SPI/display driver.
6. Cross-checks `turtle_font_draw_scene_tint()`: same width as untinted, exactly one `turtle_gpu_fill_rect_scene()` call per non-transparent glyph pixel, every call using the requested tint color. `fill_rect_scene` is faked the same way.

Requires `g++` and `python3` on `PATH`. Exits non-zero on any mismatch.

---

## `run_scene_syntax_check.sh` — actor VM `text()` / dirty-rect integration

```bash
./run_scene_syntax_check.sh
```

`turtle_scene.cpp` and `turtle_actor_lua.cpp` are too entangled with the rest of the sketch to decode-and-diff like `turtle_font.cpp` — there is no Python mirror to cross-check against. This script instead runs `g++ -fsyntax-only` (full parse + type-check, no codegen or linking) over the real, unmodified `turtle_font.cpp`, `turtle_scene.cpp`, `turtle_actor_lua.cpp`, and `TurtleReader.ino`, using the vendored Lua headers (`firmware/libraries/lua54/src/`) plus `arduino_shim/`.

This is a real compiler pass — it caught an actual bug during development (a new helper called before its forward declaration existed). It does **not** prove the code links or runs correctly on hardware, and it only covers these four files. Other firmware files (`turtle_cart.cpp`, `turtle_input.cpp`, etc.) use `digitalRead`/`pinMode`/`File::size` and similar that aren't stubbed — passing them through this shim is not expected.

---

## What these tests prove and don't prove

**Prove:** the C++ decode logic is correct against real encoder output, on a host compiler.

**Do not prove:**
- PSRAM allocation (the `#if defined(ESP32) || defined(ESP_PLATFORM)` branches compile out on host, falling through to plain `malloc`)
- ESP32-specific toolchain behavior
- Correct execution on real hardware — that still requires flashing a board

A `-Wunused-parameter` warning on `free_bytes`'s `in_psram` argument is expected on host builds: that parameter is only read inside the compiled-out ESP32 branch (same pattern as `turtle_tileset.cpp`'s `free_pixels`).
