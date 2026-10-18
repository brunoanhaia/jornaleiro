"""Testes de compilacao: tamanho unico de pagina (A4) e limpeza dos brutos."""

from __future__ import annotations

from datetime import date
from io import BytesIO

from PIL import Image
from pypdf import PdfReader, PdfWriter

from jornais import compose
from jornais.model import Asset, MarketResult

A4 = (595, 842)
DIA = date(2026, 10, 15)


def jpeg(largura: int, altura: int, cor: str = "white") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (largura, altura), cor).save(buffer, "JPEG", quality=80)
    return buffer.getvalue()


def pdf_com_pagina(largura: float, altura: float) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=largura, height=altura)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def resultado(assets: list[Asset]) -> MarketResult:
    return MarketResult(key="x", label="X", status="ok", assets=assets)


def test_imagens_e_pdf_saem_todos_em_a4() -> None:
    """Encarte do Assai misturava 92x140 pt com 2392x3632 pt; agora e tudo A4."""
    assets = [
        Asset(url="a", content=jpeg(768, 1166), kind="image", suffix=".jpg"),
        Asset(url="b", content=jpeg(3189, 4843, "gray"), kind="image", suffix=".jpg"),
        Asset(url="c", content=pdf_com_pagina(300, 900), kind="pdf", suffix=".pdf"),
        Asset(url="d", content=pdf_com_pagina(1162, 1502), kind="pdf", suffix=".pdf"),
    ]

    pdf = compose.build_pdf(resultado(assets))

    paginas = PdfReader(BytesIO(pdf)).pages
    assert len(paginas) == 4
    assert {tuple(round(float(valor)) for valor in pagina.mediabox[2:]) for pagina in paginas} == {A4}


def test_padronizar_preserva_a_proporcao_da_pagina() -> None:
    pdf = compose.build_pdf(resultado([Asset(url="a", content=pdf_com_pagina(600, 300), kind="pdf", suffix=".pdf")]))

    pagina = PdfReader(BytesIO(pdf)).pages[0]

    assert tuple(round(float(valor)) for valor in pagina.mediabox[2:]) == A4
    # 600x300 (2:1) dentro de A4: escala pela largura e sobra faixa branca em cima/embaixo
    assert round(float(pagina.mediabox.width) / 2) > round(float(pagina.mediabox.height) / 4)


def test_write_result_limpa_brutos_da_coleta_anterior(tmp_path) -> None:
    dois = resultado([Asset(url="a", content=jpeg(40, 40), kind="image", suffix=".jpg"),
                      Asset(url="b", content=jpeg(40, 40, "gray"), kind="image", suffix=".jpg")])
    compose.write_result(dois, tmp_path, DIA, None)
    assert sorted(caminho.name for caminho in (tmp_path / "2026-10-15" / "raw").iterdir()) == [
        "x-1.jpg",
        "x-2.jpg",
    ]

    um = resultado([Asset(url="a", content=jpeg(40, 40), kind="image", suffix=".jpg")])
    compose.write_result(um, tmp_path, DIA, None)

    assert sorted(caminho.name for caminho in (tmp_path / "2026-10-15" / "raw").iterdir()) == ["x-1.jpg"]
