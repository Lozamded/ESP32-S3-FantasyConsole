# FantasyConsole (ESP32-S3)

Primer objetivo del proyecto:
- Definir un formato minimo de cartucho `.turtlecart`.
- Leer ese cartucho desde microSD en ESP32-S3.
- Confirmar por Serial que se leyo un "hola mundo" desde `main.lua`.

## Estado actual (MVP v0)

- Formato: texto plano `.turtlecart` con secciones.
- Firmware: sketch Arduino que:
  - monta SD por SPI,
  - abre `/demo.turtlecart`,
  - extrae el script `main.lua`,
  - detecta `print("...")` y lo muestra por Serial.


## Estructura

- `spec/turtlecart-v0.md`: especificacion inicial.
- `cart/demo.turtlecart`: cartucho de prueba.
- `firmware/esp32_s3_sd_loader/esp32_s3_sd_loader.ino`: firmware MVP.

## Prueba rapida

1. Copia `cart/demo.turtlecart` a la raiz de la microSD con nombre `demo.turtlecart`.
2. Ajusta pines SPI/SD en el sketch segun tu cableado.
3. Flashea el sketch en tu ESP32-S3.
4. Abre monitor serial a `115200`.

Si todo sale bien, vere algo como:
- `TurtleCart cargado correctamente`
- `Mensaje en main.lua: hola mundo desde turtlecart v0`

## Specs ideales para mi consola
- resolución: 240×180
- paleta: 32 colores
