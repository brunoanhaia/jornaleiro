# AGENTS.md

CLI em Python >= 3.11 (argparse, sem framework) que coleta os encartes de 5 mercados de
Rio Claro/SP, monta um PDF por mercado e envia os PDFs por Telegram. Execução manual
local ou contínua em container (`jornaleiro serve`, agenda interna às 07:00 e 19:00); sem
API ou front-end. **Não há extração de texto/preço dos encartes** — o produto é o PDF.
Nenhum binário é versionado: PDFs, `raw/` e `run.log` ficam em `data/` (fora do git) —
nada de LFS. Código, logs, legendas e testes são em pt-BR — mantenha o
idioma. Os commits seguem *Conventional Commits*: `tipo(escopo): resumo` em pt-BR (tipos
usados: `feat`, `fix`, `docs`, `test`, `chore`), com corpo curto explicando o porquê
quando ajudar.

`README.md` é a fonte de verdade do comportamento (curto e factual). Leia a seção
relevante antes de mexer em parsers, compressão ou container, e atualize-o junto.

## Comandos

- venv local em `.venv/` com o pacote instalado editable: mudanças em `src/` valem sem
  reinstalar; dependência nova pede `.venv/bin/pip install -e ".[dev]"`.
- Testes: `.venv/bin/python -m pytest -q`. Um teste/arquivo:
  `.venv/bin/python -m pytest tests/test_parsers.py::test_nome -q`.
- Os testes não acessam a rede (fixtures inline recortadas de respostas reais, renderer
  falso, `monkeypatch` de `http`); escreva testes novos no mesmo estilo.
- Dependências (todas usadas, ver a tabela no README): httpx, pypdf, pypdfium2, img2pdf,
  pikepdf, pillow, python-dotenv; `pytest` em `[dev]`. Nada de navegador/Playwright — o
  fallback de página com JS é o `r.jina.ai` por HTTP.
- Não há lint, formatador nem typecheck configurados; o pytest é a única verificação
  local. O Codacy roda o Prospector com `.prospector.yaml` (convenção D212: resumo na
  primeira linha da docstring), então docstrings multilinha novas devem seguir D212.
- Debug: `.venv/bin/jornaleiro render <url>` imprime o texto renderizado;
  `.venv/bin/jornaleiro examine-probe` mostra a descoberta do post do Instagram.
- Todo comando chama `load_dotenv()`: `.env` (não versionado) com `TELEGRAM_BOT_TOKEN` e
  `TELEGRAM_CHAT_ID` para enviar — sem eles use `--no-send`; `JINA_API_KEY` e
  `EXAMINE_TOKEN` são opcionais.
- `data/` guarda `data/<dia>/<mercado>.pdf` (`<dia>` = `2026-11-14`), `raw/` (originais), `run.log` (espelho
  do terminal de cada execução), `state.json` e `agenda.json`. Rodar `run` no mesmo dia
  sobrescreve o PDF e limpa os brutos do mercado antes de regravar. Retenção: o `run` poda
  sozinho em `[retencao] dias` (15, contando hoje; `0` desliga); `jornaleiro limpar
  [--dias N] [--dry-run]` é manual e, sem `--dias`, usa o config.
- Agenda no container: `jornaleiro serve` roda o `run` nos horários de `[agenda]`
  (`horarios`, `tolerancia_min` = catch-up de 90 min) e grava `data/agenda.json`
  (`ultima`, `proxima`, `falhas_seguidas`, batimento `atualizado_em` a cada `batida_s`).
  `serve --agora` roda uma vez e sai; `serve --verificar` é o healthcheck (0 = em dia;
  1 = batimento velho ou `falhas_limite` falhas seguidas). Falha do run (código != 0)
  vira mensagem no Telegram com o caminho do `data/<dia>/run.log`.
- Configuração por ambiente: qualquer chave aceita `JORNALEIRO__SECAO__CHAVE=valor`
  (valor lido como Tom's Obvious Minimal Language (TOML), string crua se não for
  TOML), aplicado em `load_config` com
  precedência CLI > ambiente > `config.toml`; `JORNALEIRO_CONFIG` e
  fica fora do esquema.
  As `JORNALEIRO_HEALTHCHECK_*` são do Compose (intervalo/timeout/retries/start_period),
  não do processo.
- CI: `.github/workflows/imagem.yml` constrói e publica a imagem no GHCR
  (`ghcr.io/brunoanhaia/jornaleiro:latest` + tag por commit) em push na `main` e por
  `workflow_dispatch`; escopo mínimo (`contents: read` no workflow, `packages: write` só
  no job, `GITHUB_TOKEN`, sem gatilho de PR). O `docker-compose.yml` usa essa imagem
  (`build: .` fica para build local com `--build`).
- CI: o `main` só aceita PR (squash, histórico linear) com resultado do CodeQL
  (`.github/workflows/codeql.yml`, PR/push/semanal); `.github/workflows/testes.yml` roda o
  pytest em PR/push. A ruleset "protect default branch" tem a regra *Restrict updates*
  com bypass vazio (quem não é admin recebe `current_user_can_bypass: never`): ela
  bloqueia até o merge de PR (`Cannot update this protected ref`) — mergear na `main`
  exige admin do repositório. A regra de cobertura da mesma ruleset fica inerte sem o
  GitHub Code Quality (pago; enquanto isso o upload de Cobertura XML responde 404).

## Arquitetura

- `src/jornaleiro/cli.py` — entrypoint `jornaleiro`
  (`run|render|examine-probe|limpar|serve`), orquestração (`cmd_run` → `publish`),
  frescor/anti-duplicidade dos envios (sha em `state.json`), poda de `data/`
  (`limpar_coletas`/`config_retencao`), override de ambiente (`_override_ambiente`) e
  resumo/captions do Telegram.
- `src/jornaleiro/agenda.py` — agendador sem cron: `parametros`/`horarios` (config +
  ambiente), `devida`/`proxima_execucao` (catch-up), `Agenda` (loop + batimento +
  `agenda.json`) e `instalar_sinais` (SIGTERM/SIGINT encerram sem aviso de falha).
- `src/jornaleiro/markets/<chave>.py` — um módulo por mercado com `KEY`, `LABEL` e
  `fetch(ctx, cfg) -> MarketResult`, registrados em `markets/__init__.py`
  (`REGISTRY`/`ORDER`). `safe_fetch` impede que um mercado derrube os outros. Mercado novo =
  módulo + registro + seção `[markets.<chave>]` no `config.toml`.
- `model.py` (Asset/MarketResult/MarketCfg/Context), `compose.py` (assets → PDF único em A4),
  `comprimir.py`, `notify.py` (Telegram), `render.py` (r.jina.ai, sem navegador),
  `state.py`.
- Configuração em `config.toml` (URLs, flags por mercado, compressão, agenda, retenção);
  `--config`/`--only`/`--renderer`/`--data-dir` ajustam por execução.
- `run` não aborta por mercado: sai `0` mesmo com falha parcial, `1` se nenhum PDF sair ou
  todos falharem, `2` para erro de config.
- `Dockerfile`/`docker-compose.yml` — imagem `python:3.13-slim` + `tzdata` (sem
  navegador), usuário `app` (uid 1000), `./data` no volume e healthcheck
  `jornaleiro serve --verificar`. O compose endurece o container: `read_only`,
  `tmpfs /tmp`, `cap_drop` com todas as capabilities, `no-new-privileges`
  e só o volume de `data/`. O `data/` do host é o único estado (sem branch nem
  artifact).

## Armadilhas

- A compressão padrão (`modo = "forte"`) rasteriza as páginas e **apaga a camada de texto**:
  o PDF final é para leitura, não para extrair dados (o projeto não extrai).
- `pamphlets` (jornal oficial do Examine) só existe no endpoint `site_graphql_jornal`
  (`www.crescevendas.com/graphql`), com `Origin` de `site_url`; apontar para o do
  e-commerce dá `Field 'pamphlets' doesn't exist on type 'Query'`.
- Assaí: o JSON de ofertas está atrás do challenge Imperva — o caminho normal é dentro de
  uma página já carregada (`renderer.fetch_json_in_page`), com fallback para HTTP direto do
  JSON e da página de ofertas (`assai._json_texto`/`_offers_html`) quando o renderizador
  recebe 403. A URL leva `?v=<timestamp>` (`assai._uncached`) para escapar do CDN congelado
  por semanas. Se uma imagem der 403 no HTTP direto, `_baixar_imagem` tenta de novo pelo
  navegador (`renderer.fetch_bytes_in_page`), reaproveitando cookies/fingerprint do
  challenge. O erro final lista URL e as duas tentativas (`http:`/`renderer:`), para
  diagnosticar um 403 sem log completo.
- Atacadão: `validity` vem como meia-noite UTC com a data local do cliente — não converta
  fuso horário (a janela andaria um dia; ver docstring de `atacadao._bound`).
- `run` não reenvia encarte com o mesmo sha256 do último envio (`state.json` →
  `mercados.<chave>`), a menos que `--forcar`; o aviso de encarte vencido aparece no resumo
  sem abortar nada.
- O container e uma execução local apontando para o mesmo `data/` compartilham
  `state.json`/`agenda.json`: rodar os dois em paralelo duplica envios — use `--no-send`
  para depurar. O `data/` pertence ao uid 1000 (o `app` da imagem); sem permissão de
  escrita o run falha (`--verificar` continua respondendo pelo batimento). `.env` e
  `data/` nunca entram no git — sem LFS.
- Examine sem `EXAMINE_TOKEN` cai no Instagram. A semente vem de `data/state.json`
  (`examine_last_post_url`/`examine_seen`): apague essas chaves para reavaliar posts antigos.
- Sem navegador por decisão: o fallback de página com JS é o `r.jina.ai` (HTTP). No Assaí
  a ordem é **HTTP direto primeiro** e o renderizador depois — mexer nessa ordem sem medir
  volta a gastar chamadas do jina no caminho normal.