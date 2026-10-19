"""Estado persistido entre execucoes (JSON simples)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


LIMITE_SEEN = 200  # shortcodes guardados em `examine_seen` (mais recentes primeiro)


class State:
    """Dicionario com carga/gravação em disco.

    Chaves usadas hoje:
    - ``examine_last_post_url``: URL do ultimo post do Examine processado (semente).
    - ``examine_seen``: shortcodes recentes ja vistos do Instagram (limitados a
      `LIMITE_SEEN`, mais novos primeiro, para o arquivo nao crescer sem limite).
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

    def add_seen(self, key: str, values: list[str], limite: int = LIMITE_SEEN) -> None:
        """Junta `values` (mais recentes primeiro) com o que ja existia, aparando o fim."""
        antigos = self.data.get(key)
        anteriores = [item for item in antigos or [] if isinstance(item, str)]
        merged = list(dict.fromkeys([*values, *anteriores]))
        self.data[key] = merged[:limite] if limite > 0 else merged

    def save(self) -> None:
        """Grava de forma atomica: temporario na mesma pasta + `os.replace`.

        Se o processo morrer no meio, o `state.json` antigo continua valido (antes,
        um `write_text` interrompido deixava o arquivo pela metade).
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conteudo = json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            delete=False,
        ) as arquivo:
            arquivo.write(conteudo)
            temporario = Path(arquivo.name)
        try:
            os.replace(temporario, self.path)
        except OSError:
            temporario.unlink(missing_ok=True)
            raise
