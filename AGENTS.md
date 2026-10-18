# AGENTS.md

CLI em Python >= 3.11 (argparse, sem framework) que coleta os encartes de 5 mercados de
Rio Claro/SP, monta um PDF por mercado, lê os preços e envia PDFs + CSVs por Telegram.
Execução manual; sem agendador, banco, API ou front-end. Código, logs, legendas e testes
são em pt-BR — mantenha o idioma.

`README.md` é a fonte de verdade do comportamento (com medições datadas). Leia a seção
relevante antes de mexer em parsers, compressão ou preços, e atualize-o junto.

## Comandos

- venv local em `.venv/` com o pacote instalado editable: mudanças em `src/` valem sem
  reinstalar; dependência nova pede `.venv/bin/pip install -e ".[dev]"`.
- Testes: `.venv/bin/python -m pytest -q`. Um teste/arquivo:
  `.venv/bin/python -m pytest tests/test_precos.py::test_nome -q`.
- Os testes não acessam a rede (fixtures inline recortadas de respostas reais, renderer
  falso, `monkeypatch` de `http`); escreva testes novos no mesmo estilo.
- Não há lint, formatador nem typecheck configurados; o pytest é a única verificação.
- Iterar na extração de preços sem rede: `.venv/bin/jornais precos --dia AAAA-MM-DD`
  reprocessa os PDFs já baixados em `data/<dia>/`.
- Debug: `.venv/bin/jornais render <url>` imprime o texto renderizado;
  `.venv/bin/jornais examine-probe` mostra a descoberta do post do Instagram.
- Todo comando chama `load_dotenv()`: `.env` (não versionado) com `TELEGRAM_BOT_TOKEN` e
  `TELEGRAM_CHAT_ID` para enviar — sem eles use `--no-send`; `JINA_API_KEY` e
  `EXAMINE_TOKEN` são opcionais.
- `data/` guarda `data/<AAAA-MM-DD>/<mercado>.pdf`, `raw/` (originais), `precos/*.csv|json`
  e `state.json`. Rodar `run` no mesmo dia sobrescreve o PDF e limpa os brutos do mercado
  antes de regravar.

## Arquitetura

- `src/jornais/cli.py` — entrypoint `jornais` (`run|precos|site-precos|render|examine-probe`),
  orquestração (`cmd_run` → `publish`) e resumo/captions do Telegram.
- `src/jornais/markets/<chave>.py` — um módulo por mercado com `KEY`, `LABEL` e
  `fetch(ctx, cfg) -> MarketResult`, registrados em `markets/__init__.py`
  (`REGISTRY`/`ORDER`). `safe_fetch` impede que um mercado derrube os outros. Mercado novo =
  módulo + registro + seção `[markets.<chave>]` no `config.toml`.
- `model.py` (Asset/MarketResult/MarketCfg/Context), `compose.py` (assets → PDF único em A4),
  `comprimir.py`, `precos.py` (camada de texto + OCR), `site.py` (GraphQL do Examine),
  `notify.py` (Telegram), `render.py` (Playwright com fallback jina), `state.py`.
- Configuração em `config.toml` (URLs, flags por mercado, OCR, compressão);
  `--config`/`--only`/`--renderer`/`--data-dir` ajustam por execução.
- `run` não aborta por mercado: sai `0` mesmo com falha parcial, `1` se nenhum PDF sair ou
  todos falharem, `2` para erro de config.

## Armadilhas

- A compressão padrão (`modo = "forte"`) rasteriza as páginas e **apaga a camada de texto**.
  Por isso os preços são lidos de `data/<dia>/raw/` (nunca comprimido), não do PDF final —
  preserve isso ao mexer em `cli.publish`/`precos`.
- `pamphlets` (jornal oficial do Examine) só existe no endpoint `site_graphql_jornal`
  (`www.crescevendas.com/graphql`); o catálogo usa `site_graphql` (`.../ecommerce/graphql`).
  Inverter os dois dá `Field 'pamphlets' doesn't exist on type 'Query'`.
- Assaí: o JSON de ofertas está atrás do challenge Imperva — só responde dentro de uma
  página já carregada (`renderer.fetch_json_in_page`), e a URL leva `?v=<timestamp>`
  (`assai._uncached`) para escapar do CDN congelado por semanas.
- Atacadão: `validity` vem como meia-noite UTC com a data local do cliente — não converta
  fuso horário (a janela andaria um dia; ver docstring de `atacadao._bound`).
- Examine sem `EXAMINE_TOKEN` cai no Instagram. A semente vem de `data/state.json`
  (`examine_last_post_url`/`examine_seen`): apague essas chaves para reavaliar posts antigos.
- Chromium e tesseract podem faltar na máquina sem quebrar o run: o renderer `auto` cai para
  o jina e o OCR ausente vira aviso no resumo (`precos: OCR indisponivel`). O tesseract é
  procurado no PATH e em `~/.local/share/tesseract` (ver `[precos]` e o README).
