# One container: builds the web client, then serves it and the game server on $PORT.
# Base images are pinned to exact versions; Dependabot (.github/dependabot.yml) proposes updates weekly.
FROM node:22.23.4-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.13.18-slim
WORKDIR /app
COPY server/requirements.txt server/requirements.txt
# Debian's security patches that came out after the base image was made (they don't wait for a new image), then the
# app's libraries. pip itself goes last: the app never uses it, and it carries old copies of urllib3 and msgpack.
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r server/requirements.txt && pip uninstall -y pip
COPY server/ server/
COPY --from=web /web/dist web/dist
ENV BRIDGE_WEB_DIST=/app/web/dist \
    BRIDGE_DATA_DIR=/data \
    BRIDGE_DDS_THREADS=2 \
    MPLCONFIGDIR=/tmp/matplotlib \
    PORT=8000
# runs as a user of its own, not root: a flaw in the app can't then change the container's system files
RUN useradd --system --uid 10001 --no-create-home bridge && mkdir -p /data && chown bridge /data
USER bridge
WORKDIR /app/server
EXPOSE 8000
# --ws-max-size: a phone's messages are a few hundred bytes, so refuse anything over 64 KB
CMD ["sh", "-c", "uvicorn bridge.app:app --host 0.0.0.0 --port ${PORT} --ws-max-size 65536"]
