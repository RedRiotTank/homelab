# Restore verification image: Restic 0.19.1, rclone, Python and validation tools.
FROM ghcr.io/garethgeorge/backrest:latest AS restic

FROM python:3.12-alpine

RUN apk add --no-cache \
        ca-certificates \
        coreutils \
        gzip \
        jq \
        postgresql-client \
        rclone \
        sqlite \
        tzdata \
    && pip install --no-cache-dir pyyaml

COPY --from=restic /bin/restic /usr/local/bin/restic

WORKDIR /app
COPY backrest-verify.py /app/backrest-verify.py
RUN chmod 0755 /app/backrest-verify.py

ENV PYTHONUNBUFFERED=1 \
    TZ=Europe/Madrid

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
    CMD python3 -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('BACKREST_VERIFY_PORT','9798') + '/healthz', timeout=3)"

ENTRYPOINT ["python3", "/app/backrest-verify.py"]
