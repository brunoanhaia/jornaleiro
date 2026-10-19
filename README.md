# Jornaleiro — encartes de mercados de Rio Claro → Telegram

Coleta os encartes ("jornais de ofertas") vigentes dos mercados **Assaí, Atacadão,
Covabra, Savegnago e Examine** na cidade de Rio Claro/SP, compila **um PDF por
mercado**, lê os preços publicados nos encartes (e no catálogo do site do Examine)
e envia os PDFs e os CSVs por Telegram com uma mensagem-resumo. A execução é manual
(`jornaleiro run`) ou agendada no GitHub Actions, uma vez por dia (ver *Coleta diária no
GitHub Actions*); o SQLite é um índice derivado dos CSVs, não a fonte de verdade.

## Fontes

| Mercado | Fonte | Formato |
|---|---|---|
| Assaí (loja Rio Claro, `eid=24`/`nid=77`) | JSON `ofertas_assai.json` buscado **dentro** da página de ofertas (challenge Imperva) | JPEG por página |
| Atacadão (loja 638, `rio-claro`) | API pública `api-middleware-flyer-services/api/v2/Store/city` → `urlFinalDocument` | PDF por folheto |
| Covabra | HTML SSR de `/jornal-de-ofertas` → card da cidade → PDF no Google Drive | PDF |
| Savegnago | `imagens.savegnagoonline.com.br/jornal-semanal-app/Rio_Claro.pdf` | PDF (maior validade impressa no encarte — o CDN segue servindo o encarte antigo depois de vencer) |
| Examine | jornal oficial do site (`pamphlets`, com `EXAMINE_TOKEN`) e, sem token, post público do Instagram `@examinesupermercados` | JPEG por página |

## Requisitos

- Python 3.11+
- Chromium do Playwright (opcional: sem ele o programa usa o renderizador `jina`)
- Um bot do Telegram e o `chat_id` de destino

## Instalação

```bash
cd ~/workspace/jornaleiro
python3 -m venv .venv                     # se faltar ensurepip: apt install python3-venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/playwright install chromium
sudo .venv/bin/playwright install-deps chromium   # bibliotecas de sistema do Chromium
```

Se a máquina não tiver as bibliotecas de sistema e você não tiver root, veja
*Renderizador* abaixo (dá para rodar com `--renderer jina`, sem Chromium).

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
# le os precos dos PDFs que ja estao em data/<dia>/ (nao baixa nada)
.venv/bin/jornaleiro precos
.venv/bin/jornaleiro precos --only atacadao --json    # imprime os precos no stdout
.venv/bin/jornaleiro precos --dia 2026-10-15          # reprocessa um dia anterior

# le o catalogo do site do Examine (preco estruturado, sem OCR)
.venv/bin/jornaleiro site-precos
.venv/bin/jornaleiro site-precos --max-categorias 2   # varredura parcial
```

```bash
# retencao: apaga coletas de data/ mais velhas que 30 dias (--dry-run so lista)
.venv/bin/jornaleiro limpar --dias 30
.venv/bin/jornaleiro limpar --dias 30 --dry-run
```

```bash
# historico em SQLite, derivado dos CSVs (banco em data/historico.sqlite)
.venv/bin/jornaleiro historico                    # o que ja tem no banco
.venv/bin/jornaleiro historico --reindex          # reconstroi o banco a partir dos CSVs
.venv/bin/jornaleiro historico --produto arroz    # leituras recentes do produto
.venv/bin/jornaleiro historico --quedas           # variacoes de preco (menor do dia)
```

Opções de `run`: `--only k1,k2`, `--renderer auto|playwright|jina`, `--no-send`,
`--sem-comprimir`, `--sem-ocr`, `--sem-precos` (só os jornais: não lê nem envia preços),
`--forcar` (reenvia mesmo com o encarte idêntico ao último envio), `--data-dir DIR`,
`--config ARQUIVO`. Mercados e URLs ficam em `config.toml`, procurado
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
mesmo sha256 do último envio (`mercados.<chave>`), o PDF/CSV daquele mercado é pulado e a
linha do resumo ganha `AVISO: nao reenviado: igual ao de 15/10` (`--forcar` reenvia de
qualquer jeito). Outros avisos do resumo: `encarte vencido em DD/MM` (a validade
terminou antes de hoje) e `queda suspeita de precos` (menos da metade dos preços da
última leitura). Nenhum aviso aborta o run.

A mensagem enviada traz uma linha por mercado — com o tamanho, a validade e os preços
lidos — e o resumo de falhas:

```
Encartes Rio Claro - 15/10/2026
Assaí Atacadista - 8 pags - Preços válidos para 15/10/2026 | 12 itens/16 precos (OCR)
Atacadão - 6 folhetos - 12/10 a 19/10 | 256 itens/573 precos
Covabra - 4 pags - 15/10 - 21/10 | 169 itens/176 precos
Savegnago - 4 pags - válido até 17/10/2026 | 180 itens/261 precos
Examine - 1 pag - 15/10 a 18/10/2026 | OCR nao leu nenhum preco
Falhas: nenhuma

Quedas recentes (menor preco do item por dia):
-0% atacadao: Toalha de Papel Dadu Branca - Interfolha Pacote com 1000 unidades R$ 19.98 (15/10) -> R$ 19.90
```

(contagens remedidas em 18/10/2026, com os encartes de 15/10; o bloco de quedas aparece
quando há histórico — ver "Histórico de preços" — e vale entre as duas últimas leituras
de cada produto na janela de 30 dias.)

Cada PDF vai como documento com a legenda `<mercado> - <validade> - <n> pags`
(ou `<n> folhetos`, no caso do Atacadão); logo depois de cada PDF vai o CSV da leitura
de preços daquele mercado, com a legenda `<mercado> - <itens> itens/<precos> precos`.
Mercados sem preço lido (hoje o Examine) só mandam o PDF. Para enviar apenas os PDFs,
ponha `enviar = false` em `[precos]`. Limites respeitados: documento ≤ 50 MB (o
Atacadão para de acumular folhetos ao atingir `max_bytes`, 40 MiB, no `config.toml`)
e legenda ≤ 1024 caracteres.

## Renderizador

`renderer = "auto"` (o padrão) testa o Chromium do Playwright e, se ele não subir,
usa o **[r.jina.ai](https://r.jina.ai)** — um serviço que devolve o DOM já renderizado.
Os dois caminhos servem para as mesmas páginas; `--renderer playwright` e
`--renderer jina` forçam um deles. O renderizador é usado apenas pelo Assaí e pelo
Examine: os outros três mercados são HTTP simples.

### Sem as bibliotecas de sistema do Chromium

O Chromium precisa de bibliotecas que não vêm com o Playwright (`libglib-2.0`,
`libnss3`, `libatk`, `libgbm`, fontconfig…). O caminho normal é
`sudo .venv/bin/playwright install-deps chromium`. Sem root, dá para extrair os
pacotes num diretório do usuário e apontar as variáveis de ambiente:

```bash
# lista de dependências que o Playwright pediria
.venv/bin/playwright install-deps --dry-run chromium

# baixa (apt-get download não precisa de root) e extrai para um prefixo local
mkdir -p ~/tmp/debs ~/.local/share/chromium-libs
cd ~/tmp/debs && apt-get download <pacotes...>
for f in ~/tmp/debs/*.deb; do dpkg-deb -x "$f" ~/.local/share/chromium-libs; done
# copie só as .so que o sistema não tem para ~/.local/share/crlibs
```

O Chromium também aborta com `SkFontMgr_FontConfigInterface: Not implemented` quando
não existe `/etc/fonts/fonts.conf`; extraia `fontconfig-config` e um pacote de fontes
(`fonts-liberation`) e aponte um `fonts.conf` mínimo referenciando o diretório de fontes
extraído. No fim, a execução fica assim:

```bash
LD_LIBRARY_PATH=$HOME/.local/share/crlibs \
FONTCONFIG_FILE=$HOME/.local/share/chromium-etc/etc/fonts/local.conf \
.venv/bin/jornaleiro run
```

Sem essa ginástica, use `--renderer jina` (ou deixe o `auto` cair nele sozinho).

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
desliga tudo. O modo `forte` perde a camada de texto (a página vira imagem), então a leitura
de preços parte dos brutos em `data/<dia>/raw/` — que também são limpos a cada coleta para
não misturar folhetos de execuções anteriores.

## Preços dos encartes

`jornaleiro precos` lê os preços dos PDFs já baixados em `data/<dia>/` (não baixa nada de
novo) e grava `data/<dia>/precos/<mercado>.csv` e `<mercado>.json`, com as colunas
`mercado;pagina;produto;preco;ordem;tipo` (o CSV sai com BOM, `utf-8-sig`, para abrir
direto no Excel pt-BR).

| Mercado | Como o preço é lido | Resultado nos encartes de 15/10/2026 (medido em 18/10) |
|---|---|---|
| Atacadão | camada de texto do PDF, **por coordenadas** (abaixo) | 573 preços (256 itens) |
| Savegnago | camada de texto do PDF | 261 preços (180 itens) |
| Covabra | camada de texto do PDF | 176 preços (169 itens) |
| Assaí | **OCR** (encarte em JPEG) | 16 preços (12 itens) |
| Examine | **catálogo do site** (GraphQL) | 11.124 produtos com preço (4.408 com desconto) |

No Atacadão o PDF desenha cada item como um card solto — nome à esquerda, até três
preços empilhados à direita — e a ordem do fluxo de texto embaralha preço e nome entre
itens vizinhos (no hortifruti, um produto saía com o preço do outro). Desde 18/10/2026
esse mercado é lido **por coordenadas** (`x, y` de cada fragmento): cada `R$` vira um
slot de preço, slots da mesma coluna x formam um item e cada fragmento de nome vai para
o item à sua direita. Um vão grande entre dois preços da mesma coluna pode ser fronteira
de cards ou o preço do app em cima do cheio com o nome no meio; quem decide é o bloco de
nome do card — cobrindo boa parte do vão, os preços ficam juntos; sem cobrir, o item
fecha. A linha riscada (`de: R$ 9,99 por:`) é descartada inteira, com o rótulo junto.
Com isso, os preços com `tipo` identificado subiram de 428 (de 554 lidos) para 459 (de
573) nos encartes de 15/10/2026.

A leitura casa a descrição impressa com os preços do item (no Atacadão, por coordenadas;
nos demais mercados, a descrição vale para os preços que vêm logo depois dela no fluxo de
texto); `ordem` é a posição do preço dentro do item, porque o
encarte publica vários preços por produto (o Atacadão traz varejo/atacado, app e cartão;
o Savegnago traz "de/por"). A coluna `tipo` tenta dizer o **papel** de cada preço por
heurística de valor — o encarte publica do maior para o menor: no Atacadão, bloco de 3
preços vira `varejo/atacado`, `app`, `app/cartao` (bloco de 2, `varejo/atacado` +
`app`); no Savegnago/Covabra, bloco de 2 vira `cheio` + `clube`; blocos de tamanho
inesperado (itens fundidos pela ordem de leitura do PDF) e mercados sem padrão
conhecido ficam com `tipo` vazio. É inferência medida, não rótulo lido do PDF.

### OCR dos encartes em imagem

`[precos]` no `config.toml` controla o OCR (`ocr = true`), o binário, o `tessdata`, o
idioma e o `psm` (12 = texto esparso, que foi o melhor medido). O tesseract **não** vem
com o Playwright; nesta máquina ele foi extraído dos `.deb` para
`~/.local/share/tesseract` com as bibliotecas em `~/.local/share/tesslibs` (o deps do
Chromium não serve para ele), e é isso que `ocr_ld_library_path` aponta. Se o binário
não existir, `jornaleiro run` e `jornaleiro precos` seguem funcionando e o resumo diz
`precos: OCR indisponivel`. `--sem-ocr` desliga o OCR pontualmente.

Limitações conhecidas, todas verificadas nos encartes de hoje: no Atacadão/Covabra/
Savegnago o nome vem do texto impresso (quando o próprio PDF perde um glifo, sai torto
— ex.: `Arroz po 1` em vez de `Arroz tipo 1`); no Atacadão a leitura por coordenadas
acabou com a troca de preço entre itens vizinhos do hortifruti (a leitura por fluxo de
texto dava `Cebola` com o preço da cenoura e colava o `de: R$` riscado no nome) — o que
sobra são os itens-caixa (`CAIXA/SACO COM 19KG`) do hortifruti, cujo preço às vezes cai
no item de cima ou fica sem descrição (9 preços sem `produto` nos encartes de 15/10);
`tipo` é heurística de valor, não rótulo lido; no Assaí o OCR
acha poucos preços e as descrições saem truncadas/ruidosas (só as linhas com palavra
real e pouco lixo entram); o encarte em imagem do Examine não é lido por OCR (é arte
com preço estilizado) — para esse mercado a leitura vem do catálogo do site, abaixo.
Os PDFs continuam no `data/<dia>/` para conferência.

`jornaleiro run` também lê os preços do PDF que acabou de gerar, grava os mesmos
`data/<dia>/precos/<mercado>.csv|json`, põe a contagem na mensagem do Telegram
(uma linha por mercado, ex.: `| 256 itens/573 precos`) e manda o CSV como documento
logo depois do PDF do mercado. O marcador de fonte aparece quando a leitura não veio
da camada de texto pura: `(OCR)`, `(texto+OCR)` ou `(OCR indisponivel em parte)` (um
arquivo do mercado ficou sem OCR); se a leitura falhar, a linha vira
`precos: falha (motivo)` e o PDF do mercado ainda é enviado. `enviar = false` em
`[precos]` desliga só o envio dos CSVs. `ler = false` desliga a leitura de preços no
`run` (só coleta os jornais; o resumo traz a validade, sem contagem de preços) — o
subcomando `jornaleiro precos` continua lendo sob demanda.

### Encarte oficial do Examine (jornal do site)

Com `EXAMINE_TOKEN` no `.env` (Bearer da conta do clube), `jornaleiro run` pega o encarte do
Examine pela consulta `pamphlets { file id title }` da mesma API — é o "Jornal de
Ofertas" oficial, página por página, agrupado por campanha (em 16/10/2026: 9 páginas,
`Show de Economia 💚` com 5, mais banners de campanha). O PDF do Examine passa a ter
essas páginas, com os títulos no campo `note`. Sem token — ou se a consulta falhar — o
mercado cai no caminho antigo do Instagram, que continua no código.

`pamphlets` só existe no endpoint principal (`site_graphql_jornal`, padrão
`www.crescevendas.com/graphql`); o catálogo usa o do e-commerce (`site_graphql`). Trocar
os dois de lugar dá `Field 'pamphlets' doesn't exist on type 'Query'` — já aconteceu.

### Preços do site do Examine (GraphQL)

O site `superexaminerc.crescevendas.com` é um Next.js que conversa com a API GraphQL
`www.crescevendas.com/ecommerce/graphql` (cliente resolvido pelo `Origin` do tenant; a
consulta `app_version` responde `client_id=377, name="Examine"`). `jornaleiro site-precos`
varre `categories` e `products(categoryId, after)` — as mesmas consultas que o site usa —
e grava `data/<dia>/precos/examine.csv|json` com `id;categoria;produto;preco;pesavel;unidade;estoque;descontos`.
`--max-categorias N` limita a varredura (bom para teste). O campo `descontos` vem como
`Tipo=valor`: `Aplicativo` é o preço com oferta ativada no app (valor em R$) e `Cashback`
é fração do preço — a mesma distinção que o site faz ao exibir.

Comparado com e sem `Authorization`, os preços e descontos são **idênticos** (verificado
nos encartes de 15/10/2026): o token destrava o jornal, não preço extra. E este é
**preço do site**, não o preço impresso no encarte da semana; por isso ele não substitui
o PDF, mas é estruturado (nome, código, estoque, peso, descontos) e não depende de OCR.
Em `jornaleiro run`, `[markets.examine] precos_site = true` faz a leitura de preços do
Examine vir daqui (o CSV vai junto dos PDFs) e pula o OCR do encarte em imagem, que não
lia nada.

## Histórico de preços (SQLite)

`jornaleiro historico` indexa os CSVs de `data/<dia>/precos/` num banco SQLite
(`data/historico.sqlite`, caminho em `[historico] db` do `config.toml`); o banco **não**
entra no git e é descartável — `--reindex` o reconstrói dos CSVs a qualquer momento:

```bash
.venv/bin/jornaleiro historico                    # precos/coletas/site no banco
.venv/bin/jornaleiro historico --reindex          # reconstroi dos CSVs de data/
.venv/bin/jornaleiro historico --produto "arroz"  # ultimas leituras do produto (trecho do nome)
.venv/bin/jornaleiro historico --quedas --dias 30 # so as quedas da janela
```

`--quedas` usa o **menor preço do dia** por (mercado, produto normalizado — sem acento,
minúsculo), compara as duas últimas leituras de cada produto e lista só quedas reais
(`agora < antes`), da maior para a menor; altas ficam de fora e produtos sem duas
leituras na janela também. No exemplo dos encartes de 15 e 18/10/2026 (mesma semana de
promoção), 229 dos 230 produtos do Atacadão repetiram o preço e só a Toalha de Papel
baixou R$ 19,98 → R$ 19,90. Nos resultados de `--produto`, o `tipo` vem junto do preço.

O banco guarda uma linha por preço lido (`mercado, dia, pagina, produto, produto_norm,
preco, ordem, tipo`), uma linha por coleta (`coletas`, com `itens`, `precos` e o tamanho
dos PDFs/brutos) e o catálogo do site do Examine (`site_produtos`); os PDFs não entram.
No `run`, o banco só é atualizado se **já existir** (nunca derruba a execução) e o dia é
substituído inteiro (`registrar_dia`), então rodar duas vezes no mesmo dia não duplica
nada. As quedas da janela de 30 dias entram no resumo do Telegram quando
`[historico] quedas_no_resumo > 0` (padrão 3; o bloco está no exemplo de mensagem
acima). `jornaleiro limpar` reindexa o banco depois de apagar as coletas, para ele não
apontar para dia removido.

## Estado e a semente do Examine

`data/state.json` guarda o último post do Examine processado
(`examine_last_post_url`) e os shortcodes já vistos (`examine_seen`). A descoberta
parte da página desse post, pega os shortcodes recentes, filtra pelas legendas com
`Ofertas válidas` **e** `lojas de Rio Claro` e escolhe o post mais novo. Depois disso
o post passa a ser a nova semente, então cada execução só coleta encartes novos.

Também ficam lá, por mercado (`mercados.<chave>`), o sha256 dos brutos do último envio,
o dia, as contagens e o flag `enviado` — é o que o `run` usa para não reenviar o mesmo
encarte (ver "Uso"). A gravação é atômica (arquivo temporário + `os.replace`), então um
`Ctrl-C` no meio não deixa o JSON pela metade.

No CI, esse mesmo arquivo é restaurado e regravado no branch `estado` a cada run (o
runner é efêmero); o `data/state.json` da máquina local é independente — veja *Coleta
diária no GitHub Actions*.

Para forçar o Examine a reavaliar posts antigos, apague as duas chaves (ou o
`data/state.json`) antes de rodar.

## Coleta diária no GitHub Actions

`.github/workflows/jornaleiro.yml` roda `jornaleiro run` todo dia às 08:00 (horário de
Brasília; o cron do Actions é UTC e pode atrasar alguns minutos) e também por
`workflow_dispatch` — o botão *Run workflow* tem a opção `forcar` para reenviar mesmo com
o encarte idêntico ao último envio. O run instala o pacote e o Chromium do Playwright
(necessário para o Assaí) e não precisa de tesseract enquanto `[precos] ler = false`.

O runner é efêmero: `data/` não sobrevive entre execuções. Por isso o `data/state.json`
— a memória do "não reenviar o mesmo encarte" e a semente do Examine — fica no branch
`estado`, restaurado antes do run e atualizado depois (um commit por dia; o primeiro
estado veio da máquina local). Nenhum PDF vai para o git: os binários existem só no
runner durante o job (o envio é pelo Telegram) e `data/` continua ignorado — o branch
`estado` guarda apenas o JSON. Se um run morrer entre o envio e o commit do estado, o
próximo pode reenviar o mesmo encarte (duplicata); nunca pula um encarte novo.

### Configuração (uma vez)

1. Settings → Environments → **New environment** `producao`; em *Deployment branches*,
   selecione **Selected branches** e adicione `main` (só runs do `main` acessam os secrets).
2. No environment (ou no repositório), crie os secrets:

   | Secret | Uso | Obrigatório |
   |---|---|---|
   | `TELEGRAM_BOT_TOKEN` | envio dos PDFs | sim |
   | `TELEGRAM_CHAT_ID` | destino no Telegram | sim |
   | `EXAMINE_TOKEN` | jornal oficial do Examine (`pamphlets`) | não (cai no Instagram) |
   | `JINA_API_KEY` | renderizador de reserva (sem Chromium) | não |

3. O workflow só referencia `${{ secrets.* }}`; nada fica no repositório. O
   `GITHUB_TOKEN` do run tem apenas `contents: write` (para o branch `estado`) e expira
   ao fim do job — não há PAT nem chave SSH no CI. Se um valor vazar, rotacione
   (`/revoke` no BotFather e regeneração dos tokens) e atualize o `.env` local e o secret
   no GitHub.
4. O `.github/workflows/` também é superfície de ataque: quem consegue mudar o workflow
   consegue ler os secrets. Se o repositório ganhar colaboradores, proteja o `main`
   (PR + review) e revise mudanças nessa pasta.

O primeiro run usa o estado semeado na máquina local; se quiser forçar um reenvio dos
encartes atuais, use *Run workflow* com `forcar: true`.

### Rodando também na máquina

O CI e a máquina mantêm estados separados. Para não duplicar envios, deixe o envio
diário com o CI e use o local para depurar (`--no-send`, `--only`, `--forcar`). Para
puxar o estado do CI antes de um run local:

```bash
git fetch origin estado && git show origin/estado:state.json > data/state.json
```

O caminho inverso (publicar o estado local no branch) é o que o workflow faz ao fim de
cada run; evite fazer os dois em paralelo.

## Testes

```bash
.venv/bin/python -m pytest -q
```

Os testes usam fixtures recortadas das respostas reais (JSON do Assaí, API do
Atacadão, HTML do Covabra e os dois renders do Instagram), fragmentos sintéticos de
coordenadas para a leitura por colunas do Atacadão e bancos temporários para o
histórico — e não acessam a rede. Desde 18/10/2026 também cobrem os utilitários internos
(HTTP e Telegram com clientes falsos, estado, renderizadores) e a operação (resolução do
config, `limpar` e `run` com mercados/renderer falsos, frescor/avisos): 111 testes.

Estratégias conhecidas e ainda **não** implementadas: no Assaí, pré-processar a imagem
(escala/cinza/limiar) e usar o OCR com coordenadas (TSV) para casar nome e preço pela
posição; no Atacadão, ler os rótulos (`PREÇO VAREJO/ATACADO`, `No app`, `Cartão`) para o
`tipo` deixar de ser heurística de valor. As duas dependem de medir o ganho antes de
mexer no parser atual.

## Licença

MIT — o texto completo está em [`LICENSE`](LICENSE).
