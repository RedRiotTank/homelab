#!/bin/bash
# AppFlowy Full Disaster Recovery Script
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/.env" ]; then
  export $(grep -v '^#' "$SCRIPT_DIR/.env" | xargs)
fi

RESTIC_PASSWORD="${RESTIC_PASSWORD:?Error: undefined RESTIC_PASSWORD}"
RESTIC_REPO="${APPFLOWY_RESTIC_REPO:-rclone:gdrive:backups/appflowy}"
TEMP_RECOVERY_DIR="${APPFLOWY_TEMP_DIR:-/tmp/recovery_af}"

DB_CONTAINER="${APPFLOWY_DB_CONTAINER:-appflowy_postgres_1}"
MINIO_CONTAINER="${APPFLOWY_MINIO_CONTAINER:-appflowy_minio_1}"
APP_CONTAINERS="${APPFLOWY_APP_CONTAINERS:-appflowy_appflowy_cloud_1 appflowy_appflowy_worker_1 appflowy_appflowy_web_1 appflowy_gotrue_1 appflowy_nginx_1 appflowy_redis_1}"

echo "=== [$(date '+%Y-%m-%d %H:%M:%S')] Starting AppFlowy Disaster Recovery ==="

echo "-> 1. Stopping AppFlowy application containers..."
docker stop $APP_CONTAINERS

echo "-> 2. Wiping existing PostgreSQL database schema..."
docker exec -i "$DB_CONTAINER" psql -U postgres -d postgres -c "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;"
docker exec -i "$DB_CONTAINER" psql -U postgres -d postgres -c "DROP SCHEMA IF EXISTS auth CASCADE;"

echo "-> 3. Wiping existing MinIO storage data..."
docker exec -i "$MINIO_CONTAINER" sh -c 'rm -rf /data/* /data/.[!.]* 2>/dev/null || true'

echo "-> 4. Downloading latest snapshot..."
docker exec -e RESTIC_PASSWORD="${RESTIC_PASSWORD}" backup-manager \
  restic -r "${RESTIC_REPO}" restore latest --target "${TEMP_RECOVERY_DIR}"

echo "-> 5. Restoring PostgreSQL database..."
docker exec -i backup-manager cat "${TEMP_RECOVERY_DIR}/tmp/appflowy-db.sql" | \
  docker exec -i "$DB_CONTAINER" psql -U postgres -d postgres

echo "-> 6. Restoring MinIO physical files..."
docker exec -i backup-manager bash -c "docker cp ${TEMP_RECOVERY_DIR}/tmp/minio_data_dump/. ${MINIO_CONTAINER}:/data/"

echo "-> 7. Cleaning up temporary recovery files..."
docker exec -i backup-manager rm -rf "${TEMP_RECOVERY_DIR}"

echo "-> 8. Restarting AppFlowy containers..."
docker start $APP_CONTAINERS

echo "=== [$(date '+%Y-%m-%d %H:%M:%S')] AppFlowy Recovery Completed Successfully ==="
