"""Testes da leitura de precos (fixtures recortadas do texto real dos PDFs)."""

from __future__ import annotations

from jornais import precos

ATACADAO_TEXTO = """OFERTAS VÁLIDAS DE 13/10 A 19/10/2026
Esta página é parte integrante das ofertas das lojas do estado de São Paulo
2
MERCEARIA
Azeite de Oliva 
Andorinha
Tipo Único
Vidro com 500ml
PREÇO VAREJO/ATACADO
PREÇO COM OFERTA ATIVADA  
NO APP PAGANDO COM: 
CARTÃO ATACADÃO,  
CARREFOUR OU  
SAM’S CLUB
PREÇO COM OFERTA  
ATIVADA NO
Limite máximo de 6 un 
por cliente nos cartões
Limite máximo de 6 un 
por cliente no APP
R$20,90
R$18,90
R$22,90
Cebola 
Quilo
PREÇO VAREJO/ATACADO
R$5,39
R$4,69
R$5,98
"""

COVABRA_TEXTO = """Papel Higiênico Mimmo
Folha Dupla 30 Metros
Lv24 Pg 21 Rolos
R$ 32 , 90
Lava Roupas Tixan Power Act 2,2Kg
R$ 19 , 90
Chocolate Tablete Milka
87, 90, 92 e 100 Gr
R$ 16 , 99
  R$ 11 ,  49
Bebida alcoólica pode causar dependência química e, em excesso, provoca grandes males à saúde.
"""

SAVEGNAGO_TEXTO = """As ofertas deste box são válidas até sábado - 17/10/2026.
Café Brasileiro 500g
 18 , 90
Molho de tomate
Predilecta tradicional
sachê 300g
 1 , 49
6Limite de
unid. por cliente/compra
Azeite italiano
extra virgem
Filippo Berio
500ml
 28 , 90
 26 , 90
Leite condensado
Italac
395g
 5 , 79 5 , 79R$
"""


def test_atacadao_le_descricao_e_precos_em_colunas() -> None:
    rows = precos._extract_page(ATACADAO_TEXTO, "atacadao", 2)

    assert [(r.produto, r.preco, r.ordem) for r in rows] == [
        ("Azeite de Oliva Andorinha Tipo Único Vidro com 500ml", 20.90, 1),
        ("Azeite de Oliva Andorinha Tipo Único Vidro com 500ml", 18.90, 2),
        ("Azeite de Oliva Andorinha Tipo Único Vidro com 500ml", 22.90, 3),
        ("Cebola Quilo", 5.39, 1),
        ("Cebola Quilo", 4.69, 2),
        ("Cebola Quilo", 5.98, 3),
    ]
    assert {r.pagina for r in rows} == {2}


def test_covabra_ignora_gramatura_e_ruido_legal() -> None:
    rows = precos._extract_page(COVABRA_TEXTO, "covabra", 1)

    assert [(r.produto, r.preco) for r in rows] == [
        ("Papel Higiênico Mimmo Folha Dupla 30 Metros Lv24 Pg 21 Rolos", 32.90),
        ("Lava Roupas Tixan Power Act 2,2Kg", 19.90),
        ("Chocolate Tablete Milka 87, 90, 92 e 100 Gr", 16.99),
        # linha so de ruido legal nao abre item novo: o preco fica com a ultima descricao
        ("Chocolate Tablete Milka 87, 90, 92 e 100 Gr", 11.49),
    ]


def test_savegnago_preco_sem_rs_e_duplicado() -> None:
    rows = precos._extract_page(SAVEGNAGO_TEXTO, "savegnago", 1)

    assert [(r.produto, r.preco, r.ordem) for r in rows] == [
        ("Café Brasileiro 500g", 18.90, 1),
        ("Molho de tomate Predilecta tradicional sachê 300g", 1.49, 1),
        ("Azeite italiano extra virgem Filippo Berio 500ml", 28.90, 1),
        ("Azeite italiano extra virgem Filippo Berio 500ml", 26.90, 2),
        ("Leite condensado Italac 395g", 5.79, 1),
    ]


def test_extract_marca_encarte_sem_texto() -> None:
    """Assai e Examine sao imagens: sem OCR pedido, `extract` devolve vazio e a fonte."""
    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buffer = BytesIO()
    writer.write(buffer)

    leitura = precos.extract(buffer.getvalue(), "assai")

    assert leitura.precos == []
    assert leitura.fonte == "nenhuma"
    assert leitura.itens == 0


def test_arquivos_brutos_ordena_por_indice(tmp_path) -> None:
    from datetime import date

    pasta = tmp_path / "2026-10-15" / "raw"
    pasta.mkdir(parents=True)
    for nome in ("atacadao-10.pdf", "atacadao-2.pdf", "atacadao-1.jpg"):
        (pasta / nome).write_bytes(b"x")

    nomes = [caminho.name for caminho in precos.arquivos_brutos(tmp_path, date(2026, 10, 15), "atacadao")]

    assert nomes == ["atacadao-1.jpg", "atacadao-2.pdf", "atacadao-10.pdf"]


def test_extract_de_imagem_sem_ocr_nao_chuta() -> None:
    leitura = precos.extract(b"\xff\xd8\xff\xe0resto-do-jpeg", "assai")

    assert leitura.precos == []
    assert leitura.fonte == "nenhuma"


def test_extract_de_webp_nao_tenta_ler_como_pdf() -> None:
    """O CDN do Examine ja devolveu WebP com URL .png; sem isso cai no pypdf e quebra."""
    webp = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 32

    leitura = precos.extract(webp, "examine")

    assert precos._eh_imagem(webp) is True
    assert leitura.precos == []
    assert leitura.fonte == "nenhuma"


def test_extract_arquivos_junta_as_fontes(tmp_path) -> None:
    from datetime import date
    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buffer = BytesIO()
    writer.write(buffer)
    pasta = tmp_path / "2026-10-15" / "raw"
    pasta.mkdir(parents=True)
    (pasta / "x-1.pdf").write_bytes(buffer.getvalue())
    (pasta / "x-2.jpg").write_bytes(b"\xff\xd8\xff\xe0jpeg")

    leitura = precos.extract_arquivos(precos.arquivos_brutos(tmp_path, date(2026, 10, 15), "x"), "x")

    assert leitura.precos == []
    assert leitura.fonte == "nenhuma"


def test_csv_uma_linha_por_preco(tmp_path) -> None:
    from datetime import date

    rows = precos._extract_page(SAVEGNAGO_TEXTO, "savegnago", 1)
    json_path, csv_path = precos.write(rows, tmp_path, date(2026, 10, 15), "savegnago")

    assert csv_path.read_bytes().startswith(b"\xef\xbb\xbf")  # BOM para o Excel pt-BR
    linhas = csv_path.read_text(encoding="utf-8-sig").strip().splitlines()
    assert linhas[0] == "mercado;pagina;produto;preco;ordem;tipo"
    assert len(linhas) == len(rows) + 1
    assert linhas[1] == "savegnago;1;Café Brasileiro 500g;18.90;1;"
    assert json_path.name == "savegnago.json"
    assert '"preco": 18.9' in json_path.read_text(encoding="utf-8")


ATACADAO_PRECO_ANTES_DO_NOME = """PREÇO VAREJO/ATACADO
PREÇO COM OFERTA ATIVADA
NO APP PAGANDO COM:
CARTÃO ATACADÃO,
CARREFOUR OU
SAM’S CLUB
Limite máximo de 6 kg
por cliente nos cartões
R$5,49
R$4,79
R$5,99
Cebola
Quilo
"""


def test_atacadao_preco_antes_do_nome_fica_com_o_item() -> None:
    """Na regiao de hortifruti o preco vem antes do nome na arte do encarte."""
    rows = precos._extract_page(ATACADAO_PRECO_ANTES_DO_NOME, "atacadao", 1)

    assert [(r.produto, r.preco, r.ordem, r.tipo) for r in rows] == [
        ("Cebola Quilo", 5.49, 1, "app"),
        ("Cebola Quilo", 4.79, 2, "app/cartao"),
        ("Cebola Quilo", 5.99, 3, "varejo/atacado"),
    ]


def test_tipo_por_valor_no_atacadao() -> None:
    rows = precos._extract_page(ATACADAO_TEXTO, "atacadao", 2)
    tipos = {r.preco: r.tipo for r in rows}

    assert tipos[22.90] == "varejo/atacado"
    assert tipos[20.90] == "app"
    assert tipos[18.90] == "app/cartao"


def test_tipo_cheio_e_clube_no_savegnago() -> None:
    rows = precos._extract_page(SAVEGNAGO_TEXTO, "savegnago", 1)
    tipos = {(r.produto, r.preco): r.tipo for r in rows}

    assert tipos[("Azeite italiano extra virgem Filippo Berio 500ml", 28.90)] == "cheio"
    assert tipos[("Azeite italiano extra virgem Filippo Berio 500ml", 26.90)] == "clube"
    assert tipos[("Café Brasileiro 500g", 18.90)] == ""  # preco unico: sem tipo


def test_extract_arquivos_combina_fontes(monkeypatch, tmp_path) -> None:
    """Folhetos com fontes diferentes viram `texto+sem-ocr`, sem esconder o OCR que faltou."""
    from datetime import date

    pasta = tmp_path / "2026-10-15" / "raw"
    pasta.mkdir(parents=True)
    (pasta / "x-1.pdf").write_bytes(b"a")
    (pasta / "x-2.pdf").write_bytes(b"b")
    respostas = {
        b"a": precos.Leitura([precos.Preco("x", 1, "Item", 9.99, 1)], "texto"),
        b"b": precos.Leitura([], "sem-ocr"),
    }
    monkeypatch.setattr(precos, "extract", lambda dados, mercado, ocr=None: respostas[dados])

    leitura = precos.extract_arquivos(
        precos.arquivos_brutos(tmp_path, date(2026, 10, 15), "x"), "x"
    )

    assert leitura.fonte == "texto+sem-ocr"
    assert [preco.preco for preco in leitura.precos] == [9.99]
