# Branch `estado`

Gerado automaticamente pelo workflow `.github/workflows/jornaleiro.yml`.

Guarda o `data/state.json` entre as execucoes do runner efemero: e o que garante que
encartes identicos ja enviados nao sejam reenviados no dia seguinte (sha256 por mercado
+ sementes do Examine/Instagram).

- Nao edite a mao; o run diario commita aqui (`estado: AAAA-MM-DD`).
- Para inspecionar: `git show origin/estado:state.json`.
- A maquina local usa `data/state.json`; se rodar local em paralelo ao CI, sincronize
  (README, secao "Rodando tambem na maquina") para nao duplicar envios.
