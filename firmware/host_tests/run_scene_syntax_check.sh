#!/usr/bin/env bash
# Syntax-only (-fsyntax-only: parse + typecheck, no codegen/link) sanity check for the
# files touched by the font-rendering work: turtle_scene.cpp, turtle_actor_lua.cpp,
# turtle_font.cpp, TurtleReader.ino. See README.md.
#
# NOT a full sketch build: the arduino_shim/ headers only cover what these specific
# files need. Other untouched firmware files (turtle_cart.cpp, turtle_input.cpp, ...)
# will NOT pass through this shim (missing digitalRead/pinMode/File::size/etc.) — that's
# expected, they're out of scope here, not broken.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

FLAGS=(-std=c++17 -fsyntax-only -Wall -Wextra -I arduino_shim -I ../libraries/lua54/src -DTURTLE_USE_DISPLAY=0)

echo "== turtle_font.cpp =="
g++ "${FLAGS[@]}" ../TurtleReader/turtle_font.cpp

echo "== turtle_scene.cpp =="
g++ "${FLAGS[@]}" ../TurtleReader/turtle_scene.cpp

echo "== turtle_actor_lua.cpp =="
g++ "${FLAGS[@]}" ../TurtleReader/turtle_actor_lua.cpp

echo "== TurtleReader.ino =="
g++ "${FLAGS[@]}" -x c++ ../TurtleReader/TurtleReader.ino

echo "OK: los 4 archivos pasan -fsyntax-only (parseo + chequeo de tipos, sin generar codigo ni enlazar)."
