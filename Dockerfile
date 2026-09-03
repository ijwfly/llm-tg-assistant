FROM python:3.12-slim

ARG UID=1000
ARG GID=1000
ARG CLAUDE_CODE_VERSION=2.1.259

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git gnupg \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# the host GID may already exist in the image (macOS staff = 20 = dialout): reuse it
RUN (getent group "${GID}" >/dev/null || groupadd -g "${GID}" app) \
 && useradd -m -u "${UID}" -g "${GID}" -s /bin/bash app

WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt

COPY . .
RUN mkdir -p /data/inbox && chown -R "${UID}:${GID}" /app /data

USER app
ENV CLAUDE_CONFIG_DIR=/home/app/.claude
CMD ["python", "-m", "app.main"]
