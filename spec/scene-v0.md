# Especificacion de escena y coordenadas (v0)

Documento **pre-paso 1**: define el espacio logico en el que un cartucho `.turtlecart` piensa el juego. El firmware y las herramientas (generador de cartuchos, editores) deben respetar este contrato para no mezclar convenciones.

## Escena basica (canonica)

- **Vista (viewport)** en consola: **164 × 124** píxeles logicos (lo que muestra el panel).
- **Mundo** opcionalmente mas grande: en el manifest de escena, `world_steps_x` y `world_steps_y` (enteros **1..2**) multiplican la vista. Ejemplo: `world_steps_x: 2` → ancho **328** (dos “pantallas” horizontales). Por defecto ambos son **1** (mundo = vista).
- El **firmware** recorta al viewport con camara configurable (`camera` en manifest / `scenes/<id>.json`):
  - **`mode`**: `follow` (por defecto) o `fixed`.
  - **`target`**: id de objeto a seguir (vacio = `character`, luego `player`, luego el primero de `objects`).
  - **`x`, `y`**: esquina inferior izquierda del viewport en espacio escena (`fixed`, o posicion inicial en `follow`).
  - **`margin_x`, `margin_y`**: distancia en pixeles al borde del viewport antes de desplazar la camara (solo `follow`).
- TurtleStudio dibuja un **marco naranja** del tamano de pantalla en el canvas cuando el mundo es mayor que la vista.
- Una escena ocupa un rectangulo alineado a los ejes; no hay “letterbox” dentro del viewport.

## Bandas de parallax horizontal (`parallax_bands`)

Array opcional en el bloque de la escena, junto a `camera`/`world_steps_x`/`world_steps_y`. Divide el fondo de **capa 1** (`background_layers[0].background`, horneado en `s_world_bg` junto a los tiles — ver seccion siguiente) en rangos Y con su propio factor de scroll horizontal — el efecto clasico de plataformero (nubes lejanas casi fijas, colinas a media velocidad, primer plano a la velocidad de la camara). Capa 1 es la **unica** capa elegible para `parallax_bands`; las capas 2-4 solo admiten un factor de scroll uniforme (ver seccion siguiente).

```json
"parallax_bands": [
  { "y0": 88, "y1": 123, "parallax_x": 1.0 },
  { "y0": 44, "y1": 87,  "parallax_x": 0.5, "repeat_x": true },
  { "y0": 0,  "y1": 43,  "parallax_x": 0.15, "repeat_x": true }
]
```

- **`y0`/`y1`**: rango Y de escena (inclusive, Y hacia arriba, mismo sistema que el resto de este documento). Si `y0 > y1` se intercambian; ambos se acotan a `[0, world_h-1]`.
- **`parallax_x`**: factor de scroll horizontal, acotado **0.0..2.0**. `1.0` = igual que la camara (comportamiento de hoy); menor que 1 = fondo lejano (mas lento); mayor que 1 = capa "encima" del primer plano (mas rapida).
- **`fixed`** (bool, default `false`): ignora la camara del todo (offset horizontal siempre 0) — util para una banda estatica (p. ej. un cartel de titulo).
- **`repeat_x`** (bool, default `false`): la columna de muestreo se repite (`modulo` el ancho del bitmap de fondo) en vez de recortarse en los bordes — necesario para bandas lentas (`parallax_x < 1`) que si no se quedarian sin pixeles de origen antes de que la camara llegue al borde del mundo.
- **Limite: 8 bandas** por escena. Filas de escena sin `parallax_bands` (o vacio) usan exactamente el comportamiento de hoy — no hay regresion posible. En TurtleStudio, el grupo "Bandas de parallax" tiene un checkbox que activa/desactiva la lista para la escena completa; con el checkbox activo se agregan/quitan bandas una por una (igual que la lista de objetos), no hay filas fijas.
- Filas de la escena (`scene_y`) que no caen dentro de ninguna banda activa se comportan igual que sin bandas: `parallax_x=1.0`, `fixed=false`, `repeat_x=false`.
- **Efecto en tiles**: como capa 1 se hornea junto a los tiles en el mismo `s_world_bg` (ver seccion siguiente), una banda con `fixed=true` o `parallax_x != 1.0` re-samplea esa fila del buffer entero al dibujar (`paint_world_background_banded` en `turtle_scene.cpp`) — si esa fila tambien tuviera tiles horneados ahi, el offset de la banda los afectaria a ellos tambien (tiles "pegados" a la camara o desfasados, aunque las bandas deberian tocar solo el fondo). Por eso, en cuanto la escena define **cualquier** `parallax_bands`, el firmware se salta el horneado de tiles por completo (`prepare_world_static_composite`) y los redibuja en vivo cada fotograma con la camara plana — mismo mecanismo (y mismo costo por fotograma) que activar una capa 2-4, ver "Orden de pintado vs. tiles" mas abajo.

### Fuera de alcance v0

- `parallax_y` (factor de scroll vertical, global o por banda).
- `repeat_y` por banda (envolver verticalmente dentro de una banda).
- Bandas en mas de un fondo: `parallax_bands` sigue siendo exclusivo del `background` principal de la escena. Ver siguiente seccion para fondos adicionales (`background_layers`), que solo admiten un factor de scroll uniforme, no bandas por fila.

## Capas de fondo con imagen (`background_layers`)

Un unico array de **4 capas** es la **unica** forma de asignar el fondo de una escena — no existe
un campo `background` suelto a nivel de escena (version anterior a esta unificacion; carts ya
exportados en ese formato se siguen leyendo por compatibilidad, ver "Migracion" mas abajo).
**Capa 1** (indice `0`) es la **capa base**: su `background`, si tiene, se hornea junto a los
tiles en el mismo buffer de mundo estatico (`s_world_bg`, dibujado una vez por escena, no cada
fotograma) y es la **unica** capa elegible para `parallax_bands` (seccion anterior). **Capas 2-4**
(indices `1..3`) son independientes: cada una vive en su propio buffer, se repinta cada fotograma
y solo admite un factor de scroll **uniforme** (toda la imagen a la misma velocidad) — mas simple
y mas barato de renderizar que bandas por fila, pero sin la optimizacion de "horneado una vez" de
la capa base.

```json
"background_layers": [
  { "enabled": true, "color_index": 1, "opacity": 255,
    "background": "sky_main" },
  { "enabled": true, "color_index": 1, "opacity": 255,
    "background": "clouds_far", "parallax_x": 0.2, "repeat_x": true },
  { "enabled": true, "color_index": 1, "opacity": 255,
    "background": "hills_mid", "parallax_x": 0.5, "repeat_x": true },
  { "enabled": false, "color_index": 1, "opacity": 255 }
]
```

- **`background`** (string, default `""`): id de un asset en `backgrounds/` (`.tbg`/`indexed_pixels`). Vacio = comportamiento de siempre (solo color plano via `color_index`/`opacity`, para el `cls()`).
- **`parallax_x`** / **`fixed`** / **`repeat_x`** (solo capas 2-4; sin efecto en capa 1, que usa `parallax_bands` en su lugar): mismo significado y limites que en `parallax_bands` (0.0..2.0, offset 0 si `fixed`, `modulo` el ancho propio de la imagen si `repeat_x`). Matematicamente equivale a una sola banda de `parallax_bands` que cubre toda la altura de la capa.
- **`color_index`/`opacity`** no cambian de significado: siguen siendo solo para el `cls()` de respaldo (`firmware_background_index_from_layers` en TurtleStudio); no se usan para mezclar con la imagen de la capa (sin alpha blending, ver mas abajo).
- **Anclaje**: cada capa se ancla en la esquina inferior del mundo (`scene_y` 0); filas de escena por encima de la altura propia de la imagen (`pixel_h` de ese asset) simplemente no se pintan por esa capa — no hay offset vertical configurable en v0.
- **Costo real, no gratis (capas 2-4)**: cada una reserva **su propio buffer** en RAM (PSRAM si hay, DRAM si no) del tamano de esa imagen (`pixel_w × pixel_h` bytes, 1 byte/pixel indexado) — **ademas** del buffer de mundo (`s_world_bg`, hasta 328×248 = 81 344 bytes, que ya incluye la imagen de capa 1 horneada). Capas 2-4 no se hornean (cada una debe poder desplazarse a su propio ritmo), asi que se repintan por separado cada fotograma con scroll — una pasada extra por capa habilitada. No hay un tope de PSRAM documentado en este repo para verificar contra el, asi que probar en hardware real es la unica forma de confirmar que un proyecto concreto cabe. Recomendado: imagenes pequenas (p. ej. el ancho de una pantalla) con `repeat_x: true` para las capas lejanas, en vez de imagenes del tamano del mundo completo.
- **Orden de pintado vs. tiles**: capas 2-4 van **por debajo de los tiles** (encima solo de capa 1). Como capa 1 + tiles normalmente se hornean juntos en `s_world_bg` (una sola pasada, sin costo por fotograma), lograr ese orden con capas 2-4 en medio exige un costo extra: en cuanto una escena tiene alguna capa 2-4 habilitada, el firmware **no hornea los tiles** (`prepare_world_static_composite` en `turtle_scene.cpp` se salta `bake_tile_layers_into_world`) y en su lugar los vuelve a dibujar en vivo cada fotograma, despues de pintar las capas 2-4, con el mismo camino que ya existia para el caso sin buffer de mundo (`draw_tile_layers_for_scene`). Es decir: usar cualquier capa 2-4 le agrega a la escena el costo de redibujar tiles cada fotograma, no solo el de la capa en si. Escenas sin capas 2-4 habilitadas no pagan esto — siguen horneando tiles una sola vez, como siempre. Una escena con `parallax_bands` (seccion anterior) paga el mismo costo por la misma razon (evitar que el resample por banda alcance a los tiles), aunque no tenga ninguna capa 2-4 habilitada.
- **Migracion desde el campo `background` suelto**: TurtleStudio mueve automaticamente ese valor a `background_layers[0].background` la primera vez que abre o guarda un proyecto viejo (`project.py`, `_normalize_scenes_for_save`/`_parse_scenes_from_manifest`). El firmware, por su parte, sigue aceptando el campo suelto como respaldo si `background_layers[0].background` esta vacio (`resolve_scene_base_background_id` en `turtle_scene.cpp`) — para no romper carts ya exportados sin tener que reexportarlos.

### Fuera de alcance v0 (capas con imagen)

- Mezcla alfa / opacidad real entre capas (el motor no hace blending en ningun otro lugar; una capa es opaca donde su indice no es el transparente, y no se dibuja si `enabled=false`).
- Offset vertical por capa / `parallax_y` por capa (2-4).
- Bandas por fila dentro de una capa 2-4 (solo capa 1 las admite, via `parallax_bands`).
- Capas con imagen en escenas sin scroll (`world_steps_x`/`world_steps_y` = 1): solo se renderizan cuando la escena usa camara con scroll.

## Sistema de coordenadas (espacio escena)

- **Origen (0, 0)**: esquina **inferior izquierda** del rectangulo de escena.
- **Eje X**: positivo hacia la **derecha**.
- **Eje Y**: positivo hacia **arriba** (convencion “matematica” / muchos motores 2D).

### Rango y malla de píxeles

- Las coordenadas son **enteras** para direccionar celdas de una cuadricula de **164 columnas × 124 filas**.
- **Rango valido** para dibujar un píxel en la escena:
  - `x` ∈ **{ 0, 1, …, 163 }**
  - `y` ∈ **{ 0, 1, …, 123 }**
- El píxel en `(x, y)` es la celda cuya esquina inferior izquierda coincide con el punto `(x, y)` en este sistema.

## Relacion con el framebuffer del runtime (hoy)

El buffer que usa el firmware para `pix()` y el panel sigue la convencion habitual de **raster**: la fila **0** es la **superior** de la imagen y **Y aumenta hacia abajo**.

Para pasar de **coordenadas de escena** `(sx, sy)` a **coordenadas de framebuffer** `(xfb, yfb)` con `H = 124`:

```text
xfb = sx
yfb = (H - 1) - sy
```

**Firmware**: ademas de `pix(xfb, yfb, c)` (framebuffer raster), existe **`spix(sx, sy, c)`** que aplica la conversion anterior. Para juego nuevo conviene usar **`spix`** y dejar `pix` para primitivas internas o codigo legado.

Las **herramientas** y la **documentacion de cartuchos** deben hablar en **espacio escena** `(sx, sy)` salvo que se indique lo contrario.

## Que es una “escena” en el cartucho (v0)

En **v0** no hace falta un bloque obligatorio en el `.turtlecart`: si no se declara nada, se asume la **escena canonica** (164×124, sistema de coordenadas anterior).

Mas adelante se puede anadir, por ejemplo:

- un archivo embebido `scene.toml` / `scene.json`, o
- un bloque `SCENE:` en texto,

con campos como nombre, limites, gravedad, capas, etc. Fuera de alcance de este documento hasta que se versione `TURTLECART:1` o un perfil de escena.

## Transparencia (chroma key, convencion TurtleStudio)

Para **sprites indexados**, fondos con pixeles indexados (futuro) y herramientas, el **ultimo indice de la paleta de 32 colores** es siempre transparente al componer:

- **Indice fijo: 31** (base 0; el “color 32” si se cuenta desde 1). Valido en **cualquier** archivo de paleta del proyecto, independientemente de cuantos `#RRGGBB` tenga el `.txt`.
- Ese indice puede tener un color en la paleta (util para previsualizar el recorte en el editor); al blitear `indexed_pixels`, el runtime **no copia** pixeles con ese indice.
- TurtleStudio **no permite seleccionar** el 31 como pincel ni como indice de fondo/capa; solo como valor guardado en matrices (`image.rows`).

El manifest (`turtlestudio.json`) y el bundle (`studio/project_bundle.json`) pueden incluir `transparent_index` por compatibilidad; herramientas y firmware lo tratan como **31** siempre.

Detalle de sprites y modos de dibujo: **`spec/sprite-v0.md`**.

## Escenas en proyecto TurtleStudio (manifest)

En la carpeta de proyecto, `turtlestudio.json` puede incluir una lista **`scenes`**: cada entrada tiene `id` (identificador unico; por defecto la primera escena suele ser **`intro`**, p. ej. titulo o logo), **`script`** (stem del archivo `scripts/<script>.lua` con la logica Lua de esa escena), `palette` (ruta relativa a un archivo de paleta en el proyecto, p. ej. `palettes/nivel1.txt`) y opcionalmente **`background_index`** (entero `0..N-1` con `N` = numero de colores en esa paleta; indice de fondo para la vista previa del estudio, alineado con `cls()` en el cartucho). El id **`main` esta reservado** (no usar como escena: corresponde al nombre del cartucho inicial `main.turtlecart`). El campo **`active_scene`** indica la escena seleccionada en TurtleStudio para vista previa y edicion. El **`entry`** del manifest apunta al Lua de arranque del cartucho (en TurtleStudio se convenciona `scripts/global.lua`, cuyo texto se embebe como bloque `ENTRY` en `main.turtlecart`). Al exportar ese cartucho inicial, las herramientas pueden embeber solo `studio/project_bundle.json` ademas del `ENTRY`; los Lua de escena en disco **no** se copian obligatoriamente al mismo archivo (pueden distribuirse en otros `.turtlecart` o archivos cuando el runtime lo permita). Esto no sustituye aun un bloque `SCENE:` en el `.turtlecart` v0; el cartucho sigue usando la paleta embebida opcional y el script `ENTRY` como hasta ahora.

Ademas, al guardar proyecto TurtleStudio puede generar un **espejo** por escena en `scenes/<id>.json` (`kind: "turtlestudio.scene"`, `id`, `palette`, `background_index` = indice de color de fondo en esa paleta para vista previa en el estudio) para revision en Git o edicion externa; **al abrir el proyecto la fuente de verdad sigue siendo el manifest** para no divergir listas de escenas.

## Vista previa TurtleStudio (canvas)

- Las **cuatro capas de fondo** admiten opacidad `0..255` en el manifest; el estudio las mezcla en la vista previa en el mismo orden que el firmware las pinta (capa 1 primero, luego 2-4) — incluida la imagen de cada capa si tiene `background`, no solo el color plano de respaldo.
- Hasta **cuatro capas de tiles** por escena (`tile_layers` en el manifest y en `scenes/<id>.json`): cada capa tiene `enabled`, `tileset` (stem de `tiles/<tileset>.json`) y `cells` (matriz de indices de tile en la rejilla de la escena). Solo se listan tilesets cuya `palette` coincide con la de la escena. La rejilla usa `tiles.tile_px` del proyecto (multiplo de 8, default 8 — estandar tipo GB/GG). Celda vacia = indice **31** (transparente). El editor pinta con clic / arrastrar en el canvas de escena (capa activa + tile elegido). En el panel de escena, el **pincel** es una fila de miniaturas (T0, T1, …) del tileset activo; clic en una para seleccionarla (borde amarillo). En el canvas, **Rejilla tiles** dibuja lineas cada `tile_px` px; con capa tile activa, la celda bajo el cursor se resalta en amarillo.
- **Collision por tile** (TurtleStudio, pestaña Tiles): en `tiles/<id>.json`, cada entrada de `tiles[]` puede llevar `collision`: omitido o `"solid"` = celda entera solida (defecto); `"none"` = decoracion (sin bloqueo); objeto con `mode` `aabb` (y en JSON tambien `triangle` / `hexagon` como en objetos) = forma en espacio local del tile, origen **(0,0)** esquina inferior izquierda, **Y hacia arriba**. Opcional **`oneway`** + **`oneway_direction`** (`up` | `down` | `left` | `right`): collision unidireccional (en el estudio: casilla + combo de direccion); con forma custom van dentro del objeto `collision`, con solido van al mismo nivel que `image`. **TurtleReader** carga metadatos desde `tiles/<id>.json` en la SD (o `tiles[]` inline en el bundle) al resolver el `.tts`; `triangle`/`hexagon` se aproximan por caja (AABB de los puntos).
- **Capa de colision** (`collision_tile_layer`, entero 0-3 a nivel de escena, defecto **0**): de las hasta cuatro capas de tiles, **solo una** bloquea actores — el firmware (`tile_cell_blocks_actor` en `turtle_scene.cpp`, via `s_runtime_collision_tile_layer`) ignora el metadato `collision`/`oneway` de las otras tres capas por completo, aunque sus tiles esten marcados `solid`. Pensado para poder pintar decoracion (arboles de fondo, detalles de primer plano) en capas 2-4 con un tileset que tambien tenga tiles solidos en otro contexto, sin que bloqueen el paso. TurtleStudio expone un combo **Capa de colision** en el grupo "Capas de tiles" del editor de escena; el simulador **Play** (`play_runtime.py`, `TileCollisionIndex`) respeta el mismo indice para que la prueba en el editor coincida con hardware. Compatibilidad: escenas sin el campo (carts ya exportados) se comportan igual que antes siempre que solo usen la capa 1 — el unico caso real hoy en los proyectos de ejemplo.
- La **capa de sprites** (objetos colocados en la escena) tiene en el editor **Mostrar sprites** y **Opacidad sprites (vista previa)** `0..255`; no se guarda en el proyecto. Las cruces de ancla siguen visibles para colocar objetos.

## Objetos y capas (v0)

- **v0**: no hay formato obligatorio de “lista de entidades” en el cartucho.
- Un juego puede dibujar solo con Lua (`pix`, primitivas propias) o con datos embebidos cuando el runtime los soporte.

## Resumen para compiladores / generadores

1. Tratar **164×124** como tamano de **vista**; mundo = pasos × vista (v0: pasos 1 o 2 por eje).
2. Emitir posiciones y disenos pensando **Y hacia arriba** y **(0,0) abajo-izquierda**.
3. Si el generador emite Lua que llama al `pix()` actual del firmware, aplicar la conversion `yfb = 123 - sy` (o `H-1` con `H=124`) al generar coordenadas.
4. Los scripts de objeto usan **`move(dx, dy)`** y **`posx()` / `posy()`** directamente en espacio escena; ver **`spec/lua/object-script-v0.md`**.
