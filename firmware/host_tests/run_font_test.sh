#!/usr/bin/env bash
# Phase 1 verification harness for turtle_font.cpp — see README.md.
# Not part of the Arduino sketch build; run manually or in CI on a host machine.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

FONT_JSON="${1:-../../tools/turtlestudio/exampleprojects/demo1/objects/Fonts/default.json}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "== 1. generando fixture .tfn desde $FONT_JSON =="
python3 gen_font_fixture.py "$FONT_JSON" "$WORK/font.tfn" "$WORK/expected.txt"

echo "== 2. compilando harness C++ (firmware real, sin modificar) =="
g++ -std=c++17 -Wall -Wextra -I arduino_shim -DTURTLE_USE_DISPLAY=0 \
  test_turtle_font.cpp ../TurtleReader/turtle_font.cpp ../TurtleReader/turtle_asset_bin.cpp \
  -o "$WORK/test_turtle_font"

echo "== 3. decodificando con el firmware real =="
"$WORK/test_turtle_font" "$WORK/font.tfn" > "$WORK/got.txt"

echo "== 4. comparando contra decode_font_blob() (Python) =="
if diff -u "$WORK/expected.txt" "$WORK/got.txt"; then
  echo "OK: turtle_font_load_tfn coincide byte-a-byte con decode_font_blob"
else
  echo "FALLO: ver diff arriba" >&2
  exit 1
fi
