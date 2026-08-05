# Especificacion de escena (v2) — niveles de capacidad grafica (`GFX_TIER`)

Extiende **`spec/scene-v0.md`** y **`spec/scene-v1.md`** (siguen vigentes sin cambios: viewport
264×198, paleta de 32 colores, capa 1 como capa base/horneada, capas 2-4 independientes, dither
Bayer para `opacity`). Este documento define **como un segundo objetivo de hardware con mas
musculo** (p. ej. un futuro build para ESP32-P4 + salida RCA) puede mejorar la fidelidad/tope de
rendimiento de esos mismos campos **sin** forkear el formato de cartucho ni la herramienta de
autoria — la decision de producto es "un cartucho, una libreria de juegos, dos placas", no
"Genesis/Game Gear reales" (que tenian CPU y catalogos separados). Ver contexto de la comparacion
de hardware que motiva este documento en la discusion de diseno (S3N16R8 vs ESP32-P4).

## No hace falta subir `TURTLECART:1`

Igual que v0 y v1, todo lo de este documento es **aditivo y opcional**. Un cartucho sin ningun
campo de este documento se comporta identico en cualquier build de firmware. `TURTLECART:0` sigue
siendo la cabecera correcta.

## Que NO cambia entre objetivos de hardware (a proposito)

- **Resolucion**: 264×198 sigue siendo la vista canonica en **cualquier** build. Es ya 4:3 exacto
  (264/198 = 1.333...), asi que no hace falta un modo especial para salida compuesta NTSC/PAL —
  el driver de un objetivo RCA escala/centra igual que hoy `turtle_gpu.cpp` escala 264×198 al
  panel ILI9488 fisico (240×320). No hay "resolucion P4" distinta de "resolucion S3".
- **Paleta**: 32 colores, indice 31 transparente, en todos los objetivos. Es parte de la identidad
  visual de la consola (el "corazon" compartido de la familia), no una limitacion de hardware que
  un chip mas rapido deba levantar.
- **Formato de cartucho, API Lua, `spec/lua/*`**: identicos. Un juego se escribe una vez.

Lo que **si** puede diferir entre objetivos es *como de bien* y *cuantas capas simultaneas* el
firmware puede sostener a 60 FPS — fidelidad y techo de rendimiento, nunca reglas de juego.

## `GFX_TIER`: capacidad del firmware, no del cartucho

`GFX_TIER` es una constante de **compilacion del firmware** (un `#define` por build, no un campo
del `.turtlecart` ni de ningun `scenes/<id>.json`). Cada build de TurtleReader declara la suya:

| Tier | Significado | Objetivo de referencia |
|------|-------------|-------------------------|
| `0` | Sin acelerador 2D: todo el compositing de capas es CPU + framebuffer indexado, tal como hoy (`turtle_scene.cpp`). `opacity` en `background_layers` usa el dither Bayer 4×4 de `spec/scene-v1.md`. | ESP32-S3 (build actual) |
| `1` | Hay un acelerador 2D con blend real en hardware (p. ej. la PPA del ESP32-P4: rotacion/escala/espejo/**alpha blend**, formatos ARGB8888/RGB888/RGB565/YUV420, respaldada por DMA-2D). `opacity` se resuelve con mezcla alfa real en vez de dither. | ESP32-P4 (build RCA futuro) |

Tiers futuros (`2`, `3`, ...) se agregan solo cuando exista hardware real que los justifique — no
se reservan de antemano. Un build sin `GFX_TIER` definido explicitamente se trata como `0`.

**Expuesto a Lua**: la ENTRY VM gana una constante global de solo lectura **`GFX_TIER`** (entero),
junto a `W`, `H`, `COLORS` (`spec/lua/entry-v0.md`). Uso esperado: opcional, para que un juego
active un efecto puramente decorativo si detecta mas musculo (p. ej. una transicion con blend real
en vez de un corte duro) — **nunca** para condicionar mecanicas o contenido, ver regla siguiente.

## Regla de compatibilidad: el tier solo cambia fidelidad, nunca logica de juego

Ningun campo de escena existente (`background_layers`, `parallax_bands`, `tile_layers`, etc.)
puede requerir un `GFX_TIER` minimo para **cargar correctamente**. Un cartucho hecho pensando en
tier 1 debe seguir siendo jugable en tier 0 — con menos fidelidad (dither en vez de blend real) o
menos margen de rendimiento (mas capas banded pueden bajar de 60 FPS), pero **nunca** con assets
faltantes, colisiones rotas o una escena que no carga. Esta regla es la que hace posible "un
cartucho, dos placas" en vez de forkear el formato.

## Mezcla alfa real en tier ≥ 1 (mejora de `opacity` sobre v1)

`spec/scene-v1.md` resuelve `background_layers[].opacity < 255` con un patron Bayer 4×4 porque
"el motor no lee el framebuffer destino en ningun otro punto del pipeline" en tier 0. En tier 1
eso deja de ser cierto en el punto justo donde ya existe una conversion indice→RGB: hoy
`turtle_gpu_flip()` (`turtle_gpu.cpp`, ~linea 288: `line[px] = s_palette[row[lx]]`) expande cada
pixel indexado a RGB565 fila por fila justo antes de `pushImage()`. Un driver de objetivo tier 1
puede insertar la mezcla alfa real **en ese mismo punto** en vez de en `paint_bg_image_layers()`.

Esto es **mas que solo agregar una formula de blend** — requiere un cambio de estructura en el
driver de tier 1, no en la escena/spec: hoy las capas se **aplanan** en un unico framebuffer
indexado durante el pase de pintado de escena (cada `paint_*` sobreescribe pixeles del mismo
buffer, capa por capa, sin retener las capas por separado). Para blend real en RGB al momento del
`flip()`, el driver de tier 1 necesita **retener** los buffers de las hasta 4 capas (capa 1
horneada + capas 2-4 independientes, ver `spec/scene-v0.md`) sin aplanarlos, y resolverlos con la
PPA durante el barrido de salida. Esto es trabajo de **driver de pantalla** (equivalente a
`turtle_gpu.cpp` pero para el objetivo RCA), no de `turtle_scene.cpp` — la escena sigue
produciendo los mismos buffers indexados de siempre; solo cambia quien y cuando los combina.

- **Contrato**: mismo campo `opacity` (u8, `0..255`), mismo significado percibido (mas opaco =
  mas cobertura de esa capa). Tier 0 lo aproxima con dither; tier 1 lo resuelve exacto. Un
  cartucho no declara cual usar — lo decide el firmware que lo carga.
- **Fuera de alcance de v2 (explicitamente, se implementa despues)**: la implementacion real del
  driver tier 1 (retener capas sin aplanar, formato RGB565 intermedio, integracion con PPA/DMA-2D)
  no es parte de este documento — v2 fija el **contrato** (mismo campo, mismo rango, resultado
  visualmente equivalente o mejor) para que el trabajo de driver pueda hacerse sin tocar spec ni
  TurtleStudio otra vez.

## Avisos de rendimiento por tier en TurtleStudio (no bloqueantes)

Capas 2-4 con `parallax_bands` propios (`spec/scene-v1.md`) cuestan una resolucion de banda por
fila **por capa** cada fotograma — mas notorio en tier 0 (sin acelerador, todo CPU) que en tier 1
(mas ancho de banda de PSRAM: hasta 200MHz octal en ESP32-P4 frente a 120MHz en ESP32-S3 N16R8).
TurtleStudio no debe **bloquear** el build por esto (una escena pesada puede ser intencional para
un target especifico), pero puede avisar:

- Manifest gana un campo opcional de proyecto **`recommended_gfx_tier`** (int, default `0`,
  puramente informativo — no se escribe en el `.turtlecart` exportado, no lo lee el firmware).
  Sirve para que el editor muestre una advertencia ("N capas con bandas activas; recomendado para
  tier ≥1") cuando el conteo de capas-con-bandas habilitadas supera un umbral razonable para tier
  0. El umbral exacto se calibra con pruebas en hardware real (mismo criterio que v0/v1: "no hay
  tope de PSRAM documentado en este repo, probar en hardware real").
- Esto es **solo** una advertencia de autoria, no un campo de compatibilidad — coherente con la
  regla de arriba de que el tier nunca bloquea la carga.

## Campo opcional `min_gfx_tier` (features sin degradacion sensata)

Para el caso — hoy hipotetico, sin ningun uso concreto todavia — de una funcion que no tenga una
forma razonable de degradar (a diferencia de `opacity`, que siempre puede caer a dither), una
entrada de `background_layers` puede declarar `min_gfx_tier` (int, default `0`):

```json
{ "enabled": true, "background": "fx_layer", "min_gfx_tier": 1 }
```

- Firmware con `GFX_TIER < min_gfx_tier` trata la capa como si `enabled=false` (se salta por
  completo, sin intentar cargarla ni pintarla) — degradacion limpia, no un intento fallido.
- **v2 no define ninguna funcion concreta que use este campo todavia** — se agrega el mecanismo
  ahora, vacio, para no tener que volver a tocar el formato de cartucho la proxima vez que
  aparezca una funcion exclusiva de un tier. Todo lo demas en v0/v1 (incluyendo la mezcla alfa de
  este documento) tiene degradacion automatica y **no** deberia usar `min_gfx_tier`.

## Fuera de alcance v2

- Definicion de `GFX_TIER` `2` o superiores (sin hardware concreto que lo motive todavia).
- Implementacion del driver tier 1 (PPA/RCA) en si — este documento fija el contrato, no el
  codigo del driver.
- Audio, entrada, o cualquier cosa fuera del pipeline de graficos de escena.
- Cualquier campo que cambie **contenido** o **reglas** de juego segun el tier — prohibido por la
  regla de compatibilidad de arriba, no solo pendiente.

## Resumen de campos nuevos (referencia rapida)

| Bloque | Campo | Tipo | Default | Nota |
|---|---|---|---|---|
| ENTRY Lua (global) | `GFX_TIER` | int (constante) | `0` | Solo lectura; capacidad del firmware, no del cartucho |
| Manifest de proyecto (TurtleStudio) | `recommended_gfx_tier` | int | `0` | Solo para avisos del editor; no se exporta al cartucho |
| `background_layers[]` (cualquier capa) | `min_gfx_tier` | int | `0` | Capa se trata como `enabled=false` si `GFX_TIER` del firmware es menor |

Todos los campos son opcionales; su ausencia reproduce exactamente el comportamiento de
`spec/scene-v0.md` + `spec/scene-v1.md`.
