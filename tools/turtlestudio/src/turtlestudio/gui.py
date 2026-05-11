"""Interfaz minima TurtleStudio (Dear PyGui)."""

from __future__ import annotations

import sys
from pathlib import Path

from turtlestudio.build import load_palette_rgb01_for_preview, write_turtlecart_content

# Resolucion logica de consola (mismo orden de filas que el framebuffer: Y abajo en datos)
_FB_W = 264
_FB_H = 198
_SCALE = 2
_GRID_STEP = 8

_DEFAULT_LUA = '''-- Script ENTRY (se embebe en el .turtlecart)
print("TurtleStudio")
cls(1)
flip()
'''


def _solid_rgba_float(width: int, height: int, r: float, g: float, b: float) -> list[float]:
    px = (r, g, b, 1.0)
    row: list[float] = []
    for _ in range(width):
        row.extend(px)
    out: list[float] = []
    for _ in range(height):
        out.extend(row)
    return out


def _compose_preview_texture(
    base_rgba: list[float],
    width: int,
    height: int,
    show_grid: bool,
) -> list[float]:
    if not show_grid:
        return list(base_rgba)

    out = list(base_rgba)
    step = _GRID_STEP
    lr, lg, lb = 0.22, 0.24, 0.32
    blend = 0.65

    for y in range(height):
        for x in range(width):
            if (x % step == 0) or (y % step == 0):
                i = (y * width + x) * 4
                out[i] = out[i] * (1.0 - blend) + lr * blend
                out[i + 1] = out[i + 1] * (1.0 - blend) + lg * blend
                out[i + 2] = out[i + 2] * (1.0 - blend) + lb * blend
                out[i + 3] = 1.0
    return out


def run_gui() -> int:
    try:
        import dearpygui.dearpygui as dpg
    except ImportError:
        print(
            "Falta Dear PyGui. Instala con: pip install dearpygui",
            file=sys.stderr,
        )
        return 1

    state: dict[str, object] = {
        "rgb": [],
        "hexes": [],
    }

    def palette_reload_from_path() -> str:
        pal_s = str(dpg.get_value("ts_pal_path")).strip()
        path = Path(pal_s).expanduser() if pal_s else None
        msg = ""
        if pal_s and path is not None and not path.is_file():
            msg = f"Paleta no encontrada ({path}); uso paleta por defecto del firmware.\n"
        use_path = path if (path is not None and path.is_file()) else None
        rgbs, hexes = load_palette_rgb01_for_preview(use_path)
        state["rgb"] = rgbs
        state["hexes"] = hexes
        items = [f"{i:2d}  {h}" for i, h in enumerate(hexes)]
        dpg.configure_item("ts_bg_combo", items=items)
        cur = dpg.get_value("ts_bg_combo")
        if cur not in items:
            dpg.set_value("ts_bg_combo", items[0])
        return msg + f"Paleta canvas: {len(hexes)} colores (indices 0..{len(hexes) - 1}).\n"

    def parse_bg_index() -> int:
        v = dpg.get_value("ts_bg_combo")
        if v is None:
            return 0
        s = str(v).strip()
        try:
            return int(s.split()[0])
        except (ValueError, IndexError):
            return 0

    def _update_color_swatch(r: float, g: float, b: float) -> None:
        r8 = max(0, min(255, int(round(r * 255.0))))
        g8 = max(0, min(255, int(round(g * 255.0))))
        b8 = max(0, min(255, int(round(b * 255.0))))
        dpg.set_value("ts_swatch_theme_color", (r8, g8, b8, 255))

    def refresh_canvas_texture() -> None:
        rgbs = state["rgb"]
        if not rgbs:
            return
        idx = parse_bg_index()
        idx = max(0, min(idx, len(rgbs) - 1))
        r, g, b = rgbs[idx]
        _update_color_swatch(r, g, b)
        base = _solid_rgba_float(_FB_W, _FB_H, r, g, b)
        show = bool(dpg.get_value("ts_show_grid"))
        data = _compose_preview_texture(base, _FB_W, _FB_H, show)
        dpg.set_value("preview_texture", data)

    initial_black = _solid_rgba_float(_FB_W, _FB_H, 0.08, 0.08, 0.1)

    dpg.create_context()

    with dpg.theme(tag="ts_swatch_theme"):
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(
                dpg.mvThemeCol_ChildBg,
                [22, 22, 28, 255],
                tag="ts_swatch_theme_color",
            )

    with dpg.texture_registry():
        dpg.add_dynamic_texture(
            width=_FB_W,
            height=_FB_H,
            default_value=initial_black,
            tag="preview_texture",
        )

    def on_load_lua_from_file(_sender: object, _app_data: object) -> None:
        p_s = str(dpg.get_value("ts_import_lua_path")).strip()
        if not p_s:
            dpg.set_value("ts_log", "Indica una ruta .lua para importar.\n")
            return
        p = Path(p_s).expanduser()
        if not p.is_file():
            dpg.set_value("ts_log", f"No existe el archivo: {p}\n")
            return
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as e:
            dpg.set_value("ts_log", f"No se pudo leer: {e}\n")
            return
        dpg.set_value("ts_lua_source", text)
        if not str(dpg.get_value("ts_entry")).strip():
            dpg.set_value("ts_entry", p.name)
        dpg.set_value("ts_log", f"Cargado en editor: {p} ({len(text)} caracteres)\n")

    def on_export(_sender: object, _app_data: object) -> None:
        body = str(dpg.get_value("ts_lua_source")).strip()
        out_s = dpg.get_value("ts_out_path").strip()
        pal_s = dpg.get_value("ts_pal_path").strip()
        entry_s = dpg.get_value("ts_entry").strip()
        write_lua = bool(dpg.get_value("ts_write_lua_file"))

        if not body:
            dpg.set_value("ts_log", "Escribe algo en el script Lua (panel derecho) o importa un .lua.\n")
            return
        if not out_s:
            dpg.set_value("ts_log", "Indica la ruta de salida del .turtlecart.\n")
            return

        out = Path(out_s).expanduser()
        pal: Path | None = Path(pal_s).expanduser() if pal_s else None
        if pal is not None and not pal.is_file():
            dpg.set_value("ts_log", f"No existe la paleta: {pal}\n")
            return

        entry = entry_s if entry_s else "main.lua"
        if not entry.lower().endswith(".lua"):
            entry = entry + ".lua"

        try:
            cart_path, lua_path = write_turtlecart_content(
                out,
                entry_relpath=entry,
                main_lua_body=body,
                palette_path=pal,
                write_lua_file=write_lua,
            )
            n = cart_path.stat().st_size
            if lua_path is not None:
                m = lua_path.stat().st_size
                dpg.set_value(
                    "ts_log",
                    f"Exportado OK:\n  {cart_path} ({n} bytes)\n  {lua_path} ({m} bytes)\n",
                )
            else:
                dpg.set_value("ts_log", f"Exportado OK: {cart_path} ({n} bytes)\n")
        except ValueError as e:
            dpg.set_value("ts_log", f"Error: {e}\n")
        except OSError as e:
            dpg.set_value("ts_log", f"Error de escritura: {e}\n")

    def on_grid_toggle(_sender: object, _app_data: object) -> None:
        refresh_canvas_texture()

    def on_bg_combo(_sender: object, _app_data: object) -> None:
        refresh_canvas_texture()

    def on_reload_palette_click(_sender: object, _app_data: object) -> None:
        log = palette_reload_from_path()
        prev = dpg.get_value("ts_log") or ""
        dpg.set_value("ts_log", prev + log)
        refresh_canvas_texture()

    with dpg.window(
        tag="ts_main",
        label="TurtleStudio",
        no_resize=False,
    ):
        with dpg.group(horizontal=True):
            with dpg.child_window(width=300, border=True):
                dpg.add_text("Proyecto")
                dpg.add_text("El Lua se edita a la derecha; aqui solo rutas y export.")
                dpg.add_input_text(
                    tag="ts_pal_path",
                    label="Paleta (opc.)",
                    width=-1,
                    hint="palette.txt",
                )
                dpg.add_input_text(
                    tag="ts_out_path",
                    label="Salida .turtlecart",
                    width=-1,
                    default_value="cart.turtlecart",
                )
                dpg.add_input_text(
                    tag="ts_entry",
                    label="ENTRY (nombre en cartucho)",
                    width=-1,
                    default_value="main.lua",
                    hint="p. ej. main.lua",
                )
                dpg.add_checkbox(
                    tag="ts_write_lua_file",
                    label="Guardar .lua junto al cartucho",
                    default_value=True,
                )
                dpg.add_separator()
                dpg.add_text("Importar script existente (opc.)")
                dpg.add_input_text(
                    tag="ts_import_lua_path",
                    label="Ruta .lua",
                    width=-1,
                    hint="/ruta/a/main.lua",
                )
                dpg.add_button(
                    label="Cargar en editor",
                    width=-1,
                    callback=on_load_lua_from_file,
                )
                dpg.add_button(
                    label="Exportar .turtlecart",
                    width=-1,
                    callback=on_export,
                )
                dpg.add_separator()
                dpg.add_text("Escena / canvas")
                dpg.add_button(
                    label="Recargar paleta en canvas",
                    width=-1,
                    callback=on_reload_palette_click,
                )
                dpg.add_text("Fondo = indice en esa paleta (misma que el cartucho).")
                dpg.add_text("Color de fondo")
                with dpg.group(horizontal=True):
                    dpg.add_combo(
                        tag="ts_bg_combo",
                        width=232,
                        items=[" 0  #000000"],
                        default_value=" 0  #000000",
                        callback=on_bg_combo,
                    )
                    with dpg.child_window(
                        tag="ts_color_swatch",
                        width=36,
                        height=24,
                        border=True,
                        no_scrollbar=True,
                    ):
                        dpg.add_spacer(width=2, height=2)
                dpg.bind_item_theme("ts_color_swatch", "ts_swatch_theme")
                dpg.add_separator()
                dpg.add_input_text(
                    tag="ts_log",
                    label="Registro",
                    multiline=True,
                    readonly=True,
                    width=-1,
                    height=100,
                    default_value="Edita el Lua a la derecha y Exportar.\n",
                )

            with dpg.child_window(border=True):
                with dpg.group(horizontal=True):
                    dpg.add_text(
                        f"Canvas · {_FB_W}×{_FB_H} (vista previa · rejilla cada {_GRID_STEP}px)"
                    )
                    dpg.add_checkbox(
                        tag="ts_show_grid",
                        label="Mostrar rejilla",
                        default_value=False,
                        callback=on_grid_toggle,
                    )
                dpg.add_image(
                    "preview_texture",
                    width=_FB_W * _SCALE,
                    height=_FB_H * _SCALE,
                )
                dpg.add_separator()
                dpg.add_text("Script Lua (ENTRY del cartucho; mas adelante: objetos = varios .lua)")
                dpg.add_input_text(
                    tag="ts_lua_source",
                    label="",
                    multiline=True,
                    width=-1,
                    height=220,
                    default_value=_DEFAULT_LUA,
                    tracked=True,
                )

    palette_reload_from_path()
    refresh_canvas_texture()

    dpg.create_viewport(
        title="TurtleStudio",
        width=1000,
        height=760,
    )
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("ts_main", True)
    dpg.start_dearpygui()
    dpg.destroy_context()
    return 0
