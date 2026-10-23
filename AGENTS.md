# AGENTS.md

CLI em Python >= 3.11 (argparse, sem framework) que coleta os encartes de 5 mercados de
Rio Claro/SP, monta um PDF por mercado, lê os preços e envia PDFs + CSVs por Telegram.
Execução manual local ou agendada no GitHub Actions (07:00 e 19:00); sem API ou
front-end (o SQLite é um índice derivado dos CSVs, não uma fonte de verdade). Nenhum
binário é versionado: PDFs, CSVs, banco e `run.log` ficam em `data/` (fora do git) —
nada de LFS. Código, logs, legendas e testes são em pt-BR — mantenha o
idioma. Os commits seguem *Conventional Commits*: `tipo(escopo): resumo` em pt-BR (tipos
usados: `feat`, `fix`, `docs`, `test`, `chore`), com corpo curto explicando o porquê
quando ajudar.

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
- Iterar na extração de preços sem rede: `.venv/bin/jornaleiro precos --dia AAAA-MM-DD`
  reprocessa os PDFs já baixados em `data/<dia>/`.
- Debug: `.venv/bin/jornaleiro render <url>` imprime o texto renderizado;
  `.venv/bin/jornaleiro examine-probe` mostra a descoberta do post do Instagram.
- Todo comando chama `load_dotenv()`: `.env` (não versionado) com `TELEGRAM_BOT_TOKEN` e
  `TELEGRAM_CHAT_ID` para enviar — sem eles use `--no-send`; `JINA_API_KEY` e
  `EXAMINE_TOKEN` são opcionais.
- `data/` guarda `data/<AAAA-MM-DD>/<mercado>.pdf`, `raw/` (originais), `precos/*.csv|json`,
  `run.log` (espelho do terminal de cada execução), `state.json` e `historico.sqlite`
  (índice dos CSVs, descartável: `jornaleiro historico --reindex` reconstrói, `--produto`/
  `--quedas` consultam). Rodar `run` no mesmo dia sobrescreve o PDF e limpa os brutos do
  mercado antes de regravar. Retenção: `jornaleiro limpar --dias 30 [--dry-run]` apaga
  coletas antigas.
- CI: `.github/workflows/jornaleiro.yml` roda `jornaleiro run` diariamente (07:00 e 19:00
  em America/Sao_Paulo; o 2º run do dia só reenvia com encarte novo) e por
  `workflow_dispatch` (`forcar` reenvia; `sem_envio` testa sem Telegram). O
  `data/state.json` do CI vive no branch `estado` (restaurado e commitado pelo próprio
  workflow) e os secrets no environment `producao` (criado no primeiro run; restringir as
  deployment branches à `main` exige admin).
- CI: o `main` só aceita PR (squash, histórico linear) com resultado do CodeQL
  (`.github/workflows/codeql.yml`, PR/push/semanal); `.github/workflows/testes.yml` roda o
  pytest em PR/push. A ruleset "protect default branch" tem a regra *Restrict updates*
  com bypass vazio (quem não é admin recebe `current_user_can_bypass: never`): ela
  bloqueia até o merge de PR (`Cannot update this protected ref`) — mergear na `main`
  exige admin do repositório. A regra de cobertura da mesma ruleset fica inerte sem o
  GitHub Code Quality (pago; enquanto isso o upload de Cobertura XML responde 404).

## Arquitetura

- `src/jornaleiro/cli.py` — entrypoint `jornaleiro`
  (`run|precos|site-precos|render|examine-probe|historico|limpar`), orquestração
  (`cmd_run` → `publish`), frescor/anti-duplicidade dos envios (sha em `state.json`) e
  resumo/captions do Telegram.
- `src/jornaleiro/markets/<chave>.py` — um módulo por mercado com `KEY`, `LABEL` e
  `fetch(ctx, cfg) -> MarketResult`, registrados em `markets/__init__.py`
  (`REGISTRY`/`ORDER`). `safe_fetch` impede que um mercado derrube os outros. Mercado novo =
  módulo + registro + seção `[markets.<chave>]` no `config.toml`.
- `model.py` (Asset/MarketResult/MarketCfg/Context), `compose.py` (assets → PDF único em A4),
  `comprimir.py`, `precos.py` (camada de texto + OCR + leitura por coordenadas do Atacadão),
  `site.py` (GraphQL do Examine), `historico.py` (SQLite derivado dos CSVs e quedas),
  `notify.py` (Telegram), `render.py` (Playwright com fallback jina), `state.py`.
- Configuração em `config.toml` (URLs, flags por mercado, OCR, compressão);
  `--config`/`--only`/`--renderer`/`--data-dir` ajustam por execução.
- `run` não aborta por mercado: sai `0` mesmo com falha parcial, `1` se nenhum PDF sair ou
  todos falharem, `2` para erro de config.
- `.github/workflows/jornaleiro.yml` — coleta diária (cron/dispatch), restauração/commit
  do `state.json` no branch `estado`; sem artifacts nem binários versionados.

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
- Atacadão: preços e nomes são lidos **por coordenadas** (`precos._MERCADOS_COLUNAS`).
  O corte entre dois cards empilhados não é um vão fixo — o bloco de nome do card decide
  (vãos de ~30–64 px aparecem dentro do card e na fronteira). Mexeu na segmentação? Rode
  `jornaleiro precos --dia <dia> --only atacadao` num dia com brutos em `data/` e confira os
  cards de 3 preços e os `produto` vazios; os testes sintéticos são em `tests/test_precos.py`.
- O banco `data/historico.sqlite` é derivado dos CSVs: nunca commitar (fica em `data/`,
  fora do git) e o `run` só o atualiza quando ele já existe; `--reindex` reconstrói tudo.
- `run` não reenvia encarte com o mesmo sha256 do último envio (`state.json` →
  `mercados.<chave>`), a menos que `--forcar`; avisos de frescor (encarte vencido, queda
  suspeita de preços) aparecem no resumo sem abortar nada.
- O `data/state.json` do CI vive no branch `estado` (só JSON): rodar local e CI em paralelo
  separa os estados e duplica envios — prefira o CI no dia a dia e use `--no-send`
  localmente, ou sincronize (README, "Rodando também na máquina").
- Segredos do CI: só no environment `producao` (a restrição de deployment branch à `main`
  exige admin e pode não estar aplicada); o workflow usa apenas o `GITHUB_TOKEN` com
  `contents: write` (branch `estado`). `.env` e `data/` nunca entram no git — sem LFS.
- Examine sem `EXAMINE_TOKEN` cai no Instagram. A semente vem de `data/state.json`
  (`examine_last_post_url`/`examine_seen`): apague essas chaves para reavaliar posts antigos.
- Chromium e tesseract podem faltar na máquina sem quebrar o run: o renderer `auto` cai para
  o jina e o OCR ausente vira aviso no resumo (`precos: OCR indisponivel`). O tesseract é
  procurado no PATH e em `~/.local/share/tesseract` (ver `[precos]` e o README).
