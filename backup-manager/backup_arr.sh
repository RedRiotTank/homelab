#!/bin/bash
set -eo pipefail

export DOCKER_API_VERSION="1.41"
exec 1>/proc/1/fd/1
exec 2>/proc/1/fd/2

DATA_DIR="${ARR_DATA_DIR:-/opt/arr-stack}"
RESTIC_REPO="${ARR_RESTIC_REPO:-rclone:gdrive:backups/arr}"
export RESTIC_PASSWORD="${RESTIC_PASSWORD:?Error: undefined RESTIC_PASSWORD}"
export RCLONE_CONFIG="${RCLONE_CONFIG_PATH:-/root/.config/rclone/rclone.conf}"
CONTAINERS="${ARR_CONTAINERS:-qbittorrent sonarr prowlarr kitsunarr}"

echo "========== STARTING ARR STACK BACKUP =========="

echo "-> Stopping Arr containers..."
docker stop $CONTAINERS || true

echo "-> Uploading configuration data via Restic..."

restic -r "$RESTIC_REPO" backup "$DATA_DIR" --exclude "$DATA_DIR/kitsunarr_src"

echo "-> Restarting Arr containers..."
docker start $CONTAINERS || true

echo "-> Applying retention policy..."
restic -r "$RESTIC_REPO" forget --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune

echo "========== ARR STACK BACKUP FINISHED =========="
