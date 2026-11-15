FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=America/Sao_Paulo

# `tzdata` e obrigatorio para ZoneInfo("America/Sao_Paulo"); pinar versao de pacote
# do Debian quebraria o rebuild quando o repositorio move (reprodutibilidade vem do
# `pyproject.toml`), por isso o ignore do hadolint.
# hadolint ignore=DL3008
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install . \
 && useradd --create-home --uid 1000 app

COPY config.toml ./
RUN mkdir -p /app/data && chown -R app:app /app

# versao OCI: o workflow passa `--build-arg VERSAO=X.Y.Z` (tags do repo);
# localmente o padrao e `dev`. O `RUN` existe para o cache invalidar quando a
# versao muda (o buildah nao invalida o `LABEL` so pela troca do `ARG`).
ARG VERSAO=dev
RUN printf '%s\n' "${VERSAO}" > /app/versao.txt

# vincula o pacote do GHCR ao repositorio (numero fixo evita depender do passwd)
LABEL org.opencontainers.image.source="https://github.com/brunoanhaia/jornaleiro" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSAO}"

USER 1000:1000
VOLUME ["/app/data"]
ENTRYPOINT ["jornaleiro"]
CMD ["serve"]
