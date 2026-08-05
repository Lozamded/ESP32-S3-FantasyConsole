"""Phase 1 verification: produce a .tfn fixture + the expected decode dump (Python side).

Run via run_font_test.sh, not directly. Reuses the real turtlestudio package so the
fixture is byte-identical to what the export pipeline actually ships.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS_SRC = Path(__file__).resolve().parents[2] / "tools" / "turtlestudio" / "src"
sys.path.insert(0, str(TOOLS_SRC))

from turtlestudio.asset_bin import font_json_to_tfn  # noqa: E402
from turtlestudio.asset_bin_decode import decode_font_blob  # noqa: E402


def dump_decoded(px: int, lh: int, bl: int, advances: list[int], glyphs: list[list[list[int]]]) -> str:
    lines = [f"HEADER px={px} lh={lh} bl={bl} count={len(advances)}"]
    for i, (adv, rows) in enumerate(zip(advances, glyphs)):
        flat = ",".join(str(v) for row in rows for v in row)
        lines.append(f"GLYPH {i} adv={adv} px={flat}")
    return "\n".join(lines) + "\n"


def main() -> int:
    if len(sys.argv) != 4:
        print("uso: gen_font_fixture.py <font.json> <out.tfn> <out_expected.txt>", file=sys.stderr)
        return 2
    font_json_path, out_tfn, out_expected = sys.argv[1], sys.argv[2], sys.argv[3]

    data = json.loads(Path(font_json_path).read_text(encoding="utf-8"))
    blob = font_json_to_tfn(data)
    Path(out_tfn).write_bytes(blob)

    decoded = decode_font_blob(blob)
    if decoded is None:
        print("decode_font_blob devolvio None (deberia ser correcto)", file=sys.stderr)
        return 1
    px, lh, bl, advances, glyphs = decoded
    Path(out_expected).write_text(dump_decoded(px, lh, bl, advances, glyphs), encoding="utf-8")
    print(f"fixture: {out_tfn} ({len(blob)} bytes), expected: {out_expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
