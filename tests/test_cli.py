"""Testes da linha de resumo enviada por Telegram."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from jornaleiro.cli import Row, describe, documentos, summary_message
from jornaleiro.model import MarketResult

DIA = date(2026, 10, 15)


def row(
    key: str, label: str, *, validity: str | None = None, note: str | None = None, **campos
) -> Row:
    return Row(
        result=MarketResult(key=key, label=label, status="ok", validity=validity, note=note),
        **campos,
    )


def test_resumo_traz_uma_linha_por_mercado() -> None:
    rows = [
        row("atacadao", "Atacadão", count=6, unit="folhetos", validity="12/10 a 19/10",
            path=Path("data/2026-10-15/atacadao.pdf")),
        row("assai", "Assaí Atacadista", count=8, unit="pags",
            validity="Preços válidos para 15/10/2026", path=Path("data/2026-10-15/assai.pdf")),
    ]

    texto = summary_message(DIA, rows)

    assert "Encartes Rio Claro - 15/10/2026" in texto
    assert "Atacadão - 6 folhetos - 12/10 a 19/10" in texto
    assert "Assaí Atacadista - 8 pags - Preços válidos para 15/10/2026" in texto
    assert texto.endswith("Falhas: nenhuma")


def test_resumo_usa_a_nota_quando_nao_ha_validade() -> None:
    rows = [
        row("examine", "Examine", count=1, note="jornal oficial do site (1 pag: Vinhos)",
            path=Path("data/2026-10-15/examine.pdf"))
    ]

    texto = summary_message(DIA, rows)

    assert "Examine - 1 pag - jornal oficial do site (1 pag: Vinhos)" in texto


def test_resumo_marca_mercado_que_falhou() -> None:
    falha = Row(result=MarketResult(key="savegnago", label="Savegnago", status="failed", error="HTTP 404"))
    rows = [
        falha,
        row("covabra", "Covabra", count=4, validity="15/10 - 21/10", path=Path("data/covabra.pdf")),
    ]

    texto = summary_message(DIA, rows)

    assert "Savegnago - falha: HTTP 404" in texto
    assert texto.endswith("Falhas: Savegnago")


def test_resumo_mostra_o_aviso_do_mercado() -> None:
    rows = [
        row("assai", "Assaí", count=8, path=Path("data/assai.pdf"),
            aviso="encarte vencido em 02/01")
    ]

    texto = summary_message(DIA, rows)

    assert "Assaí - 8 pag | AVISO: encarte vencido em 02/01" in texto


def test_documentos_levam_so_os_pdfs_que_vão() -> None:
    rows = [
        row("atacadao", "Atacadão", count=6, unit="folhetos", path=Path("data/atacadao.pdf")),
        row("assai", "Assaí", count=8, path=Path("data/assai.pdf"), pular_envio=True),
        Row(result=MarketResult(key="covabra", label="Covabra", status="failed", error="HTTP 404")),
    ]

    itens = documentos(rows)

    assert [nome for nome, _, _ in itens] == ["Atacadão"]
    assert itens[0][1].name == "atacadao.pdf"
    assert itens[0][2] == "Atacadão - sem validade - 6 folhetos"


def test_log_mostra_tamanho_e_economia() -> None:
    linha = describe(
        row("assai", "Assaí", count=8, unit="pags", path=Path("data/assai.pdf"),
            antes=8_920_000, depois=3_010_000)
    )

    assert "8 pags -> data/assai.pdf" in linha
    assert "pdf 8.51 MB -> 2.87 MB (-66%)" in linha


def test_log_de_falha_mostra_o_erro() -> None:
    falha = Row(result=MarketResult(key="assai", label="Assaí", status="failed", error="HTTP 403"))

    assert describe(falha) == "falha: HTTP 403"
