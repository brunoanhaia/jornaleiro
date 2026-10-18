"""Permite rodar sem o console script: `python -m jornais run`."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
