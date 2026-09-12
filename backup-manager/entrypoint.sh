#!/bin/bash
env > /etc/environment
> /etc/cron.d/backup-cron

if [ "${ENABLE_BACKUP_APPFLOWY:-false}" = "true" ]; then
  echo "${BACKUP_CRON_APPFLOWY:-0 3 * * *} /usr/local/bin/backup_appflowy.sh" >> /etc/cron.d/backup-cron
fi

if [ "${ENABLE_BACKUP_NEXTCLOUD:-false}" = "true" ]; then
  echo "${BACKUP_CRON_NEXTCLOUD:-30 3 * * *} /usr/local/bin/backup_nextcloud.sh" >> /etc/cron.d/backup-cron
fi

if [ "${ENABLE_BACKUP_HOMARR:-false}" = "true" ]; then
  echo "${BACKUP_CRON_HOMARR:-0 4 * * 0} /usr/local/bin/backup_homarr.sh" >> /etc/cron.d/backup-cron
fi

if [ "${ENABLE_BACKUP_JELLYFIN:-false}" = "true" ]; then
  echo "${BACKUP_CRON_JELLYFIN:-0 5 * * 0} /usr/local/bin/backup_jellyfin.sh" >> /etc/cron.d/backup-cron
fi

chmod 0644 /etc/cron.d/backup-cron
crontab /etc/cron.d/backup-cron
exec cron -f
