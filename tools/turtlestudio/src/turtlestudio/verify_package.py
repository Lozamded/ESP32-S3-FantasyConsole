"""Comprueba que un paquete exportado (carpeta build/) coincide con el bundle del cartucho."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_FILE_BLOCK = re.compile(
    r"---FILE:(?P<path>[^-]+)---\n(?P<body>.*?)\n---END---",
    re.DOTALL,
)


def _bundle_from_cart(cart_text: str) -> dict:
    for block in _FILE_BLOCK.finditer(cart_text):
        if block.group("path") == "studio/project_bundle.json":
            return json.loads(block.group("body"))
    raise ValueError("sin studio/project_bundle.json embebido en el cartucho")


def _bundle_from_package(package_dir: Path) -> dict:
    sidecar = package_dir / "studio" / "project_bundle.json"
    if sidecar.is_file():
        return json.loads(sidecar.read_text(encoding="utf-8"))
    cart = package_dir / "main.turtlecart"
    if cart.is_file():
        return _bundle_from_cart(cart.read_text(encoding="utf-8"))
    raise ValueError("sin studio/project_bundle.json (sidecar ni embebido)")


def verify_package_dir(package_dir: Path) -> list[str]:
    """Devuelve lista de errores (vacia = OK)."""
    errors: list[str] = []
    cart = package_dir / "main.turtlecart"
    if not cart.is_file():
        errors.append(f"falta {cart}")
        return errors

    bundle = _bundle_from_package(package_dir)

    def check_refs(section: str) -> None:
        data = bundle.get(section)
        if not isinstance(data, dict):
            return
        for key, entry in data.items():
            if not isinstance(entry, dict):
                continue
            rel = str(entry.get("file", "")).strip()
            if not rel:
                if section == "sprites" and entry.get("kind", "").endswith("_ref"):
                    errors.append(f"{section}/{key}: ref sin file")
                continue
            p = package_dir / rel.replace("\\", "/")
            if not p.is_file():
                errors.append(f"falta sidecar {rel} (ref en bundle.{section}.{key})")
                continue
            if p.suffix.lower() in (".tbg", ".tsp"):
                raw = p.read_bytes()
                if len(raw) < 11 or raw[0] != ord("T") or raw[3] != 0:
                    errors.append(f"{rel}: magic binario invalido")
            if p.suffix.lower() == ".tts":
                raw = p.read_bytes()
                if len(raw) < 10 or raw[:4] != b"TTS\x00":
                    errors.append(f"{rel}: magic .tts invalido")
            if p.suffix.lower() == ".tfn":
                raw = p.read_bytes()
                if len(raw) < 14 or raw[:4] != b"TFN\x00":
                    errors.append(f"{rel}: magic .tfn invalido")

    check_refs("backgrounds")
    check_refs("sprites")
    check_refs("tilesets")
    check_refs("fonts")
    check_refs("objects")

    sprites = bundle.get("sprites")
    if isinstance(sprites, dict) and len(sprites) == 0:
        scenes = bundle.get("scenes")
        if isinstance(scenes, list):
            oids: set[str] = set()
            for sc in scenes:
                if not isinstance(sc, dict):
                    continue
                for ob in sc.get("objects") or []:
                    if isinstance(ob, dict):
                        # "object" = referencia de catalogo (spec/scene-object-identity-v0.md);
                        # fallback a "id" para bundles legado sin migrar.
                        robj = ob.get("object")
                        oid = str(robj).strip() if isinstance(robj, str) and robj.strip() else str(ob.get("id", "")).strip()
                        if oid:
                            oids.add(oid)
            if oids:
                errors.append(
                    "sprites vacio en bundle pero hay objetos en escenas "
                    "(reexporta tras corregir build.py)"
                )

    return errors


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    root = Path(args[0]).expanduser().resolve() if args else Path("build").resolve()
    errs = verify_package_dir(root)
    if errs:
        print(f"Paquete {root}: FALLO ({len(errs)} problemas)")
        for e in errs:
            print(f"  - {e}")
        return 1
    print(f"Paquete {root}: OK (refs y sidecars coherentes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
