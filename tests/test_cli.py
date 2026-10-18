"""Testes da linha de resumo enviada por Telegram."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from jornais.cli import Row, config_ler_precos, describe, summary_message
from jornais.model import MarketResult

DIA = date(2026, 10, 15)


def row(key: str, label: str, *, validity: str | None = None, note: str | None = None, **campos) -> Row:
    return Row(
        result=MarketResult(key=key, label=label, status="ok", validity=validity, note=note),
        **campos,
    )


def test_resumo_traz_precos_por_mercado() -> None:
    rows = [
        row("atacadao", "Atacadão", count=6, unit="folhetos", validity="12/10 a 19/10",
            path=Path("data/2026-10-15/atacadao.pdf"), itens=224, precos=486, fonte="texto"),
        row("assai", "Assaí Atacadista", count=8, unit="pags", validity="Preços válidos para 15/10/2026",
            path=Path("data/2026-10-15/assai.pdf"), itens=30, precos=40, fonte="ocr"),
    ]

    texto = summary_message(DIA, rows)

    assert "Encartes Rio Claro - 15/10/2026" in texto
    assert "Atacadão - 6 folhetos - 12/10 a 19/10 | 224 itens/486 precos" in texto
    assert "Assaí Atacadista - 8 pags - Preços válidos para 15/10/2026 | 30 itens/40 precos (OCR)" in texto
    assert texto.endswith("Falhas: nenhuma")


def test_resumo_mostra_catalogo_do_site() -> None:
    rows = [
        row("examine", "Examine", count=1, validity="15/10 a 18/10/2026",
            path=Path("data/2026-10-15/examine.pdf"),
            csv=Path("data/2026-10-15/precos/examine.csv"), itens=11124, precos=11124, fonte="site")
    ]

    texto = summary_message(DIA, rows)

    assert "Examine - 1 pag - 15/10 a 18/10/2026 | 11124 produtos (site)" in texto


def test_resumo_avisa_quando_falta_ocr() -> None:
    rows = [row("examine", "Examine", count=1, path=Path("data/2026-10-15/examine.pdf"), fonte="sem-ocr")]

    texto = summary_message(DIA, rows)

    assert "Examine - 1 pag | precos: OCR indisponivel (tesseract nao encontrado)" in texto


def test_resumo_marca_mercado_que_falhou() -> None:
    falha = Row(result=MarketResult(key="savegnago", label="Savegnago", status="failed", error="HTTP 404"))
    rows = [falha, row("covabra", "Covabra", count=4, validity="15/10 - 21/10", path=Path("data/covabra.pdf"))]

    texto = summary_message(DIA, rows)

    assert "Savegnago - falha: HTTP 404" in texto
    assert texto.endswith("Falhas: Savegnago")


def test_documentos_levam_pdf_e_csv_de_precos() -> None:
    from jornais.cli import documentos

    rows = [
        row("atacadao", "Atacadão", count=6, unit="folhetos", validity="12/10 a 19/10",
            path=Path("data/2026-10-15/atacadao.pdf"),
            csv=Path("data/2026-10-15/precos/atacadao.csv"), itens=224, precos=486, fonte="texto"),
        row("examine", "Examine", count=1, path=Path("data/2026-10-15/examine.pdf"), fonte="sem-ocr"),
    ]

    itens = documentos(rows)

    assert [nome for nome, _, _ in itens] == ["Atacadão", "Atacadão (precos)", "Examine"]
    assert itens[1][1].name == "atacadao.csv"
    assert itens[1][2] == "Atacadão - 224 itens/486 precos"
    assert [nome for nome, _, _ in documentos(rows, enviar_precos=False)] == ["Atacadão", "Examine"]


def test_log_mostra_economia_e_precos() -> None:
    linha = describe(
        row("assai", "Assaí", count=8, unit="pags", path=Path("data/assai.pdf"),
            antes=8_920_000, depois=3_010_000, itens=30, precos=40, fonte="ocr")
    )

    assert "8 pags -> data/assai.pdf" in linha
    assert "pdf 8.51 MB -> 2.87 MB (-66%)" in linha
    assert linha.endswith("30 itens/40 precos (OCR)")


def test_config_ler_precos_padrao_e_desligado() -> None:
    assert config_ler_precos({}) is True
    assert config_ler_precos({"precos": {"ler": False}}) is False


def test_resumo_sem_leitura_de_precos_mostra_so_a_validade() -> None:
    rows = [
        row("covabra", "Covabra", count=4, unit="pags", validity="15/10 - 21/10",
            path=Path("data/2026-10-18/covabra.pdf"), fonte="desligado"),
        row("savegnago", "Savegnago", count=4, unit="pags",
            note="arquivo de 16/10 18:15 (America/Sao_Paulo)",
            path=Path("data/2026-10-18/savegnago.pdf"), fonte="desligado"),
    ]

    texto = summary_message(DIA, rows)

    assert "Covabra - 4 pags - 15/10 - 21/10" in texto
    assert "Savegnago - 4 pags - arquivo de 16/10 18:15 (America/Sao_Paulo)" in texto
    assert "itens" not in texto and "precos" not in texto
