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

# vincula o pacote do GHCR ao repositorio (o numero fixo evita depender do passwd)
LABEL org.opencontainers.image.source="https://github.com/brunoanhaia/jornaleiro" \
      org.opencontainers.image.licenses="MIT"

USER 1000:1000
VOLUME ["/app/data"]
ENTRYPOINT ["jornaleiro"]
CMD ["serve"]
