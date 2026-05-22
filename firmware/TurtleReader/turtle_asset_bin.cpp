#include "turtle_asset_bin.h"

#include <Arduino.h>
#include <string.h>

namespace {

constexpr uint8_t kMagicTbg[4] = {'T', 'B', 'G', 0};
constexpr uint8_t kMagicTsp[4] = {'T', 'S', 'P', 0};

static bool magic_ok(const uint8_t* data, size_t len) {
  if (!data || len < 8) {
    return false;
  }
  return (memcmp(data, kMagicTbg, 4) == 0) || (memcmp(data, kMagicTsp, 4) == 0);
}

static uint16_t read_u16_le(const uint8_t* p) {
  return static_cast<uint16_t>(p[0]) | (static_cast<uint16_t>(p[1]) << 8);
}

}  // namespace

bool turtle_asset_bin_decode_indexed(const uint8_t* data, size_t len, int expect_w, int expect_h,
                                     uint8_t* out_rows_top_first, int row_stride) {
  if (!data || len < 8 || !out_rows_top_first || row_stride <= 0 || expect_w <= 0 ||
      expect_h <= 0) {
    return false;
  }
  if (!magic_ok(data, len)) {
    return false;
  }
  if (data[4] != 0) {
    Serial.println("turtle_asset_bin: version no soportada");
    return false;
  }

  const int pw = static_cast<int>(read_u16_le(data + 6));
  const int ph = static_cast<int>(read_u16_le(data + 8));
  const uint8_t mode = data[10];
  if (pw < 1 || ph < 1 || pw > expect_w || ph > expect_h) {
    Serial.printf("turtle_asset_bin: tamano %dx%d no cabe en %dx%d\n", pw, ph, expect_w, expect_h);
    return false;
  }

  const uint8_t* payload = data + 11;
  const size_t pay_len = len - 11;

  if (mode == 0) {
    if (pay_len < 1) {
      return false;
    }
    const uint8_t ci = payload[0];
    for (int y = 0; y < ph; ++y) {
      uint8_t* row = out_rows_top_first + static_cast<size_t>(y) * static_cast<size_t>(row_stride);
      for (int x = 0; x < pw; ++x) {
        row[x] = ci;
      }
    }
    return true;
  }

  if (mode == 1) {
    const size_t need = static_cast<size_t>(pw) * static_cast<size_t>(ph);
    if (pay_len < need) {
      Serial.println("turtle_asset_bin: RAW truncado");
      return false;
    }
    for (int y = 0; y < ph; ++y) {
      memcpy(out_rows_top_first + static_cast<size_t>(y) * static_cast<size_t>(row_stride),
             payload + static_cast<size_t>(y) * static_cast<size_t>(pw),
             static_cast<size_t>(pw));
    }
    return true;
  }

  if (mode == 2) {
    const uint8_t* p = payload;
    const uint8_t* end = data + len;
    for (int y = 0; y < ph; ++y) {
      if (p + 2 > end) {
        return false;
      }
      const int nruns = static_cast<int>(read_u16_le(p));
      p += 2;
      uint8_t* row = out_rows_top_first + static_cast<size_t>(y) * static_cast<size_t>(row_stride);
      int x = 0;
      for (int r = 0; r < nruns && p < end; ++r) {
        if (p + 3 > end) {
          return false;
        }
        const uint8_t ci = p[0];
        const int cnt = static_cast<int>(read_u16_le(p + 1));
        p += 3;
        for (int i = 0; i < cnt && x < pw; ++i, ++x) {
          row[x] = ci;
        }
      }
      if ((y & 15) == 0) {
        yield();
      }
    }
    return true;
  }

  Serial.printf("turtle_asset_bin: modo %u desconocido\n", static_cast<unsigned>(mode));
  return false;
}
