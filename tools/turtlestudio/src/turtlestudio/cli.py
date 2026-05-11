"""CLI de TurtleStudio."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from turtlestudio import __version__
from turtlestudio.build import write_turtlecart


def _cmd_build(args: argparse.Namespace) -> int:
    out = Path(args.output)
    lua = Path(args.lua)
    if not lua.is_file():
        print(f"Error: no existe el archivo Lua: {lua}", file=sys.stderr)
        return 1
    entry = args.entry or lua.name
    pal: Path | None = Path(args.palette) if args.palette else None
    if pal is not None and not pal.is_file():
        print(f"Error: no existe la paleta: {pal}", file=sys.stderr)
        return 1
    try:
        write_turtlecart(
            out,
            entry_relpath=entry,
            lua_path=lua,
            palette_path=pal,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    size = out.stat().st_size
    print(f"Cartucho escrito: {out} ({size} bytes)")
    return 0


def _cmd_gui(_args: argparse.Namespace) -> int:
    from turtlestudio.gui import run_gui

    return run_gui()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="turtlestudio",
        description="Herramientas para cartuchos .turtlecart",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    sub = parser.add_subparsers(dest="command", help="Comando")

    build = sub.add_parser(
        "build",
        help="Ensamblar un .turtlecart v0 (texto) desde Lua y paleta opcional",
    )
    build.add_argument(
        "lua",
        type=Path,
        help="Ruta al script Lua (p. ej. main.lua)",
    )
    build.add_argument(
        "-o",
        "--output",
        required=True,
        type=Path,
        help="Ruta de salida del .turtlecart",
    )
    build.add_argument(
        "--entry",
        type=str,
        default=None,
        help="Nombre logico en ENTRY y ---FILE:...--- (por defecto: nombre del .lua)",
    )
    build.add_argument(
        "--palette",
        type=Path,
        default=None,
        help="Archivo de texto con una linea #RRGGBB o #RGB por color (opcional)",
    )
    build.set_defaults(func=_cmd_build)

    gui = sub.add_parser(
        "gui",
        help="Ventana minima (Dear PyGui): panel, canvas, Exportar",
    )
    gui.set_defaults(func=_cmd_gui)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        raise SystemExit(2)
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
