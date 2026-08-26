# Audio v0 (hardware + hoja de ruta)

Esta especificacion cubre la **etapa de salida analogica** (M0 del roadmap) y fija los pines / cableado que el firmware asumira en fases siguientes. Los formatos `.tsfx` / `.ttrk` se especifican en documentos aparte cuando lleguen (M2, M3).

## Estado

- **M0 (esta hoja):** bring-up de hardware. Sketch independiente en `firmware/AudioBringup/`.
- M1..M4: motor chiptune sintetico (`turtle_audio.cpp`, `.tsfx`, `.ttrk`, API Lua).
- M5+: opcional, streaming de muestras y/o DAC I2S.

Sonido pregrabado (WAV/ADPCM) queda **fuera del alcance v0** por decision del proyecto (chiptune-only).

## Etapa de salida

Cadena: `ESP32-S3 GPIO -> filtro RC pasa-bajos -> PAM8403 (L-IN) -> altavoz 8Ω`.

- **Amplificador:** PAM8403 (modulo tipico "azul" con condensadores de entrada de ~10 uF ya incluidos).
- **Altavoz:** 8Ω / 2W. Mono, un solo canal usado del PAM8403 (deja R-IN a masa o puentea L+R).
- **Alimentacion:** VCC del PAM8403 a **5V** (USB) preferido. A **3.7V** (Li-ion directo) funciona, con menos potencia (~0.5W a 8Ω). **GND comun** con el ESP32 obligatorio.
- **Generacion de la señal:** no hay DAC interno en el ESP32-S3. En v0 usamos **LEDC (PWM)** en un pin del S3 y un filtro RC como reconstruccion. Suficiente para chiptune 8-bit.

### Filtro RC recomendado (v0)

Un polo, portadora PWM a ~30 kHz, corte a ~1.6 kHz por encima del rango util 20 Hz..8 kHz de la voz sintetica:

```
ESP32 GPIO(audio) ----[ 1 kΩ ]----+---- L-IN (PAM8403)
                                  |
                                [100 nF]
                                  |
                                 GND
```

- El PAM8403 modulo ya trae acoplo AC en la entrada; el filtro RC no lleva condensador serie extra.
- Si aparece silbido audible del PWM, subir el corte: probar `R=2.2k`, `C=100n` (fc ~= 720 Hz) — se pierde brillo pero desaparece el ultrasonico.

## Pines

Reservados a partir de **`turtle_audio.h`** (aun no creado); documentados aqui para que otros modulos no los tomen.

| Simbolo | GPIO | Uso |
|---------|------|-----|
| `TURTLE_AUDIO_PIN` | **14** | Salida PWM (LEDC) hacia el filtro RC. |
| `TURTLE_AUDIO_MUTE_PIN` | **42** (opcional) | Nivel alto = amp encendido; nivel bajo = SHDN. |

Criterio de eleccion (ESP32-S3-N16R8):

- **GPIO 14** esta libre: no lo usan pantalla (8-13), botones (4-7, 15-18) ni SD (19, 20, 21, 47). No es strapping pin.
- GPIO 33..37 estan **reservados por la PSRAM octal (R8)** y no se pueden tocar.
- GPIO 42 es libre, sin strapping. La conexion a SHDN del PAM8403 es opcional: si no se cablea, dejar el SHDN del modulo tirado a VCC con su pull-up de fabrica y omitir `TURTLE_AUDIO_MUTE_PIN` en el firmware.

Si el usuario necesita cambiar de pin (por ejemplo, un GPIO ya ocupado por hardware propio), redefinir `TURTLE_AUDIO_PIN` / `TURTLE_AUDIO_MUTE_PIN` en el sketch o mediante `-D` al compilar, siguiendo el mismo patron que `TURTLE_DISP_PIN_*` en `turtle_gpu.h` y `TURTLE_BTN_PIN_*` en `turtle_input.h`.

## Procedimiento M0 (bring-up)

Ver `firmware/AudioBringup/AudioBringup.ino` (sketch independiente, no depende de `TurtleReader.ino` ni de la SD).

1. Cablear segun el diagrama de arriba.
2. Flashear `AudioBringup.ino` en el ESP32-S3.
3. Escuchar la secuencia de test:
   - Tono continuo a **440 Hz** (500 ms).
   - Silencio (200 ms).
   - Tono a **880 Hz** (500 ms).
   - Silencio (200 ms).
   - Escala **C mayor** de C4 a C5 (150 ms por nota).
   - Silencio (200 ms).
   - Sweep lineal 100 Hz -> 4 kHz (2 s), para verificar el filtro RC en toda la banda audible.
   - Silencio (1 s) y bucle.
4. Verificar por Serial (`115200`) que se imprime la nota/frecuencia actual — util para diagnosticar si el ESP32 esta generando pero no hay sonido (=> problema de cableado / amp / altavoz).

Criterios de aceptacion M0:

- Se escuchan las cuatro fases sin distorsion audible ni chasquidos entre notas.
- Sweep barre suave, sin cortes.
- Al pisar SHDN a masa (si esta cableado), el sonido desaparece por completo.

## Que **no** entra en v0

- Estereo (el S3 puede, pero el PAM8403 mono + un altavoz no lo aprovechan).
- Streaming de audio grabado (WAV, ADPCM, MP3): pospuesto a M5+.
- DAC externo I2S (MAX98357A, PCM5102): pospuesto a M6+, cuando se decida si el PWM 8-bit se queda corto.
- API Lua (`sfx`, `music`): definida en M2/M3 junto a los formatos `.tsfx` / `.ttrk`.
