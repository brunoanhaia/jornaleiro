"""Testes do estado persistido entre execucoes (JSON simples, sem rede)."""

from __future__ import annotations

import json
from pathlib import Path

from jornaleiro import state
from jornaleiro.state import State


def test_load_de_arquivo_ausente_ou_invalido_devolve_estado_vazio(tmp_path: Path) -> None:
    corrompido = tmp_path / "corrompido.json"
    corrompido.write_text("{nao sou json", encoding="utf-8")
    lista = tmp_path / "lista.json"
    lista.write_text("[1, 2, 3]", encoding="utf-8")

    for caminho in (tmp_path / "ausente.json", corrompido, lista):
        estado = State.load(caminho)

        assert estado.data == {}
        assert estado.path == caminho


def test_round_trip_set_save_load(tmp_path: Path) -> None:
    caminho = tmp_path / "state.json"

    estado = State(caminho)
    estado.set("examine_last_post_url", "https://instagram.com/p/abc/")
    estado.set("outro", 42)
    estado.save()

    recarregado = State.load(caminho)

    assert recarregado.get("examine_last_post_url") == "https://instagram.com/p/abc/"
    assert recarregado.get("outro") == 42
    assert recarregado.get("ausente", "padrao") == "padrao"


def test_seen_devolve_conjunto_e_ignora_valores_nao_lista(tmp_path: Path) -> None:
    estado = State(tmp_path / "state.json")

    assert estado.seen("examine_seen") == set()  # chave ausente

    estado.set("examine_seen", ["abc", "def"])
    assert estado.seen("examine_seen") == {"abc", "def"}

    estado.set("corrompido", "abc")  # string em vez de lista
    estado.set("nulo", None)
    assert estado.seen("corrompido") == set()
    assert estado.seen("nulo") == set()


def test_add_seen_junta_novos_primeiros_e_respeita_limite(tmp_path: Path) -> None:
    estado = State(tmp_path / "state.json")
    estado.set("examine_seen", ["antigo1", "antigo2"])

    estado.add_seen("examine_seen", ["novo1", "antigo2"], limite=3)

    # novos primeiro, dedup de "antigo2" e cauda aparada pelo limite
    assert estado.data["examine_seen"] == ["novo1", "antigo2", "antigo1"]
    assert estado.seen("examine_seen") == {"novo1", "antigo2", "antigo1"}


def test_add_seen_sem_limite_usa_o_padrao(tmp_path: Path) -> None:
    estado = State(tmp_path / "state.json")

    estado.add_seen("examine_seen", [f"n{i}" for i in range(250)])

    assert len(estado.data["examine_seen"]) == state.LIMITE_SEEN
    assert estado.data["examine_seen"][0] == "n0"


def test_save_grava_atomico_e_nao_deixa_temporario(tmp_path: Path) -> None:
    caminho = tmp_path / "state.json"
    estado = State(caminho)
    estado.set("x", 1)
    estado.set("examine_seen", ["abc"])

    estado.save()

    assert sorted(p.name for p in tmp_path.iterdir()) == ["state.json"]
    assert json.loads(caminho.read_text(encoding="utf-8")) == {"x": 1, "examine_seen": ["abc"]}
