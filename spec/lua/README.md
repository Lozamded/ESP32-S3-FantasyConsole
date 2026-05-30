# Especificaciones Lua (FantasyConsole / TurtleReader)

Documentacion del runtime **Lua 5.4** en firmware y de los scripts que exporta TurtleStudio.

| Documento | Alcance |
|-----------|---------|
| [physics-v0.md](physics-v0.md) | Plataformero: `move` con colision, `on_ground()`, gravedad en Lua |
| [animation-v0.md](animation-v0.md) | `set_anim` / `play_anim` segun `animations` del objeto |
| [firmware-bridge-v0.md](firmware-bridge-v0.md) | Orden **C++ / Lua** en TurtleReader (dos VM, loop, `move`) |
| [entry-v0.md](entry-v0.md) | Script **ENTRY** del cartucho (`cls`, `pix`, `spix`, `flip`, una ejecucion en arranque) |
| [object-script-v0.md](object-script-v0.md) | Scripts por **objeto** (`_update(dt)`, input, movimiento en escena) |
| [../input-v0.md](../input-v0.md) | Botones `btn` / `btnp` (compartido ENTRY y objetos) |
| [../scene-v0.md](../scene-v0.md) | Escena 264×198 y coordenadas (espacio de `move` / `posx`) |
| [../turtlecart-v0.md](../turtlecart-v0.md) | Cartucho, `ENTRY`, paquete en SD |

## Dos contextos Lua en v0

1. **ENTRY** — ver [entry-v0.md](entry-v0.md): `scripts/global.lua` (o la ruta en `ENTRY:`), **una vez** en arranque; graficos y `print`.
2. **Scripts de objeto** — ver [object-script-v0.md](object-script-v0.md): `scripts/<stem>.lua` en la SD, VM persistente, `_update(dt)` por fotograma.

Futuro en este directorio: scripts por escena (`scripts/<scene>.lua`), audio, señales entre objetos.
