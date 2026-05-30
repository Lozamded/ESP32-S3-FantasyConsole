# Script ENTRY (v0)

El cartucho `.turtlecart` declara un archivo Lua de **arranque** en la linea `ENTRY:` (convencion TurtleStudio: `scripts/global.lua`). El firmware lo ejecuta **una sola vez** durante `setup()`, antes de iniciar el runtime de escena en C++.

Ver formato del cartucho en **`spec/turtlecart-v0.md`**. Para logica por fotograma de objetos en escena, usar **`spec/lua/object-script-v0.md`** (VM distinta, `_update(dt)`).

## Orden de arranque (firmware)

1. Montar microSD, cargar `main.turtlecart` (o fallback `demo.turtlecart`).
2. Cargar bundle sidecar (`studio/project_bundle.json`).
3. Aplicar bloque opcional **`PALETTE:`** del cartucho al framebuffer (32 indices `0..31`).
4. Extraer y ejecutar el bloque embebido `---FILE:<ENTRY>---` (este documento).
5. Cerrar la VM Lua del ENTRY.
6. Si hay bundle: `turtle_scene_begin_runtime` con la escena **`INITIAL_SCENE:`** (por defecto `intro`), que **vuelve a dibujar** el framebuffer (fondo, tiles, sprites).
7. `flip()` para mostrar la escena inicial.

Implicacion: un `cls()` + dibujo en ENTRY **no permanece** si despues arranca el runtime de escena con el mismo bundle; el ENTRY sirve para init, pruebas sin escena, o para ajustar paleta/estado global antes del primer fotograma de C++.

## VM y alcance

| Aspecto | ENTRY | Scripts de objeto |
|---------|-------|-------------------|
| Cuando corre | Una vez en `setup` | Cada fotograma del loop |
| VM Lua | Nueva; se destruye al terminar | Persistente (`turtle_actor_lua`) |
| Graficos | `cls`, `pix`, `spix`, `flip` | No (v0) |
| Movimiento en escena | No `move` / `posx` | Si; ver object-script |

Libreria estandar Lua (`luaL_openlibs`) esta disponible, pero el contrato soportado para juegos portables es solo la API listada abajo.

## Constantes

| Nombre | Valor | Significado |
|--------|-------|-------------|
| `W` | `264` | Ancho del framebuffer logico |
| `H` | `198` | Alto del framebuffer logico |
| `COLORS` | `32` | Indices de color validos `0..31` |

## API grafica

Indices de color: enteros **`0..31`**. Valores fuera de rango se **saturan** (`< 0` → `0`, `>= 32` → `31`). No hay alpha en v0.

### `cls(color_index)`

Limpia todo el framebuffer con el indice dado.

### `pix(x, y, color_index)`

Dibuja un pixel en coordenadas de **framebuffer (raster)**:

- `(0, 0)` = esquina **superior izquierda**
- **Y aumenta hacia abajo**
- `x` ∈ `0 .. W-1`, `y` ∈ `0 .. H-1`
- Coordenadas fuera del rectangulo se ignoran (sin error)

Uso tipico: pruebas rapidas o codigo generado en espacio pantalla. Para juego alineado con el bundle y `move` de objetos, preferir **`spix`**.

### `spix(sx, sy, color_index)`

Dibuja un pixel en **espacio escena** (misma convencion que posiciones de objetos y `spec/scene-v0.md`):

- `(0, 0)` = esquina **inferior izquierda**
- **Y aumenta hacia arriba**
- `sx` ∈ `0 .. 263`, `sy` ∈ `0 .. 197`

Conversion interna: `yfb = (H - 1) - sy`, `xfb = sx`.

### `flip()`

Copia el framebuffer a la pantalla (si `TURTLE_USE_DISPLAY` esta activo) o deja el buffer en RAM. Sin argumentos.

Tras el ENTRY, el firmware llama `flip()` otra vez al terminar de dibujar la escena inicial.

## Entrada

| Funcion | Descripcion |
|---------|-------------|
| `btn(i)` | `true` si el boton `i` esta pulsado. |
| `btnp(i)` | `true` en el flanco pulsado. |

Indices: **`spec/input-v0.md`** (0–3 direccion, 4–7 accion). Indice invalido → **error Lua** (a diferencia del color).

**Limitacion v0:** durante el ENTRY, `turtle_input_poll()` **aun no se ha llamado** (solo corre en `loop()`). `btn` / `btnp` leen el estado tras `turtle_input_init()` (normalmente todo suelto). No uses ENTRY para gameplay con pulsadores; usa scripts de objeto o un bucle global futuro.

No hay `axis()` en ENTRY (solo en scripts de objeto).

## Depuracion

### `print(...)`

Imprime argumentos separados por tabulador y termina en nueva linea en **Serial** (115200 en el sketch por defecto).

## Paleta

Si el cartucho incluye `PALETTE:` con lineas `#RRGGBB` (o `#RGB`), se aplican **antes** de ejecutar el ENTRY (hasta 32 entradas validas; huecos → `#000000`). Sin bloque, paleta por defecto tipo Genesis.

Los indices usados en `cls` / `pix` / `spix` son posiciones en esa tabla, no RGB directo en Lua.

## Ejemplo minimo (TurtleStudio)

`scripts/global.lua` embebido en `main.turtlecart`:

```lua
print("Hola desde TurtleStudio (global)")
cls(1)
flip()
```

Con `INITIAL_SCENE:intro` y bundle en SD, la escena `intro` sustituye el contenido del buffer al paso 6; el `cls(1)` solo se ve si falla el runtime o no hay escena.

## Ejemplo: titulo dibujado en espacio escena

```lua
cls(0)
for sx = 10, 50 do
  spix(sx, 20, 7)
end
flip()
```

## Relacion con otros documentos

- Coordenadas escena vs raster: **`spec/scene-v0.md`**
- Botones y cableado: **`spec/input-v0.md`**
- Campo `ENTRY:` y empaquetado: **`spec/turtlecart-v0.md`**
- `_update(dt)` por objeto: **`spec/lua/object-script-v0.md`**

## Implementacion de referencia

- `firmware/TurtleReader/TurtleReader.ino` — `runCartEntryLua`, orden de `setup`
- `firmware/TurtleReader/turtle_gpu.cpp` — `turtle_gpu_register_lua`
- `firmware/TurtleReader/turtle_input.cpp` — `turtle_input_register_lua`
- `tools/turtlestudio/src/turtlestudio/project.py` — plantilla `_STARTER_GLOBAL_LUA`

## Fuera de alcance en v0 (ENTRY)

- Bucle de juego en Lua (la VM se cierra al acabar el script).
- `move`, `posx`, `posy`, `axis`.
- Cargar escenas o cambiar `sprite_id` desde Lua.
- Audio, texto en pantalla, tablas de tile desde ENTRY.

## Evolucion sugerida (v1+)

- ENTRY opcional que solo configura globals y delega en escena.
- `require` de modulos embebidos en el cartucho.
- Bucle ENTRY + misma API que objetos, o unificar VMs.
- `poll()` / `wait()` para leer entrada durante init interactivo.
