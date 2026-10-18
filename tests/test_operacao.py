"""Testes de operacao: resolucao do config, retencao (`limpar`) e `run` com fakes."""

from __future__ import annotations

import argparse
from datetime import datetime
from io import BytesIO
from pathlib import Path

from pypdf import PdfWriter

from jornais import cli, render
from jornais.model import SP, Asset, MarketResult


class RendererFalso:
    """Renderizador de mentira: nenhum teste aqui abre navegador."""

    name = "falso"

    def get_text(self, url: str) -> str:
        return ""

    def fetch_json_in_page(self, url: str, warmup_url: str) -> str:
        return ""

    def close(self) -> None:
        pass


def pdf_vazio() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def mercado_falso(key: str, label: str, conteudo: bytes):
    """Modulo de mercado de mentira, com a mesma interface de `markets/<key>.py`."""

    class MercadoFalso:
        KEY = key
        LABEL = label

        @staticmethod
        def fetch(ctx, cfg) -> MarketResult:
            return MarketResult(
                key=key,
                label=label,
                status="ok",
                assets=[
                    Asset(
                        url=f"https://exemplo.test/{key}.pdf",
                        content=conteudo,
                        kind="pdf",
                        suffix=".pdf",
                    )
                ],
                validity="15/10 - 21/10",
            )

    return MercadoFalso()


def escreve_config(tmp_path: Path, mercados: list[str]) -> Path:
    linhas = ['renderer = "jina"', 'data_dir = "data"', ""]
    for key in mercados:
        linhas += [f"[markets.{key}]", "enabled = true", ""]
    caminho = tmp_path / "config.toml"
    caminho.write_text("\n".join(linhas), encoding="utf-8")
    return caminho


def prepara_run(tmp_path: Path, monkeypatch, mercados: dict) -> Path:
    """Instala os mercados falsos, o renderer falso e grava o config.toml."""
    for key, modulo in mercados.items():
        monkeypatch.setitem(cli.REGISTRY, key, modulo)
    monkeypatch.setattr(render, "build_renderer", lambda modo=None: RendererFalso())
    return escreve_config(tmp_path, list(mercados))


def roda_run(config: Path, data_dir: Path, only: str) -> int:
    args = cli.build_parser().parse_args(
        [
            "run",
            "--only", only,
            "--no-send",
            "--sem-comprimir",
            "--sem-ocr",
            "--config", str(config),
            "--data-dir", str(data_dir),
        ]
    )
    return args.handler(args)


def test_run_grava_pdf_brutos_e_log(tmp_path, monkeypatch, capsys) -> None:
    config = prepara_run(
        tmp_path,
        monkeypatch,
        {"assai": mercado_falso("assai", "Assaí Atacadista", pdf_vazio())},
    )
    data_dir = tmp_path / "data"

    assert roda_run(config, data_dir, "assai") == 0
    capsys.readouterr()  # limpa a saida capturada

    dia = datetime.now(SP).date().isoformat()
    assert (data_dir / dia / "assai.pdf").exists()
    assert (data_dir / dia / "raw" / "assai-1.pdf").exists()

    log = (data_dir / dia / "run.log").read_text(encoding="utf-8")
    assert "==== execucao em " in log
    assert "assai: 1 pag -> " in log
    assert "Encartes Rio Claro - " in log
    assert "Falhas: nenhuma" in log


def test_run_continua_quando_um_mercado_falha(tmp_path, monkeypatch, capsys) -> None:
    config = prepara_run(
        tmp_path,
        monkeypatch,
        {
            "assai": mercado_falso("assai", "Assaí Atacadista", pdf_vazio()),
            "atacadao": mercado_falso("atacadao", "Atacadão", b"isto nao e um pdf"),
        },
    )
    data_dir = tmp_path / "data"

    assert roda_run(config, data_dir, "assai,atacadao") == 0

    dia = datetime.now(SP).date().isoformat()
    assert (data_dir / dia / "assai.pdf").exists()  # o mercado bom saiu
    assert not (data_dir / dia / "atacadao.pdf").exists()  # o ruim nao derruba o run
    saida = capsys.readouterr()
    assert "atacadao: falha: " in saida.err
    assert "Atacadão - falha: " in saida.out
    assert "Falhas: Atacadão" in saida.out


def test_localizar_config_ordem_de_preferencia(tmp_path, monkeypatch) -> None:
    explicito = tmp_path / "meu.toml"
    monkeypatch.setenv("JORNAIS_CONFIG", str(tmp_path / "env.toml"))

    assert cli.localizar_config(str(explicito)) == explicito
    assert cli.localizar_config(None) == tmp_path / "env.toml"

    # sem --config nem env, vale o config.toml da pasta atual
    monkeypatch.delenv("JORNAIS_CONFIG")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text("", encoding="utf-8")
    assert cli.localizar_config(None) == Path("config.toml")

    # sem config na pasta atual, cai na raiz do repositorio
    vazio = tmp_path / "vazio"
    vazio.mkdir()
    monkeypatch.chdir(vazio)
    raiz = Path(__file__).resolve().parents[1]
    assert cli.localizar_config(None) == raiz / "config.toml"


def test_data_dir_relativo_fica_ao_lado_do_config(tmp_path) -> None:
    config_path = tmp_path / "cfg" / "config.toml"
    config_path.parent.mkdir()
    config = {"data_dir": "dados"}

    sem_flag = cli.resolver_data_dir(argparse.Namespace(data_dir=None), config, config_path)
    com_flag = cli.resolver_data_dir(
        argparse.Namespace(data_dir=str(tmp_path / "outro")), config, config_path
    )

    assert sem_flag == config_path.parent / "dados"
    assert com_flag == tmp_path / "outro"  # --data-dir vence


def test_limpar_remove_so_coletas_antigas(tmp_path, capsys) -> None:
    config = tmp_path / "config.toml"
    config.write_text('data_dir = "data"\n', encoding="utf-8")
    data = tmp_path / "data"
    antiga = data / "2020-01-01"
    (antiga / "precos").mkdir(parents=True)
    (antiga / "x.pdf").write_bytes(b"abc")
    hoje = data / datetime.now(SP).date().isoformat()
    (hoje / "raw").mkdir(parents=True)
    (data / "raw").mkdir()  # pasta que nao e de coleta
    (data / "state.json").write_text("{}", encoding="utf-8")

    def argumentos(dry_run: bool) -> argparse.Namespace:
        return argparse.Namespace(
            dias=30, dry_run=dry_run, data_dir=str(data), config=str(config)
        )

    assert cli.cmd_limpar(argumentos(dry_run=True)) == 0
    assert antiga.exists()  # dry-run nao remove nada
    assert "seria removida" in capsys.readouterr().out

    assert cli.cmd_limpar(argumentos(dry_run=False)) == 0
    saida = capsys.readouterr().out
    assert not antiga.exists()
    assert hoje.exists()
    assert (data / "raw").exists()
    assert (data / "state.json").exists()
    assert "removidas 1 coleta(s)" in saida


def test_limpar_recusa_dias_negativos(tmp_path, capsys) -> None:
    config = tmp_path / "config.toml"
    config.write_text("", encoding="utf-8")
    args = argparse.Namespace(dias=-1, dry_run=False, data_dir=str(tmp_path), config=str(config))

    assert cli.cmd_limpar(args) == 2
    assert "--dias" in capsys.readouterr().err
