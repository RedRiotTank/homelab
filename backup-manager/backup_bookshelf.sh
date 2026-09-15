#!/bin/bash
set -eo pipefail

export DOCKER_API_VERSION="1.41"
exec 1>/proc/1/fd/1
exec 2>/proc/1/fd/2

CONTAINER_CALIBRE="${BOOKSHELF_CALIBRE_CONTAINER:-calibre-web}"
CONTAINER_LAZY="${BOOKSHELF_LAZYLIBRARIAN_CONTAINER:-lazylibrarian}"
DATA_DIR="${BOOKSHELF_DATA_DIR:-/opt/bookshelf}"
BOOKS_DIR="${BOOKSHELF_BOOKS_DIR:-/srv/media/books}"
RESTIC_REPO="${BOOKSHELF_RESTIC_REPO:-rclone:gdrive:backups/bookshelf}"
export RESTIC_PASSWORD="${RESTIC_PASSWORD:?Error: undefined RESTIC_PASSWORD}"
export RCLONE_CONFIG="${RCLONE_CONFIG_PATH:-/root/.config/rclone/rclone.conf}"

echo "========== STARTING BOOKSHELF BACKUP =========="

echo "-> Stopping Bookshelf containers to lock state..."
docker stop "$CONTAINER_CALIBRE" "$CONTAINER_LAZY" || true

BACKUP_TARGETS=("$DATA_DIR")
EXCLUDES=()

if [ "${BOOKSHELF_BACKUP_DOWNLOADS:-false}" != "true" ]; then
    echo "-> Excluding downloads folder..."
    EXCLUDES+=("--exclude" "${DATA_DIR}/data/downloads")
fi

if [ "${BOOKSHELF_BACKUP_BOOKS:-false}" = "true" ]; then
    echo "-> Including books and covers library (${BOOKS_DIR})..."
    BACKUP_TARGETS+=("$BOOKS_DIR")
else
    echo "-> Skipping books and covers library (${BOOKS_DIR})..."
fi

echo "-> Uploading snapshot via Restic..."
restic -r "$RESTIC_REPO" backup "${EXCLUDES[@]}" "${BACKUP_TARGETS[@]}"

echo "-> Restarting Bookshelf containers..."
docker start "$CONTAINER_CALIBRE" "$CONTAINER_LAZY" || true

echo "-> Applying retention policy..."
restic -r "$RESTIC_REPO" forget --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune

echo "========== BOOKSHELF BACKUP FINISHED =========="
