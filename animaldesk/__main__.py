"""Punto di ingresso: python -m animaldesk"""

from __future__ import annotations

import sys


def main() -> int:
    from .app import main as app_main

    return app_main(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
