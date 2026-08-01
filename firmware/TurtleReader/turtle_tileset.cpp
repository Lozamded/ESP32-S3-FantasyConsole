#include "turtle_tileset.h"

#include "turtle_asset_bin.h"
#include "turtle_tile_collision.h"

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

  if (memcmp(data, kMagicTts, 4) != 0 || (data[4] != 0 && data[4] != 1)) {
    return false;
  }
  const uint8_t format_version = data[4];

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
  out->format_version = format_version;

  // v1: bloque de colision por tile embebido tras los chunks de pixeles (10 bytes/tile,
  // ver spec/asset-bin-v0.md). Si falta o esta truncado, cae a defaults (todo solido).
  bool coll_from_binary = false;
  if (format_version == 1) {
    constexpr size_t kCollRecordSize = 10;
    const size_t coll_total = static_cast<size_t>(count) * kCollRecordSize;
    if (coll_total == 0 || off + coll_total <= len) {
      turtle_tile_collision_defaults(out);
      const int n = count > kTurtleTileCollMax ? kTurtleTileCollMax : count;
      for (int i = 0; i < n; ++i) {
        const uint8_t* rec = data + off + static_cast<size_t>(i) * kCollRecordSize;
        TurtleTileCollEntry* e = &out->coll[i];
        const uint8_t kind = rec[0];
        e->kind = (kind <= TURTLE_TILE_COLL_AABB) ? kind : TURTLE_TILE_COLL_SOLID;
        const uint8_t flags = rec[1];
        e->oneway = flags & 0x01;
        e->oneway_dir = static_cast<uint8_t>((flags >> 1) & 0x03);
        e->x0 = static_cast<int16_t>(read_u16_le(rec + 2));
        e->y0 = static_cast<int16_t>(read_u16_le(rec + 4));
        e->x1 = static_cast<int16_t>(read_u16_le(rec + 6));
        e->y1 = static_cast<int16_t>(read_u16_le(rec + 8));
      }
      turtle_tile_collision_recompute_has_solid(out);
      coll_from_binary = true;
    }
  }
  if (!coll_from_binary) {
    turtle_tile_collision_defaults(out);
  }

  Serial.printf("turtle_tileset: %d tiles %dx%d (%u bytes)%s\n", count, px, px,
                static_cast<unsigned>(total), coll_from_binary ? " +coll" : "");
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
  ts->format_version = 0;
  turtle_tile_collision_defaults(ts);
}

const uint8_t* turtle_tileset_tile(const TurtleTileset* ts, int index) {
  if (!ts || !ts->pixels || index < 0 || index >= ts->tile_count) {
    return nullptr;
  }
  const size_t tile_bytes =
      static_cast<size_t>(ts->tile_px) * static_cast<size_t>(ts->tile_px);
  return ts->pixels + static_cast<size_t>(index) * tile_bytes;
}
