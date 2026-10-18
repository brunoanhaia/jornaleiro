"""Estado persistido entre execucoes (JSON simples)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class State:
    """Dicionario com carga/gravação em disco.

    Chaves usadas hoje:
    - ``examine_last_post_url``: URL do ultimo post do Examine processado (semente).
    - ``examine_seen``: lista de shortcodes ja vistos/processados do Instagram.
    """

    def __init__(self, path: Path, data: dict[str, Any] | None = None) -> None:
        self.path = path
        self.data: dict[str, Any] = dict(data or {})

    @classmethod
    def load(cls, path: Path) -> "State":
        if not path.exists():
            return cls(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls(path)
        if not isinstance(data, dict):
            return cls(path)
        return cls(path, data)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def seen(self, key: str) -> set[str]:
        values = self.data.get(key) or []
        return set(values) if isinstance(values, list) else set()

    def add_seen(self, key: str, values: list[str]) -> None:
        merged = self.seen(key)
        for value in values:
            merged.add(value)
        self.data[key] = sorted(merged)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
