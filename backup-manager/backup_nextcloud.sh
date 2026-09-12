#!/bin/bash
set -eo pipefail

export DOCKER_API_VERSION="1.41"

exec 1>/proc/1/fd/1
exec 2>/proc/1/fd/2

CONTAINER_NC="${NEXTCLOUD_CONTAINER:-nextcloud}"
CONTAINER_DB="${NEXTCLOUD_DB_CONTAINER:-nextcloud-db}"
DATA_DIR="${NEXTCLOUD_DATA_DIR:-/srv/nextcloud_data}"
RESTIC_REPO="${NEXTCLOUD_RESTIC_REPO:-rclone:gdrive:backups/nextcloud}"

export RESTIC_PASSWORD="${RESTIC_PASSWORD:?Error: undefined RESTIC_PASSWORD}"
export RCLONE_CONFIG="${RCLONE_CONFIG_PATH:-/root/.config/rclone/rclone.conf}"

DB_USER="${NEXTCLOUD_DB_USER:-nextcloud_user}"
DB_NAME="${NEXTCLOUD_DB_NAME:-nextcloud}"
DB_BACKUP_TEMP="/tmp/nextcloud-db.sql"

echo "========== STARTING NEXTCLOUD BACKUP =========="

echo "-> Enabling maintenance mode in Nextcloud..."
docker exec -u www-data "$CONTAINER_NC" php occ maintenance:mode --on

echo "-> Exporting PostgreSQL database..."
docker exec -u postgres "\(CONTAINER_DB" pg_dump -U "\)DB_USER" "\(DB_NAME" > "\)DB_BACKUP_TEMP"

echo "-> Uploading encrypted data via Restic..."
restic -r "\(RESTIC_REPO" backup "\)DATA_DIR" "$DB_BACKUP_TEMP"

echo "-> Disabling maintenance mode..."
docker exec -u www-data "$CONTAINER_NC" php occ maintenance:mode --off

rm -f "$DB_BACKUP_TEMP"

echo "-> Applying retention policy..."
restic -r "$RESTIC_REPO" forget --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune

echo "========== NEXTCLOUD BACKUP FINISHED =========="
