#pragma once

// Minimal host-side stand-in for the Arduino SD library, just enough of the
// API surface turtle_actor_lua.cpp uses (SD.exists/open, File.available/read/
// close). Never opens a real file — every call fails, which is fine: nothing
// in this repo's host_tests exercises the actual script-loading codepath,
// only that it type-checks (see README.md's "syntax-only" harness).

constexpr int FILE_READ = 0;

class File {
 public:
  explicit operator bool() const { return false; }
  bool available() { return false; }
  int read() { return -1; }
  void close() {}
};

class SPIClass;

struct SDClass {
  bool exists(const char*) { return false; }
  File open(const char*, int) { return File(); }
  template <typename... Args>
  bool begin(Args&&...) {
    return false;
  }
  void end() {}
};

inline SDClass SD;
