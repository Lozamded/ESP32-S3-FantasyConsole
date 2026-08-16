# TurtleStudio

Herramientas en **Python** para autoría de cartuchos `.turtlecart` (y, más adelante, escenas, paletas y empaquetado).

## Requisitos

- Python **3.10+** recomendado.

## Instalacion (entorno virtual recomendado)

El codigo vive en `src/turtlestudio/`; hay que **instalar el paquete en el venv** (no basta con `pip install -r requirements.txt`).

```bash
cd tools/turtlestudio
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip setuptools
pip install -e .
```

Eso instala **turtlestudio** + **dearpygui** (segun `pyproject.toml`). Luego:

```bash
python -m turtlestudio gui
# o
turtlestudio gui
```

**Si ves `No module named turtlestudio`:** ejecuta `pip install -e .` dentro del venv desde `tools/turtlestudio`.

**Sin instalar el paquete** (solo para una prueba rapida):

```bash
PYTHONPATH=src python3 -m turtlestudio gui
```

## Convenciones

- Espacio de escena y coordenadas: ver `spec/scene-v0.md` (264×198, origen abajo-izquierda, Y hacia arriba).
- Formato cartucho: `spec/turtlecart-v0.md`.
- Sprites y celdas (`cell_px` default **4**): `spec/sprite-v0.md`. Indice de paleta **31** = transparente (no seleccionable como pincel/fondo).
- Proyecto TurtleStudio: el Lua de arranque se edita como `scripts/global.lua` (`entry` en `turtlestudio.json`) y forma el **ENTRY** embebido en **`main.turtlecart`**. Al exportar el paquete SD tambien se copia a **`scripts/`** junto con los Lua de escenas y de objetos con `"script"`. El cart embebe un **bundle delgado** (`studio/project_bundle.json`). Assets graficos: **`backgrounds/*.tbg`**, **`sprites/*.tsp`**, etc. (ver `spec/asset-bin-v0.md`). Copia **`build/`** entera a la SD.
- **Objetos** (`objects/Objects/<id>.json`): campo opcional **`script`** (stem → `scripts/<stem>.lua`). Ver `spec/lua/object-script-v0.md`.

## Comando `gui` (Dear PyGui)

Ventana minima: panel izquierdo (carpeta de export, escena inicial, paleta opcional, **Exportar**). Panel derecho: canvas y editor Lua (ENTRY = `scripts/global.lua` del proyecto). **Exportar paquete SD** escribe `build/` con cartucho, assets binarios, `objects/`, `scripts/` y `COPIAR_A_SD.txt`.

```bash
cd tools/turtlestudio
source .venv/bin/activate   # si usas venv
python -m turtlestudio gui
```

## Comando `build`

Ensambla un cartucho **v0** (texto plano) segun `spec/turtlecart-v0.md`:

```bash
cd tools/turtlestudio
PYTHONPATH=src python3 -m turtlestudio build ruta/al/main.lua -o salida.turtlecart
```

Con paleta (archivo de texto, una linea `#RRGGBB` o `#RGB` por color; lineas que empiezan por `#` y no son hex se ignoran como comentario):

```bash
PYTHONPATH=src python3 -m turtlestudio build main.lua -o cart.turtlecart --palette paleta.txt
```

Nombre logico distinto del archivo (ENTRY / `---FILE:...---`):

```bash
PYTHONPATH=src python3 -m turtlestudio build src/juego.lua --entry main.lua -o cart.turtlecart
```

Ejemplo minimo en `examples/minimal/`.

**Nota:** si el Lua contiene la cadena literal `---END---`, el firmware podria truncar el script; el builder emite un `warnings.warn`.

## Play (playtest en vivo, opcional)

El tab **Play** de la ventana (`turtlestudio gui`) corre la logica real de un proyecto
-- scripts de actor/ENTRY en Lua 5.4, colision, camara -- directamente sobre el estado
en memoria del proyecto, sin build/flash/SD ni emulador. No requiere instalarlo para
usar el resto de TurtleStudio; si `lupa` no esta disponible el tab se deshabilita
mostrando por que, en vez de romper el arranque de la app.

**`pip install lupa` a secas NO sirve**: el wheel de PyPI trae Lua 5.5, una version
distinta a la vendorizada en `firmware/libraries/lua54` (5.4.6) contra la que estan
escritos los scripts de actor. Hay que compilar `lupa` a mano contra esos mismos
fuentes de Lua 5.4.6, para tener paridad exacta con lo que corre en el ESP32-S3:

```bash
cd tools/turtlestudio
source .venv/bin/activate

# 1. Compilar el Lua 5.4.6 vendorizado como libreria estatica de host.
LUA_SRC=../../firmware/libraries/lua54/src
mkdir -p /tmp/liblua54 && cd /tmp/liblua54
gcc -std=c99 -O1 -c "$LUA_SRC"/*.c
ar rcs liblua54.a *.o
cd -

# 2. Bajar el sdist de lupa (NO el wheel) y compilarlo apuntando a esa libreria.
pip download --no-binary lupa --no-deps -d /tmp/lupa_src lupa
cd /tmp/lupa_src && tar xf lupa-*.tar.gz && cd lupa-*/
python3 setup.py build_ext \
  --lua-lib=/tmp/liblua54/liblua54.a \
  --lua-includes="$LUA_SRC" \
  install
```

Verificacion rapida (debe decir `Lua 5.4`, no `5.5`):

```bash
python3 -c "import lupa; print(lupa.LuaRuntime().lua_implementation)"
```

Luego `pip install -e ".[play]"` queda como referencia de la dependencia opcional en
`pyproject.toml`, pero el paso que realmente importa es el build de arriba -- un
`pip install -e ".[play]"` normal, sin este build previo, instalaria el wheel 5.5 y
seria incorrecto para este proyecto.

## Proximos pasos (roadmap interno)

1. ~~CLI `build`~~
2. Helpers coordenadas escena → framebuffer (`yfb = H - 1 - sy`) al generar o plantillar Lua.
3. Varios archivos embebidos en un solo cartucho.
4. Plantillas / assets (tortuga demo) como fuentes separadas.

## Uso (desarrollo, sin instalar)

```bash
cd tools/turtlestudio
PYTHONPATH=src python3 -m turtlestudio --help
```

## Instalacion editable (opcional)

```bash
cd tools/turtlestudio
pip install -e .
turtlestudio --help
```
