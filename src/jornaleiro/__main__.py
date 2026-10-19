"""Permite rodar sem o console script: `python -m jornaleiro run`."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
