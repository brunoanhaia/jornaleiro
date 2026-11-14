# Jornaleiro — encartes de mercados de Rio Claro → Telegram

Coleta os encartes ("jornais de ofertas") vigentes dos mercados **Assaí, Atacadão,
Covabra, Savegnago e Examine** na cidade de Rio Claro/SP, compila **um PDF por
mercado** e envia os PDFs por Telegram com uma mensagem-resumo. A execução é manual
(`jornaleiro run`) ou contínua em container (`jornaleiro serve`, com agendador interno,
duas vezes por dia — 07:00 e 19:00 — ver *Execução contínua em container*). O programa
não extrai texto nem preço dos encartes: o que sai é o PDF inteiro.

## Fontes

| Mercado | Fonte | Formato |
|---|---|---|
| Assaí (loja Rio Claro, `eid=24`/`nid=77`) | JSON `ofertas_assai.json` buscado **dentro** da página de ofertas (challenge Imperva), com fallback para HTTP direto (JSON, HTML e imagens) | JPEG por página |
| Atacadão (loja 638, `rio-claro`) | API pública `api-middleware-flyer-services/api/v2/Store/city` → `urlFinalDocument` | PDF por folheto |
| Covabra | HTML SSR de `/jornal-de-ofertas` → card da cidade → PDF no Google Drive | PDF |
| Savegnago | `imagens.savegnagoonline.com.br/jornal-semanal-app/Rio_Claro.pdf` | PDF (maior validade impressa no encarte — o CDN segue servindo o encarte antigo depois de vencer) |
| Examine | jornal oficial do site (`pamphlets`, com `EXAMINE_TOKEN`) e, sem token, post público do Instagram `@examinesupermercados` | JPEG por página |

## Requisitos

- Python 3.11+, um bot do Telegram e o `chat_id` de destino
- Nada de navegador: as páginas que precisam de JS vão pelo `r.jina.ai` (HTTP)

Dependências de execução (todas usadas, nenhuma só de conveniência):

| Pacote | Versão mínima | Para quê |
|---|---|---|
| `httpx` | 0.28.1 | cliente HTTP dos mercados, do `r.jina.ai` e da API do Telegram |
| `pypdf` | 7.1.0 | ler/remontar os PDFs dos encartes (validade do Savegnago, páginas em A4) |
| `pypdfium2` | 5.15.2 | rasterizar as páginas no modo `forte` da compressão |
| `img2pdf` | 0.6.3 | montar página A4 a partir de imagem e layout das páginas de PDF |
| `pikepdf` | 10.18.1 | reencodar JPEG/achatar máscara CMYK ao comprimir |
| `pillow` | 13.0.0 | medir imagem e converter para JPEG na compressão; `examine-probe` |
| `python-dotenv` | 1.2.4 | carregar o `.env` em todo comando |

Dev: `pytest` (9.2+) — os testes não pedem nada além disso e não acessam a rede.

## Instalação

```bash
cd ~/workspace/jornaleiro
python3 -m venv .venv                     # se faltar ensurepip: apt install python3-venv
.venv/bin/pip install -e ".[dev]"
```

O caminho de produção não precisa de nada disso: a imagem publicada no GHCR já tem tudo
(`docker compose pull`) e monta o `data/` da máquina no container (uid 1000, o usuário
`app` da imagem) — **198 MB em disco / 74 MB de pull**, sem Chromium. Se o `data/` não for
gravável por esse uid, o run falha; `sudo chown -R 1000:1000 data` resolve (ou fixe
`user:` no `docker-compose.yml`).

## Bot do Telegram

1. Fale com [@BotFather](https://t.me/BotFather), crie o bot e guarde o token.
2. Envie qualquer mensagem para o bot (ou adicione-o ao grupo e mande uma mensagem lá).
3. Descubra o `chat_id`:

```bash
curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | grep -o '"chat":{"id":-\?[0-9]*'
```

4. Copie `.env.example` para `.env` e preencha:

```
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=-1001234567890
```

`JINA_API_KEY` é opcional (só para o renderizador `jina`), e `EXAMINE_TOKEN` é o Bearer da
conta do clube Examine — com ele o encarte do Examine vem do jornal oficial do site
(`pamphlets`) em vez do Instagram, veja *Preços do site do Examine*.

## Uso

```bash
# coleta, compila e envia
.venv/bin/jornaleiro run

# apenas gera os PDFs (não precisa de token/chat_id)
.venv/bin/jornaleiro run --no-send

# só alguns mercados, e/ou forçando um renderizador
.venv/bin/jornaleiro run --only assai,covabra --renderer jina

# depurar o renderizador (imprime os primeiros 2000 caracteres do texto renderizado)
.venv/bin/jornaleiro render "https://www.assai.com.br/sites/default/files/static/ofertas_assai.json"

# depurar a descoberta do post do Examine (semente, candidatos, legenda, imagem)
.venv/bin/jornaleiro examine-probe
```

```bash
# agenda interna (container): roda nos horarios do config.toml e atualiza data/agenda.json
.venv/bin/jornaleiro serve
.venv/bin/jornaleiro serve --agora --no-send   # uma execucao agora, sem Telegram
.venv/bin/jornaleiro serve --verificar         # healthcheck: 0 = agenda em dia, 1 = parada
```

Opções de `run`: `--only k1,k2`, `--renderer auto|jina`, `--no-send`,
`--sem-comprimir`, `--forcar` (reenvia mesmo com o encarte idêntico ao último envio),
`--data-dir DIR`, `--config ARQUIVO`. Mercados e URLs ficam em `config.toml`, procurado
nesta ordem: `--config`, `$JORNALEIRO_CONFIG`, `./config.toml` e a raiz do repositório; um
`data_dir` relativo no config é resolvido ao lado dele. Tudo roda igual como
`python -m jornaleiro ...`.

Saída: `data/<AAAA-MM-DD>/<mercado>.pdf` (um por mercado, sobrescrito se rodar duas
vezes no mesmo dia) e os arquivos brutos em `data/<AAAA-MM-DD>/raw/`. O `run` também
espelha o terminal em `data/<AAAA-MM-DD>/run.log`, com um cabeçalho por execução
(o arquivo é acrescentado, não sobrescrito).

Códigos de saída: `0` mesmo com um mercado falhando, `1` se **todos** os mercados
selecionados falharem (ou nenhum PDF sair), `2` para erro de configuração
(token/chat_id ausente ou mercado desconhecido).

Antes de enviar, o `run` confere o `data/state.json`: se os brutos de um mercado têm o
mesmo sha256 do último envio (`mercados.<chave>`), o PDF daquele mercado é pulado e a
linha do resumo ganha `AVISO: nao reenviado: igual ao de 15/10` (`--forcar` reenvia de
qualquer jeito). O outro aviso é `encarte vencido em DD/MM` (a validade terminou antes de
hoje). Nenhum aviso aborta o run.

A mensagem enviada traz uma linha por mercado — com o tamanho e a validade — e o resumo
de falhas:

```
Encartes Rio Claro - 15/10/2026
Assaí Atacadista - 8 pags - Preços válidos para 15/10/2026
Atacadão - 6 folhetos - 12/10 a 19/10
Covabra - 4 pags - 15/10 - 21/10
Savegnago - 4 pags - válido até 17/10/2026
Examine - 1 pag - 15/10 a 18/10/2026
Falhas: nenhuma
```

Cada PDF vai como documento com a legenda `<mercado> - <validade> - <n> pags`
(ou `<n> folhetos`, no caso do Atacadão). Limites respeitados: documento ≤ 50 MB (o
Atacadão para de acumular folhetos ao atingir `max_bytes`, 40 MiB, no `config.toml`)
e legenda ≤ 1024 caracteres.

## Renderizador

Não há navegador no projeto. Os mercados usam HTTP direto e, quando a página precisa de
JavaScript (ou responde ao cliente simples com o challenge Imperva, caso do Assaí), o
fallback é o **[r.jina.ai](https://r.jina.ai)**, que renderiza do lado do servidor e
devolve o DOM em markdown — uma chamada HTTP comum.

`renderer = "auto"` (o padrão) e `--renderer jina` fazem a mesma coisa: usam o jina.
`JINA_API_KEY` no `.env` é opcional (aumenta o limite do serviço). Quem usa o
renderizador é só o Assaí (JSON de ofertas e, se o HTTP der 403, a página) e o Examine
**sem** `EXAMINE_TOKEN` (o post do Instagram); os outros três mercados são HTTP simples.

Medido em 14/11/2026: o HTTP direto do Assaí devolveu `200` (108 KB, `Last-Modified` do
dia) e as imagens vieram sem challenge, então o caminho normal nem chega no jina; o jina
também serviu o JSON do Assaí (108 KB com `ofertas`) e a legenda do post do Instagram
quando exercitado como fallback. A ordem das tentativas no Assaí é **HTTP primeiro,
renderizador depois**.

Com o navegador fora, a imagem do container caiu de ~410 MB para ~80 MB de transferência
e o run não gasta mais os 20–30 s de subir o Chromium no Assaí.

## Compressão e tamanho das páginas

Todas as páginas saem **em A4 retrato** (imagens via `layout_fun` do img2pdf, páginas de
PDF escaladas e centralizadas com `pypdf.Transformation`). Antes disso o encarte do Assaí
misturava página de 92×140 pt com outra de 2392×3632 pt, e o do Atacadão tinha três
alturas diferentes.

`[comprimir] modo` escolhe a compressão:

| modo | como | resultado em 16/10/2026 |
|---|---|---|
| `forte` (padrão) | rasteriza cada página a `dpi` (150), JPEG `qualidade` (60) | Assaí 8,92→1,65 MB, Atacadão 26,45→4,57 MB, Covabra 4,03→1,09 MB, Savegnago 3,56→1,07 MB, Examine 7,94→1,99 MB (−70% a −83%) |
| `padrao` | reencoda as imagens embutidas, achata máscara suave no branco, `largura_max` 1400 | Assaí 8,92→1,62 MB, Atacadão 26,45→13,4 MB, Covabra →2,04 MB (−34% a −82%) |

`dpi = 110` no modo forte deixa mais ~15% menor (texto um pouco mais suave); `--sem-comprimir`
desliga tudo. O modo `forte` perde a camada de texto (a página vira imagem) — irrelevante
aqui, porque o PDF é para leitura, não para extrair dados. Os brutos de `data/<dia>/raw/`
são limpos a cada coleta para não misturar folhetos de execuções anteriores.

### Encarte oficial do Examine (jornal do site)

Com `EXAMINE_TOKEN` no `.env` (Bearer da conta do clube), `jornaleiro run` pega o encarte do
Examine pela consulta `pamphlets { file id title }` da mesma API — é o "Jornal de
Ofertas" oficial, página por página, agrupado por campanha (em 16/10/2026: 9 páginas,
`Show de Economia 💚` com 5, mais banners de campanha). O PDF do Examine passa a ter
essas páginas, com os títulos no campo `note`. Sem token — ou se a consulta falhar — o
mercado cai no caminho antigo do Instagram, que continua no código.

`pamphlets` só existe no endpoint principal (`site_graphql_jornal`, padrão
`www.crescevendas.com/graphql`); o `Origin` enviado é o de `site_url`. Apontar para o
endpoint do e-commerce dá `Field 'pamphlets' doesn't exist on type 'Query'` — já aconteceu.

## Estado e a semente do Examine

`data/state.json` guarda o último post do Examine processado
(`examine_last_post_url`) e os shortcodes já vistos (`examine_seen`). A descoberta
parte da página desse post, pega os shortcodes recentes, filtra pelas legendas com
`Ofertas válidas` **e** `lojas de Rio Claro` e escolhe o post mais novo. Depois disso
o post passa a ser a nova semente, então cada execução só coleta encartes novos.

Também ficam lá, por mercado (`mercados.<chave>`), o sha256 dos brutos do último envio,
o dia e o flag `enviado` — é o que o `run` usa para não reenviar o mesmo encarte (ver
"Uso"). A gravação é atômica (arquivo temporário + `os.replace`), então um
`Ctrl-C` no meio não deixa o JSON pela metade.

No container o arquivo vive no volume (`./data`), então é o único estado: não há branch
nem cópia no CI — veja *Execução contínua em container*. O `data/agenda.json` (ao lado
dele) guarda `ultima`, `proxima`, `falhas_seguidas` e o batimento `atualizado_em` do
agendador.

Para forçar o Examine a reavaliar posts antigos, apague as duas chaves (ou o
`data/state.json`) antes de rodar.

## Execução contínua em container (agenda interna)

`docker compose up -d` sobe um processo só — a imagem publicada no GHCR pelo workflow
`Imagem` (`ghcr.io/brunoanhaia/jornaleiro:latest`, mais uma tag por commit) —,
`jornaleiro serve`, que roda o `run` nos horários de `[agenda] horarios` (padrão 07:00 e
19:00, America/Sao_Paulo).
Não há cron no container: o loop grava batimentos em `data/agenda.json`, dispara o run
como subprocesso e faz *catch-up* — se o container subir 07:40, ainda executa o slot das
07:00 (`tolerancia_min = 90`); às 12:00 não executa mais. O segundo run do dia só envia
de novo se aparecer encarte novo, pelo mesmo sha256 do `state.json`.

```bash
cp .env.example .env            # preencha TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID
docker compose pull             # baixa ghcr.io/brunoanhaia/jornaleiro:latest
docker compose up -d
docker compose logs -f          # procura "[agenda] proxima execucao: ..."
docker compose ps               # coluna STATUS mostra o healthcheck (healthy)
```

Se o pacote do GHCR estiver **privado** (repositório privado), autentique antes do `pull`
com um token de leitura de pacotes: `echo "$TOKEN" | docker login ghcr.io -u <usuario>
--password-stdin`. Com repositório público o pacote herda a visibilidade e o login é
desnecessário. Para construir na máquina em vez de puxar (desenvolvimento), o
`docker-compose.yml` mantém `build: .`: `docker compose up -d --build` gera a mesma tag.

### Isolamento do container

O serviço roda com o mínimo de privilégios, e nada além disso:

| Item | Configuração | Efeito |
|---|---|---|
| Usuário | `USER app` (uid 1000) na imagem | nenhum processo roda como root |
| Rootfs | `read_only: true` | nada é gravado fora dos volumes; só `./data` e `/tmp` |
| `/tmp` | `tmpfs: /tmp:size=512m,mode=1777` | área temporária em memória (Pillow/img2pdf) |
| Capabilities | `cap_drop: [ALL]` | nenhuma capability (não precisa de porta <1024, raw socket etc.) |
| Escalada | `security_opt: no-new-privileges:true` | setuid/setgid não eleva privilégio |
| Volumes | só `./data:/app/data` | nada do host além do diretório de dados |
| Rede/pid | padrão do Compose | sem `privileged`, `network_mode: host` nem socket do Docker |
| Segredos | `env_file: .env` | tokens do Telegram no ambiente do processo, nunca na imagem |

O workflow `Imagem` também é escopo mínimo: `contents: read` no workflow e
`packages: write` só no job, usando o `GITHUB_TOKEN` do run (sem PAT), sem gatilho de
`pull_request` — código de PR não recebe token de escrita.

Sem esperar o horário, para testar a instalação:

```bash
docker compose run --rm jornaleiro serve --agora --no-send   # coleta sem Telegram
docker compose run --rm jornaleiro serve --agora             # executa agora e envia
```

O `data/` da máquina é montado em `/app/data`: PDFs, `raw/`, `run.log`, `state.json` e
`agenda.json` ficam nele (nada binário vai para o git). Rodar o
`run` na máquina contra o mesmo `data/` compartilha o estado — use `--no-send` para
depurar sem duplicar envio no grupo.

### Agenda, saúde e falhas

`data/agenda.json` tem `ultima` (`inicio`, `fim`, `codigo`), `proxima` e
`falhas_seguidas`, além do batimento `atualizado_em` — regravado a cada `batida_s` (30 s)
durante um run longo. O healthcheck do Compose roda `jornaleiro serve --verificar` e
reprova se o batimento estiver mais velho que `saude_janela_s` (300 s) ou se houver
`falhas_limite` (3) execuções seguidas com falha; Docker não reinicia container
*unhealthy* sozinho, então a saúde aparece em `docker compose ps`.

Quando o run sai com código != 0, a agenda manda uma mensagem no Telegram com o horário,
o código, a duração, o caminho do `data/<dia>/run.log` e a próxima execução:

```
Jornaleiro: execucao das 16/11 07:00 falhou (codigo 1) em 412s.
Log: /app/data/2026-11-16/run.log
Proxima: 16/11 19:00
```

SIGTERM/SIGINT (parar o container, `Ctrl-C`) encerram o loop sem aviso de falha e sem
contar falha no estado. Com `--no-send` o aviso de falha sai só no stderr — teste local
não mexe no Telegram.

### Retenção automática de 15 dias

Ao fim de cada `run`, o `data/` é podado em `[retencao] dias` (padrão 15, contando hoje):
as pastas `data/<AAAA-MM-DD>/` mais antigas saem e o SQLite é reindexado. `dias = 0`
desliga a poda. Para conferir/apagar à mão antes, `jornaleiro limpar` (usa o valor do
config) e `--dias N`/`--dry-run`.

### Configuração por ambiente

Qualquer chave de qualquer seção aceita `JORNALEIRO__SECAO__CHAVE=valor`; cada segmento
vira um nível do `config.toml` e o valor é lido como TOML (o que não for TOML entra como
string crua). A precedência é CLI (`--horarios`) > ambiente > `config.toml` > padrão:

```bash
JORNALEIRO__AGENDA__HORARIOS='["08:00","20:00"]'
JORNALEIRO__RETENCAO__DIAS=15
JORNALEIRO__RENDERER=jina
JORNALEIRO__MARKETS__ASSAI__ENABLED=false
```

`JORNALEIRO_CONFIG` (caminho do config) usa um underscore só e não entra no esquema. O ritmo do healthcheck é do
Docker, não do processo: `JORNALEIRO_HEALTHCHECK_INTERVAL`, `..._TIMEOUT`, `..._RETRIES`
e `..._START_PERIOD` são interpolados pelo Compose a partir do `.env` ou do ambiente
(padrões `2m`, `60s`, `2` e `3m`).

## Testes

```bash
.venv/bin/python -m pytest -q
```

São **104 testes** com fixtures recortadas das respostas reais (JSON do Assaí, API do
Atacadão, HTML do Covabra, `pamphlets` do Examine e os dois renders do Instagram) e não
acessam a rede. Cobrem os parsers de mercado, o renderizador (jina com `http` falso), o
Telegram, o estado, a composição/compressão dos PDFs, a operação (resolução do config,
`limpar`, poda automática, `run` com mercados/renderer falsos, resumo/avisos) e a agenda
com relógio/dormir falsos (`devida`/catch-up, batimento, falhas seguidas, overrides de
ambiente, `serve` sem Telegram com `--no-send`).

## Licença

MIT — o texto completo está em [`LICENSE`](LICENSE).
