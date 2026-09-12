#!/bin/bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

RESTIC_PASSWORD="${RESTIC_PASSWORD:?Error: undefined RESTIC_PASSWORD}"
RESTIC_REPO="${JELLYFIN_RESTIC_REPO:-rclone:gdrive:backups/jellyfin}"
CONFIG_DIR="${JELLYFIN_CONFIG_DIR:-/srv/appdata/jellyfin/config}"
CONTAINER="${JELLYFIN_CONTAINER:-jellyfin}"
TEMP_RECOVERY_DIR="${JELLYFIN_TEMP_DIR:-/tmp/recovery_jellyfin}"
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

echo "========== Starting Jellyfin Disaster Recovery =========="

echo "-> 1. Stopping Jellyfin container..."
docker stop "$CONTAINER" || true

echo "-> 2. Wiping corrupted config directory..."
sudo rm -rf "${CONFIG_DIR}"
sudo mkdir -p "${CONFIG_DIR}"

echo "-> 3. Downloading latest snapshot from Restic..."
docker exec -e RESTIC_PASSWORD="${RESTIC_PASSWORD}" backup-manager \
  restic -r "${RESTIC_REPO}" restore latest --target "${TEMP_RECOVERY_DIR}"

echo "-> 4. Copying physical files to ${CONFIG_DIR}..."
sudo docker cp backup-manager:"${TEMP_RECOVERY_DIR}${CONFIG_DIR}/." "${CONFIG_DIR}/"

echo "-> 5. Setting ownership to ${PUID}:${PGID}..."
sudo chown -R "${PUID}:${PGID}" "${CONFIG_DIR}"

echo "-> 6. Starting Jellyfin container..."
docker start "$CONTAINER"

echo "-> 7. Cleaning up temporary recovery files..."
docker exec -i backup-manager rm -rf "${TEMP_RECOVERY_DIR}"

echo "========== Jellyfin Recovery Completed Successfully =========="
