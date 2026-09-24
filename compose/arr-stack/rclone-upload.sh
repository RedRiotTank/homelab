#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

LOCK_FILE="/tmp/rclone_upload.lock"
LOG_FILE="${RCLONE_UPLOAD_LOG:-/opt/arr-stack/rclone-upload.log}"
DESTINATION_RCLONE="${RCLONE_UPLOAD_DESTINATION:-private_remote:uploads}"
SOURCE_LOCAL="${RCLONE_UPLOAD_SOURCE:-/srv/media-local/Anime}"

if [ -f "$LOCK_FILE" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Upload skipped: process already running." >> "$LOG_FILE"
    exit 1
fi

if [ ! -d "$SOURCE_LOCAL" ] || [ -z "$(ls -A "$SOURCE_LOCAL" 2>/dev/null)" ]; then
    exit 0
fi

touch "$LOCK_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Starting upload to ${DESTINATION_RCLONE} ===" >> "$LOG_FILE"

rclone move "$SOURCE_LOCAL" "$DESTINATION_RCLONE" \
    --delete-empty-src-dirs \
    --transfers 1 \
    --checkers 2 \
    --timeout 30s \
    --contimeout 15s \
    --log-file="$LOG_FILE" \
    --log-level INFO \
    --stats 20s

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Upload completed successfully ===" >> "$LOG_FILE"

rm -f "$LOCK_FILE"
