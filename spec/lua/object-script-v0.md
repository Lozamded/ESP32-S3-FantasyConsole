# Scripts de objeto (v0)

Logica por **instancia** de objeto en escena: lectura de entrada, movimiento y (mas adelante) cambio de animacion o estado. El **dibujo** del sprite y el loop de fotogramas del asset siguen en C++ (`turtle_scene`); Lua decide comportamiento y posicion.

## Enlace en el proyecto (TurtleStudio)

En el JSON del objeto (`objects/Objects/<id>.json` o el exportado `objects/<id>.json` en la SD):

```json
{
  "id": "character",
  "sprite_id": "character_idle",
  "script": "character"
}
```

- **`script`**: stem del archivo, **sin** `.lua`. Opcional; si falta, el actor no ejecuta Lua.
- Archivo en el proyecto: `scripts/<stem>.lua` (misma regla que scripts de escena).
- Stem valido: letra inicial, luego letras, digitos, `_` o `-` (max 64 caracteres; misma validacion que ids de escena en TurtleStudio).

En la pestaña **Objetos** de TurtleStudio puedes editar el stem y usar **Crear .lua en scripts/** para generar la plantilla.

## Paquete en microSD

TurtleStudio copia al export (`build/`):

- `objects/<id>.json` (incluye `"script"` si esta definido)
- `scripts/<stem>.lua` para cada objeto con `"script"`, cada escena (stem por `id` o campo `script`) y el ENTRY (`scripts/global.lua` por convencion)
- El ENTRY va tambien **embebido** en `main.turtlecart`; la copia en `scripts/` es la misma fuente para depuracion y coherencia con el firmware

Ruta en la SD (raiz del volumen):

```text
/scripts/character.lua
/objects/character.json
```

El firmware abre `/scripts/<stem>.lua` con el stem del JSON del objeto colocado en la escena activa.

## Ciclo de vida (firmware)

1. Arranque: se ejecuta el Lua de **`ENTRY`** del cartucho (una sola vez; ver `spec/turtlecart-v0.md`).
2. Si hay bundle y `INITIAL_SCENE`, `turtle_scene_begin_runtime` dibuja fondo/tiles, crea **actores** por cada colocacion en la escena y arranca la VM de scripts de objeto.
3. Cada fotograma del loop de juego (segun `target_fps` del bundle/escena):
   - `turtle_input_poll()`
   - Para cada actor con script cargado: **`_update(dt)`** con `dt` en **segundos** (`float`, p. ej. `0.033` a ~30 FPS)
   - Animacion de sprites y redibujado en C++

Un actor = una entrada en la lista `objects` de la escena (posicion inicial `x`, `y` en espacio escena).

## Contrato del script

Al cargar el archivo, el runtime ejecuta el chunk completo (definiciones `local`, etc.) y exige una funcion global:

```lua
function _update(dt)
  -- dt: segundos desde el fotograma anterior
end
```

Si falta `_update` o el archivo no existe en la SD, se registra aviso en Serial y ese actor no recibe tick Lua.

### Contexto implicito

No hay `self` en v0: las funciones de movimiento y posicion actuan sobre el **actor cuyo script se esta ejecutando** en ese fotograma. Varios objetos pueden compartir el mismo stem (misma logica, distinta instancia y posicion).

## API Lua (v0)

### Entrada

Ver indices en **`spec/input-v0.md`**.

| Funcion | Descripcion |
|---------|-------------|
| `btn(i)` | `true` si el boton `i` esta pulsado (sostenido). |
| `btnp(i)` | `true` solo en el fotograma del flanco pulsado. |
| `axis(neg, pos)` | Entero **-1**, **0** o **1**: resta 1 si `btn(neg)`, suma 1 si `btn(pos)`. Util para ejes (izq/der, abajo/arriba). |

Ejemplo eje vertical en espacio escena (Y hacia arriba):

```lua
local dy = axis(BTN_DOWN, BTN_UP)  -- abajo = -1, arriba = +1
```

### Posicion y movimiento

Coordenadas en **espacio escena** (164×124, origen abajo-izquierda, Y hacia arriba): **`spec/scene-v0.md`**.

| Funcion | Descripcion |
|---------|-------------|
| `posx()` | Posicion X actual del actor (entero). |
| `posy()` | Posicion Y actual del actor (entero). |
| `move(dx, dy)` | Movimiento con **colision por ejes** contra tiles solidos y borde de escena. Ver **`spec/lua/physics-v0.md`**. |
| `on_ground()` | `true` si el actor apoya sobre tile o suelo de escena (tras el ultimo `move` del frame). |

### Animacion

Ver **`spec/lua/animation-v0.md`**. Nombres definidos en `animations` del JSON del objeto.

| Funcion | Descripcion |
|---------|-------------|
| `set_anim(anim)` | Sprite en loop, velocidad 1; no reinicia si ya esta en `anim`. |
| `play_anim(anim, speed, repeat)` | Cambia sprite; `speed` float; `repeat` bool; reinicia en fotograma 0. |
| `flip_h(flip)` | Espejo **horizontal** del sprite (`true` = mirar izquierda). Eje: ancla del sprite en escena. |

Convencion recomendada para velocidad horizontal:

```lua
move(dx * speed * dt, dy * speed * dt)
```

Gravedad vertical (Y escena hacia arriba): ver ejemplo en **`spec/lua/physics-v0.md`**.

### Depuracion

| Funcion | Descripcion |
|---------|-------------|
| `print(...)` | Salida a Serial (como en ENTRY). |

### Fuera de alcance en v0 (scripts de objeto)

- `cls`, `pix`, `spix`, `flip` (reservados al ENTRY / futuro bucle global).
- Colision entre actores; slide en rampas (`move_and_slide`).
- Scripts por escena (`scene.script` en manifest): reservado; misma carpeta `scripts/` cuando se implemente.

## Ejemplo plataformero

`scripts/character.lua` (demo1):

```lua
local walk_speed = 85
local jump_speed = 240
local gravity = 420
local vy = 0

function _update(dt)
  -- LEFT/RIGHT, salto, gravedad, move; set_anim(idle/walk/jump/fall)
  -- Ver spec/lua/physics-v0.md y animation-v0.md
end
```

## Ejemplo top-down (8 direcciones)

```lua
local walk_speed = 120
local rem_x, rem_y = 0.0, 0.0

function _update(dt)
  local dx = axis(BTN_LEFT, BTN_RIGHT)
  local dy = axis(BTN_DOWN, BTN_UP)
  -- ... acumulador + move(mx, my) sin gravedad
end
```

`objects/character.json` debe incluir `"script": "character"` y la escena debe colocar el objeto `character`.

## Implementacion de referencia

- `firmware/TurtleReader/turtle_actor_lua.cpp` — VM, carga SD, `_update`
- `firmware/TurtleReader/turtle_scene.cpp` — actores, `move` / clamp, tick de escena
- `tools/turtlestudio/src/turtlestudio/build.py` — export de `scripts/*.lua`
- `tools/turtlestudio/src/turtlestudio/objects.py` — campo `script` en objeto

## Evolucion sugerida (v1+)

- `on_collide(other)` o capa de fisica
- Constantes globales `LEFT`, `RIGHT`, … en Lua
- Unificar ENTRY y objetos en una API compartida (ENTRY: **`spec/lua/entry-v0.md`**)
