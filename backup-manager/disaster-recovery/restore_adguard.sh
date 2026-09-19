#!/bin/bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$DIR/.env" ]; then
    set -a
    source "$DIR/.env"
    set +a
fi

RESTIC_PASSWORD="${RESTIC_PASSWORD}"
RESTIC_REPO="rclone:gdrive:backups/adguard"
TARGET_DIR="/opt/adguard"
TEMP_RECOVERY_DIR="/tmp/recovery_adguard"

echo "=== [$(date '+%Y-%m-%d %H:%M:%S')] Starting AdGuard Home Disaster Recovery ==="

echo "-> 1. Stopping AdGuard Home container..."
cd "$TARGET_DIR" && docker compose down || true

echo "-> 2. Downloading latest snapshot from Google Drive..."
docker exec -e RESTIC_PASSWORD="${RESTIC_PASSWORD}" backup-manager \
  restic -r "${RESTIC_REPO}" restore latest --target "${TEMP_RECOVERY_DIR}"

echo "-> 3. Restoring configuration files..."
sudo docker cp backup-manager:"${TEMP_RECOVERY_DIR}${TARGET_DIR}/conf/." "${TARGET_DIR}/conf/"

echo "-> 4. Restarting AdGuard Home..."
cd "$TARGET_DIR" && docker compose up -d

echo "-> 5. Cleaning up temporary recovery files..."
docker exec -i backup-manager rm -rf "${TEMP_RECOVERY_DIR}"

echo "=== [$(date '+%Y-%m-%d %H:%M:%S')] AdGuard Home Recovery Completed Successfully ==="
