#!/bin/bash
set -euo pipefail

export DOCKER_API_VERSION="1.41"
exec 1>/proc/1/fd/1
exec 2>/proc/1/fd/2

run_post_hooks() {
  local exit_code=$?
  POST_HOOKS=$(jq -r --arg s "$SERVICE_NAME" '.[$s].post_hooks[]?' "$JSON_FILE" 2>/dev/null)
  if [ -n "$POST_HOOKS" ]; then
    echo "-> Executing post-hooks (Exit status: $exit_code)..."
    while IFS= read -r hook; do
      [ -n "$hook" ] && eval "$hook" || true
    done <<< "$POST_HOOKS"
  fi
  [ -f "$TEMP_DB_DUMP" ] && rm -f "$TEMP_DB_DUMP"
}
trap run_post_hooks EXIT

SERVICE_NAME="${1}"
JSON_FILE="/app/services.json"

if [ -z "$SERVICE_NAME" ]; then
  echo "ERROR: No service name provided to engine." >&2
  exit 1
fi

echo "========== STARTING BACKUP: $(echo "$SERVICE_NAME" | tr '[:lower:]' '[:upper:]') =========="

ENABLED=$(jq -r --arg s "$SERVICE_NAME" '.[$s].enabled // false' "$JSON_FILE")
if [ "$ENABLED" != "true" ]; then
  echo "Service $SERVICE_NAME is disabled or not found."
  exit 0
fi

RESTIC_REPO=$(jq -r --arg s "$SERVICE_NAME" '.[$s].repo' "$JSON_FILE")
export RESTIC_PASSWORD="${RESTIC_PASSWORD:?Error: undefined RESTIC_PASSWORD}"
export RCLONE_CONFIG="${RCLONE_CONFIG_PATH:-/root/.config/rclone/rclone.conf}"

TEMP_DB_DUMP="/tmp/${SERVICE_NAME}-db.sql"

PRE_HOOKS=$(jq -r --arg s "$SERVICE_NAME" '.[$s].pre_hooks[]?' "$JSON_FILE")
if [ -n "$PRE_HOOKS" ]; then
  echo "-> Executing pre-hooks..."
  while IFS= read -r hook; do
    [ -n "$hook" ] && eval "$hook"
  done <<< "$PRE_HOOKS"
fi

STOP_CONTAINERS=$(jq -r --arg s "$SERVICE_NAME" '.[$s].stop_containers[]?' "$JSON_FILE")
if [ -n "$STOP_CONTAINERS" ]; then
  echo "-> Stopping containers..."
  while IFS= read -r container; do
    [ -n "$container" ] && docker stop "$container"
  done <<< "$STOP_CONTAINERS"
fi

RESTIC_ARGS=()
EXCLUDES=$(jq -r --arg s "$SERVICE_NAME" '.[$s].exclude[]?' "$JSON_FILE")
if [ -n "$EXCLUDES" ]; then
  while IFS= read -r exc; do
    if [[ "$exc" == *"*"* ]]; then
      RESTIC_ARGS+=(--exclude "$exc")
    else
      VOL_PATH=$(jq -r --arg s "$SERVICE_NAME" '.[$s].volumes[0]' "$JSON_FILE")
      RESTIC_ARGS+=(--exclude "${VOL_PATH}/${exc}")
    fi
  done <<< "$EXCLUDES"
fi

    DB_TYPE=$(jq -r --arg s "$SERVICE_NAME" '.[$s].database.type // empty' "$JSON_FILE")
    if [ "$DB_TYPE" == "postgres" ]; then
      DB_CONTAINER=$(jq -r --arg s "$SERVICE_NAME" '.[$s].database.container' "$JSON_FILE")
      DB_USER=$(jq -r --arg s "$SERVICE_NAME" '.[$s].database.user' "$JSON_FILE")
      DB_NAME=$(jq -r --arg s "$SERVICE_NAME" '.[$s].database.db_name' "$JSON_FILE")
      echo "-> Exporting PostgreSQL database ($DB_CONTAINER, DB: $DB_NAME)..."
      docker exec -u postgres "$DB_CONTAINER" pg_dump -U "$DB_USER" "$DB_NAME" > "$TEMP_DB_DUMP"
      RESTIC_ARGS+=("$TEMP_DB_DUMP")
elif [ "$DB_TYPE" == "postgres_all" ]; then
  DB_CONTAINER=$(jq -r --arg s "$SERVICE_NAME" '.[$s].db_container' "$JSON_FILE")
  echo "-> Exporting PostgreSQL all databases ($DB_CONTAINER)..."
  docker exec "$DB_CONTAINER" pg_dumpall -U postgres > "$TEMP_DB_DUMP"
  RESTIC_ARGS+=("$TEMP_DB_DUMP")
fi

VOLUMES=$(jq -r --arg s "$SERVICE_NAME" '.[$s].volumes[]?' "$JSON_FILE")
if [ -n "$VOLUMES" ]; then
  while IFS= read -r vol; do
    [ -n "$vol" ] && RESTIC_ARGS+=("$vol")
  done <<< "$VOLUMES"
fi

SRC_DIRS=$(jq -r --arg s "$SERVICE_NAME" '.[$s].source_dirs[]?' "$JSON_FILE")
if [ -n "$SRC_DIRS" ]; then
  while IFS= read -r src; do
    [ -n "$src" ] && RESTIC_ARGS+=("$src")
  done <<< "$SRC_DIRS"
fi

COND_VOLS=$(jq -c --arg s "$SERVICE_NAME" '.[$s].conditional_volumes[]?' "$JSON_FILE")
if [ -n "$COND_VOLS" ]; then
  while IFS= read -r cond; do
    ENV_FLAG=$(echo "$cond" | jq -r '.env_flag')
    PATH_DIR=$(echo "$cond" | jq -r '.path')
    VAL="${!ENV_FLAG:-false}"
    if [ "$VAL" = "true" ]; then
      echo "-> Including conditional volume ($PATH_DIR) because $ENV_FLAG=true"
      RESTIC_ARGS+=("$PATH_DIR")
    else
      echo "-> Skipping conditional volume ($PATH_DIR) because $ENV_FLAG=$VAL"
    fi
  done <<< "$COND_VOLS"
fi

echo "-> Uploading snapshot to Restic repository ($RESTIC_REPO)..."
restic -r "$RESTIC_REPO" backup "${RESTIC_ARGS[@]}"

[ -f "$TEMP_DB_DUMP" ] && rm -f "$TEMP_DB_DUMP"

echo "-> Applying retention policy..."
restic -r "$RESTIC_REPO" forget --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune

echo "========== BACKUP FINISHED: $(echo "$SERVICE_NAME" | tr '[:lower:]' '[:upper:]') =========="
