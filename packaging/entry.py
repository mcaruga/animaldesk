"""Entrypoint per PyInstaller."""

import sys

from animaldesk.app import main

if __name__ == "__main__":
    sys.exit(main(sys.argv))
