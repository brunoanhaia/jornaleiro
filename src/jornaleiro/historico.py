"""Historico das leituras de precos em SQLite (indice derivado dos CSVs).

A fonte de verdade continua sendo `data/<dia>/precos/*.csv` (com PDFs e brutos ao
lado); o banco e apenas um indice para consulta, recriavel a qualquer momento com
`jornaleiro historico --reindex`. Ele fica em `data/historico.sqlite` — dentro de
`data/`, que nao entra no git — e o `run` atualiza o dia quando o banco ja existe.

Nomes de produto sao normalizados (`produto_norm`: sem acento, minusculo) para o
filtro e para casar o mesmo item entre dias; sem fuzzy match (v1).
"""

from __future__ import annotations

import csv
import sqlite3
import unicodedata
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS precos (
  mercado TEXT NOT NULL,
  dia TEXT NOT NULL,
  pagina INTEGER NOT NULL,
  produto TEXT NOT NULL,
  produto_norm TEXT NOT NULL,
  preco REAL NOT NULL,
  ordem INTEGER NOT NULL,
  tipo TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS precos_produto_idx ON precos (produto_norm);
CREATE INDEX IF NOT EXISTS precos_dia_idx ON precos (dia);

CREATE TABLE IF NOT EXISTS coletas (
  dia TEXT NOT NULL,
  mercado TEXT NOT NULL,
  itens INTEGER NOT NULL,
  precos INTEGER NOT NULL,
  pdf_bytes INTEGER NOT NULL DEFAULT 0,
  raw_bytes INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (dia, mercado)
);

CREATE TABLE IF NOT EXISTS site_produtos (
  dia TEXT NOT NULL,
  id TEXT NOT NULL,
  categoria TEXT NOT NULL,
  produto TEXT NOT NULL,
  produto_norm TEXT NOT NULL,
  preco REAL NOT NULL,
  pesavel TEXT NOT NULL DEFAULT '',
  unidade TEXT NOT NULL DEFAULT '',
  estoque TEXT NOT NULL DEFAULT '',
  descontos TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS site_produto_idx ON site_produtos (produto_norm);
"""


def normalizar(texto: str) -> str:
    """Chave de busca do produto: sem acento, minusculo, espacos colapsados."""
    decomposto = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(letra for letra in decomposto if not unicodedata.combining(letra))
    return " ".join(sem_acento.lower().split())


def abrir(db: Path) -> sqlite3.Connection:
    """Abre (criando se preciso) o banco com o schema garantido."""
    db.parent.mkdir(parents=True, exist_ok=True)
    conexao = sqlite3.connect(db)
    conexao.executescript(SCHEMA)
    return conexao


def reindexar(data_dir: Path, db: Path) -> dict[str, int]:
    """Reconstroi o banco inteiro a partir dos CSVs de `data_dir`."""
    with closing(abrir(db)) as conexao:
        conexao.execute("DELETE FROM precos")
        conexao.execute("DELETE FROM coletas")
        conexao.execute("DELETE FROM site_produtos")
        contagens = _importar(conexao, data_dir)
        conexao.commit()
    return contagens


def registrar_dia(data_dir: Path, dia: date, db: Path) -> dict[str, int]:
    """Atualiza so o dia pedido (o `run` usa para nao reindexar a historia toda)."""
    with closing(abrir(db)) as conexao:
        for tabela in ("precos", "coletas", "site_produtos"):
            conexao.execute(f"DELETE FROM {tabela} WHERE dia = ?", (dia.isoformat(),))
        contagens = _importar(conexao, data_dir, so_dia=dia)
        conexao.commit()
    return contagens


def buscar(
    db: Path, texto: str, desde: date, limite: int = 40
) -> list[tuple[str, str, str, float, str]]:
    """Linhas (mercado, dia, produto, preco, tipo) cujo nome contem `texto`."""
    with closing(abrir(db)) as conexao:
        return conexao.execute(
            """
            SELECT mercado, dia, produto, preco, tipo
            FROM precos
            WHERE produto_norm LIKE ? AND dia >= ?
            ORDER BY dia DESC, mercado, preco
            LIMIT ?
            """,
            (f"%{normalizar(texto)}%", desde.isoformat(), limite),
        ).fetchall()


@dataclass
class Queda:
    """Variacao entre as duas ultimas leituras de um produto (menor preco do dia)."""

    mercado: str
    produto: str
    dia_antes: str
    preco_antes: float
    dia_agora: str
    preco_agora: float

    @property
    def variacao(self) -> float:
        if not self.preco_antes:
            return 0.0
        return (self.preco_agora - self.preco_antes) / self.preco_antes


def quedas(db: Path, desde: date, limite: int = 20) -> list[Queda]:
    """Maiores quedas (as menores variacoes primeiro) na janela `desde..hoje`.

    Compara a ultima leitura de cada produto com a anterior, usando o menor preco
    de cada dia (o mesmo item aparece varias vezes por pagina). Variacoes de alta
    ficam de fora: a pergunta aqui e "o que baixou de preco".
    """
    consulta = """
    WITH por_dia AS (
        SELECT mercado, produto_norm, dia, MIN(preco) AS preco
        FROM precos
        WHERE dia >= ?
        GROUP BY mercado, produto_norm, dia
    ),
    ranqueado AS (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY mercado, produto_norm ORDER BY dia DESC
        ) AS rn
        FROM por_dia
    )
    SELECT a.mercado,
           (SELECT x.produto FROM precos x
             WHERE x.mercado = a.mercado AND x.produto_norm = a.produto_norm AND x.dia = a.dia
             ORDER BY x.preco LIMIT 1) AS produto,
           p.dia, p.preco, a.dia, a.preco
    FROM ranqueado a
    JOIN ranqueado p ON p.mercado = a.mercado AND p.produto_norm = a.produto_norm
    WHERE a.rn = 1 AND p.rn = 2 AND p.preco > 0 AND a.preco < p.preco
    ORDER BY (a.preco - p.preco) / p.preco ASC
    LIMIT ?
    """
    with closing(abrir(db)) as conexao:
        linhas = conexao.execute(consulta, (desde.isoformat(), limite)).fetchall()
    return [
        Queda(
            mercado=linha[0],
            produto=linha[1] or "",
            dia_antes=linha[2],
            preco_antes=float(linha[3]),
            dia_agora=linha[4],
            preco_agora=float(linha[5]),
        )
        for linha in linhas
    ]


def resumo(db: Path) -> dict[str, object]:
    """Contagens para o comando sem consulta (datas em ISO, `None` se vazio)."""
    with closing(abrir(db)) as conexao:
        precos, dias, dia_min, dia_max = conexao.execute(
            "SELECT COUNT(*), COUNT(DISTINCT dia), MIN(dia), MAX(dia) FROM precos"
        ).fetchone()
        coletas = conexao.execute("SELECT COUNT(*) FROM coletas").fetchone()[0]
        site = conexao.execute("SELECT COUNT(*) FROM site_produtos").fetchone()[0]
    return {"precos": precos, "dias": dias, "de": dia_min, "ate": dia_max, "coletas": coletas, "site": site}


def _importar(conexao: sqlite3.Connection, data_dir: Path, so_dia: date | None = None) -> dict[str, int]:
    """Varre `data/<dia>/precos/*.csv` (e os PDFs/brutos de `coletas`)."""
    contagens = {"dias": 0, "precos": 0, "site": 0, "coletas": 0}
    if not data_dir.is_dir():
        return contagens
    for pasta in sorted(data_dir.iterdir()):
        if not pasta.is_dir():
            continue
        try:
            dia = date.fromisoformat(pasta.name)
        except ValueError:
            continue
        if so_dia is not None and dia != so_dia:
            continue
        contagens["dias"] += 1
        dia_txt = dia.isoformat()
        for caminho in sorted((pasta / "precos").glob("*.csv")):
            n_precos, n_site = _importar_csv(conexao, caminho, dia_txt)
            contagens["precos"] += n_precos
            contagens["site"] += n_site
        contagens["coletas"] += _importar_coletas(conexao, pasta, dia_txt)
    return contagens


def _importar_csv(conexao: sqlite3.Connection, caminho: Path, dia: str) -> tuple[int, int]:
    """Importa um CSV de precos (schema do mercado) ou do site; devolve as contagens.

    O `examine.csv` e o mesmo nome para os dois formatos: o catalogo do site tem as
    colunas `id;categoria;...` e a leitura do encarte tem `mercado;pagina;...`.
    """
    try:
        with caminho.open(encoding="utf-8-sig", newline="") as arquivo:
            linhas = list(csv.DictReader(arquivo, delimiter=";"))
    except OSError:
        return 0, 0
    if not linhas:
        return 0, 0
    campos = set(linhas[0])
    if {"id", "categoria"} <= campos:
        conexao.executemany(
            "INSERT INTO site_produtos"
            " (dia, id, categoria, produto, produto_norm, preco, pesavel, unidade, estoque, descontos)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    dia,
                    linha.get("id", ""),
                    linha.get("categoria", ""),
                    linha.get("produto", ""),
                    normalizar(linha.get("produto", "")),
                    _float(linha.get("preco")),
                    linha.get("pesavel", ""),
                    linha.get("unidade", ""),
                    linha.get("estoque", ""),
                    linha.get("descontos", ""),
                )
                for linha in linhas
            ],
        )
        return 0, len(linhas)
    if {"mercado", "produto", "preco"} <= campos:
        conexao.executemany(
            "INSERT INTO precos (mercado, dia, pagina, produto, produto_norm, preco, ordem, tipo)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    linha.get("mercado", ""),
                    dia,
                    _int(linha.get("pagina")),
                    linha.get("produto", ""),
                    normalizar(linha.get("produto", "")),
                    _float(linha.get("preco")),
                    _int(linha.get("ordem")),
                    linha.get("tipo", ""),
                )
                for linha in linhas
            ],
        )
        return len(linhas), 0
    return 0, 0


def _importar_coletas(conexao: sqlite3.Connection, pasta: Path, dia: str) -> int:
    """Uma linha por mercado com PDF do dia (itens/precos saem dos CSVs importados)."""
    total = 0
    for pdf in sorted(pasta.glob("*.pdf")):
        mercado = pdf.stem
        precos, itens = conexao.execute(
            "SELECT COUNT(*), COUNT(DISTINCT produto_norm) FROM precos WHERE dia = ? AND mercado = ?",
            (dia, mercado),
        ).fetchone()
        raw_bytes = sum(
            arquivo.stat().st_size
            for arquivo in (pasta / "raw").glob(f"{mercado}-*")
            if arquivo.is_file()
        )
        conexao.execute(
            "INSERT OR REPLACE INTO coletas (dia, mercado, itens, precos, pdf_bytes, raw_bytes)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (dia, mercado, itens, precos, pdf.stat().st_size, raw_bytes),
        )
        total += 1
    return total


def _float(valor: object) -> float:
    """Aceita `5.49` (CSV do projeto) e `1.234,56` (pt-BR colado a mao)."""
    texto = str(valor).strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return 0.0


def _int(valor: object) -> int:
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return 0
