# Fisica de plataformero (v0)

Contrato **Lua + C++** para personajes con gravedad, suelo y colision con **tiles** de escena.

Ver tambien: [object-script-v0.md](object-script-v0.md), [firmware-bridge-v0.md](firmware-bridge-v0.md), [scene-v0.md](../scene-v0.md).

## Division de responsabilidades

| Capa | Que hace |
|------|----------|
| **Lua** | Velocidad (`vx`, `vy`), gravedad, salto, input |
| **C++** | Colision del AABB del objeto con tiles solidos, `on_ground()`, resolver `move` |

Inspiracion: Godot `move_and_collide` **lite** (por ejes, sin slide en rampas).

## Colision (C++)

### AABB del objeto

Se lee del JSON del objeto (`objects/<id>.json`), campo opcional **`collision`**:

```json
"collision": {
  "mode": "aabb",
  "x0": -7,
  "y0": 0,
  "x1": 6,
  "y1": 16
}
```

Coordenadas **locales al ancla** del sprite en escena (pies en `(0,0)`, Y hacia arriba). Ver [sprite-v0.md](../sprite-v0.md).

Si falta `collision`, el firmware usa el rectangulo del sprite segun `origin`.

### Tiles solidos

Celdas de **`tile_layers`** en la escena activa con indice distinto de **`transparent_index`** del bundle (por defecto 31) cuentan como solidas. Capas con `"enabled": false` se ignoran.

### `move(dx, dy)` (v1)

1. Resuelve **X** en pasos de 1 px (para hasta `|dx|`).
2. Resuelve **Y** en pasos de 1 px.
3. Si al bajar (`dy < 0` en espacio escena) choca con tile, marca **grounded**.
4. Al final, si aun no hay grounded, prueba apoyo bajo los pies (`on_ground`).

Clamp al borde de escena usa el AABB de colision (no solo el sprite).

## API Lua (v1)

| Funcion | Descripcion |
|---------|-------------|
| `move(dx, dy)` | Movimiento con colision por ejes (enteros; fracciones redondeadas en Lua). |
| `on_ground()` | `true` si el actor apoya en tile solido justo debajo del AABB o en `y = 0` de escena. |

`on_ground()` refleja el estado **despues** del ultimo `move()` del mismo fotograma.

### Gravedad en Lua (convencion)

Espacio escena: **Y hacia arriba**. Caida = velocidad vertical negativa:

```lua
if on_ground() then
  vy = 0
else
  vy = vy - gravity * dt
end
move(mx, math.floor(vy * dt + (vy >= 0 and 0.5 or -0.5)))
```

### Salto en Lua

Impulso vertical al pulsar **A** (`btnp(4)`), solo si `on_ground()` al inicio del fotograma (estado del `move` anterior):

```lua
local jump_speed = 240  -- px/s, positivo = subir

if on_ground() then
  if vy < 0 then
    vy = 0
  end
  if btnp(4) then  -- BTN_A
    vy = jump_speed
  end
else
  vy = vy - gravity * dt
end
```

Altura aproximada del salto: `jump_speed² / (2 * gravity)` (p. ej. 240 y 420 → ~69 px).

## Ejemplo plataformero

Ver `scripts/character.lua` en demo1: LEFT/RIGHT, gravedad y salto con **A**.

## Fuera de alcance v0

- `move_and_slide` / normales de superficie
- Plataformas one-way, knockback, rebotar en techo
- Colision entre actores
- Colision con objetos (solo tiles + borde de escena)

## Evolucion (v1+)

- Colision actor-actor

## Implementacion

- `firmware/TurtleReader/turtle_scene.cpp` — AABB, tiles, `move`, `on_ground`
- `firmware/TurtleReader/turtle_actor_lua.cpp` — `on_ground()` en Lua
