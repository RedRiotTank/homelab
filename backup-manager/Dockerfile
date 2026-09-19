FROM ubuntu:latest

ARG TZ=Europe/Madrid
ENV DOCKER_API_VERSION=1.41
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=${TZ}

RUN apt-get update && apt-get install -y \
    cron \
    restic \
    rclone \
    docker.io \
    jq \
    tzdata \
    ca-certificates \
    curl && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY services.json /app/services.json
COPY backup_engine.sh /usr/local/bin/backup_engine.sh
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /usr/local/bin/backup_engine.sh /entrypoint.sh

CMD ["/entrypoint.sh"]
