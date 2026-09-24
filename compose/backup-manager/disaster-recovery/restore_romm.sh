#!/bin/bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

RESTIC_PASSWORD="${RESTIC_PASSWORD:?Error: undefined RESTIC_PASSWORD}"
RESTIC_REPO="${ROMM_RESTIC_REPO:-rclone:gdrive:backups/romm}"
DATA_DIR="${ROMM_DATA_DIR:-/opt/romm}"
TEMP_RECOVERY_DIR="${ROMM_TEMP_DIR:-/tmp/recovery_romm}"
CONTAINER_ROMM="${ROMM_CONTAINER:-romm}"
CONTAINER_DB="${ROMM_DB_CONTAINER:-romm-db}"

echo "========== Starting RomM Disaster Recovery =========="

echo "-> 1. Stopping RomM container..."
docker stop "$CONTAINER_ROMM" || true

echo "-> 2. Wiping corrupted metadata (keeping library intact)..."
sudo rm -rf "${DATA_DIR}/assets" "${DATA_DIR}/config" "${DATA_DIR}/resources"
sudo mkdir -p "${DATA_DIR}/assets" "${DATA_DIR}/config" "${DATA_DIR}/resources"

echo "-> 3. Downloading snapshot from Restic..."
docker exec \
    -e RESTIC_PASSWORD="${RESTIC_PASSWORD}" \
    backup-manager \
    restic -r "${RESTIC_REPO}" restore latest --target "${TEMP_RECOVERY_DIR}"

echo "-> 4. Restoring MariaDB database..."
docker exec -i backup-manager \
    cat "${TEMP_RECOVERY_DIR}/tmp/romm-db.sql" | \
    docker exec -i "$CONTAINER_DB" \
    sh -c 'mariadb -u "$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE"'

echo "-> 5. Restoring physical configuration and assets..."
sudo docker cp \
    "backup-manager:${TEMP_RECOVERY_DIR}${DATA_DIR}/." \
    "${DATA_DIR}/"

sudo chown -R 1000:1000 \
    "${DATA_DIR}/assets" \
    "${DATA_DIR}/config" \
    "${DATA_DIR}/resources"

echo "-> 6. Starting RomM container..."
docker start "$CONTAINER_ROMM"

echo "-> 7. Cleaning up..."
docker exec -i backup-manager \
    rm -rf "${TEMP_RECOVERY_DIR}"

echo "========== RomM Recovery Completed Successfully =========="
