#!/bin/bash
# Nextcloud Full Disaster Recovery Script
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/.env" ]; then
  export $(grep -v '^#' "$SCRIPT_DIR/.env" | xargs)
fi

RESTIC_PASSWORD="${RESTIC_PASSWORD:?Error: undefined RESTIC_PASSWORD}"
RESTIC_REPO="${NEXTCLOUD_RESTIC_REPO:-rclone:gdrive:backups/nextcloud}"
DATA_DIR="${NEXTCLOUD_DATA_DIR:-/srv/nextcloud_data}"
DB_USER="${NEXTCLOUD_DB_USER:-nextcloud_user}"
DB_NAME="${NEXTCLOUD_DB_NAME:-nextcloud}"
TEMP_RECOVERY_DIR="${NEXTCLOUD_TEMP_DIR:-/tmp/recovery_nc}"
CONTAINER_NC="${NEXTCLOUD_CONTAINER:-nextcloud}"
CONTAINER_DB="${NEXTCLOUD_DB_CONTAINER:-nextcloud-db}"
WEB_UID="${NEXTCLOUD_WEB_UID:-33}"
WEB_GID="${NEXTCLOUD_WEB_GID:-33}"

echo "========== [$(date '+%Y-%m-%d %H:%M:%S')] Starting Nextcloud Disaster Recovery =========="

echo "-> 1. Stopping Nextcloud container..."
docker stop "$CONTAINER_NC"

echo "-> 2. Wiping existing database schema..."
docker exec -i "$CONTAINER_DB" psql -U "$DB_USER" -d "$DB_NAME" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

echo "-> 3. Wiping and recreating data directory..."
sudo rm -rf "${DATA_DIR}"
sudo mkdir -p "${DATA_DIR}"

echo "-> 4. Downloading snapshot from Restic..."
docker exec -e RESTIC_PASSWORD="${RESTIC_PASSWORD}" backup-manager \
  restic -r "${RESTIC_REPO}" restore latest --target "${TEMP_RECOVERY_DIR}"

echo "-> 5. Restoring PostgreSQL database..."
docker exec -i backup-manager cat "${TEMP_RECOVERY_DIR}/tmp/nextcloud-db.sql" | \
  docker exec -i "$CONTAINER_DB" psql -U "$DB_USER" -d "$DB_NAME"

echo "-> 6. Restoring physical files to ${DATA_DIR}..."
sudo docker cp backup-manager:"${TEMP_RECOVERY_DIR}${DATA_DIR}/." "${DATA_DIR}/"

echo "-> 7. Fixing ownership and permissions..."
sudo chown -R "${WEB_UID}:${WEB_GID}" "${DATA_DIR}"
sudo chmod 0750 "${DATA_DIR}"

echo "-> 8. Fixing PostgreSQL database permissions..."
docker exec -i "$CONTAINER_DB" psql -U "$DB_USER" -d "$DB_NAME" -c "
GRANT USAGE, CREATE ON SCHEMA public TO PUBLIC;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO PUBLIC;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO PUBLIC;
ALTER DATABASE ${DB_NAME} SET search_path TO public;
"

echo "-> 9. Restarting containers..."
docker restart "$CONTAINER_DB" "$CONTAINER_NC"

echo "-> 10. Waiting 10 seconds for database initialization..."
sleep 10

echo "-> 11. Disabling maintenance mode..."
docker exec -u www-data "$CONTAINER_NC" php occ maintenance:mode --off || true

echo "-> 12. Cleaning up temporary recovery files..."
docker exec -i backup-manager rm -rf "${TEMP_RECOVERY_DIR}"

echo "========== [$(date '+%Y-%m-%d %H:%M:%S')] Nextcloud Recovery Completed Successfully =========="
