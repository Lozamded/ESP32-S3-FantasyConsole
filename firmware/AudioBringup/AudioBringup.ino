// FantasyConsole - Audio M0 bring-up (spec/audio-v0.md)
//
// Sketch INDEPENDIENTE de TurtleReader. Sirve solo para validar el cableado
// del amplificador PAM8403 + altavoz 8Ω antes de integrar audio al firmware
// principal. Flashear este sketch en el ESP32-S3, escuchar la secuencia:
//
//   1) 440 Hz  (500 ms)
//   2) silencio (200 ms)
//   3) 880 Hz  (500 ms)
//   4) silencio (200 ms)
//   5) Escala C mayor C4..C5 (150 ms/nota)
//   6) silencio (200 ms)
//   7) Sweep lineal 100 Hz -> 4 kHz (2 s)
//   8) silencio (1 s) y repite
//
// Cableado (ver spec/audio-v0.md):
//
//   GPIO 14 --[ 1 kΩ ]--+-- L-IN PAM8403 -- (amp) --> altavoz 8Ω
//                       |
//                    [100 nF]
//                       |
//                      GND (comun con ESP32 y PAM8403 GND)
//
// El pin de mute (GPIO 42 -> SHDN del PAM8403) es opcional. Si el modulo se
// deja siempre encendido, comentar TURTLE_AUDIO_MUTE_PIN mas abajo.
//
// Para M1 (turtle_audio.cpp) cambiaremos a un carrier PWM fijo a ~30 kHz con
// modulacion de duty; aqui, para M0, LEDC directamente a la frecuencia de la
// nota es suficiente para verificar que se oye algo.

#include <Arduino.h>

#ifndef TURTLE_AUDIO_PIN
#define TURTLE_AUDIO_PIN 14
#endif

// Comentar la linea siguiente si no hay pin de mute cableado.
#ifndef TURTLE_AUDIO_MUTE_PIN
#define TURTLE_AUDIO_MUTE_PIN 42
#endif

// Resolucion LEDC. 8 bits basta para un cuadrado 50% (duty=128).
static const uint8_t kAudioResBits = 8;
static const uint32_t kAudioInitFreq = 440;

// Wrapper compatible con Arduino-ESP32 2.x y 3.x. La 3.x usa API por pin,
// la 2.x por canal.
// Duty al 50% del rango de 8 bits = maxima amplitud AC posible desde un pin
// single-ended. No hay margen para "subir volumen" desde software: subir el
// duty por encima de 128 reduce la amplitud AC (se acerca a DC alto), bajarlo
// hace lo mismo hacia DC bajo.
static const uint32_t kAudioMaxDuty = 128;  // 50% de 2^8

#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
static void audio_attach(int pin, uint32_t freq, uint8_t res_bits) {
  ledcAttach(pin, freq, res_bits);
}
static void audio_tone(int pin, uint32_t freq) {
  ledcWriteTone(pin, freq);
  ledcWrite(pin, kAudioMaxDuty);  // forzamos 50% por si la version no lo hace
}
static void audio_silence(int pin) {
  ledcWrite(pin, 0);
}
#else
static const int kAudioChannel = 0;
static void audio_attach(int pin, uint32_t freq, uint8_t res_bits) {
  ledcSetup(kAudioChannel, freq, res_bits);
  ledcAttachPin(pin, kAudioChannel);
}
static void audio_tone(int pin, uint32_t freq) {
  (void)pin;
  ledcWriteTone(kAudioChannel, freq);
  ledcWrite(kAudioChannel, kAudioMaxDuty);  // forzamos 50% por si la version no lo hace
}
static void audio_silence(int pin) {
  (void)pin;
  ledcWrite(kAudioChannel, 0);
}
#endif

static void amp_enable(bool on) {
#ifdef TURTLE_AUDIO_MUTE_PIN
  digitalWrite(TURTLE_AUDIO_MUTE_PIN, on ? HIGH : LOW);
#else
  (void)on;
#endif
}

static void play_tone(uint32_t freq_hz, uint32_t duration_ms) {
  Serial.printf("  tono %5u Hz  %4u ms\n", (unsigned)freq_hz, (unsigned)duration_ms);
  audio_tone(TURTLE_AUDIO_PIN, freq_hz);
  delay(duration_ms);
}

static void play_silence(uint32_t duration_ms) {
  audio_silence(TURTLE_AUDIO_PIN);
  delay(duration_ms);
}

// C4..C5 en escala mayor (do, re, mi, fa, sol, la, si, do)
static const uint32_t kMajorScale[] = {262, 294, 330, 349, 392, 440, 494, 523};

static void play_scale() {
  Serial.println("Escala C4..C5:");
  for (uint32_t f : kMajorScale) {
    play_tone(f, 150);
  }
}

// Sweep lineal en frecuencia. Paso pequeño para que suene continuo.
static void play_sweep(uint32_t from_hz, uint32_t to_hz, uint32_t total_ms) {
  Serial.printf("Sweep %u -> %u Hz en %u ms\n",
                (unsigned)from_hz, (unsigned)to_hz, (unsigned)total_ms);
  const uint32_t steps = 200;
  const uint32_t step_ms = total_ms / steps;
  for (uint32_t i = 0; i < steps; i++) {
    const uint32_t f = from_hz + (to_hz - from_hz) * i / steps;
    audio_tone(TURTLE_AUDIO_PIN, f);
    delay(step_ms);
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println("== FantasyConsole audio bring-up (M0) ==");
  Serial.printf("Pin audio (LEDC PWM) : GPIO %d\n", TURTLE_AUDIO_PIN);
#ifdef TURTLE_AUDIO_MUTE_PIN
  Serial.printf("Pin mute (SHDN)      : GPIO %d (HIGH = amp ON)\n", TURTLE_AUDIO_MUTE_PIN);
  pinMode(TURTLE_AUDIO_MUTE_PIN, OUTPUT);
  amp_enable(true);
#else
  Serial.println("Pin mute             : no cableado");
#endif

  audio_attach(TURTLE_AUDIO_PIN, kAudioInitFreq, kAudioResBits);
  audio_silence(TURTLE_AUDIO_PIN);
  Serial.println("LEDC inicializado; iniciando secuencia de test.");
}

void loop() {
  Serial.println("--- ciclo test ---");

  play_tone(440, 500);
  play_silence(200);

  play_tone(880, 500);
  play_silence(200);

  play_scale();
  play_silence(200);

  play_sweep(100, 4000, 2000);
  play_silence(1000);
}
