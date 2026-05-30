# Entrada de control (v0)

## Botones (fase actual: 8)

Cableado tipico: un lado del pulsador a **GPIO**, el otro a **GND**. Firmware con `INPUT_PULLUP` (reposo = suelto = alto; pulsado = bajo).

| Indice | Nombre | Uso habitual |
|--------|--------|----------------|
| 0 | LEFT | Izquierda |
| 1 | RIGHT | Derecha |
| 2 | UP | Arriba |
| 3 | DOWN | Abajo |
| 4 | A | Accion 1 |
| 5 | B | Accion 2 |
| 6 | C | Accion 3 |
| 7 | D | Accion 4 |

Reservado para ampliar a **11** botones (menu, start, etc.) en una revision posterior.

## API Lua

- **`btn(i)`** — `true` si el boton `i` esta **pulsado** (estado sostenido).
- **`btnp(i)`** — `true` solo en el **fotograma** en que paso de suelto a pulsado (flanco). El firmware **retiene** el flanco hasta que Lua lo consulta (así no se pierde si hay varios `poll` o el tick de juego va a 30 FPS).

El firmware llama a `turtle_input_poll()` cada iteracion del `loop()` principal.

### Donde esta disponible `btn` / `btnp`

| Contexto | Cuando |
|----------|--------|
| **ENTRY** (`scripts/global.lua` en el cartucho) | Durante la ejecucion unica al arranque; ver **`spec/lua/entry-v0.md`** (sin `poll` previo: `btnp` casi nunca util en ENTRY). |
| **Scripts de objeto** | Cada fotograma del runtime de escena, dentro de `_update(dt)`; ver **`spec/lua/object-script-v0.md`**. |

En scripts de objeto tambien existe **`axis(neg, pos)`** (helper sobre `btn`, documentado alli).

## Pines

Se configuran en `firmware/TurtleReader/turtle_input.h` (`TURTLE_BTN_PIN_*`). Valor **-1** desactiva ese boton. Ajusta a tu placa sin chocar con SD (36–39) ni pantalla (8–12 en la config por defecto del repo).
