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

RUN chmod +x /usr/local/bin/backup_nextcloud.sh /usr/local/bin/backup_appflowy.sh

# Entrypoint script to configure cron dynamically on container start
RUN echo '#!/bin/bash\n\
AF_CRON="${BACKUP_CRON_APPFLOWY:-0 3 * * *}"\n\
NC_CRON="${BACKUP_CRON_NEXTCLOUD:-30 3 * * *}"\n\
echo "$AF_CRON /usr/local/bin/backup_appflowy.sh" > /etc/cron.d/backup-cron\n\
echo "$NC_CRON /usr/local/bin/backup_nextcloud.sh" >> /etc/cron.d/backup-cron\n\
chmod 0644 /etc/cron.d/backup-cron\n\
crontab /etc/cron.d/backup-cron\n\
exec cron -f' > /entrypoint.sh && chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
