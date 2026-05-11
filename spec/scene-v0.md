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

## Objetos y capas (v0)

- **v0**: no hay formato obligatorio de “lista de entidades” en el cartucho.
- Un juego puede dibujar solo con Lua (`pix`, primitivas propias) o con datos embebidos cuando el runtime los soporte.

## Resumen para compiladores / generadores

1. Tratar **264×198** como tamano unico de escena logica (hasta nueva spec).
2. Emitir posiciones y disenos pensando **Y hacia arriba** y **(0,0) abajo-izquierda**.
3. Si el generador emite Lua que llama al `pix()` actual del firmware, aplicar la conversion `yfb = 197 - sy` (o `H-1` con `H=198`) al generar coordenadas.
