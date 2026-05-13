#!/usr/bin/env python3
"""Lanzador local (no sustituye `pip install -e .`).

Si tras crear el venv solo hiciste `pip install -r requirements.txt`, no existira
`.venv/bin/turtlestudio` (ese wrapper lo crea la instalacion editable del paquete).

Desde esta carpeta (`tools/turtlestudio`):

  .venv/bin/python turtlestudio.py gui
  # o, con el venv activado:
  python turtlestudio.py gui

Para tener el comando `turtlestudio` en el PATH del venv:

  pip install -U pip setuptools
  pip install -e .
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_SRC = (_ROOT / "src").resolve()


def _normalize(p: str) -> str:
    try:
        return str(Path(p).resolve())
    except OSError:
        return p


# Evitar que este archivo se cargue como el modulo `turtlestudio` cuando el cwd
# o PYTHONPATH dejan el directorio del repo delante de `src/`.
_root_s = str(_ROOT)
_src_s = str(_SRC)
_drop = {_normalize(_root_s), _normalize(_src_s)}
sys.path[:] = [_src_s] + [
    p for p in sys.path if _normalize(p) not in _drop
]

from turtlestudio.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
