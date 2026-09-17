#!/bin/bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

RESTIC_PASSWORD="${RESTIC_PASSWORD:?Error: undefined RESTIC_PASSWORD}"
RESTIC_REPO="${ARR_RESTIC_REPO:-rclone:gdrive:backups/arr}"
DATA_DIR="${ARR_DATA_DIR:-/opt/arr-stack}"
TEMP_RECOVERY_DIR="${ARR_TEMP_DIR:-/tmp/recovery_arr}"
BACKEND_CONTAINER="backup-manager"

echo "========== [$(date '+%Y-%m-%d %H:%M:%S')] Starting Arr Stack Disaster Recovery =========="

echo "-> 1. Stopping Arr stack..."
(cd "${DATA_DIR}" && docker compose down 2>/dev/null) || true

echo "-> 2. Downloading snapshot from Restic..."
docker exec -e RESTIC_PASSWORD="${RESTIC_PASSWORD}" "$BACKEND_CONTAINER" \
  restic -r "${RESTIC_REPO}" restore latest --target "${TEMP_RECOVERY_DIR}"

echo "-> 3. Restoring configuration files to ${DATA_DIR}..."
sudo docker cp "$BACKEND_CONTAINER:${TEMP_RECOVERY_DIR}${DATA_DIR}/." "${DATA_DIR}/"

echo "-> 4. Fixing ownership and permissions..."
sudo chown -R 1001:1001 "${DATA_DIR}/qbit-config" "${DATA_DIR}/sonarr" "${DATA_DIR}/prowlarr" 2>/dev/null || true
[ -d "${DATA_DIR}/kitsunarr-data" ] && sudo chown -R 1001:1001 "${DATA_DIR}/kitsunarr-data" "${DATA_DIR}/kitsunarr-secrets" 2>/dev/null || true

echo "-> 5. Recreating and starting Arr stack..."
cd "${DATA_DIR}" && docker compose up -d --remove-orphans

echo "-> 6. Cleaning up temporary recovery files..."
docker exec -i "$BACKEND_CONTAINER" rm -rf "${TEMP_RECOVERY_DIR}"

echo "========== [$(date '+%Y-%m-%d %H:%M:%S')] Arr Stack Recovery Completed Successfully =========="
