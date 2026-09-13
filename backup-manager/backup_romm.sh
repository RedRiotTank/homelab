#!/bin/bash
set -eo pipefail

export DOCKER_API_VERSION="1.41"

exec 1>/proc/1/fd/1
exec 2>/proc/1/fd/2

CONTAINER_ROMM="${ROMM_CONTAINER:-romm}"
CONTAINER_DB="${ROMM_DB_CONTAINER:-romm-db}"
DATA_DIR="${ROMM_DATA_DIR:-/opt/romm}"
RESTIC_REPO="${ROMM_RESTIC_REPO:-rclone:gdrive:backups/romm}"

export RESTIC_PASSWORD="${RESTIC_PASSWORD:?Error: undefined RESTIC_PASSWORD}"
export RCLONE_CONFIG="${RCLONE_CONFIG_PATH:-/root/.config/rclone/rclone.conf}"

DB_BACKUP_TEMP="/tmp/romm-db.sql"

echo "========== STARTING ROMM BACKUP =========="

echo "-> Stopping RomM container to lock state..."
docker stop "$CONTAINER_ROMM"

echo "-> Exporting MariaDB database..."
docker exec "$CONTAINER_DB" \
    sh -c 'mariadb-dump -u "$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE"' \
    > "$DB_BACKUP_TEMP"

EXCLUDES=(
    "--exclude"
    "${DATA_DIR}/database"
)

if [ "${ROMM_BACKUP_LIBRARY:-false}" != "true" ]; then
    echo "-> Skipping library (ROMs) backup..."
    EXCLUDES+=(
        "--exclude"
        "${DATA_DIR}/library"
    )
fi

if [ "${ROMM_BACKUP_ASSETS:-true}" != "true" ]; then
    echo "-> Skipping assets and resources (Covers/Metadata) backup..."
    EXCLUDES+=(
        "--exclude"
        "${DATA_DIR}/assets"
        "--exclude"
        "${DATA_DIR}/resources"
    )
fi

echo "-> Uploading snapshot via Restic..."

restic -r "$RESTIC_REPO" backup \
    "${EXCLUDES[@]}" \
    "${DATA_DIR}" \
    "$DB_BACKUP_TEMP"

echo "-> Restarting RomM container..."
docker start "$CONTAINER_ROMM"

rm -f "$DB_BACKUP_TEMP"

echo "-> Applying retention policy..."
restic -r "$RESTIC_REPO" forget \
    --keep-daily 7 \
    --keep-weekly 4 \
    --keep-monthly 12 \
    --prune

echo "========== ROMM BACKUP FINISHED =========="
