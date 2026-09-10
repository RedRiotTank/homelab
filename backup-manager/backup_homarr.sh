#!/bin/bash
set -eo pipefail

export DOCKER_API_VERSION="1.41"
exec 1>/proc/1/fd/1
exec 2>/proc/1/fd/2

CONTAINER="${HOMARR_CONTAINER:-homarr}"
DATA_DIR="${HOMARR_DATA_DIR:-/opt/homarr/appdata}"
RESTIC_REPO="${HOMARR_RESTIC_REPO:-rclone:gdrive:backups/homarr}"
export RESTIC_PASSWORD="${RESTIC_PASSWORD:?Error: undefined RESTIC_PASSWORD}"
export RCLONE_CONFIG="${RCLONE_CONFIG_PATH:-/root/.config/rclone/rclone.conf}"

echo "========== [$(date '+%Y-%m-%d %H:%M:%S')] Starting Homarr Backup =========="
echo "-> Stopping Homarr container to ensure SQLite consistency..."
docker stop "$CONTAINER"

echo "-> Uploading encrypted data via Restic..."
restic -r "$RESTIC_REPO" backup "$DATA_DIR"

echo "-> Starting Homarr container..."
docker start "$CONTAINER"

echo "-> Applying retention policy..."
restic -r "$RESTIC_REPO" forget --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune

echo "========== [$(date '+%Y-%m-%d %H:%M:%S')] Backup completed successfully =========="
