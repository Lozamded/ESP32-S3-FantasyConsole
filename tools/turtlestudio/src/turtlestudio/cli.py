"""CLI de TurtleStudio."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from turtlestudio import __version__
from turtlestudio.build import write_turtlecart
from turtlestudio.project import MANIFEST_NAME, TargetBoard, create_project


def _cmd_project_init(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser()
    try:
        mp = create_project(
            path,
            display_name=args.name,
            force=args.force,
            board=TargetBoard(args.board),
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"Error de escritura: {e}", file=sys.stderr)
        return 1
    print(f"Proyecto creado: {mp.parent}")
    print(f"  manifest: {mp}")
    return 0


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


def _cmd_gui(args: argparse.Namespace) -> int:
    from turtlestudio.mainwindow import run_studio

    project = Path(args.project).resolve() if args.project else None
    return run_studio(project)


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
        help="Editor TurtleStudio (PyQt6)",
    )
    gui.add_argument("project", nargs="?", help="Carpeta de proyecto a abrir")
    gui.set_defaults(func=_cmd_gui)

    proj = sub.add_parser(
        "project",
        help="Proyecto en carpeta (turtlestudio.json + arbol de directorios)",
    )
    proj_sub = proj.add_subparsers(
        dest="project_command",
        help="Subcomando proyecto",
        required=True,
    )
    p_init = proj_sub.add_parser(
        "init",
        help=f"Crear carpeta de proyecto con {MANIFEST_NAME!r} y arbol estandar",
    )
    p_init.add_argument(
        "path",
        type=Path,
        help="Carpeta del proyecto (se crea si no existe)",
    )
    p_init.add_argument(
        "--name",
        type=str,
        default=None,
        help="Nombre legible en el manifest (por defecto: nombre de la carpeta)",
    )
    p_init.add_argument(
        "--force",
        action="store_true",
        help="Si ya existe el manifest, reescribirlo y asegurar carpetas (no borra archivos)",
    )
    p_init.add_argument(
        "--board",
        type=str,
        default=TargetBoard.ESP32_S3_N16R8.value,
        choices=[b.value for b in TargetBoard],
        help="Placa objetivo (por defecto: esp32s3_n16r8)",
    )
    p_init.set_defaults(func=_cmd_project_init)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        raise SystemExit(2)
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
