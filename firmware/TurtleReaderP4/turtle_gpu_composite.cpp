// Driver de video compuesto (RCA) para ESP32-P4, Etapa 1/2 de bring-up
// (spec/rca-composite-driver-v0.md): genera sync NTSC 240p no entrelazado +
// un campo solido, via PARLIO TX + GDMA. Sin framebuffer real todavia.
//
// IMPORTANTE: escrito contra la documentacion publica de ESP-IDF de
// `driver/parlio_tx.h` (no hay un ESP32-P4 fisico disponible para compilar
// esto en este entorno). Antes de flashear: verificar los nombres exactos
// de campos de `parlio_tx_unit_config_t`/`parlio_transmit_config_t` y el
// tamano real del array `data_gpio_nums` contra el header instalado por el
// toolchain ESP-IDF/Arduino-ESP32 3.3.x que se este usando -- puede haber
// cambiado entre versiones del SDK.

#include "turtle_gpu_composite.h"

#include <string.h>

#include "driver/parlio_tx.h"
#include "esp_heap_caps.h"
#include "esp_log.h"

namespace {

const char* const kTag = "turtle_gpu_composite";

// spec/rca-composite-driver-v0.md "Temporizacion NTSC 240p": cuentas de
// muestras elegidas para sumar EXACTO (no redondear cada segmento por
// separado contra su duracion en us -- eso no cuadra, ver nota en el spec).
constexpr int kLineSamples = 320;        // 64.0 us @ 5 MHz
constexpr int kHsyncSamples = 24;        // 4.8 us, nivel sync
constexpr int kBackPorchSamples = 24;    // 4.8 us, nivel negro
constexpr int kActiveSamples = 264;      // 52.8 us -- == ancho de escena (spix 1:1)
constexpr int kFrontPorchSamples = 8;    // 1.6 us, nivel negro
constexpr int kBroadSyncSamples = kLineSamples / 2;  // 160 muestras, pulso ancho de vsync

static_assert(kHsyncSamples + kBackPorchSamples + kActiveSamples + kFrontPorchSamples ==
                  kLineSamples,
              "los segmentos de linea deben sumar exacto kLineSamples");

constexpr int kTotalLines = 262;   // no entrelazado, ~59.6 Hz de cuadro
constexpr int kVsyncLines = 3;     // lineas de pulso ancho
constexpr int kVblankLines = 19;   // blanking vertical restante (lineas normales, sin video)
constexpr int kActiveLines = 240;  // lineas disponibles para video

static_assert(kVsyncLines + kVblankLines + kActiveLines == kTotalLines,
              "las lineas deben sumar exacto kTotalLines");

constexpr int kSceneH = 198;  // spec/scene-v0.md
constexpr int kLetterboxLines = (kActiveLines - kSceneH) / 2;  // 21 arriba, 21 abajo

static_assert(kLetterboxLines * 2 + kSceneH == kActiveLines,
              "letterbox arriba/abajo debe llenar exacto kActiveLines");

parlio_tx_unit_handle_t s_tx_unit = nullptr;
uint8_t* s_field_buf = nullptr;
size_t s_field_bytes = 0;

void build_normal_line(uint8_t* line, uint8_t active_level) {
  memset(line, TURTLE_COMPOSITE_LEVEL_SYNC, kHsyncSamples);
  memset(line + kHsyncSamples, TURTLE_COMPOSITE_LEVEL_BLACK, kBackPorchSamples);
  memset(line + kHsyncSamples + kBackPorchSamples, active_level, kActiveSamples);
  memset(line + kHsyncSamples + kBackPorchSamples + kActiveSamples,
         TURTLE_COMPOSITE_LEVEL_BLACK, kFrontPorchSamples);
}

// Pulso ancho sin serrar (spec: suficiente para no entrelazado; si una TV no
// engancha, serracion a mitad de linea es la primera mejora a probar).
void build_broad_sync_line(uint8_t* line) {
  memset(line, TURTLE_COMPOSITE_LEVEL_SYNC, kBroadSyncSamples);
  memset(line + kBroadSyncSamples, TURTLE_COMPOSITE_LEVEL_BLACK, kLineSamples - kBroadSyncSamples);
}

// Arma un campo completo (262 lineas): vsync, blanking, letterbox arriba,
// zona de escena (a `active_level` -- un solo nivel solido en Etapas 1/2,
// sin framebuffer real), letterbox abajo.
void build_field(uint8_t* buf, uint8_t active_level) {
  int line_idx = 0;
  for (int i = 0; i < kVsyncLines; ++i, ++line_idx) {
    build_broad_sync_line(buf + static_cast<size_t>(line_idx) * kLineSamples);
  }
  for (int i = 0; i < kVblankLines; ++i, ++line_idx) {
    build_normal_line(buf + static_cast<size_t>(line_idx) * kLineSamples,
                       TURTLE_COMPOSITE_LEVEL_BLACK);
  }
  for (int i = 0; i < kLetterboxLines; ++i, ++line_idx) {
    build_normal_line(buf + static_cast<size_t>(line_idx) * kLineSamples,
                       TURTLE_COMPOSITE_LEVEL_BLACK);
  }
  for (int i = 0; i < kSceneH; ++i, ++line_idx) {
    build_normal_line(buf + static_cast<size_t>(line_idx) * kLineSamples, active_level);
  }
  for (int i = 0; i < kLetterboxLines; ++i, ++line_idx) {
    build_normal_line(buf + static_cast<size_t>(line_idx) * kLineSamples,
                       TURTLE_COMPOSITE_LEVEL_BLACK);
  }
}

}  // namespace

bool turtle_gpu_composite_init(void) {
  parlio_tx_unit_config_t config = {};
  config.clk_src = PARLIO_CLK_SRC_DEFAULT;
  config.clk_in_gpio_num = -1;  // reloj interno, no entrada externa
  config.data_width = 8;        // 1 byte = 1 muestra de luma -> escalera R-2R de 8 bits
  config.data_gpio_nums[0] = TURTLE_COMPOSITE_PIN_D0;
  config.data_gpio_nums[1] = TURTLE_COMPOSITE_PIN_D1;
  config.data_gpio_nums[2] = TURTLE_COMPOSITE_PIN_D2;
  config.data_gpio_nums[3] = TURTLE_COMPOSITE_PIN_D3;
  config.data_gpio_nums[4] = TURTLE_COMPOSITE_PIN_D4;
  config.data_gpio_nums[5] = TURTLE_COMPOSITE_PIN_D5;
  config.data_gpio_nums[6] = TURTLE_COMPOSITE_PIN_D6;
  config.data_gpio_nums[7] = TURTLE_COMPOSITE_PIN_D7;
  config.clk_out_gpio_num = TURTLE_COMPOSITE_PIN_CLK_OUT;
  config.output_clk_freq_hz = TURTLE_COMPOSITE_SAMPLE_HZ;
  config.trans_queue_depth = 2;
  // Un campo completo por transaccion (Etapa 1/2: contenido estatico, se
  // repite por DMA via loop_transmission sin tocar CPU). Etapa 3 (framebuffer
  // real) cambiara esto a transmision por linea en cola -- no es parte de v0.
  config.max_transfer_size = static_cast<size_t>(kTotalLines) * kLineSamples;
  config.dma_burst_size = 0;  // por defecto del driver; ajustar en bring-up si hace falta
  config.shift_edge = PARLIO_SHIFT_EDGE_NEG;

  esp_err_t err = parlio_new_tx_unit(&config, &s_tx_unit);
  if (err != ESP_OK) {
    ESP_LOGE(kTag, "parlio_new_tx_unit fallo: %d", static_cast<int>(err));
    return false;
  }
  err = parlio_tx_unit_enable(s_tx_unit);
  if (err != ESP_OK) {
    ESP_LOGE(kTag, "parlio_tx_unit_enable fallo: %d", static_cast<int>(err));
    return false;
  }

  s_field_bytes = static_cast<size_t>(kTotalLines) * kLineSamples;
  // MALLOC_CAP_DMA: el buffer completo (~82 KB) cabe comodo en RAM interna;
  // no hace falta PSRAM para esta etapa (evita cualquier duda sobre soporte
  // de GDMA hacia PSRAM en este SDK todavia sin verificar en hardware).
  s_field_buf = static_cast<uint8_t*>(heap_caps_malloc(s_field_bytes, MALLOC_CAP_DMA));
  if (!s_field_buf) {
    ESP_LOGE(kTag, "sin RAM DMA-capable para el buffer de campo (%u bytes)",
              static_cast<unsigned>(s_field_bytes));
    return false;
  }
  return true;
}

bool turtle_gpu_composite_start_solid_field(uint8_t active_level) {
  if (!s_tx_unit || !s_field_buf) {
    return false;
  }
  build_field(s_field_buf, active_level);

  parlio_transmit_config_t tx_cfg = {};
  tx_cfg.idle_value = TURTLE_COMPOSITE_LEVEL_BLACK;
  tx_cfg.loop_transmission = true;

  esp_err_t err = parlio_tx_unit_transmit(s_tx_unit, s_field_buf, s_field_bytes * 8, &tx_cfg);
  if (err != ESP_OK) {
    ESP_LOGE(kTag, "parlio_tx_unit_transmit fallo: %d", static_cast<int>(err));
    return false;
  }
  return true;
}

void turtle_gpu_composite_stop(void) {
  if (s_tx_unit) {
    parlio_tx_unit_disable(s_tx_unit);
  }
}
