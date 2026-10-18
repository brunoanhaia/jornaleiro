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


# --- leitura por coordenadas (Atacadao) ---------------------------------------
# Os fragmentos abaixo sao recortes reais do PDF de 15/10/2026 (x, y, texto):
# o nome do card fica a esquerda e o bloco de 1-3 precos empilha na mesma coluna.

def test_colunas_pareia_nome_a_esquerda_e_nao_troca_itens_vizinhos() -> None:
    frags = [
        (24.0, 652.0, "Arroz Bulnez"),
        (24.0, 645.0, "Agulhinha Tipo 1"),
        (78.0, 720.0, "R$"),
        (82.0, 720.0, "19,79"),
        (78.0, 686.0, "R$"),
        (82.0, 686.0, "18,89"),
        (78.0, 644.0, "R$"),
        (82.0, 644.0, "16,99"),
        (150.0, 667.0, "Feijão Carioca"),
        (150.0, 660.0, "Bulnez"),
        (205.0, 723.0, "R$"),
        (209.0, 723.0, "7,79"),
        (205.0, 689.0, "R$"),
        (209.0, 689.0, "7,59"),
        (205.0, 648.0, "R$"),
        (209.0, 648.0, "6,79"),
    ]

    rows = precos._extract_colunas(frags, "atacadao", 1)

    assert [(r.produto, r.preco, r.ordem, r.tipo) for r in rows] == [
        ("Feijão Carioca Bulnez", 7.79, 1, "varejo/atacado"),
        ("Feijão Carioca Bulnez", 7.59, 2, "app"),
        ("Feijão Carioca Bulnez", 6.79, 3, "app/cartao"),
        ("Arroz Bulnez Agulhinha Tipo 1", 19.79, 4, "varejo/atacado"),
        ("Arroz Bulnez Agulhinha Tipo 1", 18.89, 5, "app"),
        ("Arroz Bulnez Agulhinha Tipo 1", 16.99, 6, "app/cartao"),
    ]


def test_colunas_ignora_preco_riscado_e_ruido_de_layout() -> None:
    frags = [
        # card do iogurte: o "de: R$ 3,29 por:" some; o preco valido fica abaixo
        (49.7, 775.8, "Iogurte Frutap"),
        (49.7, 763.8, "Morango"),
        (49.7, 751.8, "Pouch com 90g"),
        (158.8, 787.3, "de:"),
        (171.7, 787.3, "R$"),
        (177.2, 787.3, "3,29"),
        (201.5, 787.3, "por:"),
        (147.0, 748.8, "R$"),
        (155.6, 748.8, "1,99"),
        (147.0, 700.0, "Limite máximo de 6 un"),
        (150.0, 690.0, "Consulte condições."),
        # card da cebola, mais abaixo
        (83.9, 126.0, "Cebola"),
        (83.9, 115.0, "Quilo"),
        (146.7, 193.3, "R$"),
        (150.8, 193.3, "5,99"),
        (146.9, 160.7, "R$"),
        (151.0, 160.7, "5,49"),
        (146.7, 121.3, "R$"),
        (150.8, 121.3, "4,79"),
    ]

    rows = precos._extract_colunas(frags, "atacadao", 1)

    assert [(r.produto, r.preco) for r in rows] == [
        ("Iogurte Frutap Morango Pouch com 90g", 1.99),
        ("Cebola Quilo", 5.99),
        ("Cebola Quilo", 5.49),
        ("Cebola Quilo", 4.79),
    ]


def test_colunas_separa_dois_itens_da_mesma_coluna() -> None:
    """O vao grande em y separa dois cards empilhados na mesma coluna de precos."""
    frags = [
        (24.0, 652.0, "Arroz Bulnez"),
        (78.0, 720.0, "R$"),
        (82.0, 720.0, "19,79"),
        (78.0, 686.0, "R$"),
        (82.0, 686.0, "18,89"),
        (24.0, 340.0, "Cebola"),
        (78.0, 420.0, "R$"),
        (82.0, 420.0, "5,99"),
        (78.0, 380.0, "R$"),
        (82.0, 380.0, "5,49"),
    ]

    rows = precos._extract_colunas(frags, "atacadao", 1)

    assert [(r.produto, r.preco) for r in rows] == [
        ("Arroz Bulnez", 19.79),
        ("Arroz Bulnez", 18.89),
        ("Cebola", 5.99),
        ("Cebola", 5.49),
    ]


def test_colunas_mantem_junto_o_vao_coberto_por_bloco_de_nome() -> None:
    """Card com desconto no app: preco do app em cima e o cheio embaixo do nome."""
    frags = [
        (86.5, 788.4, "Salgadinho Elma Chips"),
        (86.5, 776.6, "Cheetos"),
        (86.5, 764.8, "Vários sabores"),
        (86.5, 753.0, "Pacote com 33g/35g/36g/40g"),
        (236.3, 811.6, "R$"),
        (244.4, 811.6, "2,23"),
        (232.6, 753.2, "R$"),
        (241.0, 753.2, "2,48"),
    ]

    rows = precos._extract_colunas(frags, "atacadao", 1)

    assert [(r.produto, r.preco, r.tipo) for r in rows] == [
        ("Salgadinho Elma Chips Cheetos Vários sabores Pacote com 33g/35g/36g/40g", 2.23, "app"),
        ("Salgadinho Elma Chips Cheetos Vários sabores Pacote com 33g/35g/36g/40g", 2.48, "varejo/atacado"),
    ]


def test_colunas_corta_o_vao_grande_sem_nome_cobrindo() -> None:
    """Sem bloco de nome entre os precos, o vao grande vira fronteira de cards."""
    frags = [
        (236.3, 811.6, "R$"),
        (244.4, 811.6, "2,23"),
        (232.6, 753.2, "R$"),
        (241.0, 753.2, "2,48"),
    ]

    rows = precos._extract_colunas(frags, "atacadao", 1)

    assert [(r.produto, r.preco) for r in rows] == [("", 2.23), ("", 2.48)]


def test_colunas_sem_preco_devolve_vazio() -> None:
    """Pagina sem card nenhum: o fluxo de texto assume (fallback)."""
    frags = [(10.0, 500.0, "Bem-vindo ao encarte de ofertas")]

    assert precos._extract_colunas(frags, "atacadao", 1) == []


def test_extract_do_atacadao_usa_leitura_por_coordenadas(monkeypatch) -> None:
    monkeypatch.setattr(precos, "page_texts", lambda dados: ["texto " * 60])
    sentinela = [precos.Preco("atacadao", 1, "Teste", 1.0, 1)]
    chamadas: list[str] = []
    monkeypatch.setattr(
        precos,
        "_extract_colunas_pdf",
        lambda dados, textos, mercado: chamadas.append("colunas") or sentinela,
    )
    monkeypatch.setattr(
        precos,
        "_extract_page",
        lambda texto, mercado, pagina, limpar=False: chamadas.append("texto") or sentinela,
    )

    de_atacadao = precos.extract(b"%PDF-1.4 falso", "atacadao")
    assert de_atacadao.precos == sentinela
    assert chamadas == ["colunas"]  # so o Atacadao le por coordenadas

    chamadas.clear()
    de_covabra = precos.extract(b"%PDF-1.4 falso", "covabra")
    assert de_covabra.precos == sentinela
    assert chamadas == ["texto"]


def test_colunas_pdf_usa_o_texto_quando_a_pagina_nao_tem_card(monkeypatch) -> None:
    class LeitorFalso:
        def __init__(self, dados: bytes) -> None:
            self.pages = ["pagina 1", "pagina 2"]

    monkeypatch.setattr(precos, "PdfReader", LeitorFalso)
    card = [(50.0, 100.0, "Cebola"), (100.0, 100.0, "R$"), (104.0, 100.0, "5,99")]
    monkeypatch.setattr(precos, "_fragmentos", lambda page: card if page == "pagina 1" else [])
    sentinela = precos.Preco("atacadao", 2, "Do fluxo de texto", 9.90, 1)
    monkeypatch.setattr(
        precos, "_extract_page", lambda texto, mercado, pagina, limpar=False: [sentinela]
    )

    linhas = precos._extract_colunas_pdf(b"fake", ["texto 1", "texto 2"], "atacadao")

    assert [(r.produto, r.preco, r.pagina) for r in linhas] == [
        ("Cebola", 5.99, 1),
        ("Do fluxo de texto", 9.90, 2),
    ]
