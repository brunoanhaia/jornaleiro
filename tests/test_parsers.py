"""Testes dos parsers, com fixtures inline recortadas das respostas reais."""

from __future__ import annotations

import html as html_lib
from datetime import date
from pathlib import Path

import pytest

from jornaleiro.markets import assai, atacadao, covabra, examine, savegnago
from jornaleiro.model import Context, MarketCfg
from jornaleiro.state import State

TODAY = date(2026, 10, 15)


class FakeRenderer:
    """Renderer que devolve sempre o mesmo texto (fixture), sem rede."""

    name = "fake"

    def __init__(self, text: str) -> None:
        self.text = text

    def get_text(self, url: str) -> str:
        return self.text

    def fetch_json_in_page(self, url: str, warmup_url: str) -> str:
        return self.text

    def close(self) -> None:
        pass


def make_ctx(text: str) -> Context:
    return Context(renderer=FakeRenderer(text), today_sp=TODAY, state=State(Path("unused.json")))


# --------------------------------------------------------------------------- Assai

ASSAI_JSON = """<html><head><meta name="color-scheme" content="light dark"></head><body><pre>
{"ofertas":[
 {"id":"27446","id_oferta":"49994-74","title":"","start_date":"12\\/10\\/2026","end_date":"16\\/10\\/2026","custom_text":"Pre\\u00e7os v\\u00e1lidos de 12\\/10\\/2026 at\\u00e9 16\\/10\\/2026","lojas":[{"loja_id":24,"tid":55,"nid":77,"eid":24},{"loja_id":122,"tid":123,"nid":1250,"eid":3}],"images":[{"url":"https:\\/\\/d2q57q7k4hzryv.cloudfront.net\\/RPA\\/v3\\/173705\\/campanha-173705-cluster-883-pagina-1.jpeg"},{"url":"https:\\/\\/d2q57q7k4hzryv.cloudfront.net\\/RPA\\/v3\\/173705\\/campanha-173705-cluster-883-pagina-2.jpeg"},{"url":"https:\\/\\/d2q57q7k4hzryv.cloudfront.net\\/RPA\\/v3\\/173705\\/campanha-173705-cluster-883-pagina-3.jpeg"},{"url":"https:\\/\\/d2q57q7k4hzryv.cloudfront.net\\/RPA\\/v3\\/173705\\/campanha-173705-cluster-883-pagina-4.jpeg"}],"origem":"integracao","destaque":"0"},
 {"id":"27542","id_oferta":"49994-75","title":"","start_date":"15\\/10\\/2026","end_date":"15\\/10\\/2026","custom_text":"Pre\\u00e7os v\\u00e1lidos para 15\\/10\\/2026","lojas":[{"loja_id":24,"tid":55,"nid":77,"eid":24}],"images":[{"url":"https:\\/\\/d2q57q7k4hzryv.cloudfront.net\\/RPA\\/v3\\/173868\\/campanha-173868-cluster-788-pagina-1.jpeg"},{"url":"https:\\/\\/d2q57q7k4hzryv.cloudfront.net\\/RPA\\/v3\\/173868\\/campanha-173868-cluster-788-pagina-2.jpeg"}],"origem":"integracao","destaque":"0"},
 {"start_date":"13\\/10\\/2026","end_date":"15\\/10\\/2026","custom_text":"","title":"","lojas":[{"loja_id":24,"tid":55,"nid":77,"eid":24}],"images":[{"url":"\\/sites\\/default\\/files\\/part_1_page-0001.jpg_1.jpeg"},{"url":"\\/sites\\/default\\/files\\/part_2_page-0001.jpg_1.jpeg"}],"origem":"integracao","destaque":"1"},
 {"id":"999","start_date":"15\\/10\\/2026","end_date":"18\\/10\\/2026","custom_text":"outra loja","lojas":[{"loja_id":99,"tid":55,"nid":37709,"eid":24}],"images":[{"url":"https:\\/\\/d2q57q7k4hzryv.cloudfront.net\\/RPA\\/v3\\/999\\/campanha-999-cluster-9-pagina-1.jpeg"}],"origem":"integracao","destaque":"10"},
 {"id":"888","start_date":"01\\/10\\/2026","end_date":"05\\/10\\/2026","custom_text":"vencida","lojas":[{"loja_id":24,"tid":55,"nid":77,"eid":24}],"images":[{"url":"https:\\/\\/d2q57q7k4hzryv.cloudfront.net\\/RPA\\/v3\\/888\\/campanha-888-cluster-8-pagina-1.jpeg"}],"origem":"integracao","destaque":"3"},
 {"id":"777","start_date":"15\\/10\\/2026","end_date":"20\\/10\\/2026","custom_text":"sem imagem","lojas":[{"loja_id":24,"tid":55,"nid":77,"eid":24}],"images":[],"origem":"integracao","destaque":"9"}
],"lojas":[{"tid":55,"name":"Assa\\u00ed Rio Claro","city_id":155,"nid":77,"eid":24,"loja_id":24,"url":"\\/ofertas\\/sao-paulo\\/assai-rio-claro"}]}</pre></body></html>
"""


def make_assai_cfg(max_paginas: int = 12, **overrides) -> MarketCfg:
    cfg = {
        "enabled": True,
        "eid": 24,
        "nid": 77,
        "offers_page": "https://www.assai.com.br/ofertas/sao-paulo/assai-rio-claro",
        "json_url": "https://www.assai.com.br/sites/default/files/static/ofertas_assai.json",
        "max_paginas": max_paginas,
    }
    cfg.update(overrides)
    return MarketCfg(cfg)


def test_assai_filtra_loja_e_vigencia() -> None:
    ctx = make_ctx(ASSAI_JSON)
    pages, validity = assai._from_json(ctx, make_assai_cfg())

    assert validity == "Preços válidos para 15/10/2026"
    assert pages == [
        "https://www.assai.com.br/sites/default/files/part_1_page-0001.jpg_1.jpeg",
        "https://www.assai.com.br/sites/default/files/part_2_page-0001.jpg_1.jpeg",
        "https://d2q57q7k4hzryv.cloudfront.net/RPA/v3/173868/campanha-173868-cluster-788-pagina-1.jpeg",
        "https://d2q57q7k4hzryv.cloudfront.net/RPA/v3/173868/campanha-173868-cluster-788-pagina-2.jpeg",
        "https://d2q57q7k4hzryv.cloudfront.net/RPA/v3/173705/campanha-173705-cluster-883-pagina-1.jpeg",
        "https://d2q57q7k4hzryv.cloudfront.net/RPA/v3/173705/campanha-173705-cluster-883-pagina-2.jpeg",
        "https://d2q57q7k4hzryv.cloudfront.net/RPA/v3/173705/campanha-173705-cluster-883-pagina-3.jpeg",
        "https://d2q57q7k4hzryv.cloudfront.net/RPA/v3/173705/campanha-173705-cluster-883-pagina-4.jpeg",
    ]


def test_assai_respeita_teto_de_paginas() -> None:
    ctx = make_ctx(ASSAI_JSON)
    pages, _ = assai._from_json(ctx, make_assai_cfg(max_paginas=3))

    assert len(pages) == 3
    assert pages[-1].endswith("campanha-173868-cluster-788-pagina-1.jpeg")


def test_assai_sem_oferta_vigente_falha() -> None:
    ctx = make_ctx(ASSAI_JSON)
    result = assai.fetch(ctx, MarketCfg(make_assai_cfg(eid=1, nid=2)))

    assert result.status == "failed"
    assert result.error == "nenhuma oferta vigente para loja eid=1/nid=2"


def test_assai_extrai_paginas_do_html() -> None:
    html = (
        '<a href="https:\\/\\/d2q57q7k4hzryv.cloudfront.net\\/RPA\\/v3\\/1\\/campanha-1-cluster-1-pagina-1.jpeg">'
        '</a><img src="https://d2q57q7k4hzryv.cloudfront.net/RPA/v3/2/campanha-2-cluster-2-pagina-9.jpeg">'
    )
    assert assai._from_page(html, 5) == [
        "https://d2q57q7k4hzryv.cloudfront.net/RPA/v3/1/campanha-1-cluster-1-pagina-1.jpeg",
        "https://d2q57q7k4hzryv.cloudfront.net/RPA/v3/2/campanha-2-cluster-2-pagina-9.jpeg",
    ]


class ImpervaRenderer(FakeRenderer):
    """JSON de ofertas bloqueado (o que acontece com clientes HTTP simples)."""

    def fetch_json_in_page(self, url: str, warmup_url: str) -> str:
        raise RuntimeError("challenge Imperva sem cookies da pagina")


class RecordingRenderer(FakeRenderer):
    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.requested: list[str] = []

    def fetch_json_in_page(self, url: str, warmup_url: str) -> str:
        self.requested.append(url)
        return self.text


def test_assai_pede_o_json_sem_cache_do_cdn() -> None:
    """A URL sem query fica presa num objeto antigo do CDN (ofertas vencidas)."""
    renderer = RecordingRenderer(ASSAI_JSON)
    ctx = Context(renderer=renderer, today_sp=TODAY, state=State(Path("unused.json")))

    assai._from_json(ctx, make_assai_cfg())

    (url,) = renderer.requested
    assert url.startswith("https://www.assai.com.br/sites/default/files/static/ofertas_assai.json?v=")


def test_assai_cai_para_o_html_quando_o_json_falha(monkeypatch: pytest.MonkeyPatch) -> None:
    page = (
        '<img src="https://d2q57q7k4hzryv.cloudfront.net/RPA/v3/173705/'
        'campanha-173705-cluster-883-pagina-1.jpeg">'
    )
    ctx = Context(renderer=ImpervaRenderer(page), today_sp=TODAY, state=State(Path("unused.json")))
    monkeypatch.setattr(assai.http, "get_bytes", lambda url, **kwargs: f"img:{url}".encode())

    result = assai.fetch(ctx, make_assai_cfg())

    assert result.status == "ok"
    assert [asset.url for asset in result.assets] == [
        "https://d2q57q7k4hzryv.cloudfront.net/RPA/v3/173705/campanha-173705-cluster-883-pagina-1.jpeg"
    ]
    assert result.note is not None and "challenge Imperva" in result.note


# ------------------------------------------------------------------------ Atacadao

ATACADAO_FLYERS = [
    {
        "id": "1rZEhOCfwop6qcD4mnYRVNl-FXUgI4aOD",
        "name": "Boa do Dia",
        "validity": {"initial": "2026-10-15T00:00:00Z", "final": "2026-10-15T00:00:00Z"},
        "exclude": False,
        "prioridade": 162540,
    },
    {
        "id": "11lDcPhRH7xb-oZBnvZPmUiC1pkumeGQi",
        "name": "Ofertããão Atacadão",
        "validity": {"initial": "2026-10-13T00:00:00Z", "final": "2026-10-19T00:00:00Z"},
        "exclude": False,
        "prioridade": 31070,
    },
    {
        "id": "1meUAC141-R_FT_AozbUvdGYC1hgVTafK",
        "name": "Especial Dia das Crianças",
        "validity": {"initial": "2026-10-12T00:00:00Z", "final": "2026-10-18T00:00:00Z"},
        "exclude": False,
        "prioridade": 1130,
    },
    {
        "id": "1kAxPIJwC8OI1-47hk9nUVwqr_FulmPWB",
        "name": "Salgadinhos",
        "validity": {"initial": "2026-10-12T00:00:00Z", "final": "2026-10-18T00:00:00Z"},
        "exclude": False,
        "prioridade": 70,
    },
    {
        "id": "vencido",
        "name": "Promo Velha",
        "validity": {"initial": "2026-10-01T00:00:00Z", "final": "2026-10-05T00:00:00Z"},
        "exclude": False,
        "prioridade": 999999,
    },
    {
        "id": "excluido",
        "name": "Fora do ar",
        "validity": {"initial": "2026-10-15T00:00:00Z", "final": "2026-10-15T00:00:00Z"},
        "exclude": True,
        "prioridade": 999999,
    },
    {
        "id": "sem-vigencia",
        "name": "Sem vigencia",
        "validity": {"initial": None, "final": None},
        "exclude": False,
        "prioridade": 999999,
    },
]


def test_atacadao_janela_e_ordem() -> None:
    names = [flyer["name"] for flyer in atacadao._vigentes(ATACADAO_FLYERS, TODAY)]

    assert names == [
        "Boa do Dia",
        "Ofertããão Atacadão",
        "Especial Dia das Crianças",
        "Salgadinhos",
    ]


@pytest.mark.parametrize("day,expected", [(date(2026, 10, 15), True), (date(2026, 10, 16), False)])
def test_atacadao_vigencia_de_um_dia(day: date, expected: bool) -> None:
    """`Boa do Dia` vem com initial == final == data local em `T00:00:00Z`."""
    flyer = ATACADAO_FLYERS[0]
    assert atacadao._vigente(flyer, day) is expected


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def json(self) -> dict:
        return self.payload


def _flyer(name: str, document: str, priority: int) -> dict:
    return {
        "id": document,
        "name": name,
        "validity": {"initial": "2026-10-13T00:00:00Z", "final": "2026-10-19T00:00:00Z"},
        "exclude": False,
        "prioridade": priority,
        "urlFinalDocument": document,
    }


@pytest.mark.parametrize("max_bytes,expected", [(2, ["a.pdf", "b.pdf"]), (0, ["a.pdf"])])
def test_atacadao_respeita_teto_de_bytes(
    monkeypatch: pytest.MonkeyPatch, max_bytes: int, expected: list[str]
) -> None:
    """Acumula folhetos ate o teto, sempre incluindo o primeiro."""
    flyers = [_flyer("A", "a.pdf", 3), _flyer("B", "b.pdf", 2), _flyer("C", "c.pdf", 1)]
    payload = {"stores": [{"slug": "rio-claro", "flyers": flyers}]}
    cfg = MarketCfg({"uf": "SP", "city": "Rio Claro", "slug": "rio-claro", "max_bytes": max_bytes})
    ctx = Context(renderer=FakeRenderer(""), today_sp=TODAY, state=State(Path("unused.json")))
    monkeypatch.setattr(atacadao.http, "get", lambda url, **kwargs: FakeResponse(payload))
    monkeypatch.setattr(atacadao.http, "get_bytes", lambda url, **kwargs: b"x")

    result = atacadao.fetch(ctx, cfg)

    assert [asset.url for asset in result.assets] == expected
    assert result.note == "; ".join(name for name in ["A", "B", "C"][: len(expected)])


# ------------------------------------------------------------------------- Covabra

COVABRA_HTML = """
<div class="covabra-jornal-ofertas-0-x-link"><div class="covabra-jornal-ofertas-0-x-coverContainer">
<img src="https://drive.google.com/thumbnail?id=12dRDKBVTN8l6WJMVLHQwthZu1OYKE7Kl&amp;sz=w1000" alt="Campinas"/></div>
<div class="covabra-jornal-ofertas-0-x-subtitle">15/10 - 21/10</div>
<a href="https://drive.google.com/uc?export=download&amp;id=12dRDKBVTN8l6WJMVLHQwthZu1OYKE7Kl" download="">Baixar</a></div>
<script>__STATE__ = {"items":[
{"__editorItemTitle":"Feira Bem-Estar","url":"https:\\u002F\\u002Fdrive.google.com\\u002Ffile\\u002Fd\\u002F13N0jPt08yJyUy-Yjn1LfGKLopoU9Lo2f\\u002Fview?usp=drive_link","title":"Rio Claro","subtitle":"12\\u002F10 - 14\\u002F10","startDate":"2026-10-12T12:00:00.000Z"},
{"__editorItemTitle":"Semanal","url":"https:\\u002F\\u002Fdrive.google.com\\u002Ffile\\u002Fd\\u002F1SPEpjBftp4zZuzCrGjiYHNyvDiL-uUSk\\u002Fview?usp=drive_link","title":"Rio Claro","subtitle":"15\\u002F10 - 21\\u002F10","startDate":"2026-10-15T12:00:00.000Z"}]}</script>
<div class="covabra-jornal-ofertas-0-x-link"><div class="covabra-jornal-ofertas-0-x-coverContainer">
<img src="https://drive.google.com/thumbnail?id=1SPEpjBftp4zZuzCrGjiYHNyvDiL-uUSk&amp;sz=w1000" alt="Rio Claro"/></div>
<div class="covabra-jornal-ofertas-0-x-actions"><a href="https://drive.google.com/file/d/1SPEpjBftp4zZuzCrGjiYHNyvDiL-uUSk/view?usp=drive_link">Visualizar</a>
<a href="https://drive.google.com/uc?export=download&amp;id=1SPEpjBftp4zZuzCrGjiYHNyvDiL-uUSk" download="">Baixar</a></div></div>
"""


def test_covabra_extrai_id_do_card_rio_claro() -> None:
    unescaped = html_lib.unescape(COVABRA_HTML)
    file_id = covabra._drive_id(unescaped, "Rio Claro")

    assert file_id == "1SPEpjBftp4zZuzCrGjiYHNyvDiL-uUSk"
    assert covabra._validity(unescaped, file_id, "Rio Claro") == "15/10 - 21/10"
    assert covabra._drive_id(unescaped, "Indaiatuba") is None


# ------------------------------------------------------------------------- Examine

EXAMINE_JINA = '''Title: Examine Supermercados ®️ on Instagram: "Apaixonados por churrasco entendem: não é só sobre comer bem, é sobre compartilhar momentos.
Neste fim de semana, reúna a família, chame os amigos e faça do churrasco o ponto de encontro das melhores histórias. 🔥🍖

Ofertas válidas para as lojas de Rio Claro, Santa Gertrudes e Cordeirópolis de 15/10 a 18/10/2026."

URL Source: https://www.instagram.com/p/Deh37qhjcMZ/

Markdown Content:
[Log In](https://www.instagram.com/accounts/login/?next=%2Fp%2FDeh37qhjcMZ%2F)

![Image 4: examinesupermercados's profile picture](https://scontent-atl3-2.cdninstagram.com/v/t51.82787-19/740953825_18332442256266485_2229427642037710806_n.jpg?stp=dst-jpg_s150x150_tt6&amp;_nc_cat=101)

![Image 5: Photo by Examine Supermercados ®️ on October 15, 2026. May be an image of pork and text.](https://scontent-atl3-1.cdninstagram.com/v/t39.30808-6/850497816_1412664067703607_9019892044627896368_n.jpg?stp=dst-jpg_e35_tt6&amp;_nc_cat=103&amp;ig_cache_key=NDAwODczMTEzNjAwMzc4NTQ5Nw%3D%3D.3-ccb7-5)

Never miss a post from examinesupermercados

![Image 9: Photo by Examine Supermercados ®️ on October 13, 2026.](https://scontent-atl3-1.cdninstagram.com/v/t51.82787-15/849709417_14108718_n.jpg?stp=dst-jpg_s640x640_tt6&amp;_nc_cat=103)

[More posts from examinesupermercados](https://www.instagram.com/examinesupermercados/)
'''

EXAMINE_PLAYWRIGHT = (
    '<html><head><meta property="og:description" content="10 likes, 0 comments - '
    "examinesupermercados no October 15, 2026: &quot;Apaixonados por churrasco entendem: "
    "n&#xe3;o &#xe9; s&#xf3; sobre comer bem.\\nOfertas v&#xe1;lidas para as lojas de Rio "
    'Claro, Santa Gertrudes e Cordeir&#xf3;polis de 15/10 a 18/10/2026.&quot;"/>'
    '<meta property="og:image" content="https://scontent.cdninstagram.com/v/t39.30808-6/'
    "850497816_1412664067703607_9019892044627896368_n.jpg?stp=c224.0.673.673a_dst-jpg_e35_s640x640_tt6"
    '&amp;_nc_cat=103"/>'
    '<link rel="stylesheet" href="https://static.cdninstagram.com/rsrc.php/v5/yC/l/0,cross/abc.css"/>'
    "<script>"
    '"display_uri":"https:\\/\\/scontent.cdninstagram.com\\/v\\/t39.30808-6\\/850497816_1412664067703607_9019892044627896368_n.jpg?stp=dst-jpg_e35_s640x640_tt6",'
    '"image_versions2":{"candidates":['
    '{"url":"https:\\/\\/instagram.fsod2-1.fna.fbcdn.net\\/v\\/t39.30808-6\\/850497816_1412664067703607_9019892044627896368_n.jpg?stp=dst-jpg_e35_tt6&_nc_cat=103&ig_cache_key=NDAwODczMTEzNjAwMzc4NTQ5Nw\\u00253D\\u00253D.3-ccb7-5&oh=00_AQMEj8FzlRZ2cQRFg8Z72UaGOkFfT-MESjFMvs5CkQpQYw&oe=6AD73715"},'
    '{"url":"https:\\/\\/instagram.fsod2-1.fna.fbcdn.net\\/v\\/t39.30808-6\\/850497816_1412664067703607_9019892044627896368_n.jpg?stp=dst-jpg_e35_p720x720_tt6&_nc_cat=103&oe=6AD73715"},'
    '{"url":"https:\\/\\/instagram.fsod2-1.fna.fbcdn.net\\/v\\/t39.30808-6\\/850497816_1412664067703607_9019892044627896368_n.jpg?stp=c0.140.1122.1122a_dst-jpg_e35_s640x640_tt6&_nc_cat=103&oe=6AD73715"}]},'
    '"profile_pic_url":"https:\\/\\/scontent-atl3-2.cdninstagram.com\\/v\\/t51.82787-19\\/740953825_18332442256266485_n.jpg?stp=dst-jpg_s150x150_tt6"'
    "</script>"
    '<link rel="preload" as="image" href="https://instagram.fsod2-1.fna.fbcdn.net/v/t39.30808-6/'
    "850497816_1412664067703607_9019892044627896368_n.jpg?stp=dst-jpg_e35_tt6&amp;_nc_cat=103&amp;oe=6AD71BC6\"/>"
    '<img src="https://scontent-atl3-1.cdninstagram.com/v/t51.82787-15/849709417_n.jpg?stp=dst-jpg_s640x640_tt6"/>'
    '<img alt="Photo by Examine Supermercados ®️ no October 13, 2026." '
    'src="https://scontent-atl3-1.cdninstagram.com/v/t51.82787-15/827856031_n.jpg?stp=dst-jpg_s640x640_tt6"/>'
    "</html>"
)

EXAMINE_OTHER_POST = (
    'Title: Examine Supermercados ®️ on Instagram: "Sabe aquele momento que merece algo a mais? '
    "Ele começa com a escolha certa da carne. 🥩✨\n"
    "*Ofertas válidas apenas para a Loja 5 (JD Itapuã), de 07/10 a 20/10/2026.\"\n"
    "\nURL Source: https://www.instagram.com/examinesupermercados/p/Decj8g3DHAn/\n"
)

FULL_SIZE = (
    "https://scontent-atl3-1.cdninstagram.com/v/t39.30808-6/"
    "850497816_1412664067703607_9019892044627896368_n.jpg?stp=dst-jpg_e35_tt6"
    "&_nc_cat=103&ig_cache_key=NDAwODczMTEzNjAwMzc4NTQ5Nw%3D%3D.3-ccb7-5"
)

EXAMINE_CFG = MarketCfg(
    {
        "enabled": True,
        "seed_url": "https://www.instagram.com/examinesupermercados/p/Deh37qhjcMZ/",
        "caption_filter": "Ofertas válidas",
        "max_posts": 12,
    }
)


def test_examine_legenda_e_imagem_full_size() -> None:
    caption = examine.extract_caption(EXAMINE_JINA)

    assert caption is not None
    assert "Ofertas válidas para as lojas de Rio Claro" in caption
    assert "15/10 a 18/10/2026" in caption
    assert examine.is_encarte(caption, EXAMINE_CFG) is True
    # a legenda do render jina nao traz a data: ela vem do "Photo by ... on October 15, 2026"
    assert examine.post_date(caption, EXAMINE_JINA) == date(2026, 10, 15)
    assert examine.validity_of(caption) == "15/10 a 18/10/2026"
    assert examine.image_urls(EXAMINE_JINA) == [FULL_SIZE]


def test_examine_html_do_playwright() -> None:
    caption = examine.extract_caption(EXAMINE_PLAYWRIGHT)

    assert caption is not None
    assert "lojas de Rio Claro" in caption
    assert "&#xe3;" not in caption and "&quot;" not in caption
    assert examine.post_date(caption, EXAMINE_PLAYWRIGHT) == date(2026, 10, 15)
    urls = examine.image_urls(EXAMINE_PLAYWRIGHT)
    assert len(urls) == 1
    assert urls[0].startswith("https://instagram.fsod2-1.fna.fbcdn.net/")
    # `\u0025` no JSON vira `%`: sem isso a URL quebra em `ig_cache_key=...Nw`
    assert "%3D%3D.3-ccb7-5" in urls[0]
    assert "s640x640" not in urls[0] and "_p720x720" not in urls[0]


def test_examine_descarta_post_de_outra_loja() -> None:
    caption = examine.extract_caption(EXAMINE_OTHER_POST)

    assert caption is not None and "Loja 5" in caption
    assert examine.is_encarte(caption, EXAMINE_CFG) is False


def test_examine_shortcode_da_semente() -> None:
    assert (
        examine.shortcode("https://www.instagram.com/examinesupermercados/p/Deh37qhjcMZ/")
        == "Deh37qhjcMZ"
    )
    assert examine.shortcode("https://www.instagram.com/reel/Deh37qhjcMZ/") == "Deh37qhjcMZ"


# ----------------------------------------------------------------------- Savegnago

def test_savegnago_validade_impressa_marca_vencido() -> None:
    texto = "As ofertas deste box são válidas até sábado - 17/10/2026."

    assert savegnago.validade_texto(texto, date(2026, 10, 16)) == "válido até 17/10/2026"
    assert savegnago.validade_texto(texto, date(2026, 10, 18)) == "válido até 17/10/2026 (vencido)"


def test_savegnago_usa_a_maior_validade_do_encarte() -> None:
    """Box do inicio vencido + validade geral no fim: vale a maior data do PDF."""
    texto = (
        "As ofertas deste box são válidas até sábado - 17/10/2026.\n"
        "Ofertas válidas de 15 a 18/10/2026 ou enquanto durarem os nossos estoques.\n"
    )

    assert savegnago.validade_texto(texto, date(2026, 10, 18)) == "válido até 18/10/2026"
    assert savegnago.validade_texto(texto, date(2026, 10, 19)) == "válido até 18/10/2026 (vencido)"


def test_savegnago_validade_olha_todas_as_paginas(monkeypatch) -> None:
    """A validade geral fica na ultima pagina; nao pode parar na primeira mencao."""

    class PaginaFalsa:
        def __init__(self, texto: str) -> None:
            self.texto = texto

        def extract_text(self) -> str:
            return self.texto

    class ReaderFalso:
        def __init__(self, _: object) -> None:
            self.pages = [
                PaginaFalsa("As ofertas deste box são válidas até sábado - 17/10/2026."),
                PaginaFalsa("Ofertas válidas de 15 a 18/10/2026 ou enquanto durarem os estoques."),
            ]

    monkeypatch.setattr(savegnago, "PdfReader", ReaderFalso)

    assert savegnago.validade(b"pdf", date(2026, 10, 18)) == "válido até 18/10/2026"
    assert savegnago.validade(b"pdf", date(2026, 10, 19)) == "válido até 18/10/2026 (vencido)"


def test_savegnago_sem_validade_legivel() -> None:
    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buffer = BytesIO()
    writer.write(buffer)

    assert savegnago.validade_texto("encarte sem data", date(2026, 10, 18)) is None
    assert savegnago.validade(buffer.getvalue(), date(2026, 10, 18)) is None
