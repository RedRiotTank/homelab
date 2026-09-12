#!/bin/bash
set -eo pipefail

export DOCKER_API_VERSION="1.41"
exec 1>/proc/1/fd/1
exec 2>/proc/1/fd/2

CONTAINER="${JELLYFIN_CONTAINER:-jellyfin}"
CONFIG_DIR="${JELLYFIN_CONFIG_DIR:-/srv/appdata/jellyfin/config}"
MEDIA_DIR="${JELLYFIN_MEDIA_DIR:-/mnt/media}"
RESTIC_REPO="${JELLYFIN_RESTIC_REPO:-rclone:gdrive:backups/jellyfin}"
export RESTIC_PASSWORD="${RESTIC_PASSWORD:?Error: undefined RESTIC_PASSWORD}"
export RCLONE_CONFIG="${RCLONE_CONFIG_PATH:-/root/.config/rclone/rclone.conf}"

echo "========== STARTING JELLYFIN BACKUP =========="

EXCLUDE_PARAMS=()
EXCLUDE_PARAMS+=(--exclude "${CONFIG_DIR}/cache")
EXCLUDE_PARAMS+=(--exclude "${CONFIG_DIR}/.cache")
EXCLUDE_PARAMS+=(--exclude "${CONFIG_DIR}/log")
EXCLUDE_PARAMS+=(--exclude "${CONFIG_DIR}/data/transcodes")

if [ "${JELLYFIN_BACKUP_METADATA:-false}" != "true" ]; then
  echo "-> Skipping metadata/posters (JELLYFIN_BACKUP_METADATA=false)"
  EXCLUDE_PARAMS+=(--exclude "${CONFIG_DIR}/data/metadata")
else
  echo "-> Including metadata/posters in backup."
fi

if [ "${JELLYFIN_BACKUP_TRICKPLAY:-false}" != "true" ]; then
  echo "-> Skipping trickplay/scrubbing images (JELLYFIN_BACKUP_TRICKPLAY=false)"
  EXCLUDE_PARAMS+=(--exclude "${CONFIG_DIR}/data/trickplay")
  EXCLUDE_PARAMS+=(--exclude "*.bif")
else
  echo "-> Including trickplay files in backup."
fi

BACKUP_PATHS=("${CONFIG_DIR}")
if [ "${JELLYFIN_BACKUP_MEDIA:-false}" = "true" ]; then
  echo "-> Including media directory (${MEDIA_DIR})..."
  BACKUP_PATHS+=("${MEDIA_DIR}")
else
  echo "-> Skipping media directory (JELLYFIN_BACKUP_MEDIA=false)"
fi

echo "-> Stopping Jellyfin container to lock SQLite databases..."
docker stop "$CONTAINER"

echo "-> Uploading Jellyfin snapshot via Restic..."
restic -r "\(RESTIC_REPO" backup "\){EXCLUDE_PARAMS[@]}" "${BACKUP_PATHS[@]}"

echo "-> Restarting Jellyfin container..."
docker start "$CONTAINER"

echo "-> Applying retention policy..."
restic -r "$RESTIC_REPO" forget --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune

echo "========== JELLYFIN BACKUP FINISHED =========="
