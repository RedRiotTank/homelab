#!/bin/bash
env > /etc/environment
> /etc/cron.d/backup-cron

JSON_FILE="/app/services.json"
SERVICES=$(jq -r 'keys[]' "$JSON_FILE")

for service in $SERVICES; do
  ENABLED=$(jq -r --arg s "$service" '.[$s].enabled // false' "$JSON_FILE")
  if [ "$ENABLED" = "true" ]; then
    CRON_SCHEDULE=$(jq -r --arg s "$service" '.[$s].cron // "0 3 * * *"' "$JSON_FILE")
    echo "-> Registering cron for $service: $CRON_SCHEDULE"
    echo "$CRON_SCHEDULE /usr/local/bin/backup_engine.sh $service" >> /etc/cron.d/backup-cron
  fi
done

chmod 0644 /etc/cron.d/backup-cron
crontab /etc/cron.d/backup-cron
exec cron -f
