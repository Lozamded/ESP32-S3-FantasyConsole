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

static uint32_t read_u32_le(const uint8_t* p) {
  return static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8) |
         (static_cast<uint32_t>(p[2]) << 16) | (static_cast<uint32_t>(p[3]) << 24);
}

static bool decode_mode_payload(uint8_t mode, const uint8_t* payload, size_t pay_len, int pw,
                                int ph, uint8_t* out_rows_top_first, int row_stride) {
  if (pw <= 0 || ph <= 0 || !out_rows_top_first || row_stride <= 0) {
    return false;
  }

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
    const uint8_t* end = payload + pay_len;
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
    }
    return true;
  }

  return false;
}

}  // namespace

bool turtle_asset_bin_decode_indexed(const uint8_t* data, size_t len, int expect_w, int expect_h,
                                     uint8_t* out_rows_top_first, int row_stride) {
  if (!data || len < 11 || !out_rows_top_first || row_stride <= 0 || expect_w <= 0 ||
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

  return decode_mode_payload(mode, data + 11, len - 11, pw, ph, out_rows_top_first, row_stride);
}

int turtle_asset_bin_sprite_frame_count(const uint8_t* data, size_t len) {
  if (!data || len < 11 || memcmp(data, kMagicTsp, 4) != 0) {
    return 0;
  }
  if (data[4] == 0) {
    return 1;
  }
  if (data[4] == 1 && len >= 12) {
    const int fc = static_cast<int>(read_u16_le(data + 10));
    return fc > 0 ? fc : 0;
  }
  return 0;
}

bool turtle_asset_bin_decode_sprite_frame(const uint8_t* data, size_t len, int frame_index,
                                          int expect_w, int expect_h,
                                          uint8_t* out_rows_top_first, int row_stride) {
  if (!data || len < 11 || frame_index < 0 || !out_rows_top_first) {
    return false;
  }
  if (memcmp(data, kMagicTsp, 4) != 0) {
    return false;
  }

  if (data[4] == 0) {
    if (frame_index != 0) {
      return false;
    }
    return turtle_asset_bin_decode_indexed(data, len, expect_w, expect_h, out_rows_top_first,
                                           row_stride);
  }

  if (data[4] != 1 || len < 12) {
    return false;
  }

  const int pw = static_cast<int>(read_u16_le(data + 6));
  const int ph = static_cast<int>(read_u16_le(data + 8));
  const int fc = static_cast<int>(read_u16_le(data + 10));
  if (pw < 1 || ph < 1 || pw > expect_w || ph > expect_h || fc < 1 || frame_index >= fc) {
    return false;
  }

  size_t off = 12;
  for (int i = 0; i < fc; ++i) {
    if (off + 4 > len) {
      return false;
    }
    const uint32_t chunk_len = read_u32_le(data + off);
    off += 4;
    if (chunk_len < 1 || off + chunk_len > len) {
      return false;
    }
    if (i == frame_index) {
      const uint8_t mode = data[off];
      return decode_mode_payload(mode, data + off + 1, chunk_len - 1, pw, ph, out_rows_top_first,
                                 row_stride);
    }
    off += chunk_len;
  }
  return false;
}
