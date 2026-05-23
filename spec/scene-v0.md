# Especificacion de escena y coordenadas (v0)

Documento **pre-paso 1**: define el espacio logico en el que un cartucho `.turtlecart` piensa el juego. El firmware y las herramientas (generador de cartuchos, editores) deben respetar este contrato para no mezclar convenciones.

## Escena basica (canonica)

- **Tamano fijo** de la escena de juego: **264 × 198** unidades (píxeles logicos).
- Una escena ocupa un rectangulo alineado a los ejes; no hay “letterbox” dentro de la escena: el rectangulo completo es el mundo del juego para esta consola.

## Sistema de coordenadas (espacio escena)

- **Origen (0, 0)**: esquina **inferior izquierda** del rectangulo de escena.
- **Eje X**: positivo hacia la **derecha**.
- **Eje Y**: positivo hacia **arriba** (convencion “matematica” / muchos motores 2D).

### Rango y malla de píxeles

- Las coordenadas son **enteras** para direccionar celdas de una cuadricula de **264 columnas × 198 filas**.
- **Rango valido** para dibujar un píxel en la escena:
  - `x` ∈ **{ 0, 1, …, 263 }**
  - `y` ∈ **{ 0, 1, …, 197 }**
- El píxel en `(x, y)` es la celda cuya esquina inferior izquierda coincide con el punto `(x, y)` en este sistema.

## Relacion con el framebuffer del runtime (hoy)

El buffer que usa el firmware para `pix()` y el panel sigue la convencion habitual de **raster**: la fila **0** es la **superior** de la imagen y **Y aumenta hacia abajo**.

Para pasar de **coordenadas de escena** `(sx, sy)` a **coordenadas de framebuffer** `(xfb, yfb)` con `H = 198`:

```text
xfb = sx
yfb = (H - 1) - sy
```

**Firmware**: ademas de `pix(xfb, yfb, c)` (framebuffer raster), existe **`spix(sx, sy, c)`** que aplica la conversion anterior. Para juego nuevo conviene usar **`spix`** y dejar `pix` para primitivas internas o codigo legado.

Las **herramientas** y la **documentacion de cartuchos** deben hablar en **espacio escena** `(sx, sy)` salvo que se indique lo contrario.

## Que es una “escena” en el cartucho (v0)

En **v0** no hace falta un bloque obligatorio en el `.turtlecart`: si no se declara nada, se asume la **escena canonica** (264×198, sistema de coordenadas anterior).

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

- Las **cuatro capas de fondo** admiten opacidad `0..255` en el manifest; el estudio las mezcla en la vista previa (el firmware sigue usando un unico `cls()` hasta soporte multilayer).
- Hasta **cuatro capas de tiles** por escena (`tile_layers` en el manifest y en `scenes/<id>.json`): cada capa tiene `enabled`, `tileset` (stem de `tiles/<tileset>.json`) y `cells` (matriz de indices de tile en la rejilla de la escena). Solo se listan tilesets cuya `palette` coincide con la de la escena. La rejilla usa `tiles.tile_px` del proyecto (multiplo de 4). Celda vacia = indice **31** (transparente). El editor pinta con clic / arrastrar en el canvas de escena (capa activa + tile elegido). En el panel de escena, el **pincel** es una fila de miniaturas (T0, T1, …) del tileset activo; clic en una para seleccionarla (borde amarillo). En el canvas, **Rejilla tiles** dibuja lineas cada `tile_px` px; con capa tile activa, la celda bajo el cursor se resalta en amarillo.
- La **capa de sprites** (objetos colocados en la escena) tiene en el editor **Mostrar sprites** y **Opacidad sprites (vista previa)** `0..255`; no se guarda en el proyecto. Las cruces de ancla siguen visibles para colocar objetos.

## Objetos y capas (v0)

- **v0**: no hay formato obligatorio de “lista de entidades” en el cartucho.
- Un juego puede dibujar solo con Lua (`pix`, primitivas propias) o con datos embebidos cuando el runtime los soporte.

## Resumen para compiladores / generadores

1. Tratar **264×198** como tamano unico de escena logica (hasta nueva spec).
2. Emitir posiciones y disenos pensando **Y hacia arriba** y **(0,0) abajo-izquierda**.
3. Si el generador emite Lua que llama al `pix()` actual del firmware, aplicar la conversion `yfb = 197 - sy` (o `H-1` con `H=198`) al generar coordenadas.
