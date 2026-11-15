"""Testes do agendador interno (nenhum sleep real, nenhum navegador, nenhum rede)."""

# pylint: disable=protected-access

from __future__ import annotations

import sys
from datetime import datetime, time, timedelta
from pathlib import Path

import pytest

from jornaleiro import agenda
from jornaleiro.model import SP

AGORA = datetime(2026, 11, 16, 7, 5, tzinfo=SP)
SLOTS = (time(7, 0), time(19, 0))


def momento(*partes: int) -> datetime:
    return datetime(2026, 11, *partes, tzinfo=SP)


def parametros_curtos(**extra) -> agenda.Parametros:
    base = {
        "slots": SLOTS,
        "tolerancia_min": 90,
        "batida_s": 30,
        "espera_max_s": 30,
        "saude_janela_s": 300,
        "falhas_limite": 3,
    }
    base.update(extra)
    return agenda.Parametros(**base)


def test_horarios_aceita_string_lista_e_padrao() -> None:
    assert agenda.horarios("07:00, 19:00") == [time(7, 0), time(19, 0)]
    assert agenda.horarios("19:00,07:00,07:00") == [time(7, 0), time(19, 0)]
    assert agenda.horarios(["08:00", "20:00"]) == [time(8, 0), time(20, 0)]
    assert agenda.horarios(None) == [time(7, 0), time(19, 0)]
    assert agenda.horarios("") == [time(7, 0), time(19, 0)]
    assert agenda.horarios([]) == [time(7, 0), time(19, 0)]


def test_horarios_recusa_token_invalido() -> None:
    with pytest.raises(ValueError, match="horario invalido: '7h'"):
        agenda.horarios("7h")


def test_proxima_execucao_no_mesmo_dia_e_na_virada() -> None:
    assert agenda.proxima_execucao(momento(16, 6, 0), SLOTS) == momento(16, 7, 0)
    # exatamente no horario ja conta como passado
    assert agenda.proxima_execucao(momento(16, 7, 0), SLOTS) == momento(16, 19, 0)
    assert agenda.proxima_execucao(momento(16, 20, 0), SLOTS) == momento(17, 7, 0)


def test_devida_faz_catch_up_dentro_da_tolerancia() -> None:
    assert agenda.devida(momento(16, 7, 5), SLOTS, 90, {}) == momento(16, 7, 0)
    assert agenda.devida(momento(16, 12, 0), SLOTS, 90, {}) is None  # tarde demais
    assert agenda.devida(momento(16, 6, 0), SLOTS, 90, {}) is None  # nada vencido ainda


def test_devida_nao_repete_o_slot_ja_executado() -> None:
    estado = {"ultima": {"inicio": momento(16, 7, 5).isoformat()}}

    assert agenda.devida(momento(16, 7, 6), SLOTS, 90, estado) is None
    # estado corrompido conta como "nunca rodou"
    assert agenda.devida(momento(16, 7, 6), SLOTS, 90, {"ultima": "lixo"}) == momento(16, 7, 0)
    assert agenda.devida(momento(16, 7, 6), SLOTS, 90, {"ultima": {"inicio": "x"}}) == momento(
        16, 7, 0
    )


def test_devida_respeita_o_limite_exato_da_tolerancia() -> None:
    assert agenda.devida(momento(16, 8, 30), SLOTS, 90, {}) == momento(16, 7, 0)
    assert agenda.devida(momento(16, 8, 30), SLOTS, 89, {}) is None


def test_parametros_usa_os_padroes() -> None:
    params = agenda.parametros({})

    assert params.slots == (time(7, 0), time(19, 0))
    assert params.tolerancia_min == agenda.TOLERANCIA_PADRAO_MIN
    assert params.batida_s == agenda.BATIDA_PADRAO_S
    assert params.espera_max_s == agenda.ESPERA_PADRAO_S
    assert params.saude_janela_s == agenda.SAUDE_JANELA_PADRAO_S
    assert params.falhas_limite == agenda.FALHAS_PADRAO


def test_parametros_le_a_secao() -> None:
    params = agenda.parametros(
        {
            "horarios": ["08:00"],
            "tolerancia_min": 15,
            "batida_s": 10,
            "espera_max_s": 5,
            "saude_janela_s": 60,
            "falhas_limite": 2,
        }
    )

    assert params.slots == (time(8, 0),)
    assert (params.tolerancia_min, params.batida_s, params.espera_max_s) == (15, 10, 5)
    assert (params.saude_janela_s, params.falhas_limite) == (60, 2)
    assert agenda.parametros({"horarios": "08:00,20:00"}).slots == (time(8, 0), time(20, 0))


def test_parametros_recusa_valores_fora_da_faixa() -> None:
    with pytest.raises(ValueError, match="agenda: batida_s"):
        agenda.parametros({"batida_s": 0})
    with pytest.raises(ValueError, match="esperado inteiro"):
        agenda.parametros({"tolerancia_min": "abc"})
    with pytest.raises(ValueError, match="pelo menos o dobro"):
        agenda.parametros({"batida_s": 30, "saude_janela_s": 50})
    with pytest.raises(ValueError, match="agenda: falhas_limite"):
        agenda.parametros({"falhas_limite": 0})


def test_verificar_aprova_batida_recente() -> None:
    agora = AGORA

    assert agenda.verificar({}, agora, saude_janela_s=300, falhas_limite=3) == (
        "agenda.json sem atualizado_em"
    )
    assert agenda.verificar(
        {"atualizado_em": agora.isoformat()}, agora, saude_janela_s=300, falhas_limite=3
    ) is None
    assert agenda.verificar(
        {"atualizado_em": "nem data"}, agora, saude_janela_s=300, falhas_limite=3
    ) == "agenda.json com atualizado_em ilegivel: 'nem data'"


def test_verificar_reprova_batida_velha_e_falhas_seguidas() -> None:
    agora = AGORA
    velho = (agora - timedelta(minutes=10)).isoformat()

    motivo = agenda.verificar({"atualizado_em": velho}, agora, saude_janela_s=300, falhas_limite=3)
    assert motivo == "agenda parada ha 600s"

    recente = {"atualizado_em": agora.isoformat(), "falhas_seguidas": 3}
    assert agenda.verificar(recente, agora, saude_janela_s=300, falhas_limite=3) == (
        "3 execucoes seguidas com falha"
    )
    assert agenda.verificar(recente, agora, saude_janela_s=300, falhas_limite=5) is None


def test_comando_do_run(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"

    minimo = agenda.comando(config, None, False)
    assert minimo[:4] == [sys.executable, "-m", "jornaleiro", "run"]
    assert minimo[-2:] == ["--config", str(config)]

    completo = agenda.comando(config, tmp_path / "dados", True)
    assert completo[-5:] == [
        "--config",
        str(config),
        "--data-dir",
        str(tmp_path / "dados"),
        "--no-send",
    ]


def test_rodar_executa_o_slot_devido_uma_vez(tmp_path: Path, monkeypatch, capsys) -> None:
    destino = tmp_path / "agenda.json"
    avisos: list[str] = []
    fila = agenda.Agenda(
        params=parametros_curtos(),
        estado_path=destino,
        comando=["jornaleiro", "run"],
        avisar=avisos.append,
        relogio=lambda: AGORA,
        dormir=lambda _segundos: None,
    )
    monkeypatch.setattr(
        agenda.Agenda, "_executar", lambda self: (0, AGORA + timedelta(seconds=40))
    )

    assert fila.rodar(max_execucoes=1) == 0
    assert not avisos
    assert "[agenda] proxima execucao: 16/11 19:00" in capsys.readouterr().out

    estado = agenda.State.load(destino).data
    assert estado["ultima"]["codigo"] == 0
    assert estado["ultima"]["inicio"] == AGORA.isoformat()
    assert estado["falhas_seguidas"] == 0
    assert datetime.fromisoformat(estado["proxima"]) == momento(16, 19, 0)
    assert datetime.fromisoformat(estado["atualizado_em"]) == AGORA

    # o mesmo slot nao roda de novo
    assert fila.passo() is False


def test_executar_agora_avisa_e_conta_falhas(tmp_path: Path, monkeypatch) -> None:
    destino = tmp_path / "agenda.json"
    avisos: list[str] = []
    fila = agenda.Agenda(
        params=parametros_curtos(),
        estado_path=destino,
        comando=["jornaleiro", "run"],
        avisar=avisos.append,
        relogio=lambda: AGORA,
        dormir=lambda _segundos: None,
    )
    monkeypatch.setattr(
        agenda.Agenda, "_executar", lambda self: (1, AGORA + timedelta(seconds=12))
    )

    assert fila.executar_agora() == 1
    assert len(avisos) == 1
    assert "falhou (codigo 1)" in avisos[0]
    assert "em 12s" in avisos[0]
    assert f"Log: {tmp_path / '2026-11-16' / 'run.log'}" in avisos[0]
    assert "Proxima: 16/11 19:00" in avisos[0]
    estado = agenda.State.load(destino).data
    assert estado["falhas_seguidas"] == 1

    # segunda falha seguida soma
    fila.executar_agora()
    assert agenda.State.load(destino).data["falhas_seguidas"] == 2


def test_executar_agora_nao_avisa_no_encerramento(tmp_path: Path, monkeypatch) -> None:
    avisos: list[str] = []
    fila = agenda.Agenda(
        params=parametros_curtos(),
        estado_path=tmp_path / "agenda.json",
        comando=["jornaleiro", "run"],
        avisar=avisos.append,
        relogio=lambda: AGORA,
        dormir=lambda _segundos: None,
    )
    monkeypatch.setattr(
        agenda.Agenda, "_executar", lambda self: (1, AGORA + timedelta(seconds=1))
    )
    monkeypatch.setattr(agenda._PARADA, "ligada", True)

    try:
        assert fila.executar_agora() == 1
    finally:
        monkeypatch.setattr(agenda._PARADA, "ligada", False)
    assert not avisos


def test_executar_roda_o_subprocesso_e_bate_o_coracao(tmp_path: Path) -> None:
    destino = tmp_path / "agenda.json"
    relogio = AGORA
    batidas: list[datetime] = []

    def avancar() -> datetime:
        nonlocal relogio
        relogio = relogio + timedelta(seconds=31)
        batidas.append(relogio)
        return relogio

    fila = agenda.Agenda(
        params=parametros_curtos(batida_s=30),
        estado_path=destino,
        comando=[sys.executable, "-c", "pass"],
        avisar=lambda _texto: None,
        relogio=avancar,
        dormir=lambda _segundos: None,
    )

    code, fim = fila._executar()

    assert code == 0
    assert fim > AGORA
    assert destino.exists()  # a batida gravou agenda.json durante o run
    assert agenda.State.load(destino).data["atualizado_em"] in {b.isoformat() for b in batidas}


def test_instalar_sinais_liga_o_parar(monkeypatch) -> None:
    handlers: dict[int, object] = {}

    def guardar(sig, fn):
        handlers[sig] = fn

    monkeypatch.setattr(agenda.signal, "signal", guardar)
    monkeypatch.setattr(agenda._PARADA, "ligada", False)

    agenda.instalar_sinais()
    assert set(handlers) == {agenda.signal.SIGTERM, agenda.signal.SIGINT}

    handler = handlers[agenda.signal.SIGTERM]
    assert callable(handler)
    handler(int(agenda.signal.SIGTERM), None)
    try:
        assert agenda._PARADA.ligada is True
    finally:
        monkeypatch.setattr(agenda._PARADA, "ligada", False)
