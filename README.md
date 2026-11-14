# Jornaleiro — encartes de mercados de Rio Claro → Telegram

Coleta os encartes ("jornais de ofertas") vigentes do **Assaí, Atacadão, Covabra,
Savegnago e Examine** em Rio Claro/SP, monta **um PDF por mercado** e envia os PDFs pelo
Telegram com uma mensagem-resumo. Não extrai texto nem preço: o produto é o PDF.

Execução manual (`jornaleiro run`) ou contínua em container (`jornaleiro serve`, com
agenda interna às 07:00 e 19:00).

## Fontes

| Mercado | Como o encarte é obtido | Formato |
|---|---|---|
| Assaí (Loja Rio Claro, `eid=24`/`nid=77`) | JSON `ofertas_assai.json` com `?v=<epoch>` (escapa do CDN congelado); atrás do challenge Imperva, com fallback HTTP e `r.jina.ai` | JPEG por página |
| Atacadão (loja 638, `rio-claro`) | API `api-middleware-flyer-services/api/v2/Store/city` → `urlFinalDocument` | PDF por folheto |
| Covabra | HTML de `/jornal-de-ofertas` → card da cidade → PDF no Google Drive | PDF |
| Savegnago | `imagens.savegnagoonline.com.br/jornal-semanal-app/Rio_Claro.pdf` | PDF |
| Examine | jornal oficial (`pamphlets`, precisa de `EXAMINE_TOKEN`) ou, sem token, post público do Instagram `@examinesupermercados` | JPEG por página |

## Instalação

```bash
python3 -m venv .venv                 # se faltar ensurepip: apt install python3-venv
.venv/bin/pip install -e ".[dev]"     # runtime: httpx, pypdf, pypdfium2, img2pdf, pikepdf, pillow, python-dotenv
```

Não há navegador: páginas que exigem JavaScript vão pelo `r.jina.ai` (HTTP).

## Bot do Telegram

1. Crie o bot no [@BotFather](https://t.me/BotFather) e mande uma mensagem para ele.
2. Descubra o destino:
   `curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | grep -o '"chat":{"id":-\?[0-9]*'`
3. `cp .env.example .env` e preencha `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`.

Opcionais no `.env`: `EXAMINE_TOKEN` (Bearer do clube; sem ele o Examine cai no Instagram)
e `JINA_API_KEY` (aumenta o limite do `r.jina.ai`).

## Uso

```bash
.venv/bin/jornaleiro run                      # coleta, compila e envia
.venv/bin/jornaleiro run --no-send            # só gera os PDFs (não precisa de token)
.venv/bin/jornaleiro run --only assai,covabra # alguns mercados
.venv/bin/jornaleiro run --forcar             # reenvia mesmo com encarte idêntico
.venv/bin/jornaleiro limpar [--dias N] [--dry-run]   # retenção manual (padrão: [retencao] dias)
.venv/bin/jornaleiro serve --agora --no-send  # uma execução agora, sem Telegram
.venv/bin/jornaleiro render <url>             # debug: texto renderizado da URL
.venv/bin/jornaleiro examine-probe            # debug: descoberta do post do Examine
```

`run` aceita `--renderer auto|jina`, `--sem-comprimir`, `--data-dir DIR`, `--config ARQUIVO`.
O config é procurado em `--config`, `$JORNALEIRO_CONFIG`, `./config.toml` e na raiz do
repositório; `data_dir` relativo é resolvido ao lado do config. Tudo também roda como
`python -m jornaleiro ...`.

Saída em `data/<dia>/` (dia no formato `2026-11-14`): `<mercado>.pdf`, `raw/` com os
arquivos originais e `run.log` com o espelho do terminal (acrescentado a cada execução).

Códigos de saída: `0` mesmo com um mercado falhando, `1` se nenhum PDF saiu (ou todos
falharam), `2` para erro de configuração.

Antes de enviar, o `run` compara o sha256 dos brutos com `data/state.json`
(`mercados.<chave>`): encarte idêntico ao último envio não vai de novo e a linha do resumo
ganha `AVISO: nao reenviado: igual ao de 15/10` (`--forcar` ignora). Outro aviso:
`encarte vencido em DD/MM`. Nenhum aviso aborta o run.

Mensagem enviada (uma linha por mercado, depois os PDFs com legenda
`<mercado> - <validade> - <n> pags` ou `<n> folhetos`):

```
Encartes Rio Claro - 14/11/2026
Assaí Atacadista - 5 pags - Preços válidos de 13/11/2026 até 15/11/2026
Atacadão - 5 folhetos - 09/11 a 16/11
Covabra - 4 pags - 12/11 - 18/11
Savegnago - 4 pags - válido até 15/11/2026
Examine - 29 pags - jornal oficial do site (29 pags: ...)
Falhas: nenhuma
```

Limites do Telegram: documento ≤ 50 MB (o Atacadão para de acumular folhetos em
`max_bytes`, 40 MiB no config) e legenda ≤ 1024 caracteres.

## Container (agenda interna)

A imagem é publicada no GHCR pelo workflow `Imagem` (`ghcr.io/brunoanhaia/jornaleiro:latest`
e uma tag por commit). No host:

```bash
cp .env.example .env         # tokens do Telegram
docker compose pull          # ou `up -d --build` para construir na máquina
docker compose up -d
docker compose logs -f       # "[agenda] proxima execucao: ..."
docker compose ps            # healthcheck (healthy)
```

O container roda `jornaleiro serve`: dorme, dispara o `run` nos horários de
`[agenda] horarios` (07:00 e 19:00, America/Sao_Paulo) e faz catch-up dentro de
`tolerancia_min` (subir 07:40 ainda executa o slot das 07:00; às 12:00 não). O estado fica
em `data/agenda.json` (`ultima`, `proxima`, `falhas_seguidas` e o batimento
`atualizado_em`); `serve --verificar` reprova (saída 1) se o batimento estiver mais velho
que `saude_janela_s` ou se houver `falhas_limite` falhas seguidas. Run com código != 0
vira mensagem no Telegram com o caminho do `data/<dia>/run.log`.

O `data/` da máquina é o único estado: PDFs, `raw/`, `state.json` e `agenda.json` (nada
binário no git). O dono precisa ser o uid 1000 (usuário `app` da imagem); caso contrário o
run falha (`sudo chown -R 1000:1000 data`). Rodar `run` local contra o mesmo `data/`
compartilha o estado — use `--no-send` para não duplicar envio.

Isolamento do serviço no compose: `USER app` (uid 1000), `read_only` com `tmpfs` em `/tmp`,
`cap_drop: [ALL]`, `no-new-privileges`, único volume `./data` (sem socket do Docker, sem
rede do host) e `env_file: .env` para os segredos. A imagem tem ~198 MB (74 MB de pull).

`run` poda `data/` sozinho em `[retencao] dias` (15, contando hoje; `0` desliga) ao final
de cada execução; `jornaleiro limpar` faz o mesmo à mão.

## Configuração

`config.toml`: `renderer`, `data_dir`, `[comprimir]` (compressão dos PDFs; `modo = "forte"`
rasteriza as páginas), `[agenda]`, `[retencao]` e `[markets.<chave>]` (flags e URLs de cada
mercado).

Qualquer chave aceita ambiente na forma `JORNALEIRO__SECAO__CHAVE=valor` (valor lido como
TOML; o que não for TOML entra cru), com precedência CLI > ambiente > `config.toml`:

```bash
JORNALEIRO__AGENDA__HORARIOS='["08:00","20:00"]'
JORNALEIRO__RETENCAO__DIAS=7
JORNALEIRO__RENDERER=jina
JORNALEIRO__MARKETS__ASSAI__ENABLED=false
```

`JORNALEIRO_CONFIG` (caminho do config) usa um underscore só e fica fora do esquema. As
`JORNALEIRO_HEALTHCHECK_*` (interval/timeout/retries/start_period) são do Compose, não do
processo.

## Estado e semente do Examine

`data/state.json` guarda, por mercado, o sha256/dia do último envio e o flag `enviado`
(anti-duplicidade), e a semente do Instagram (`examine_last_post_url`/`examine_seen`) — sem
token, só posts novos são avaliados. Apague essas duas chaves (ou o arquivo) para reavaliar
posts antigos. A gravação é atômica.

## Testes e CI

```bash
.venv/bin/python -m pytest -q   # 104 testes, sem rede (fixtures inline e fakes de http)
```

`pytest` e CodeQL rodam em PR/push (`.github/workflows/testes.yml` e `codeql.yml`); o
`main` só aceita PR com squash. `imagem.yml` constrói e publica a imagem no GHCR em push na
`main` (escopo mínimo: `contents: read` no workflow, `packages: write` só no job, sem
gatilho de PR).

## Licença

MIT — texto completo em [`LICENSE`](LICENSE).
