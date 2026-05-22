#include "turtle_cart.h"

#include <Arduino.h>
#include <SD.h>
#include <string.h>

#if defined(ESP32) || defined(ESP_PLATFORM)
#include <esp_heap_caps.h>
#endif

namespace {

constexpr size_t kMaxCartBytes = 4 * 1024 * 1024;

static size_t psram_free_bytes(void) {
#if defined(ESP32) || defined(ESP_PLATFORM)
  return heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
#else
  return 0;
#endif
}

static char* alloc_cart_buffer(size_t sz, bool* used_psram) {
  *used_psram = false;
#if defined(ESP32) || defined(ESP_PLATFORM)
  if (psram_free_bytes() >= sz + 64) {
    char* p = static_cast<char*>(heap_caps_malloc(sz + 1, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (p) {
      *used_psram = true;
      return p;
    }
  }
#endif
  return static_cast<char*>(malloc(sz + 1));
}

}  // namespace

bool turtle_cart_load_sd_file(const char* path, TurtleCartBuffer* out, bool quiet) {
  if (!out) {
    return false;
  }
  out->data = nullptr;
  out->len = 0;
  out->in_psram = false;

  File file = SD.open(path, FILE_READ);
  if (!file) {
    Serial.printf("SD: no se pudo abrir %s\n", path);
    return false;
  }

  const size_t sz = file.size();
  if (sz == 0) {
    Serial.printf("SD: %s vacio\n", path);
    file.close();
    return false;
  }
  if (sz > kMaxCartBytes) {
    Serial.printf("SD: %s demasiado grande (%u bytes)\n", path, static_cast<unsigned>(sz));
    file.close();
    return false;
  }

  if (!quiet) {
    Serial.printf("SD: leyendo %s (%u bytes", path, static_cast<unsigned>(sz));
#if defined(ESP32) || defined(ESP_PLATFORM)
    Serial.printf(", PSRAM libre ~%u", static_cast<unsigned>(psram_free_bytes()));
#endif
    Serial.println(")...");
  }

  bool in_psram = false;
  char* buf = alloc_cart_buffer(sz, &in_psram);
  if (!buf) {
    Serial.printf("SD: sin RAM para %u bytes (activa PSRAM en la placa si el cart es grande)\n",
                  static_cast<unsigned>(sz));
    file.close();
    return false;
  }

  const size_t rd = file.read(reinterpret_cast<uint8_t*>(buf), sz);
  file.close();
  if (rd != sz) {
    Serial.printf("SD: lectura incompleta %u/%u\n", static_cast<unsigned>(rd),
                  static_cast<unsigned>(sz));
    if (in_psram) {
      heap_caps_free(buf);
    } else {
      free(buf);
    }
    return false;
  }
  buf[sz] = '\0';

  out->data = buf;
  out->len = sz;
  out->in_psram = in_psram;
  if (!quiet) {
    Serial.printf("SD: %s OK (%u bytes%s)\n", path, static_cast<unsigned>(sz),
                  in_psram ? ", PSRAM" : ", heap interna");
  }
  return true;
}

void turtle_cart_free(TurtleCartBuffer* buf) {
  if (!buf || !buf->data) {
    return;
  }
#if defined(ESP32) || defined(ESP_PLATFORM)
  if (buf->in_psram) {
    heap_caps_free(buf->data);
  } else {
    free(buf->data);
  }
#else
  free(buf->data);
#endif
  buf->data = nullptr;
  buf->len = 0;
  buf->in_psram = false;
}

bool turtle_cart_extract_embedded(const TurtleCartBuffer* cart, const char* rel_path,
                                  const char** out_begin, size_t* out_len) {
  if (!cart || !cart->data || cart->len == 0 || !rel_path || !out_begin || !out_len) {
    return false;
  }
  char marker[96];
  const int n = snprintf(marker, sizeof marker, "---FILE:%s---", rel_path);
  if (n <= 0 || static_cast<size_t>(n) >= sizeof marker) {
    return false;
  }

  const char* hay = cart->data;
  const char* hay_end = cart->data + cart->len;
  const size_t mlen = static_cast<size_t>(n);

  const char* start_marker = nullptr;
  for (const char* p = hay; p + mlen <= hay_end; ++p) {
    if (memcmp(p, marker, mlen) == 0) {
      start_marker = p;
      break;
    }
  }
  if (!start_marker) {
    return false;
  }

  const char* content = start_marker + mlen;
  while (content < hay_end && (*content == '\r' || *content == '\n')) {
    ++content;
  }

  const char* end_tag = "---END---";
  const size_t end_len = strlen(end_tag);
  const char* end_marker = nullptr;
  for (const char* p = content; p + end_len <= hay_end; ++p) {
    if (memcmp(p, end_tag, end_len) == 0) {
      end_marker = p;
      break;
    }
  }
  if (!end_marker || end_marker <= content) {
    return false;
  }

  while (end_marker > content &&
         (end_marker[-1] == '\r' || end_marker[-1] == '\n' || end_marker[-1] == ' ')) {
    --end_marker;
  }

  *out_begin = content;
  *out_len = static_cast<size_t>(end_marker - content);
  return true;
}

bool turtle_cart_header_value(const TurtleCartBuffer* cart, const char* key, char* out,
                              size_t out_cap) {
  if (!cart || !cart->data || !key || !out || out_cap < 2) {
    return false;
  }
  out[0] = '\0';

  const char* p = cart->data;
  const char* end = cart->data + cart->len;
  const size_t klen = strlen(key);

  while (p < end) {
    const char* line_end = static_cast<const char*>(memchr(p, '\n', static_cast<size_t>(end - p)));
    if (!line_end) {
      line_end = end;
    }
    size_t line_len = static_cast<size_t>(line_end - p);
    if (line_len > 0 && p[line_len - 1] == '\r') {
      --line_len;
    }
    if (line_len >= klen && memcmp(p, key, klen) == 0) {
      const char* val = p + klen;
      size_t vlen = line_len - klen;
      while (vlen > 0 && (*val == ' ' || *val == '\t')) {
        ++val;
        --vlen;
      }
      while (vlen > 0 && (val[vlen - 1] == ' ' || val[vlen - 1] == '\t' || val[vlen - 1] == '\r')) {
        --vlen;
      }
      if (vlen >= out_cap) {
        vlen = out_cap - 1;
      }
      memcpy(out, val, vlen);
      out[vlen] = '\0';
      return true;
    }
    if (line_len >= 9 && memcmp(p, "---FILE:", 9) == 0) {
      break;
    }
    p = (line_end < end) ? line_end + 1 : end;
  }
  return false;
}

bool turtle_cart_extract_palette(const TurtleCartBuffer* cart, const char** out_begin,
                                 size_t* out_len) {
  if (!cart || !cart->data || !out_begin || !out_len) {
    return false;
  }
  *out_begin = nullptr;
  *out_len = 0;

  const char* tag = "PALETTE:";
  const char* p = cart->data;
  const char* end = cart->data + cart->len;
  const size_t tlen = strlen(tag);

  while (p + tlen <= end) {
    if (memcmp(p, tag, tlen) != 0) {
      ++p;
      continue;
    }
    if (p > cart->data && p[-1] != '\n' && p[-1] != '\r') {
      ++p;
      continue;
    }
    const char* line_end = static_cast<const char*>(memchr(p, '\n', static_cast<size_t>(end - p)));
    if (!line_end) {
      line_end = end;
    }
    const char* content = line_end;
    if (content < end && *content == '\n') {
      ++content;
    }
    const char* file_mark = "---FILE:";
    const char* stop = end;
    for (const char* q = content; q + 9 <= end; ++q) {
      if (memcmp(q, file_mark, 9) == 0) {
        stop = q;
        break;
      }
    }
    while (stop > content && (stop[-1] == '\r' || stop[-1] == '\n' || stop[-1] == ' ')) {
      --stop;
    }
    if (stop > content) {
      *out_begin = content;
      *out_len = static_cast<size_t>(stop - content);
      return true;
    }
    return false;
  }
  return false;
}
