"""Testes da compressao dos PDFs (imagens geradas no proprio teste, sem rede)."""

from __future__ import annotations

import os
from io import BytesIO

import img2pdf
from PIL import Image
from pypdf import PdfReader

from jornaleiro import comprimir

OPCOES = comprimir.Compressao(qualidade=60, largura_max=400)


def jpeg_ruido(largura: int = 900, altura: int = 1200) -> bytes:
    """JPEG grande de proposito: ruido nao comprime, entao a recompressao aparece."""
    imagem = Image.frombytes("RGB", (largura, altura), os.urandom(largura * altura * 3))
    buffer = BytesIO()
    imagem.save(buffer, "JPEG", quality=95)
    return buffer.getvalue()


def test_comprimir_reduz_e_preserva_paginas() -> None:
    original = img2pdf.convert([jpeg_ruido(), jpeg_ruido()])

    comprimido, stats = comprimir.compress(original, OPCOES)

    assert len(comprimido) < len(original)
    assert stats.antes == len(original)
    assert stats.depois == len(comprimido)
    assert stats.imagens == 2
    assert stats.economia > 0.3
    assert len(PdfReader(BytesIO(comprimido)).pages) == 2


def test_modo_forte_rasteriza_em_a4_e_mantem_paginas() -> None:
    original = img2pdf.convert([jpeg_ruido(1200, 1600), jpeg_ruido(800, 1200)])

    comprimido, stats = comprimir.compress(
        original, comprimir.Compressao(rasterizar=True, dpi=110, qualidade=60)
    )

    paginas = PdfReader(BytesIO(comprimido)).pages
    assert len(paginas) == 2
    assert {tuple(round(float(valor)) for valor in pagina.mediabox[2:]) for pagina in paginas} == {(595, 842)}
    assert stats.imagens == 2 and stats.achatadas == 2
    assert len(comprimido) < len(original)


def test_imagem_flate_tambem_e_recomprimida() -> None:
    """PNG entra como /FlateDecode e tambem e reencodada (virou JPEG): pesa bem menos."""
    buffer = BytesIO()
    Image.frombytes("L", (600, 800), os.urandom(600 * 800)).save(buffer, "PNG")
    original = img2pdf.convert([buffer.getvalue()])

    comprimido, stats = comprimir.compress(original, OPCOES)

    assert stats.imagens == 1
    assert len(comprimido) < len(original)
