#!/bin/bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

RESTIC_PASSWORD="${RESTIC_PASSWORD:?Error: undefined RESTIC_PASSWORD}"
RESTIC_REPO="${BOOKSHELF_RESTIC_REPO:-rclone:gdrive:backups/bookshelf}"
DATA_DIR="${BOOKSHELF_DATA_DIR:-/opt/bookshelf}"
BOOKS_DIR="${BOOKSHELF_BOOKS_DIR:-/srv/media/books}"
TEMP_RECOVERY_DIR="${BOOKSHELF_TEMP_DIR:-/tmp/recovery_bookshelf}"
CONTAINER_CALIBRE="${BOOKSHELF_CALIBRE_CONTAINER:-calibre-web}"
CONTAINER_LAZY="${BOOKSHELF_LAZYLIBRARIAN_CONTAINER:-lazylibrarian}"

echo "========== [$(date '+%Y-%m-%d %H:%M:%S')] Starting Bookshelf Disaster Recovery =========="

echo "-> 1. Stopping Bookshelf containers..."
docker stop "$CONTAINER_CALIBRE" "$CONTAINER_LAZY" 2>/dev/null || true

echo "-> 2. Wiping existing configuration metadata..."
sudo rm -rf "${DATA_DIR}/config"
sudo mkdir -p "${DATA_DIR}/config"

echo "-> 3. Downloading snapshot from Restic..."
docker exec \
  -e RESTIC_PASSWORD="${RESTIC_PASSWORD}" \
  backup-manager \
  restic -r "${RESTIC_REPO}" restore latest --target "${TEMP_RECOVERY_DIR}"

echo "-> 4. Restoring physical configuration files..."
sudo docker cp \
  "backup-manager:${TEMP_RECOVERY_DIR}${DATA_DIR}/." \
  "${DATA_DIR}/"

sudo chown -R "${BOOKSHELF_UID:-1001}:${BOOKSHELF_GID:-1001}" "${DATA_DIR}"

if [ "${BOOKSHELF_BACKUP_BOOKS:-false}" = "true" ]; then
    echo "-> 4.1. Restoring books library (${BOOKS_DIR})..."
    sudo mkdir -p "${BOOKS_DIR}"
    sudo docker cp \
      "backup-manager:${TEMP_RECOVERY_DIR}${BOOKS_DIR}/." \
      "${BOOKS_DIR}/"
    sudo chown -R "${BOOKSHELF_UID:-1001}:${BOOKSHELF_GID:-1001}" "${BOOKS_DIR}"
else
    echo "-> 4.1. Skipping books library restore (BOOKSHELF_BACKUP_BOOKS is false)..."
fi

echo "-> 5. Restarting Bookshelf containers..."
cd "${DATA_DIR}" && \
  (docker-compose up -d || \
   docker start "$CONTAINER_CALIBRE" "$CONTAINER_LAZY" || true)

echo "-> 6. Cleaning up temporary recovery files..."
docker exec -i backup-manager rm -rf "${TEMP_RECOVERY_DIR}"

echo "========== [$(date '+%Y-%m-%d %H:%M:%S')] Bookshelf Recovery Completed Successfully =========="
