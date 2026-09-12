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
    tzdata \
    ca-certificates \
    curl && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone && \
    rm -rf /var/lib/apt/lists/*

COPY backup_nextcloud.sh /usr/local/bin/backup_nextcloud.sh
COPY backup_appflowy.sh /usr/local/bin/backup_appflowy.sh
COPY backup_homarr.sh /usr/local/bin/backup_homarr.sh
COPY backup_jellyfin.sh /usr/local/bin/backup_jellyfin.sh
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /usr/local/bin/backup_nextcloud.sh \
             /usr/local/bin/backup_appflowy.sh \
             /usr/local/bin/backup_homarr.sh \
             /usr/local/bin/backup_jellyfin.sh \
             /entrypoint.sh

CMD ["/entrypoint.sh"]
