#!/bin/bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

RESTIC_PASSWORD="${RESTIC_PASSWORD:?Error: undefined RESTIC_PASSWORD}"
RESTIC_REPO="${HOMARR_RESTIC_REPO:-rclone:gdrive:backups/homarr}"
DATA_DIR="${HOMARR_DATA_DIR:-/opt/homarr/appdata}"
CONTAINER="${HOMARR_CONTAINER:-homarr}"
TEMP_RECOVERY_DIR="${HOMARR_TEMP_DIR:-/tmp/recovery_homarr}"

echo "========== [$(date '+%Y-%m-%d %H:%M:%S')] Starting Homarr Disaster Recovery =========="
echo "-> 1. Stopping Homarr container..."
docker stop "$CONTAINER" || true

echo "-> 2. Wiping and recreating data directory..."
sudo rm -rf "${DATA_DIR}"
sudo mkdir -p "${DATA_DIR}"

echo "-> 3. Downloading snapshot from Restic..."
docker exec -e RESTIC_PASSWORD="${RESTIC_PASSWORD}" backup-manager \
  restic -r "${RESTIC_REPO}" restore latest --target "${TEMP_RECOVERY_DIR}"

echo "-> 4. Restoring physical files to ${DATA_DIR}..."
sudo docker cp backup-manager:"${TEMP_RECOVERY_DIR}${DATA_DIR}/." "${DATA_DIR}/"

echo "-> 5. Fixing ownership (node user standard)..."
sudo chown -R 1000:1000 "${DATA_DIR}"

echo "-> 6. Starting Homarr container..."
docker start "$CONTAINER"

echo "-> 7. Cleaning up temporary recovery files..."
docker exec -i backup-manager rm -rf "${TEMP_RECOVERY_DIR}"

echo "========== [$(date '+%Y-%m-%d %H:%M:%S')] Homarr Recovery Completed Successfully =========="
