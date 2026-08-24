"""Compila scripts Lua a bytecode precompilado Lua 5.4, via lupa compilado contra el
Lua 5.4.6 vendorizado en firmware/libraries/lua54 (ver tools/turtlestudio/README.md,
seccion "Play" -- el mismo build de lupa habilita esto y el tab de Play; el wheel de PyPI
trae Lua 5.5 y NO sirve para esto, ver play_lua_bridge.py).

Segundo modulo (junto con play_lua_bridge.py) que importa lupa. build.py comprueba
lua_bytecode_available() y sigue exportando scripts/*.lua como texto plano si no esta
disponible, en vez de romper el export -- mismo criterio que play_widget.py con el tab de
Play cuando lupa falta.

turtle_actor_lua.cpp (firmware/TurtleReader) carga scripts/<stem>.lua via luaL_loadbuffer,
que acepta texto Lua o un chunk binario precompilado indistintamente (autodetectado por la
firma del chunk) -- no requiere ningun cambio de codigo en el firmware para consumir el
bytecode que produce este modulo.
"""

from __future__ import annotations

try:
    import lupa
except ImportError as _exc:  # pragma: no cover - entorno sin build de lupa
    lupa = None  # type: ignore[assignment]
    _IMPORT_ERROR: Exception | None = _exc
else:
    _IMPORT_ERROR = None


class LuaCompileError(Exception):
    """Error de sintaxis Lua al compilar un script a bytecode (mensaje propio de load())."""


# Runtime propio y separado del de play_lua_bridge.py, en modo bytes crudos
# (encoding=None): string.dump() devuelve binario arbitrario (firma \x1bLua + opcodes),
# NO texto UTF-8 -- un runtime con encoding="utf-8" (como el de ActorLuaBridge, pensado
# para EJECUTAR scripts de verdad con strings de texto) intentaria decodificar ese binario
# como UTF-8 y romperia. Se construye una sola vez y se reutiliza entre compilaciones.
_compiler_lua = None
# None hasta el primer chequeo; despues, "" si todo OK o el motivo si no esta disponible
# (import fallido O build de 32/64 bits desajustado -- ver _ensure_compiler_lua).
_unavailable_reason: str | None = None

# lua_Integer/lua_Number de 32 bits en el firmware real (LUA_32BITS, ver
# firmware/libraries/lua54/src/luaconf.h: activo solo bajo ARDUINO/ESP_PLATFORM). Si
# liblua54.a se compilo sin -DESP_PLATFORM (ver README, seccion "Play", paso 1) el host
# queda con Lua de 64 bits y el bytecode que produce NO pasa el checkHeader del firmware
# (lundump.c) -- el script simplemente no carga ahi (load_script_update_ref falla, sin
# _update nunca se llama, ej. un personaje que no se mueve). math.maxinteger es la forma
# mas simple de distinguir los dos builds desde Python.
_EXPECTED_MAXINTEGER = 2**31 - 1

# Expresion Lua (funcion anonima): compila `src` con nombre de chunk `chunk_name` y
# devuelve su bytecode via string.dump. level=0 en error() porque el mensaje de load() ya
# trae su propia posicion "chunk_name:linea:" -- no hace falta que error() le agregue otra.
_DUMP_CHUNK = b"""
function(src, chunk_name, strip)
  local f, err = load(src, chunk_name)
  if not f then
    error(err, 0)
  end
  return string.dump(f, strip)
end
"""


def _ensure_compiler_lua() -> None:
    global _compiler_lua, _unavailable_reason
    if _compiler_lua is not None or _unavailable_reason is not None:
        return
    if lupa is None:
        _unavailable_reason = f"lupa no disponible: {str(_IMPORT_ERROR) if _IMPORT_ERROR else ''}"
        return
    lua = lupa.LuaRuntime(encoding=None)
    maxint = lua.eval(b"math.maxinteger")
    if maxint != _EXPECTED_MAXINTEGER:
        _unavailable_reason = (
            f"lupa esta compilado con Lua de 64 bits (math.maxinteger={maxint}); el "
            "firmware usa LUA_32BITS (ver firmware/libraries/lua54/src/luaconf.h) y el "
            "bytecode no seria compatible -- recompila liblua54.a con -DESP_PLATFORM "
            '(ver README, seccion "Play", paso 1)'
        )
        return
    _compiler_lua = lua


def lua_bytecode_available() -> bool:
    _ensure_compiler_lua()
    return _compiler_lua is not None


def lua_bytecode_unavailable_reason() -> str:
    _ensure_compiler_lua()
    return _unavailable_reason or ""


def compile_lua_to_bytecode(source: str, chunk_name: str, *, strip: bool = False) -> bytes:
    """Compila `source` (texto Lua) a bytecode Lua 5.4 precompilado.

    `strip` controla si se descarta la info de debug (numeros de linea, nombres de
    locales/upvalues): False (default) la conserva, para que los errores de script en
    tiempo de ejecucion en el firmware sigan reportando "chunk_name:linea:" via
    Serial.printf(lua_tostring(...)) igual que hoy con texto plano.

    Lanza LuaCompileError con el mensaje de Lua si `source` tiene un error de sintaxis, o
    si lua_bytecode_available() es False (llamar solo despues de comprobarlo).
    """
    _ensure_compiler_lua()
    if _compiler_lua is None:
        raise LuaCompileError(lua_bytecode_unavailable_reason())
    dump_fn = _compiler_lua.eval(_DUMP_CHUNK)
    try:
        result = dump_fn(source.encode("utf-8"), chunk_name.encode("utf-8"), strip)
    except Exception as exc:  # lupa.LuaError -- error de sintaxis propagado desde load()
        raise LuaCompileError(str(exc)) from exc
    if not isinstance(result, bytes):
        raise LuaCompileError(f"string.dump no devolvio bytes (tipo {type(result)!r})")
    return result
