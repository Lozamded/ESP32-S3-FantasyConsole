# Driver de salida RCA/compuesto para ESP32-P4 (v0 — bring-up, NTSC monocromo)

Documento de diseno para el driver de pantalla del objetivo P4 (`GFX_TIER 1` en
`spec/scene-v2.md`), equivalente a `firmware/TurtleReader/turtle_gpu.*` pero generando video
compuesto en vez de manejar un panel SPI. **No hay prior art directo**: las librerias conocidas de
video compuesto en ESP32 (bitluni, aquaticus) usan el DAC analogico interno de 8 bits del ESP32
original en GPIO25/26 — el S3 y el P4 **no tienen ese periferico**. Este documento es diseno
propio sobre el periferico PARLIO (Parallel IO) del P4, verificado contra la documentacion oficial
de ESP-IDF, no una adaptacion de una libreria existente.

## Decisiones de alcance (bring-up)

- **NTSC primero, PAL como variable interna.** El usuario esta en Chile (CRTs NTSC). Todas las
  constantes de temporizacion viven en una sola tabla seleccionada por una variable de codigo
  (`TURTLE_VIDEO_STD`, ver abajo) — no hardcodeadas inline — para poder agregar PAL despues sin
  reescribir el driver. Un selector fisico (switch/jumper leido por GPIO en boot) es una extension
  trivial una vez que la variable exista; no es parte de v0.
- **Monocromo/escala de grises primero, color como trabajo futuro separado.** Codificar color
  NTSC real (subportadora de 3.579545 MHz con fase exacta por pixel) es sustancialmente mas dificil
  y es la causa mas comun de que un generador de video casero funcione "casi bien" (imagen con
  colores incorrectos o rodando) en vez de fallar limpio. v0 genera solo luma (nivel de voltaje =
  brillo), igual que como funcionaba NTSC antes de agregarle color en 1953 — cualquier TV/capturadora
  moderna lo muestra correctamente en blanco y negro.
- **240p no entrelazado, no NTSC de broadcast entrelazado.** Broadcast NTSC intercala 2 campos de
  262.5 lineas para dar 525 lineas/cuadro a 59.94 Hz — requiere pulsos de ecualizacion y
  serracion para que el intercalado enganche bien. Prácticamente ninguna consola retro (NES, SNES,
  Genesis, Game Boy Player, etc.) hace esto: todas emiten **262 lineas fijas sin intercalar a
  ~60 Hz** ("240p"), que cualquier TV CRT engancha sin problema y es mucho mas simple de generar
  (sin necesidad de alternar la fase del pulso de sync cuadro a cuadro). v0 sigue ese mismo camino.

## Etapas de bring-up (cada una es un hito verificable en tu TV)

No se escribe el driver completo de una — cada etapa es un sketch/build separado y minimo:

1. **Solo sync**: pantalla negra estable, sin "roll" ni parpadeo — confirma que la TV engancha el
   timing horizontal y vertical. **Esta es la etapa que entrega este documento.**
2. Campo solido gris medio en la zona activa (en vez de negro) — confirma los niveles de voltaje
   (sync/negro/blanco) y el letterboxing vertical (bordes negros arriba/abajo visibles y centrados).
3. Framebuffer real: paleta de 32 colores → luma (escala de grises), una columna de muestra por
   pixel de escena (264 columnas mapean 1:1 a 264 muestras de la ventana activa).
4. Color NTSC (subportadora) — **trabajo futuro, fuera de alcance de este documento**.

## Periferico: PARLIO TX + GDMA

Verificado contra `docs.espressif.com/.../esp32p4/api-reference/peripherals/parlio/parlio_tx.html`
(ESP-IDF, no Arduino wrapper — el sketch `.ino` llama estas funciones de ESP-IDF directamente,
igual de valido en Arduino-ESP32 3.3.x que ya soporta P4).

- **Por que PARLIO y no bit-banging por GPIO**: video compuesto necesita una muestra de voltaje
  cada ~0.2 µs con jitter minimo — un timer/GPIO manejado por CPU no lo sostiene de forma
  confiable. PARLIO TX transmite un buffer por DMA (GDMA) a un reloj de salida fijo, sin
  intervencion de CPU una vez armada la transmision — exactamente lo que hace falta.
- **`data_width = 8`**: un byte = una muestra de luma (0..255 niveles), alimentando una escalera de
  resistencias R-2R de 8 bits (ver seccion de hardware). Con paleta de 32 colores ya hay de sobra
  de resolucion — no hace falta mas bits.
- **`loop_transmission = true`** (en `parlio_transmit_config_t`): para la Etapa 1/2, el campo
  completo (262 lineas) es estatico — se arma un buffer una vez y PARLIO lo repite por DMA sin
  tocar CPU. Para la Etapa 3 (framebuffer real) esto cambia a transmision por lineas en cola
  (`trans_queue_depth`) con doble buffer, para poder actualizar contenido cuadro a cuadro — **no
  es parte de v0**.
- **Frecuencia de muestreo objetivo**: `output_clk_freq_hz` se pide en **5 000 000 Hz** (5 MHz).
  La documentacion de PARLIO advierte que "no todas las frecuencias son alcanzables" y el driver
  redondea a la mas cercana — **verificar en hardware real cual frecuencia efectiva se obtuvo**
  (con osciloscopio en `clk_out_gpio_num`, o si el SDK expone la frecuencia real lograda,
  leerla) y recalcular las constantes de muestras-por-linea de esta tabla si difiere de 5 MHz.

## Temporizacion NTSC 240p (v0, monocromo, no entrelazado)

Los cuatro segmentos de una linea se definen **como cuentas enteras de muestras que suman
exactamente el total** (no se redondea cada segmento por separado contra su duracion en µs de
forma independiente — eso no cuadra: 4.7+1.5+4.7+52.656 µs redondeados por separado da una suma
distinta al total de linea redondeado por separado, un error de redondeo real que este documento
tenia en un borrador anterior). En cambio, se elige `kLineSamples = 320` (un numero redondo,
**64.0 µs** a 5 MHz — ~0.7% mas largo que el 63.5556 µs "de libro" del NTSC color-lock, diferencia
irrelevante para un bring-up monocromo no enganchado a color) y los porches/sync se fijan en
muestras enteras que se acercan a sus valores de libro, dejando el video activo como **el resto
exacto**:

| Segmento | Muestras @ 5 MHz | ≈ Duracion | Nota |
|---|---|---|---|
| Linea completa | **320** | 64.0 µs | Elegido redondo; sustituye al "63.5556 µs de libro" (color-lock), no aplica sin color |
| Pulso de sync horizontal | 24 | 4.8 µs | Nivel 0 V ("sync tip"); libro: 4.7 µs |
| Front porch | 8 | 1.6 µs | Nivel de negro (0.3 V); libro: 1.5 µs |
| Back porch | 24 | 4.8 µs | Nivel de negro (0.3 V); libro: 4.7 µs |
| Video activo | **320 − 24 − 8 − 24 = 264** | 52.8 µs | Coincide exactamente con el ancho de escena (264 px) **por construccion** — 1 muestra = 1 pixel de columna, sin escalado horizontal |

Verticalmente (no entrelazado, 262 lineas/cuadro, ~60 Hz):

| Segmento | Lineas | Nota |
|---|---|---|
| Sync vertical (pulso ancho) | 3 | Ver "Pulso ancho" abajo |
| Blanking vertical restante | 19 | Lineas normales (sync horizontal normal) sin video, nivel de negro en toda la zona activa |
| Video activo disponible | 240 | Nuestra escena (H=198) se centra: **21 lineas de margen negro arriba, 21 abajo** (240-198=42, /2=21) |
| **Total** | **262** | ~59.6 Hz de cuadro (262 × 64.0 µs = 16.768 ms) |

**Pulso ancho (broad sync)**: en vez del pulso de sync horizontal normal (4.7 µs), las 3 lineas de
sync vertical usan un pulso mucho mas largo (medio periodo de linea, 160 muestras = 32.0 µs) al
nivel de sync (0 V). No se implementa serracion (el pulso partido a mitad de linea que usa NTSC de
broadcast para que el intercalado enganche) porque v0 no intercala — un pulso ancho simple sin
serrar es exactamente lo que emiten la mayoria de consolas retro y lo que casi cualquier CRT
engancha sin problema. Si una TV especifica no engancha bien con esto, la serracion es la primera
mejora a probar (no deberia hacer falta).

### Niveles de voltaje (referencia 1 Vpp estandar hacia 75 Ω)

| Nivel | Voltaje | Uso |
|---|---|---|
| Sync tip | 0.0 V | Pulsos de sync (horizontal y vertical) |
| Negro/blanking | 0.3 V | Porches, blanking vertical, margenes de letterbox |
| Blanco | 1.0 V | Pixel de luma maxima (Etapa 2: gris medio ≈ 0.65 V para probar niveles sin llegar a blanco puro) |

## Hardware: escalera de resistencias (R-2R, 8 bits)

PARLIO saca 8 lineas digitales (`data_gpio_nums[8]`) a 3.3 V logicos; hace falta convertirlas a
un voltaje analogico 0..1 V (los niveles de arriba) hacia el conector RCA:

1. **R-2R DAC de 8 bits** en las 8 lineas de datos → produce 0..3.3 V analogico proporcional al
   byte de muestra (256 escalones). Valores tipicos R=10kΩ / 2R=20kΩ (o R=1kΩ/2R=2kΩ si se
   prefiere menos impedancia de salida — a definir en la implementacion fisica, no cambia el
   diseno logico).
2. **Atenuador + acople**: la salida del R-2R (0..3.3 V) se atenua a 0..1 V (divisor resistivo) y
   se acopla en AC (capacitor, igual que hacen bitluni/aquaticus con el DAC del ESP32 clasico) para
   no inyectar DC al conector RCA.
3. **Resistencia serie de 75 Ω** en la salida hacia el RCA, para que la TV (que termina en 75 Ω)
   vea la impedancia correcta y no haya reflexiones/ghosting en la imagen.

Esto es diseño de referencia, no un valor medido en un prototipo real — **ajustar con
osciloscopio contra un TV real en la Etapa 2** (campo gris) antes de confiar en los niveles
exactos. Verificar tambien que 3.3 V del P4 no exceda ningun limite del punto de atenuacion antes
de conectar a una TV real.

## `TURTLE_VIDEO_STD`: variable de estandar de video

```c
// turtle_gpu_composite.h
enum TurtleVideoStd { TURTLE_VIDEO_NTSC = 0, TURTLE_VIDEO_PAL = 1 };

#ifndef TURTLE_VIDEO_STD
#define TURTLE_VIDEO_STD TURTLE_VIDEO_NTSC
#endif
```

Todas las constantes de temporizacion de esta tabla viven en una struct `TurtleVideoTiming`
seleccionada por `TURTLE_VIDEO_STD` (`#if`/tabla indexada, a decidir en implementacion) en vez de
usarse inline — asi agregar PAL mas adelante es llenar una segunda fila de la tabla, no reescribir
el generador de lineas. v0 **solo llena la fila NTSC**; PAL queda declarado pero sin implementar
(el enum ya existe para no tener que tocar la interfaz publica despues). Un selector fisico
(GPIO leido en `setup()` para elegir `TURTLE_VIDEO_STD` en vez de fijarlo en compilacion) es una
extension de una linea una vez que exista mas de una fila en la tabla — no es parte de v0.

## Estructura del driver (etapa 1)

`firmware/TurtleReaderP4/turtle_gpu_composite.h` / `.cpp` — mismo espiritu que
`turtle_gpu.h`/`.cpp` del build S3 (config por `#define`, un `turtle_gpu_composite_init()` /
`_start()`), pero **standalone**: no depende de `turtle_scene.cpp` todavia. El sketch de bring-up
(`TurtleReaderP4_CompositeBringup.ino`) solo llama al driver, sin leer SD ni cartucho — el
objetivo de la Etapa 1 es exclusivamente "¿la TV engancha una imagen estable?", nada de logica de
consola todavia. Integrar con el resto del firmware (Lua VM, `turtle_scene.cpp`, lectura de
cartucho) es trabajo posterior, una vez que la Etapa 3 (framebuffer real) este verificada en
hardware.

## Fuera de alcance v0

- Color NTSC (subportadora).
- PAL (declarado, no implementado).
- Framebuffer real / integracion con `turtle_scene.cpp` (Etapa 3+).
- Selector fisico de estandar de video.
- Valores exactos de la escalera de resistencias (referencia de diseno, no medidos).
