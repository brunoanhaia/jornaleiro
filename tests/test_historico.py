"""Testes do historico em SQLite (sem rede: CSVs e PDFs falsos gravados em tmp_path)."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from jornais import historico


# --- helpers locais (gravam os CSVs no mesmo formato que o projeto grava) -----

def _gravar_precos(
    data_dir: Path,
    dia: str,
    mercado: str,
    linhas: list[tuple[int, str, float, int, str]],
) -> None:
    """Grava `<dia>/precos/<mercado>.csv`; cada linha e (pagina, produto, preco, ordem, tipo)."""
    pasta = data_dir / dia / "precos"
    pasta.mkdir(parents=True, exist_ok=True)
    corpo = "".join(f"{mercado};{p};{n};{v:.2f};{o};{t}\n" for p, n, v, o, t in linhas)
    (pasta / f"{mercado}.csv").write_text(
        "mercado;pagina;produto;preco;ordem;tipo\n" + corpo, encoding="utf-8-sig"
    )


def _gravar_site(
    data_dir: Path,
    dia: str,
    linhas: list[tuple[str, str, str, float, str, str, str, str]],
) -> None:
    """Grava `<dia>/precos/examine.csv` (catalogo do site); linha = todas as 8 colunas."""
    pasta = data_dir / dia / "precos"
    pasta.mkdir(parents=True, exist_ok=True)
    corpo = "".join(
        f"{i};{c};{n};{v:.2f};{p};{u};{e};{d}\n"
        for i, c, n, v, p, u, e, d in linhas
    )
    (pasta / "examine.csv").write_text(
        "id;categoria;produto;preco;pesavel;unidade;estoque;descontos\n" + corpo,
        encoding="utf-8-sig",
    )


def _pdf_falso(data_dir: Path, dia: str, mercado: str, tamanho: int = 16) -> None:
    """Cria `<dia>/<mercado>.pdf` com bytes falsos, como se o run tivesse gravado."""
    caminho = data_dir / dia / f"{mercado}.pdf"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(b"%PDF" + b"x" * (tamanho - 4))  # tamanho exato em bytes


def _bruto_falso(data_dir: Path, dia: str, mercado: str, tamanho: int = 10) -> None:
    """Cria `<dia>/raw/<mercado>-1.pdf`, o bruto original antes da compressao."""
    pasta = data_dir / dia / "raw"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / f"{mercado}-1.pdf").write_bytes(b"raw" * tamanho)


def _ler(sql: str, db: Path, parametros: tuple = ()) -> list[tuple]:
    with sqlite3.connect(db) as conexao:
        return conexao.execute(sql, parametros).fetchall()


# --- testes ------------------------------------------------------------------


def test_normalizar_remove_acento_caixa_e_espacos() -> None:
    assert historico.normalizar("  Áçúcar   Refinado ") == "acucar refinado"
    assert historico.normalizar("Café\tPILÃO\n500g") == "cafe pilao 500g"
    assert historico.normalizar("Óleo De Soja") == "oleo de soja"


def test_reindexar_conta_precos_site_dias_e_coletas(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _gravar_precos(data_dir, "2026-10-10", "atacadao", [(1, "Arroz Tipo 1", 10.00, 1, "app")])
    _gravar_precos(data_dir, "2026-10-10", "covabra", [(2, "Feijão Carioca", 7.50, 1, "")])
    _gravar_precos(data_dir, "2026-10-11", "atacadao", [(1, "Arroz Tipo 1", 8.00, 1, "")])
    _gravar_site(
        data_dir,
        "2026-10-11",
        [
            ("123", "Mercearia", "Café Pilão 500g", 15.90, "nao", "", "10", ""),
            ("124", "Frios", "Queijo Mussarela", 44.90, "sim", "kg", "", ""),
        ],
    )
    # PDFs falam que houve coleta nos dois dias; so o dia 10 tem bruto
    _pdf_falso(data_dir, "2026-10-10", "atacadao", tamanho=16)
    _pdf_falso(data_dir, "2026-10-11", "atacadao", tamanho=32)
    _bruto_falso(data_dir, "2026-10-10", "atacadao", tamanho=10)
    db = tmp_path / "historico.sqlite"

    contagens = historico.reindexar(data_dir, db)

    assert contagens == {"dias": 2, "precos": 3, "site": 2, "coletas": 2}
    # a tabela de precos guarda o nome normalizado e o dia passado pela pasta
    assert _ler(
        "SELECT mercado, dia, produto, produto_norm, preco, tipo FROM precos"
        " ORDER BY dia, mercado, preco",
        db,
    ) == [
        ("atacadao", "2026-10-10", "Arroz Tipo 1", "arroz tipo 1", 10.00, "app"),
        ("covabra", "2026-10-10", "Feijão Carioca", "feijao carioca", 7.50, ""),
        ("atacadao", "2026-10-11", "Arroz Tipo 1", "arroz tipo 1", 8.00, ""),
    ]
    # coletas: itens/precos vêm dos CSVs importados; bytes dos arquivos no disco
    assert _ler(
        "SELECT dia, mercado, itens, precos, pdf_bytes, raw_bytes FROM coletas ORDER BY dia",
        db,
    ) == [
        ("2026-10-10", "atacadao", 1, 1, 16, len(b"raw" * 10)),
        ("2026-10-11", "atacadao", 1, 1, 32, 0),
    ]
    # catalogo do site cai na tabela propria, com o nome normalizado
    assert _ler(
        "SELECT dia, id, produto, produto_norm, preco FROM site_produtos ORDER BY id", db
    ) == [
        ("2026-10-11", "123", "Café Pilão 500g", "cafe pilao 500g", 15.90),
        ("2026-10-11", "124", "Queijo Mussarela", "queijo mussarela", 44.90),
    ]


def test_reindexar_rodado_2x_nao_duplica(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _gravar_precos(data_dir, "2026-10-10", "atacadao", [(1, "Arroz Tipo 1", 10.00, 1, "")])
    _gravar_site(data_dir, "2026-10-10", [("9", "Mercearia", "Sal Refinado", 2.50, "nao", "", "", "")])
    _pdf_falso(data_dir, "2026-10-10", "atacadao")
    db = tmp_path / "historico.sqlite"

    historico.reindexar(data_dir, db)
    historico.reindexar(data_dir, db)

    assert _ler("SELECT COUNT(*) FROM precos", db)[0][0] == 1
    assert _ler("SELECT COUNT(*) FROM site_produtos", db)[0][0] == 1
    assert _ler("SELECT COUNT(*) FROM coletas", db)[0][0] == 1


def test_registrar_dia_troca_somente_o_dia_pedido(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _gravar_precos(data_dir, "2026-10-10", "atacadao", [(1, "Arroz Tipo 1", 10.00, 1, "")])
    _gravar_precos(data_dir, "2026-10-10", "covabra", [(2, "Feijão Carioca", 7.50, 1, "")])
    _pdf_falso(data_dir, "2026-10-10", "atacadao")
    db = tmp_path / "historico.sqlite"
    historico.reindexar(data_dir, db)

    # o run regrava o dia 11 (novo arquivo) e chama registrar_dia em vez de reindexar
    _gravar_precos(data_dir, "2026-10-11", "atacadao", [(1, "Arroz Tipo 1", 8.00, 1, "")])
    _pdf_falso(data_dir, "2026-10-11", "atacadao")
    contagens = historico.registrar_dia(data_dir, date(2026, 10, 11), db)

    assert contagens == {"dias": 1, "precos": 1, "site": 0, "coletas": 1}
    # o dia 10 continua exatamente como estava; o dia 11 entrou
    assert _ler("SELECT dia, COUNT(*) FROM precos GROUP BY dia ORDER BY dia", db) == [
        ("2026-10-10", 2),
        ("2026-10-11", 1),
    ]
    assert _ler("SELECT COUNT(*) FROM coletas", db)[0][0] == 2

    # rodar 2x para o mesmo dia nao duplica (e o run sobrescreve os CSVs do dia)
    assert historico.registrar_dia(data_dir, date(2026, 10, 11), db)["precos"] == 1
    assert _ler("SELECT COUNT(*) FROM precos", db)[0][0] == 3

    # regravar o dia troca as linhas dele, mas nao toca nos outros dias
    _gravar_precos(
        data_dir,
        "2026-10-11",
        "atacadao",
        [(1, "Arroz Tipo 1", 8.50, 1, ""), (1, "Óleo de Soja", 6.99, 2, "")],
    )
    historico.registrar_dia(data_dir, date(2026, 10, 11), db)

    assert _ler("SELECT dia, COUNT(*) FROM precos GROUP BY dia ORDER BY dia", db) == [
        ("2026-10-10", 2),
        ("2026-10-11", 2),
    ]
    assert _ler("SELECT preco FROM precos WHERE dia = '2026-10-10'", db) == [(10.0,), (7.5,)]


def test_buscar_filtra_sem_acento_e_respeita_desde_limite_e_ordem(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _gravar_precos(data_dir, "2026-10-01", "atacadao", [(1, "Açúcar Refinado", 4.00, 1, "")])
    _gravar_precos(data_dir, "2026-10-05", "atacadao", [(1, "Açúcar Refinado", 4.50, 1, "")])
    _gravar_precos(data_dir, "2026-10-05", "covabra", [(2, "Açúcar Mascavo", 6.00, 1, "")])
    _gravar_precos(data_dir, "2026-10-10", "savegnago", [(1, "Açúcar Refinado", 4.20, 1, "")])
    _gravar_precos(data_dir, "2026-10-10", "atacadao", [(3, "Arroz Tipo 1", 8.00, 1, "")])
    db = tmp_path / "historico.sqlite"
    historico.reindexar(data_dir, db)

    # acento/caixa nao importam: "acucar" acha "Açúcar"; dia desc, mercado e preco
    achados = historico.buscar(db, "  ACÚCAR  ", date(2026, 10, 1))
    assert achados == [
        ("savegnago", "2026-10-10", "Açúcar Refinado", 4.20, ""),
        ("atacadao", "2026-10-05", "Açúcar Refinado", 4.50, ""),
        ("covabra", "2026-10-05", "Açúcar Mascavo", 6.00, ""),
        ("atacadao", "2026-10-01", "Açúcar Refinado", 4.00, ""),
    ]
    # `desde` corta os dias antigos
    assert [linha[1] for linha in historico.buscar(db, "acucar", date(2026, 10, 5))] == [
        "2026-10-10",
        "2026-10-05",
        "2026-10-05",
    ]
    # `limite` corta o fim da lista (sao os dias mais antigos que saem)
    cortado = historico.buscar(db, "acucar", date(2026, 10, 1), limite=2)
    assert [(linha[2], linha[1]) for linha in cortado] == [
        ("Açúcar Refinado", "2026-10-10"),
        ("Açúcar Refinado", "2026-10-05"),
    ]
    # texto que nao casa com nada devolve lista vazia
    assert historico.buscar(db, "macarrao", date(2026, 10, 1)) == []


def test_quedas_usa_menor_preco_do_dia_e_exclui_alta_e_dia_unico(tmp_path) -> None:
    data_dir = tmp_path / "data"
    # dia 1: dois precos de acucar (so o MENOR conta), oleo no ponto baixo,
    # mel aparece nesse dia apenas
    _gravar_precos(
        data_dir,
        "2026-10-01",
        "atacadao",
        [
            (1, "Açúcar Refinado", 12.00, 1, "app"),
            (2, "Açúcar Refinado", 10.00, 1, "clube"),
            (3, "Óleo de Soja", 8.00, 1, ""),
            (4, "Arroz Tipo 1", 10.00, 1, ""),
        ],
    )
    _gravar_precos(
        data_dir,
        "2026-10-01",
        "covabra",
        [(1, "Café Torrado", 20.00, 1, ""), (2, "Mel Puro", 15.00, 1, "")],
    )
    # dia 2: arroz e cafe caem, acucar cai (vs 10.00, nao 12.00), oleo sobe
    _gravar_precos(
        data_dir,
        "2026-10-05",
        "atacadao",
        [
            (1, "Arroz Tipo 1", 8.00, 1, ""),
            (3, "Óleo de Soja", 9.00, 1, ""),
            (4, "Açúcar Refinado", 9.00, 1, ""),
        ],
    )
    _gravar_precos(data_dir, "2026-10-05", "covabra", [(1, "Café Torrado", 12.00, 1, "")])
    db = tmp_path / "historico.sqlite"
    historico.reindexar(data_dir, db)

    quedas = historico.quedas(db, date(2026, 10, 1))

    # maior queda primeiro; acucar compara com o menor do dia anterior (10.00)
    assert [
        (q.mercado, q.produto, q.variacao, q.preco_antes, q.preco_agora) for q in quedas
    ] == [
        ("covabra", "Café Torrado", -0.4, 20.00, 12.00),
        ("atacadao", "Arroz Tipo 1", -0.2, 10.00, 8.00),
        ("atacadao", "Açúcar Refinado", -0.1, 10.00, 9.00),
    ]
    assert [q.dia_antes for q in quedas] == ["2026-10-01", "2026-10-01", "2026-10-01"]
    assert [q.dia_agora for q in quedas] == ["2026-10-05", "2026-10-05", "2026-10-05"]
    # alta (8.00 -> 9.00) e produto so com um dia (mel) ficam de fora
    assert all("Óleo" not in q.produto and "Mel" not in q.produto for q in quedas)
    # fora da janela `desde` nao entra
    assert historico.quedas(db, date(2026, 10, 5)) == []


def test_resumo_banco_vazio_devolve_zeros_e_datas_none(tmp_path) -> None:
    db = tmp_path / "vazio.sqlite"

    resumo = historico.resumo(db)

    assert resumo == {"precos": 0, "dias": 0, "de": None, "ate": None, "coletas": 0, "site": 0}


def test_resumo_depois_de_reindexar_mostra_janela(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _gravar_precos(data_dir, "2026-10-01", "atacadao", [(1, "Arroz Tipo 1", 10.00, 1, "")])
    _gravar_precos(data_dir, "2026-10-05", "covabra", [(1, "Feijão Carioca", 7.50, 1, "")])
    db = tmp_path / "historico.sqlite"
    historico.reindexar(data_dir, db)

    resumo = historico.resumo(db)

    assert resumo == {"precos": 2, "dias": 2, "de": "2026-10-01", "ate": "2026-10-05",
                      "coletas": 0, "site": 0}


def test_banco_e_criado_com_a_pasta_do_caminho(tmp_path) -> None:
    """O caminho do banco pode incluir pastas que ainda nao existem."""
    data_dir = tmp_path / "data"
    _gravar_precos(data_dir, "2026-10-10", "atacadao", [(1, "Arroz Tipo 1", 10.00, 1, "")])
    db = tmp_path / "sub" / "historico.sqlite"

    contagens = historico.reindexar(data_dir, db)

    assert (tmp_path / "sub" / "historico.sqlite").exists()
    assert contagens["precos"] == 1
    assert historico.resumo(db)["precos"] == 1
