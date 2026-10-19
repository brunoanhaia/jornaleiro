"""Compilacao dos assets de um mercado em um unico PDF + gravacao em disco.

As paginas saem **todas do mesmo tamanho** (A4 retrato por padrao): imagens entram com
`layout_fun` do img2pdf e paginas de PDF de origem sao escaladas e centralizadas com
`pypdf.Transformation`. Sem isso o encarte do Assai misturava pagina de 92x140 pt com
outra de 2392x3632 pt, e o do Atacadao tinha tres alturas diferentes.
"""

from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path

import img2pdf
from pypdf import PdfReader, PdfWriter, Transformation

from . import comprimir
from .comprimir import Compressao, Resultado
from .model import MarketResult

A4 = comprimir.A4


def build_pdf(result: MarketResult, pagina: tuple[float, float] | None = A4) -> bytes:
    """Concatena PDFs (pypdf) e imagens (img2pdf), padronizando o tamanho das paginas."""
    writer = PdfWriter()
    pending_images: list[bytes] = []

    def flush_images() -> None:
        if not pending_images:
            return
        if pagina:
            layout = img2pdf.get_layout_fun(pagina, fit=img2pdf.FitMode.into)
            convertido = img2pdf.convert(list(pending_images), layout_fun=layout)
        else:
            convertido = img2pdf.convert(list(pending_images))
        writer.append(PdfReader(BytesIO(convertido)))
        pending_images.clear()

    for asset in result.assets:
        if asset.kind == "image":
            pending_images.append(asset.content)
        else:
            flush_images()
            writer.append(_padronizar(PdfReader(BytesIO(asset.content)), pagina))
    flush_images()

    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _padronizar(reader: PdfReader, pagina: tuple[float, float] | None) -> PdfReader:
    """Escala e centraliza cada pagina no tamanho alvo (mantendo a proporcao)."""
    if not pagina:
        return reader
    alvo_largura, alvo_altura = pagina
    for page in reader.pages:
        largura = float(page.mediabox.width)
        altura = float(page.mediabox.height)
        if largura <= 0 or altura <= 0:
            continue
        escala = min(alvo_largura / largura, alvo_altura / altura)
        x0, y0 = float(page.mediabox.left), float(page.mediabox.bottom)
        desloc_x = (alvo_largura - largura * escala) / 2
        desloc_y = (alvo_altura - altura * escala) / 2
        page.add_transformation(
            Transformation()
            .translate(-x0, -y0)
            .scale(escala)
            .translate(desloc_x, desloc_y)
        )
        page.mediabox.lower_left = (0, 0)
        page.mediabox.upper_right = (alvo_largura, alvo_altura)
    return reader


def page_count(pdf: bytes) -> int:
    return len(PdfReader(BytesIO(pdf)).pages)


def write_result(
    result: MarketResult,
    data_dir: Path,
    day: date,
    compressao: Compressao | None = None,
) -> tuple[Path, bytes, Resultado | None]:
    """Grava o PDF do dia e os arquivos brutos (auditoria).

    Sobrescreve se o comando rodar duas vezes no mesmo dia. Devolve
    (caminho, bytes do PDF gravado, resultado da compressao ou None).
    """
    folder = data_dir / day.isoformat()
    raw_dir = folder / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    for antigo in raw_dir.glob(f"{result.key}-*"):  # nao mistura com a coleta anterior
        antigo.unlink()

    for index, asset in enumerate(result.assets, start=1):
        (raw_dir / f"{result.key}-{index}{asset.suffix}").write_bytes(asset.content)

    pdf = build_pdf(result)
    estatisticas = None
    if compressao is not None:
        pdf, estatisticas = comprimir.compress(pdf, compressao)
    path = folder / f"{result.key}.pdf"
    path.write_bytes(pdf)
    return path, pdf, estatisticas
