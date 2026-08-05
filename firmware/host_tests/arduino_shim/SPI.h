#pragma once

// Minimal host-side stand-in for the Arduino SPI library — just enough to
// type-check TurtleReader.ino's `SPIClass sdSPI(FSPI); sdSPI.begin(...)`.
// Never talks to real hardware. See README.md's "syntax-only" harness.

enum { FSPI = 0, HSPI = 1, VSPI = 2 };

class SPIClass {
 public:
  explicit SPIClass(int) {}
  void begin(int, int, int, int) {}
};
