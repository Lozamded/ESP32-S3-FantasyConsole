#include "turtle_tileset.h"

#include "turtle_asset_bin.h"

#include <Arduino.h>
#include <stdlib.h>
#include <string.h>

#if defined(ESP32) || defined(ESP_PLATFORM)
#include <esp_heap_caps.h>
#endif

namespace {

constexpr uint8_t kMagicTts[4] = {'T', 'T', 'S', 0};

static uint16_t read_u16_le(const uint8_t* p) {
  return static_cast<uint16_t>(p[0]) | (static_cast<uint16_t>(p[1]) << 8);
}

static uint32_t read_u32_le(const uint8_t* p) {
  return static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8) |
         (static_cast<uint32_t>(p[2]) << 16) | (static_cast<uint32_t>(p[3]) << 24);
}

static uint8_t* alloc_pixels(size_t nbytes, bool* in_psram) {
  *in_psram = false;
#if defined(ESP32) || defined(ESP_PLATFORM)
  if (heap_caps_get_free_size(MALLOC_CAP_SPIRAM) >= nbytes + 64) {
    uint8_t* p = static_cast<uint8_t*>(
        heap_caps_malloc(nbytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (p) {
      *in_psram = true;
      return p;
    }
  }
#endif
  return static_cast<uint8_t*>(malloc(nbytes));
}

static void free_pixels(uint8_t* p, bool in_psram) {
  if (!p) {
    return;
  }
#if defined(ESP32) || defined(ESP_PLATFORM)
  if (in_psram) {
    heap_caps_free(p);
    return;
  }
#endif
  free(p);
}

}  // namespace

bool turtle_tileset_load_tts(const uint8_t* data, size_t len, TurtleTileset* out) {
  if (!out || !data || len < 10) {
    return false;
  }
  out->tile_px = 16;
  out->tile_count = 0;
  out->pixels = nullptr;
  out->in_psram = false;

  if (memcmp(data, kMagicTts, 4) != 0 || data[4] != 0) {
    return false;
  }

  const int px = static_cast<int>(read_u16_le(data + 6));
  const int count = static_cast<int>(read_u16_le(data + 8));
  if (px < 1 || px > 128 || count < 0 || count > 256) {
    return false;
  }

  const size_t tile_bytes = static_cast<size_t>(px) * static_cast<size_t>(px);
  const size_t total = static_cast<size_t>(count) * tile_bytes;
  uint8_t* pixels = alloc_pixels(total, &out->in_psram);
  if (!pixels && total > 0) {
    Serial.printf("turtle_tileset: sin RAM para %u bytes (%d tiles)\n",
                  static_cast<unsigned>(total), count);
    return false;
  }

  size_t off = 10;
  for (int i = 0; i < count; ++i) {
    if (off + 4 > len) {
      turtle_tileset_free(out);
      return false;
    }
    const uint32_t chunk_len = read_u32_le(data + off);
    off += 4;
    if (chunk_len < 11 || off + chunk_len > len) {
      turtle_tileset_free(out);
      return false;
    }
    if (!turtle_asset_bin_decode_indexed(data + off, chunk_len, px, px,
                                         pixels + static_cast<size_t>(i) * tile_bytes, px)) {
      turtle_tileset_free(out);
      return false;
    }
    off += chunk_len;
  }

  out->tile_px = static_cast<uint8_t>(px);
  out->tile_count = static_cast<uint16_t>(count);
  out->pixels = pixels;
  Serial.printf("turtle_tileset: %d tiles %dx%d (%u bytes)\n", count, px, px,
                static_cast<unsigned>(total));
  return true;
}

void turtle_tileset_free(TurtleTileset* ts) {
  if (!ts) {
    return;
  }
  free_pixels(ts->pixels, ts->in_psram);
  ts->pixels = nullptr;
  ts->tile_count = 0;
  ts->in_psram = false;
}

const uint8_t* turtle_tileset_tile(const TurtleTileset* ts, int index) {
  if (!ts || !ts->pixels || index < 0 || index >= ts->tile_count) {
    return nullptr;
  }
  const size_t tile_bytes =
      static_cast<size_t>(ts->tile_px) * static_cast<size_t>(ts->tile_px);
  return ts->pixels + static_cast<size_t>(index) * tile_bytes;
}
