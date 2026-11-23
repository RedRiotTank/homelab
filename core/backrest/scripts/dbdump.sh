#!/bin/sh
# Backrest pre-backup hook: consistent logical dumps for all stateful services.
# No container is paused or stopped. Writes to /data/dbdumps (backed up by the
# Core plans). Idempotent: if a successful dump is younger than MAX_AGE, it
# skips so the three Core plans can share the same dump set.

set -eu
umask 077

DUMP_DIR=/data/dbdumps
STAMP="$DUMP_DIR/.last_success"
LOCK="$DUMP_DIR/.lock"
MAX_AGE=21600          # 6 hours
LOCK_STALE=3600        # 1 hour
SQLITE_IMG='lscr.io/linuxserver/calibre-web:latest'

mkdir -p "$DUMP_DIR/sqlite" "$DUMP_DIR/vaultwarden-data" "$DUMP_DIR/tmp"

log() { echo "[dbdump $(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# Skip if a recent successful dump exists (the 3 Core plans run 30 min apart).
if [ -f "$STAMP" ]; then
    now=$(date +%s)
    last=$(cat "$STAMP" 2>/dev/null || echo 0)
    case "$last" in ''|*[!0-9]*) last=0 ;; esac
    if [ $((now - last)) -lt "$MAX_AGE" ]; then
        log "Fresh dump found (less than ${MAX_AGE}s old); skipping"
        exit 0
    fi
fi

# One dump at a time. If a fresh lock exists, fail the plan instead of backing
# up a possibly stale dump set. A lock older than LOCK_STALE is removed.
if ! mkdir "$LOCK" 2>/dev/null; then
    if [ -d "$LOCK" ]; then
        age=$(( $(date +%s) - $(stat -c %Y "$LOCK" 2>/dev/null || echo 0) ))
        if [ "$age" -gt "$LOCK_STALE" ]; then
            log "Removing stale lock (${age}s old)"
            rmdir "$LOCK" 2>/dev/null || true
        fi
    fi
    if ! mkdir "$LOCK" 2>/dev/null; then
        log "ERROR: another dbdump is running; aborting plan" >&2
        exit 1
    fi
fi
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

dump_pg_all() {
    name=$1
    container=$2
    log "PostgreSQL (pg_dumpall): $container"
    docker exec "$container" sh -c \
        'PGPASSWORD="$POSTGRES_PASSWORD" pg_dumpall -U "$POSTGRES_USER"' \
        > "$DUMP_DIR/tmp/$name.sql.part"
    gzip -c "$DUMP_DIR/tmp/$name.sql.part" > "$DUMP_DIR/$name.sql.gz.part"
    mv "$DUMP_DIR/$name.sql.gz.part" "$DUMP_DIR/$name.sql.gz"
    rm -f "$DUMP_DIR/tmp/$name.sql.part"
    gzip -t "$DUMP_DIR/$name.sql.gz"
}

dump_pg_db() {
    name=$1
    container=$2
    log "PostgreSQL (pg_dump -Fc): $container"
    docker exec "$container" sh -c \
        'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
        > "$DUMP_DIR/tmp/$name.dump.part"
    docker exec -i "$container" pg_restore --list \
        < "$DUMP_DIR/tmp/$name.dump.part" > /dev/null
    mv "$DUMP_DIR/tmp/$name.dump.part" "$DUMP_DIR/$name.dump"
}

dump_mariadb() {
    log "MariaDB (mariadb-dump --single-transaction): romm-db"
    docker exec romm-db sh -c \
        'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb-dump -uroot --single-transaction --quick --routines --events --all-databases' \
        > "$DUMP_DIR/tmp/romm-mariadb.sql.part"
    gzip -c "$DUMP_DIR/tmp/romm-mariadb.sql.part" > "$DUMP_DIR/romm-mariadb.sql.gz.part"
    mv "$DUMP_DIR/romm-mariadb.sql.gz.part" "$DUMP_DIR/romm-mariadb.sql.gz"
    rm -f "$DUMP_DIR/tmp/romm-mariadb.sql.part"
    gzip -t "$DUMP_DIR/romm-mariadb.sql.gz"
}

dump_mongo() {
    log "MongoDB (mongodump --archive --gzip): komodo-mongo"
    docker exec komodo-mongo mongodump --archive --gzip \
        > "$DUMP_DIR/tmp/komodo-mongo.archive.gz.part"
    mv "$DUMP_DIR/tmp/komodo-mongo.archive.gz.part" "$DUMP_DIR/komodo-mongo.archive.gz"
    gzip -t "$DUMP_DIR/komodo-mongo.archive.gz"
}

sqlite_backup() {
    name=$1
    container=$2
    path=$3

    if ! docker inspect "$container" >/dev/null 2>&1; then
        log "WARN: container $container not found; skipping SQLite $name"
        return 0
    fi
    if ! docker run --rm --entrypoint /bin/sh --volumes-from "$container" "$SQLITE_IMG" \
            -c "test -f '$path'" >/dev/null 2>&1; then
        log "WARN: $path not found in $container; skipping SQLite $name"
        return 0
    fi

    log "SQLite (online .backup): $name ($container:$path)"
    docker run --rm --entrypoint /usr/bin/sqlite3 \
        --volumes-from "$container" \
        -v backrest_data:/dst \
        "$SQLITE_IMG" \
        "$path" ".backup '/dst/dbdumps/sqlite/$name.sqlite.part'"
    mv "$DUMP_DIR/sqlite/$name.sqlite.part" "$DUMP_DIR/sqlite/$name.sqlite"
}

vaultwarden_data() {
    if ! docker inspect vaultwarden >/dev/null 2>&1; then
        log "WARN: vaultwarden not found; skipping its files"
        return 0
    fi
    log "Vaultwarden: attachments and keys (DB comes from the SQLite dump)"
    rm -rf "$DUMP_DIR/vaultwarden-data"
    mkdir -p "$DUMP_DIR/vaultwarden-data"
    docker run --rm --entrypoint /bin/sh --volumes-from vaultwarden \
        -v backrest_data:/dst "$SQLITE_IMG" -c '
        set -e
        d=/dst/dbdumps/vaultwarden-data
        cp -a /data/config.json /data/rsa_key.pem "$d"/
        for x in attachments sends icon_cache; do
            if [ -d "/data/$x" ]; then cp -a "/data/$x" "$d"/; fi
        done
    '
}

# --- PostgreSQL / MariaDB / MongoDB ---------------------------------------
dump_pg_all appflowy-postgres appflowy-postgres-1
dump_pg_db  nextcloud-postgres nextcloud-db
dump_mariadb
dump_mongo

# --- SQLite (consistent online backups) -----------------------------------
sqlite_backup vaultwarden vaultwarden             /data/db.sqlite3
sqlite_backup npm         nginx-proxy-manager     /data/database.sqlite
sqlite_backup headscale   headscale               /var/lib/headscale/db.sqlite
sqlite_backup homarr      homarr                  /appdata/db/db.sqlite
sqlite_backup sonarr      sonarr                  /config/sonarr.db
sqlite_backup prowlarr    prowlarr                /config/prowlarr.db
sqlite_backup calibre     calibre-web             /config/app.db
sqlite_backup grafana     grafana                 /var/lib/grafana/grafana.db

# --- Files outside the backrest mounts ------------------------------------
vaultwarden_data

# --- Mark success ----------------------------------------------------------
rm -rf "$DUMP_DIR/tmp"
date +%s > "$STAMP"
chmod -R go-rwx "$DUMP_DIR"
log "OK: dumps completed"
ls -lh "$DUMP_DIR" "$DUMP_DIR/sqlite" 2>/dev/null || true
