#!/bin/bash
set -eo pipefail

export DOCKER_API_VERSION="1.41"

exec 1>/proc/1/fd/1
exec 2>/proc/1/fd/2

# Dynamic discovery with environment override
CONTAINER_DB="${APPFLOWY_DB_CONTAINER:-$(docker ps --filter "name=appflowy.*postgres" --format "{{.Names}}" | head -n 1)}"
CONTAINER_MINIO="${APPFLOWY_MINIO_CONTAINER:-$(docker ps --filter "name=appflowy.*minio" --format "{{.Names}}" | head -n 1)}"

RESTIC_REPO="${APPFLOWY_RESTIC_REPO:-rclone:gdrive:backups/appflowy}"
export RESTIC_PASSWORD="${RESTIC_PASSWORD:?Error: undefined RESTIC_PASSWORD}"
export RCLONE_CONFIG="${RCLONE_CONFIG_PATH:-/root/.config/rclone/rclone.conf}"

DB_BACKUP_TEMP="/tmp/appflowy-db.sql"
MINIO_DUMP_DIR="/tmp/minio_data_dump"

echo "========== STARTING APPFLOWY BACKUP =========="

if [ -z "$CONTAINER_DB" ]; then
    echo "ERROR: AppFlowy PostgreSQL container not found." >&2
    exit 1
fi

if [ -z "$CONTAINER_MINIO" ]; then
    echo "ERROR: AppFlowy MinIO container not found." >&2
    exit 1
fi

echo "-> Exporting AppFlowy PostgreSQL database ($CONTAINER_DB)..."
docker exec "$CONTAINER_DB" pg_dumpall -U postgres > "$DB_BACKUP_TEMP"

echo "-> Extracting MinIO storage data ($CONTAINER_MINIO)..."
rm -rf "$MINIO_DUMP_DIR" && mkdir -p "$MINIO_DUMP_DIR"
docker cp "$CONTAINER_MINIO":/data/. "$MINIO_DUMP_DIR/"

echo "-> Uploading AppFlowy snapshot to Restic repository..."
restic -r "$RESTIC_REPO" backup "$DB_BACKUP_TEMP" "$MINIO_DUMP_DIR"

echo "-> Cleaning temporary files..."
rm -f "$DB_BACKUP_TEMP"
rm -rf "$MINIO_DUMP_DIR"

echo "-> Applying retention policy..."
restic -r "$RESTIC_REPO" forget --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune

echo "========== APPFLOWY BACKUP FINISHED =========="
