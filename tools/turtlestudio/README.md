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
