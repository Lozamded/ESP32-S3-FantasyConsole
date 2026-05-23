# Assets binarios en SD (exportacion v0)

TurtleStudio **sigue editando JSON** en el proyecto (`backgrounds/*.json`, `sprites/*.json`).

Al **exportar el paquete SD**, los pixeles indexados se convierten a binario:

| Extension | Uso |
|-----------|-----|
| `.tbg` | Fondo (`TBG\0`) |
| `.tsp` | Sprite (`TSP\0`) |
| `.json` | Objetos (pequenos, legibles) |

## Cabecera (little-endian)

| Offset | Campo |
|--------|--------|
| 0 | Magic `TBG\0` o `TSP\0` |
| 4 | `version` u8 (=0) |
| 5 | `flags` u8 (=0) |
| 6 | `pixel_w` u16 |
| 8 | `pixel_h` u16 |
| 10 | `mode` u8 (solo v0 mono-fotograma) |

### Sprite multi-fotograma (`.tsp` version 1)

| Offset | Campo |
|--------|--------|
| 4 | `version` u8 (=1) |
| 6 | `pixel_w` u16 |
| 8 | `pixel_h` u16 |
| 10 | `frame_count` u16 |
| 12+ | Por fotograma: `chunk_len` u32 + `[mode u8][payload…]` (mismo payload que v0 tras `mode`) |

`version` 0 = un solo fotograma (layout anterior). El exportador usa v1 si `frame_count > 1` en el JSON del sprite.

## Modos (`mode`)

| Valor | Nombre | Payload |
|-------|--------|---------|
| 0 | SOLID | 1 byte: indice de paleta |
| 1 | RAW | `pixel_w * pixel_h` bytes (fila 0 = arriba) |
| 2 | ROW_RLE | Por fila: `nruns` u16, luego `nruns` × (`idx` u8, `count` u16) |

El exportador elige el modo mas pequeno (solid &lt; RLE &lt; RAW segun imagen).

## Bundle

Referencias en `studio/project_bundle.json`:

```json
"backgrounds": {
  "cielo": { "kind": "turtlestudio.background_ref", "file": "backgrounds/cielo.tbg" }
}
```

Firmware: `turtle_asset_bin.cpp` + JSON legacy (`.json` en SD si hace falta).
