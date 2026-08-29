# Estado compartido entre VMs (v0)

Documento complementario a `spec/lua/firmware-bridge-v0.md` y `spec/lua/object-script-v0.md`. Describe un almacen clave-valor de enteros int32 accesible desde **ambas** VMs (ENTRY y actores) sin romper la separacion actor-no-toca-UI: los bindings `gui_layer_*` siguen siendo exclusivos de la VM ENTRY; para que un actor "empuje" datos a la HUD escribe una entrada de `state_*` y la VM ENTRY la lee desde `_hud(dt)`.

## Motivacion

Un actor no puede alterar la HUD directamente (por spec — mantiene el compositing del HUD centralizado). Sin un puente, casos como "recoger un objeto y sumar +1 al contador visible" o "recibir un golpe y bajar un pip de HP" quedaban sin manera limpia de comunicarse: el actor sabe que paso, la HUD tiene que enterarse pero no puede depender de nada del actor VM (VMs distintas, memoria distinta).

`state_*` es un tercer espacio compartido: 16 slots `(clave, valor int32)`, escribible desde cualquier VM, leible desde cualquier VM.

## API

### Bindings (disponibles en VM ENTRY y actor VMs)

| Firma Lua                          | Efecto                                                                                              |
|------------------------------------|-----------------------------------------------------------------------------------------------------|
| `state_set(key, value)` → int      | Setea (o crea) `key` con `value`. Devuelve `value`. No-op si `key` es vacio o tabla llena.          |
| `state_get(key)` → int \| nil      | Devuelve el valor de `key`, o `nil` si no existe. Cero es un valor valido y no nil.                 |
| `state_add(key, delta)` → int      | Suma atomica: si `key` no existe la crea en 0, aplica `+delta`, devuelve el nuevo valor.            |

- **Claves**: strings de hasta 31 caracteres (el buffer del firmware es 32 con el nul). Convencion: `snake_case` — `"gears"`, `"hp"`, `"lives"`, `"score"`, `"boss_hp"`. Sin restricciones adicionales de charset.
- **Valores**: int32 (`[-2_147_483_648, 2_147_483_647]`). Sin floats en v0 — los games pueden usar centesimas si necesitan mas resolucion (`state_set("timer_cs", math.floor(t * 100))`).
- **Slots**: 16 fijos. Si se agotan, `state_set`/`state_add` con una clave NUEVA fallan silenciosamente (devuelven `value` / `0` para no romper la aritmetica del script). Sobreescribir una clave existente siempre funciona.

## Semantica

- **Persistencia entre escenas**: el store NO se limpia en `turtle_scene_begin_runtime`. Un contador `"gears"` sube en `Lvl_1` y se conserva al pasar a `Lvl_2` — comportamiento intencional para score/inventario/lives.
- **Reset**: solo al **cargar otro cart** (`turtle_state_reset()` en `setup()` de TurtleReader.ino, antes del primer bind de la VM ENTRY). Un reset manual desde Lua se puede hacer via `state_set("mykey", 0)` clave por clave, o "resetear al empezar" (`if state_get("run_id") ~= 1 then state_set("gears", 0); state_set("run_id", 1) end`).
- **Orden entre VMs**: en un mismo tick, actor `_update(dt)` corre antes que `_hud(dt)` (ver `spec/lua/firmware-bridge-v0.md`). Un actor que escribe `state_set` es leido por el `_hud` de ese mismo frame — sin lag.

## Ejemplo canonico: gear pickup + HUD counter

Un pickup escribe al store cuando el jugador lo toca; la HUD lo lee cada frame.

### `scripts/gear.lua` (actor)

```lua
local collected = false
local player_h = nil
local gear_x0, gear_x1, gear_y0, gear_y1 = -6, 6, -6, 6
local player_x0, player_x1, player_y0, player_y1 = -9, 8, 0, 27

function _update(dt)
  if collected then return end
  if not player_h then
    player_h = find_by_id("player")
    if not player_h then return end
  end
  local px, py = obj_posx(player_h), obj_posy(player_h)
  if not px or not py then return end
  local sx, sy = posx(), posy()
  local overlap_x = (sx + gear_x1) > (px + player_x0) and (sx + gear_x0) < (px + player_x1)
  local overlap_y = (sy + gear_y1) > (py + player_y0) and (sy + gear_y0) < (py + player_y1)
  if overlap_x and overlap_y then
    collected = true
    set_visible(false)
    state_add("gears", 1)   -- <-- unica linea nueva
  end
end
```

### `scripts/global.lua` (ENTRY)

```lua
function _hud(dt)
  local gears = state_get("gears") or 0
  gui_layer_set_text("hud", "gears_lbl", tostring(gears))
end
```

## Ejemplo: HP con pip bar

El actor decrementa un contador local en cada golpe y lo publica al store; la HUD lo refleja como pip bar.

### `scripts/character.lua` (fragmento)

```lua
local healthpoints = 3
state_set("hp", healthpoints)  -- publica el HP inicial al arrancar la escena

-- ... dentro de la logica de dano existente:
if got_hit then
  healthpoints = healthpoints - 1
  state_set("hp", healthpoints)
  if healthpoints <= 0 then
    goto_scene("game_over")
  end
end
```

### `scripts/global.lua` (`_hud(dt)` combinado)

```lua
function _hud(dt)
  gui_layer_set_text("hud", "gears_lbl", tostring(state_get("gears") or 0))
  gui_layer_set_pips("hud", "healthshells", state_get("hp") or 0)
end
```

## Errores comunes

| Sintoma                                                        | Causa tipica                                                                              |
|----------------------------------------------------------------|-------------------------------------------------------------------------------------------|
| `state_get("gears")` devuelve nil aunque un actor escribio.    | Typo en la clave (`"gears"` vs `"gear"`). Las claves son case-sensitive.                  |
| Contador se resetea al cambiar de escena.                      | Uso de `state_set` en `_hud_init` de la nueva escena — sobreescribe el valor persistente. |
| Contador arranca "cargado" (no en 0) en cada arranque del cart.| Falso: `turtle_state_reset` en `setup()` limpia todo antes del primer bind de la VM ENTRY. Si persiste, revisar que TurtleReader.ino no llame `turtle_state_reset` doble en el ciclo de reinicio. |
| `state_set(nil, 42)` crashea el script.                        | `luaL_checkstring` levanta error Lua si la clave no es string. Usar `tostring(k)` si viene de otra fuente. |
| 17ma clave nueva no se guarda.                                 | Tabla llena (16 slots). Reusar claves existentes o compactar el diseno.                   |

## Fuera de alcance en v0

- **Valores no-int** (strings, floats, tablas): la mayoria de HUDs se resuelven con enteros; si se necesita string el cart puede empujar N chars via `state_set("name_" .. i, string.byte(c))` — feo pero cabe.
- **Callbacks/observadores** ("dispara F cuando cambie X"): el patron actual es polling desde `_hud(dt)` cada frame, suficiente porque `_hud` corre a 30 FPS y la HUD no necesita reaccion sub-frame.
- **Namespacing por escena**: los games que necesiten scopes distintos usan prefijos manuales (`"lvl1_gears"`, `"lvl2_gears"`).
- **Persistencia entre encendidos**: v0 no toca la NVS. Al apagar el ESP32 se pierde todo. Save states son un spec aparte.
