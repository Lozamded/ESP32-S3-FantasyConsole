"""Interfaz minima TurtleStudio (Dear PyGui)."""

from __future__ import annotations

import sys
from pathlib import Path

from turtlestudio.build import load_palette_rgb01_for_preview, write_turtlecart_content
from turtlestudio.project import (
    DEFAULT_EXAMPLE_PALETTE_REL,
    DEFAULT_TRANSPARENT_INDEX,
    ProjectInfo,
    create_project,
    load_project,
    save_project,
)

# Resolucion logica de consola (mismo orden de filas que el framebuffer: Y abajo en datos)
_FB_W = 264
_FB_H = 198
_SCALE = 2
_GRID_STEP = 8
# Panel izquierdo: ancho del child modesto; los controles usan ancho FIJO para que no
# estiren con el panel y no roben espacio al canvas (Dear PyGui: width=-1 = 100% del padre).
_LEFT_FORM_WIDTH = 232
_LEFT_PANEL_WIDTH = _LEFT_FORM_WIDTH + 264
_LEFT_TEXT_WRAP = _LEFT_FORM_WIDTH
_LEFT_BG_COMBO_WIDTH = _LEFT_FORM_WIDTH - 42

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
        "project_root": None,
        "scenes": [],
        "active_scene_id": "main",
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

    def _set_bg_combo_to_scene_index(idx: int) -> None:
        cfg = dpg.get_item_configuration("ts_bg_combo")
        items = cfg.get("items") if cfg else None
        if not items:
            return
        i = max(0, min(int(idx), len(items) - 1))
        dpg.set_value("ts_bg_combo", items[i])

    def _commit_background_for_scene_id(sid: str) -> None:
        scenes = state.get("scenes")
        if not isinstance(scenes, list) or not sid:
            return
        bi = parse_bg_index()
        for row in scenes:
            if row.get("id") == sid:
                row["background_index"] = bi
                break

    def _commit_background_for_active_scene() -> None:
        _commit_background_for_scene_id(str(state.get("active_scene_id") or ""))

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

    def _set_project_save_enabled(enabled: bool) -> None:
        dpg.configure_item("ts_menu_save_project", enabled=enabled)
        dpg.configure_item("ts_btn_save_project", enabled=enabled)
        for tag in (
            "ts_scene_combo",
            "ts_scene_pal",
            "ts_btn_new_scene",
            "ts_transparent_idx",
        ):
            dpg.configure_item(tag, enabled=enabled)

    def enter_main_editor(*, log_append: str) -> None:
        dpg.configure_item("ts_startup", show=False)
        dpg.configure_item("ts_main", show=True)
        dpg.set_primary_window("ts_main", True)
        if isinstance(state.get("project_root"), Path):
            _set_project_save_enabled(True)
        else:
            _set_project_save_enabled(False)
            state["scenes"] = []
            state["active_scene_id"] = "main"
            dpg.configure_item("ts_scene_combo", items=["—"])
            dpg.set_value("ts_scene_combo", "—")
            dpg.set_value("ts_scene_pal", "")
            dpg.set_value("ts_transparent_idx", DEFAULT_TRANSPARENT_INDEX)
        log = palette_reload_from_path()
        refresh_canvas_texture()
        if isinstance(state.get("project_root"), Path):
            scenes = state.get("scenes")
            active = str(state.get("active_scene_id") or "")
            if isinstance(scenes, list) and scenes:
                row = next((x for x in scenes if x.get("id") == active), None)
                if row is not None:
                    _set_bg_combo_to_scene_index(int(row.get("background_index", 1)))
                    refresh_canvas_texture()
        dpg.set_value("ts_log", log_append + log)

    def show_project_startup_dialog(_sender: object | None = None, _app_data: object | None = None) -> None:
        root = state.get("project_root")
        if isinstance(root, Path):
            dpg.set_value("ts_open_project_path", str(root))
            dpg.set_value("ts_new_project_path", str(root.parent / "nuevo_proyecto"))
        dpg.set_value("ts_startup_log", "")
        dpg.configure_item("ts_main", show=False)
        dpg.configure_item("ts_startup", show=True)
        dpg.set_primary_window("ts_startup", True)
        dpg.focus_item("ts_startup")

    def _commit_palette_for_scene_id(sid: str) -> None:
        scenes = state.get("scenes")
        if not isinstance(scenes, list) or not sid:
            return
        pal = str(dpg.get_value("ts_scene_pal")).strip().replace("\\", "/")
        while pal.startswith("./"):
            pal = pal[2:]
        if not pal:
            return
        for row in scenes:
            if row.get("id") == sid:
                row["palette"] = pal
                break

    def _sync_canvas_palette_from_active_scene() -> None:
        root = state.get("project_root")
        active = str(state.get("active_scene_id") or "")
        scenes = state.get("scenes")
        if not isinstance(root, Path) or not isinstance(scenes, list):
            return
        row = next((x for x in scenes if x.get("id") == active), None)
        if not row:
            return
        rel = str(row.get("palette", "")).strip()
        if rel:
            dpg.set_value("ts_pal_path", str((root / rel).resolve()))

    def _refresh_scene_widgets() -> None:
        scenes = state.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            return
        ids = [str(x["id"]) for x in scenes]
        dpg.configure_item("ts_scene_combo", items=ids)
        active = str(state.get("active_scene_id") or ids[0])
        if active not in ids:
            active = ids[0]
        state["active_scene_id"] = active
        dpg.set_value("ts_scene_combo", active)
        pal = next((str(x["palette"]) for x in scenes if x["id"] == active), str(scenes[0]["palette"]))
        dpg.set_value("ts_scene_pal", pal)
        _sync_canvas_palette_from_active_scene()
        palette_reload_from_path()
        row = next((x for x in scenes if x["id"] == active), scenes[0])
        _set_bg_combo_to_scene_index(int(row.get("background_index", 1)))
        refresh_canvas_texture()

    def _apply_project_scenes_from_info(info: ProjectInfo) -> None:
        state["scenes"] = [
            {
                "id": s.id,
                "palette": s.palette,
                "background_index": s.background_index,
            }
            for s in info.scenes
        ]
        state["active_scene_id"] = info.active_scene
        dpg.set_value("ts_transparent_idx", info.transparent_index)
        _refresh_scene_widgets()

    def on_scene_combo(_sender: object, _app_data: object) -> None:
        old_active = str(state.get("active_scene_id") or "")
        _commit_palette_for_scene_id(old_active)
        _commit_background_for_scene_id(old_active)
        new_id = str(dpg.get_value("ts_scene_combo")).strip()
        scenes = state.get("scenes")
        if not isinstance(scenes, list):
            return
        if new_id not in {x.get("id") for x in scenes}:
            dpg.set_value("ts_scene_combo", old_active)
            return
        state["active_scene_id"] = new_id
        _refresh_scene_widgets()
        prev_log = dpg.get_value("ts_log") or ""
        dpg.set_value("ts_log", prev_log + f"Escena activa: {new_id}\n")

    def on_new_scene(_sender: object, _app_data: object) -> None:
        if not isinstance(state.get("project_root"), Path):
            return
        cur = str(state.get("active_scene_id") or "")
        _commit_palette_for_scene_id(cur)
        _commit_background_for_scene_id(cur)
        scenes = state.get("scenes")
        if not isinstance(scenes, list):
            scenes = []
            state["scenes"] = scenes
        used = {str(x["id"]) for x in scenes}
        n = 1
        while f"scene_{n}" in used:
            n += 1
        new_id = f"scene_{n}"
        scenes.append(
            {"id": new_id, "palette": DEFAULT_EXAMPLE_PALETTE_REL, "background_index": 1}
        )
        state["active_scene_id"] = new_id
        _refresh_scene_widgets()
        prev_log = dpg.get_value("ts_log") or ""
        dpg.set_value(
            "ts_log",
            prev_log + f"Nueva escena '{new_id}' (Guardar proyecto para persistir).\n",
        )

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
        if isinstance(state.get("project_root"), Path):
            _commit_background_for_active_scene()
        refresh_canvas_texture()

    def on_reload_palette_click(_sender: object, _app_data: object) -> None:
        log = palette_reload_from_path()
        prev = dpg.get_value("ts_log") or ""
        dpg.set_value("ts_log", prev + log)
        if isinstance(state.get("project_root"), Path):
            scenes = state.get("scenes")
            active = str(state.get("active_scene_id") or "")
            if isinstance(scenes, list):
                row = next((x for x in scenes if x.get("id") == active), None)
                hexes = state.get("hexes")
                if row is not None and isinstance(hexes, list) and hexes:
                    max_i = len(hexes) - 1
                    bg = max(0, min(int(row.get("background_index", 1)), max_i))
                    row["background_index"] = bg
                    _set_bg_combo_to_scene_index(bg)
        refresh_canvas_texture()

    def on_save_project(_sender: object, _app_data: object) -> None:
        root = state.get("project_root")
        if not isinstance(root, Path):
            dpg.set_value(
                "ts_log",
                (dpg.get_value("ts_log") or "")
                + "No hay proyecto abierto. Proyecto > Cambiar proyecto…\n",
            )
            return
        _commit_palette_for_scene_id(str(state.get("active_scene_id") or ""))
        _commit_background_for_active_scene()
        pal_s = str(dpg.get_value("ts_pal_path")).strip()
        pal: Path | None = Path(pal_s).expanduser() if pal_s else None
        body = str(dpg.get_value("ts_lua_source"))
        scenes_list = [dict(x) for x in state.get("scenes", []) if isinstance(x, dict)]
        active = str(state.get("active_scene_id") or "").strip()
        try:
            ti = int(dpg.get_value("ts_transparent_idx"))
        except (TypeError, ValueError):
            ti = DEFAULT_TRANSPARENT_INDEX
        try:
            script_path, pal_updated, scenes_updated = save_project(
                root,
                main_lua_body=body,
                palette_file=pal,
                scenes=scenes_list,
                active_scene=active,
                transparent_index=ti,
            )
        except ValueError as e:
            dpg.set_value("ts_log", (dpg.get_value("ts_log") or "") + f"Error al guardar: {e}\n")
            return
        except OSError as e:
            dpg.set_value("ts_log", (dpg.get_value("ts_log") or "") + f"Error de escritura: {e}\n")
            return
        bits = []
        if pal_updated:
            bits.append("default_palette")
        if scenes_updated:
            bits.append("escenas / transparent_index")
        extra = f" ({', '.join(bits)} en manifest)\n" if bits else "\n"
        dpg.set_value(
            "ts_log",
            (dpg.get_value("ts_log") or "")
            + f"Proyecto guardado: {script_path}{extra}",
        )

    def on_startup_create(_sender: object, _app_data: object) -> None:
        root_s = str(dpg.get_value("ts_new_project_path")).strip()
        name_s = str(dpg.get_value("ts_new_project_name")).strip()
        if not root_s:
            dpg.set_value("ts_startup_log", "Indica la carpeta donde crear el proyecto.\n")
            return
        root = Path(root_s).expanduser()
        display_name = name_s if name_s else None
        try:
            mp = create_project(root, display_name=display_name, force=False)
        except ValueError as e:
            dpg.set_value("ts_startup_log", f"{e}\nUsa CLI: turtlestudio project init ... --force\n")
            return
        except OSError as e:
            dpg.set_value("ts_startup_log", f"Error de escritura: {e}\n")
            return
        state["project_root"] = root.resolve()
        try:
            body = (root / "scripts" / "main.lua").read_text(encoding="utf-8")
        except OSError:
            body = _DEFAULT_LUA
        dpg.set_value("ts_lua_source", body)
        dpg.set_value("ts_entry", "main.lua")
        pr = root.resolve()
        try:
            pinfo = load_project(pr)
        except ValueError:
            pinfo = None
        if pinfo is not None:
            _apply_project_scenes_from_info(pinfo)
        else:
            dpg.set_value("ts_pal_path", str(pr / DEFAULT_EXAMPLE_PALETTE_REL))
        out_default = pr / "build" / "cart.turtlecart"
        dpg.set_value("ts_out_path", str(out_default))
        enter_main_editor(log_append=f"Proyecto creado.\n  {mp}\n")

    def on_startup_open(_sender: object, _app_data: object) -> None:
        root_s = str(dpg.get_value("ts_open_project_path")).strip()
        if not root_s:
            dpg.set_value("ts_startup_log", "Indica la carpeta que contiene turtlestudio.json\n")
            return
        root = Path(root_s).expanduser()
        try:
            info = load_project(root)
        except ValueError as e:
            dpg.set_value("ts_startup_log", f"{e}\n")
            return
        state["project_root"] = info.root
        try:
            body = (info.root / info.entry).read_text(encoding="utf-8")
        except OSError as e:
            dpg.set_value("ts_startup_log", f"No se pudo leer el entry: {e}\n")
            return
        dpg.set_value("ts_lua_source", body)
        dpg.set_value("ts_entry", Path(info.entry).name)
        _apply_project_scenes_from_info(info)
        out_default = info.root / "build" / "cart.turtlecart"
        dpg.set_value("ts_out_path", str(out_default))
        enter_main_editor(
            log_append=(
                f"Proyecto abierto: {info.name}\n"
                f"  root: {info.root}\n"
                f"  entry: {info.entry}\n"
            ),
        )

    def on_startup_skip_project(_sender: object, _app_data: object) -> None:
        state["project_root"] = None
        state["scenes"] = []
        state["active_scene_id"] = "main"
        dpg.set_value("ts_lua_source", _DEFAULT_LUA)
        dpg.set_value("ts_entry", "main.lua")
        dpg.set_value("ts_pal_path", "")
        dpg.set_value("ts_out_path", "cart.turtlecart")
        dpg.set_value("ts_transparent_idx", DEFAULT_TRANSPARENT_INDEX)
        enter_main_editor(log_append="Modo sin proyecto (solo editor y export manual).\n")

    with dpg.window(
        tag="ts_startup",
        label="TurtleStudio — Proyecto",
        modal=True,
        no_resize=True,
        no_move=False,
        autosize=True,
        show=True,
    ):
        dpg.add_text("Elige como empezar. Un proyecto es una carpeta con turtlestudio.json.")
        dpg.add_separator()
        dpg.add_text("Nuevo proyecto", color=(200, 220, 255, 255))
        dpg.add_input_text(
            tag="ts_new_project_path",
            label="Carpeta (se crea si no existe)",
            width=480,
            hint="/home/usuario/MisJuegos/MiCartucho",
        )
        dpg.add_input_text(
            tag="ts_new_project_name",
            label="Nombre en manifest (opc.)",
            width=480,
            hint="Si vacio, se usa el nombre de la carpeta",
        )
        dpg.add_button(label="Crear proyecto", width=480, callback=on_startup_create)
        dpg.add_separator()
        dpg.add_text("Abrir proyecto existente", color=(200, 220, 255, 255))
        dpg.add_input_text(
            tag="ts_open_project_path",
            label="Carpeta con turtlestudio.json",
            width=480,
            hint="/home/usuario/MisJuegos/MiCartucho",
        )
        dpg.add_button(label="Abrir", width=480, callback=on_startup_open)
        dpg.add_separator()
        dpg.add_button(
            label="Continuar sin proyecto",
            width=480,
            callback=on_startup_skip_project,
        )
        dpg.add_spacer(height=6)
        dpg.add_input_text(
            tag="ts_startup_log",
            label="Mensajes",
            multiline=True,
            readonly=True,
            width=480,
            height=72,
            default_value="",
        )

    with dpg.window(
        tag="ts_main",
        label="TurtleStudio",
        no_resize=False,
        show=False,
    ):
        with dpg.menu_bar():
            with dpg.menu(label="Proyecto"):
                dpg.add_menu_item(
                    tag="ts_menu_save_project",
                    label="Guardar proyecto",
                    callback=on_save_project,
                    enabled=False,
                )
                dpg.add_menu_item(
                    label="Cambiar proyecto…",
                    callback=show_project_startup_dialog,
                )

        with dpg.group(horizontal=True):
            with dpg.child_window(width=_LEFT_PANEL_WIDTH, border=True):
                dpg.add_text("Cartucho / paleta")
                dpg.add_text(
                    "El Lua se edita a la derecha.",
                    wrap=_LEFT_TEXT_WRAP,
                )
                dpg.add_input_text(
                    tag="ts_pal_path",
                    label="Paleta (opc.)",
                    width=_LEFT_FORM_WIDTH,
                    hint="palette.txt",
                    use_internal_label=False,
                )
                dpg.add_input_text(
                    tag="ts_out_path",
                    label="Salida .turtlecart",
                    width=_LEFT_FORM_WIDTH,
                    default_value="cart.turtlecart",
                    use_internal_label=False,
                )
                dpg.add_input_text(
                    tag="ts_entry",
                    label="ENTRY (nombre en cartucho)",
                    width=_LEFT_FORM_WIDTH,
                    default_value="main.lua",
                    hint="p. ej. main.lua",
                    use_internal_label=False,
                )
                dpg.add_checkbox(
                    tag="ts_write_lua_file",
                    label="Guardar .lua junto al cartucho",
                    default_value=True,
                    use_internal_label=False,
                )
                dpg.add_separator()
                dpg.add_text("Importar script (opc.)")
                dpg.add_input_text(
                    tag="ts_import_lua_path",
                    label="Ruta .lua",
                    width=_LEFT_FORM_WIDTH,
                    hint="/ruta/a/main.lua",
                    use_internal_label=False,
                )
                dpg.add_button(
                    label="Cargar en editor",
                    width=_LEFT_FORM_WIDTH,
                    callback=on_load_lua_from_file,
                )
                dpg.add_button(
                    tag="ts_btn_save_project",
                    label="Guardar proyecto",
                    width=_LEFT_FORM_WIDTH,
                    callback=on_save_project,
                    enabled=False,
                )
                dpg.add_button(
                    label="Exportar .turtlecart",
                    width=_LEFT_FORM_WIDTH,
                    callback=on_export,
                )
                dpg.add_separator()
                dpg.add_text("Escenas (proyecto)")
                dpg.add_combo(
                    tag="ts_scene_combo",
                    label="Escena activa",
                    width=_LEFT_FORM_WIDTH,
                    items=["main"],
                    default_value="main",
                    callback=on_scene_combo,
                    enabled=False,
                    use_internal_label=False,
                )
                dpg.add_input_text(
                    tag="ts_scene_pal",
                    label="Paleta (ruta relativa al proyecto)",
                    width=_LEFT_FORM_WIDTH,
                    hint="palettes/palette.txt",
                    enabled=False,
                    use_internal_label=False,
                )
                dpg.add_button(
                    tag="ts_btn_new_scene",
                    label="Nueva escena",
                    width=_LEFT_FORM_WIDTH,
                    callback=on_new_scene,
                    enabled=False,
                )
                dpg.add_input_int(
                    tag="ts_transparent_idx",
                    label="Indice transparente (chroma)",
                    width=_LEFT_FORM_WIDTH,
                    default_value=DEFAULT_TRANSPARENT_INDEX,
                    min_value=0,
                    max_value=31,
                    min_clamped=True,
                    max_clamped=True,
                    enabled=False,
                    use_internal_label=False,
                )
                dpg.add_separator()
                dpg.add_text("Escena / canvas")
                dpg.add_button(
                    label="Recargar paleta en canvas",
                    width=_LEFT_FORM_WIDTH,
                    callback=on_reload_palette_click,
                )
                dpg.add_text(
                    "Fondo = indice en esa paleta (misma que el cartucho).",
                    wrap=_LEFT_TEXT_WRAP,
                )
                dpg.add_text("Color de fondo")
                with dpg.group(horizontal=True):
                    dpg.add_combo(
                        tag="ts_bg_combo",
                        width=_LEFT_BG_COMBO_WIDTH,
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
                    width=_LEFT_FORM_WIDTH,
                    height=100,
                    default_value="",
                    use_internal_label=False,
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

    dpg.create_viewport(
        title="TurtleStudio",
        width=1080,
        height=760,
    )
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("ts_startup", True)
    dpg.start_dearpygui()
    dpg.destroy_context()
    return 0
