"""Prueba export .tbg/.tsp vs JSON del proyecto (sin hardware)."""

from __future__ import annotations

import sys
from pathlib import Path

from turtlestudio.asset_bin_decode import decode_indexed_blob
from turtlestudio.backgrounds import (
    parse_background_palette_rows,
    read_background_file,
    shrink_background_json_for_export,
)
from turtlestudio.build import collect_studio_bundle_files, write_cart_package
from turtlestudio.sprites import parse_palette_rows_image, read_sprite_file
from turtlestudio.verify_package import verify_package_dir


def _rows_equal(a: list[list[int]], b: list[list[int]]) -> bool:
    if len(a) != len(b):
        return False
    for ra, rb in zip(a, b):
        if ra != rb:
            return False
    return True


def test_demo1_build(project_root: Path) -> list[str]:
    errors: list[str] = []
    build = project_root / "build"
    import json

    manifest = json.loads((project_root / "turtlestudio.json").read_text(encoding="utf-8"))
    pkg = collect_studio_bundle_files(
        project_root,
        scenes=manifest["scenes"],
        active_scene="intro",
        transparent_index=31,
        entry_relpath="scripts/global.lua",
    )
    write_cart_package(
        build,
        entry_relpath="scripts/global.lua",
        main_lua_body="print('test')",
        embedded_files=pkg.embedded,
        sidecar_files=pkg.sidecar,
        initial_scene="intro",
    )
    errors.extend(verify_package_dir(build))

    for tbg in (build / "backgrounds").glob("*.tbg"):
        stem = tbg.stem
        try:
            src = shrink_background_json_for_export(read_background_file(project_root, stem))
            expect = parse_background_palette_rows(src)
            if expect is None:
                continue
            pw, ph = int(src["pixel_w"]), int(src["pixel_h"])
            got = decode_indexed_blob(tbg.read_bytes(), expect_w=pw, expect_h=ph)
            if got is None:
                errors.append(f"{tbg.name}: decode fallo")
                continue
            _, _, rows = got
            if not _rows_equal(rows, expect):
                errors.append(f"{tbg.name}: pixels distintos al JSON")
        except ValueError as e:
            errors.append(f"{tbg.name}: {e}")

    for tsp in (build / "sprites").glob("*.tsp"):
        stem = tsp.stem
        try:
            src = read_sprite_file(project_root, stem)
            expect = parse_palette_rows_image(src)
            if expect is None:
                continue
            from turtlestudio.sprites import sprite_pixel_dimensions

            _, pw, ph = sprite_pixel_dimensions(src)
            got = decode_indexed_blob(tsp.read_bytes(), expect_w=pw, expect_h=ph)
            if got is None:
                errors.append(f"{tsp.name}: decode fallo")
                continue
            _, _, rows = got
            if not _rows_equal(rows, expect):
                errors.append(f"{tsp.name}: pixels distintos al JSON")
        except ValueError as e:
            errors.append(f"{tsp.name}: {e}")

    return errors


def main() -> int:
    root = (
        Path(sys.argv[1]).expanduser().resolve()
        if len(sys.argv) > 1
        else Path(__file__).resolve().parents[2] / "exampleprojects" / "demo1"
    )
    errs = test_demo1_build(root)
    if errs:
        print(f"test_asset_bin: FALLO ({len(errs)})")
        for e in errs:
            print(f"  - {e}")
        return 1
    print(f"test_asset_bin: OK ({root / 'build'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
