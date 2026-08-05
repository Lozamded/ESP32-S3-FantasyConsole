#pragma once

// Minimal host-side stand-in for <Arduino.h>, just enough to compile the
// firmware .cpp files listed in run_font_test.sh outside the Arduino toolchain
// (see README.md). NOT part of the sketch build — never included by TurtleReader.ino.

#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <string>

struct SerialShim {
  void begin(unsigned long) {}
  void printf(const char* fmt, ...) {
    va_list args;
    va_start(args, fmt);
    vfprintf(stderr, fmt, args);
    va_end(args);
  }
  void println() { fprintf(stderr, "\n"); }
  void println(const char* s) { fprintf(stderr, "%s\n", s); }
  void print(const char* s) { fprintf(stderr, "%s", s); }
  void print(char c) { fputc(c, stderr); }
};

inline SerialShim Serial;

// No-op: real Arduino core yields to the RTOS scheduler during long loops
// (turtle_scene.cpp calls this while scanning big JSON buffers).
inline void yield() {}

inline void delay(unsigned long) {}
inline unsigned long millis() { return 0; }

// Minimal stand-in for Arduino's WString.h String class — just enough of the
// API surface turtle_actor_lua.cpp uses (+= char, c_str(), length()).
class String : public std::string {
 public:
  String() = default;
  String(const char* s) : std::string(s) {}  // NOLINT(google-explicit-constructor)
  String& operator+=(char c) {
    std::string::operator+=(c);
    return *this;
  }
};
