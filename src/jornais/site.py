"""Precos do site do Examine (e-commerce crescevendas) via GraphQL.

O site `superexaminerc.crescevendas.com` e um Next.js que conversa com uma API GraphQL
compartilhada (`www.crescevendas.com/ecommerce/graphql`); o cliente e resolvido pelo
`Origin` do tenant (a consulta `app_version` devolve `client_id=377, name="Examine"`).
As consultas abaixo sao as mesmas que o proprio site usa (extraidas dos chunks do
Next.js em 15/10/2026): `categories` pagina de 20 em 20 e `products(categoryId, after)`
devolve 20 itens por pagina, com `salePrice` e os `discounts` do clube
(`type: "Aplicativo"` e `"Cashback"`).

Diferente do OCR do encarte, aqui o preco vem estruturado: nome, codigo, preco, estoque,
pesavel/peso e os descontos. O que **nao** e a mesma coisa: isto e o preco do site, nao
necessariamente o preco impresso no encarte da semana.
"""

from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from io import StringIO
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from . import http

GRAPHQL_PADRAO = "https://www.crescevendas.com/ecommerce/graphql"
PAGINA = 20  # o servidor devolve 20 por pagina, independente de `first`

_CATEGORIAS = """query ($after: String) {
  categories(after: $after) { pageInfo { hasNextPage endCursor } edges { node { id name } } }
}"""

_PRODUTOS = """query ($categoryId: ID, $after: String) {
  products(categoryId: $categoryId, after: $after) {
    pageInfo { hasNextPage endCursor }
    edges { node { ... on ProductRecord {
      id name code description salePrice stock weighable unitWeight
      discounts { name value type promotion limit }
    } } }
  }
}"""

# jornal de ofertas oficial (precisa do Bearer do clube; sem token devolve null)
_FOLHETOS = """query { pamphlets { file id title } }"""


@dataclass
class Folheto:
    """Uma pagina do jornal de ofertas: `url` absoluta + titulo da campanha."""

    id: str
    titulo: str
    url: str


@dataclass
class Produto:
    id: str
    nome: str
    categoria: str
    preco: float
    codigo: str | None = None
    descricao: str | None = None
    estoque: float | None = None
    pesavel: bool = False
    unidade: float | None = None
    descontos: list[dict] = field(default_factory=list)


def desconto_texto(descontos: list[dict]) -> str:
    """`Aplicativo=3.1; Cashback=0.05495`: `value` depende do tipo (ver README)."""
    return "; ".join(
        f"{d.get('type') or d.get('name') or '?'}={d.get('value')}" for d in descontos or []
    )


class Site:
    def __init__(
        self,
        url: str = GRAPHQL_PADRAO,
        *,
        origin: str,
        pausa: float = 0.2,
        timeout: float = 60.0,
        token: str = "",
    ) -> None:
        self.url = url
        self.origin = origin.rstrip("/")
        self.pausa = pausa
        self.timeout = timeout
        self.token = token.strip()

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Origin": self.origin,
            "Referer": self.origin + "/",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def consultar(self, query: str, variables: dict | None = None) -> dict:
        resposta = http.post_json(
            self.url, {"query": query, "variables": variables or {}}, headers=self._headers()
        )
        dados = resposta.json()
        if dados.get("errors"):
            raise RuntimeError(f"graphql: {json.dumps(dados['errors'], ensure_ascii=False)[:200]}")
        return dados.get("data") or {}

    def folhetos(self) -> list[Folheto]:
        """Paginas do jornal de ofertas, na ordem que a API devolve (campanha por campanha)."""
        dados = self.consultar(_FOLHETOS)
        partes = urlsplit(self.url)
        base = f"{partes.scheme}://{partes.netloc}"
        folhetos: list[Folheto] = []
        for item in dados.get("pamphlets") or []:
            arquivo = str(item.get("file") or "")
            if not arquivo:
                continue
            folhetos.append(
                Folheto(
                    id=str(item.get("id")),
                    titulo=(item.get("title") or "").strip(),
                    url=arquivo if arquivo.startswith("http") else base + arquivo,
                )
            )
        return folhetos

    def categorias(self) -> list[tuple[str, str]]:
        achadas: list[tuple[str, str]] = []
        after: str | None = None
        while True:
            dados = self.consultar(_CATEGORIAS, {"after": after})
            pagina = dados.get("categories") or {}
            for borda in pagina.get("edges") or []:
                no = borda["node"]
                achadas.append((str(no["id"]), no["name"]))
            pagina_info = pagina.get("pageInfo") or {}
            if not pagina_info.get("hasNextPage"):
                return achadas
            after = pagina_info.get("endCursor")
            self._pausa()

    def produtos_da_categoria(self, categoria_id: str, categoria: str) -> list[Produto]:
        produtos: list[Produto] = []
        after: str | None = None
        while True:
            dados = self.consultar(_PRODUTOS, {"categoryId": categoria_id, "after": after})
            pagina = dados.get("products") or {}
            for borda in pagina.get("edges") or []:
                produtos.append(_produto(borda["node"], categoria))
            pagina_info = pagina.get("pageInfo") or {}
            if not pagina_info.get("hasNextPage"):
                return produtos
            after = pagina_info.get("endCursor")
            self._pausa()

    def catalogo(
        self,
        *,
        max_categorias: int = 0,
        ao_progredir: Callable[[str, int, int], None] | None = None,
    ) -> list[Produto]:
        categorias = self.categorias()
        if max_categorias:
            categorias = categorias[:max_categorias]
        produtos: list[Produto] = []
        for indice, (categoria_id, nome) in enumerate(categorias, start=1):
            da_categoria = self.produtos_da_categoria(categoria_id, nome)
            produtos.extend(da_categoria)
            if ao_progredir is not None:
                ao_progredir(nome, len(da_categoria), len(produtos))
            self._pausa()
        return produtos

    def _pausa(self) -> None:
        if self.pausa:
            time.sleep(self.pausa)


def _produto(no: dict, categoria: str) -> Produto:
    return Produto(
        id=str(no.get("id")),
        nome=(no.get("name") or "").strip(),
        categoria=categoria,
        preco=float(no.get("salePrice") or 0),
        codigo=no.get("code"),
        descricao=(no.get("description") or None),
        estoque=no.get("stock"),
        pesavel=bool(no.get("weighable")),
        unidade=no.get("unitWeight"),
        descontos=no.get("discounts") or [],
    )


CABECALHO = ["id", "categoria", "produto", "preco", "pesavel", "unidade", "estoque", "descontos"]


def csv_text(produtos: list[Produto]) -> str:
    out = StringIO()
    escritor = csv.writer(out, delimiter=";", lineterminator="\n")
    escritor.writerow(CABECALHO)
    for produto in produtos:
        escritor.writerow(
            [
                produto.id,
                produto.categoria,
                produto.nome,
                f"{produto.preco:.2f}",
                "sim" if produto.pesavel else "nao",
                "" if produto.unidade is None else produto.unidade,
                "" if produto.estoque is None else produto.estoque,
                desconto_texto(produto.descontos),
            ]
        )
    return out.getvalue()


def write(produtos: list[Produto], data_dir: Path, dia: date, nome: str = "examine") -> tuple[Path, Path]:
    folder = data_dir / dia.isoformat() / "precos"
    folder.mkdir(parents=True, exist_ok=True)
    json_path = folder / f"{nome}.json"
    csv_path = folder / f"{nome}.csv"
    json_path.write_text(
        json.dumps([asdict(produto) for produto in produtos], ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    csv_path.write_text(csv_text(produtos), encoding="utf-8-sig")
    return json_path, csv_path
