#!/bin/sh
# Backrest pre-backup hook: stage small, disaster-recovery-critical configuration
# into the Backrest data volume so the Core plans can archive it.
#
# Sources:
#   /backup/opt/stacks/**/.env     Komodo-rendered stack environments
#   $HOST_HOME_DIR                 selected home configuration and SSH keys
#   $HOST_ETC_DIR                  selected host configuration
#
# Output (inside the backrest_data volume, archived by the Core plans):
#   /data/stack-envs/              mirrored opt/stacks tree with .env files
#   /data/home-config/             .ssh, .gnupg, bin, dotfiles, selected .config
#   /data/host-config/             /etc whitelist
#   /data/stack-envs/manifest.sha256
#
# The script is intentionally fail-closed: if a mandatory file cannot be
# staged, the backup plan fails instead of silently archiving less coverage.

set -eu
umask 077

DATA_DIR=${DATA_DIR:-/data}
STAGE_TMP="$DATA_DIR/.collect-config.tmp"
STACK_OUT="$DATA_DIR/stack-envs"
HOME_OUT="$DATA_DIR/home-config"
HOST_OUT="$DATA_DIR/host-config"
LOCK="$DATA_DIR/.collect-config.lock"
LOCK_STALE=${LOCK_STALE:-3600}
HOST_HOME_DIR=${HOST_HOME_DIR:-/home/deployer}
HOST_ETC_DIR=${HOST_ETC_DIR:-/etc}
HELPER_IMAGE=${HELPER_IMAGE:-ghcr.io/garethgeorge/backrest:latest}
BACKREST_DATA_VOLUME=${BACKREST_DATA_VOLUME:-backrest_data}
MIN_STACK_ENVS=${MIN_STACK_ENVS:-10}

log() { echo "[collect-config $(date '+%Y-%m-%d %H:%M:%S')] $*"; }
fail() { log "ERROR: $*" >&2; exit 1; }

mkdir -p "$DATA_DIR"

if ! mkdir "$LOCK" 2>/dev/null; then
    if [ -d "$LOCK" ]; then
        age=$(( $(date +%s) - $(stat -c %Y "$LOCK" 2>/dev/null || echo 0) ))
        if [ "$age" -gt "$LOCK_STALE" ]; then
            log "Removing stale lock (${age}s old)"
            rmdir "$LOCK" 2>/dev/null || true
        fi
    fi
    if ! mkdir "$LOCK" 2>/dev/null; then
        fail "another collect-config run is in progress"
    fi
fi
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

rm -rf "$STAGE_TMP"
mkdir -p "$STAGE_TMP/stack-envs" "$STAGE_TMP/home-config" "$STAGE_TMP/host-config"

# --- 1. Stack environments rendered by Komodo ------------------------------
log "staging stack .env files from /backup/opt/stacks"
find /backup/opt/stacks -type f -name '.env' 2>/dev/null | while IFS= read -r src; do
    rel=${src#/backup/}
    dest="$STAGE_TMP/stack-envs/$rel"
    mkdir -p "$(dirname "$dest")"
    cp -a "$src" "$dest"
done

STACK_COUNT=$(find "$STAGE_TMP/stack-envs" -type f -name '.env' | wc -l)
[ "$STACK_COUNT" -ge "$MIN_STACK_ENVS" ] || \
    fail "only $STACK_COUNT stack .env files found (minimum $MIN_STACK_ENVS)"
find "$STAGE_TMP/stack-envs" -type f -name '.env' -exec chmod 600 {} \;
log "staged $STACK_COUNT stack .env files"

# Record the homelab commit for provenance. The .git directory itself is
# excluded from the backup, but this small file survives inside stack-envs.
if [ -f /backup/homelab/.git/HEAD ]; then
    head_value=$(cat /backup/homelab/.git/HEAD 2>/dev/null || true)
    case "$head_value" in
        ref:\ *)
            ref=${head_value#ref: }
            commit=$(cat "/backup/homelab/.git/$ref" 2>/dev/null || true)
            if [ -z "$commit" ] && [ -f /backup/homelab/.git/packed-refs ]; then
                commit=$(awk -v ref="$ref" '$2 == ref {print $1; exit}' \
                    /backup/homelab/.git/packed-refs 2>/dev/null || true)
            fi
            ;;
        *)
            commit=$head_value
            ;;
    esac
    {
        echo "head=$head_value"
        echo "commit=$commit"
    } > "$STAGE_TMP/stack-envs/git-head.txt"
    chmod 600 "$STAGE_TMP/stack-envs/git-head.txt"
fi

# --- 2. Home and host configuration ---------------------------------------
# Use a short-lived helper container so /home/deployer and /etc do not have to
# be mounted into the long-running Backrest container. The Docker socket is
# already available for the existing dbdump hook.
log "staging home config ($HOST_HOME_DIR) and host config ($HOST_ETC_DIR)"

docker run --rm \
    --entrypoint /bin/sh \
    -v "$HOST_HOME_DIR:/src-home:ro" \
    -v "$HOST_ETC_DIR:/src-etc:ro" \
    -v "$BACKREST_DATA_VOLUME:/dst" \
    "$HELPER_IMAGE" -c '
        set -eu
        umask 077
        out=/dst/.collect-config.tmp
        home_out="$out/home-config"
        host_out="$out/host-config"

        strip_sockets() {
            find "$1" -type s -delete 2>/dev/null || true
        }

        # Home configuration: keep it small and explicit.
        for path in .ssh .gnupg bin; do
            if [ -e "/src-home/$path" ]; then
                cp -a "/src-home/$path" "$home_out/"
            fi
        done
        for file in .gitconfig .bashrc .bash_aliases .profile .selected_editor \
                    alertmanager-telegram.local.yml; do
            if [ -e "/src-home/$file" ]; then
                cp -a "/src-home/$file" "$home_out/"
            fi
        done
        if [ -d /src-home/.config ]; then
            mkdir -p "$home_out/.config"
            tar -C /src-home/.config \
                --exclude=opencode --exclude=rclone --exclude=herdr \
                -cf - . | tar -C "$home_out/.config" -xf -
        fi
        strip_sockets "$home_out"

        # Host configuration whitelist. Machine identity and host keys are
        # deliberately excluded.
        for file in ssh/sshd_config ssh/ssh_config fstab hosts hostname timezone \
                    sysctl.conf nsswitch.conf rc.local crontab default/grub \
                    network/interfaces apt/sources.list docker/daemon.json; do
            if [ -f "/src-etc/$file" ]; then
                mkdir -p "$host_out/$(dirname "$file")"
                cp -a "/src-etc/$file" "$host_out/$file"
            fi
        done
        for dir in systemd/system sysctl.d cron.d apt/sources.list.d \
                   ssh/sshd_config.d iptables NetworkManager/system-connections; do
            if [ -d "/src-etc/$dir" ]; then
                mkdir -p "$host_out/$dir"
                tar -C "/src-etc/$dir" --exclude='*.swp' --exclude='.*.swp' -cf - . 2>/dev/null | \
                    tar -C "$host_out/$dir" -xf - 2>/dev/null || true
            fi
        done
        strip_sockets "$host_out"
    '

[ -d "$STAGE_TMP/home-config/.ssh" ] || fail "home .ssh directory was not staged"
[ -f "$STAGE_TMP/home-config/alertmanager-telegram.local.yml" ] || \
    fail "alertmanager-telegram.local.yml was not staged"

HOST_COUNT=$(find "$STAGE_TMP/host-config" -type f | wc -l)
[ "$HOST_COUNT" -gt 0 ] || fail "host configuration whitelist is empty"
log "staged home config and $HOST_COUNT host config files"

# --- 3. Manifest and notes -------------------------------------------------
{
    echo "# collect-config manifest"
    echo "# generated: $(date -Is)"
    echo "# source-home: $HOST_HOME_DIR"
    echo "# source-etc: $HOST_ETC_DIR"
    (cd "$STAGE_TMP" && find . -type f ! -name manifest.sha256 -exec sha256sum {} \; | sort)
} > "$STAGE_TMP/manifest.sha256"

cat > "$STAGE_TMP/README.md" <<'EOF'
# Staged disaster-recovery configuration

Generated by `/data/scripts/collect-config.sh` at Backrest snapshot start.

- `stack-envs/opt/stacks/.../.env` — environments rendered by Komodo.
- `home-config/` — selected `/home/deployer` files (`.ssh`, `.gnupg`, `bin`,
  shell dotfiles, selected `.config`, Telegram Alertmanager config).
- `host-config/` — selected `/etc` whitelist (systemd units, sshd, fstab,
  sysctl, apt sources, firewall files).
- `manifest.sha256` — hashes of every staged file.

`rclone.conf`, caches, editor data, shell history, machine identity and SSH
host keys are intentionally excluded.

See `docs/backup-verification.md` and `docs/disaster-recovery.md`.
EOF

chmod -R go-rwx "$STAGE_TMP"

# --- 4. Publish atomically -------------------------------------------------
rm -rf "$STACK_OUT" "$HOME_OUT" "$HOST_OUT"
mv "$STAGE_TMP/stack-envs" "$STACK_OUT"
mv "$STAGE_TMP/home-config" "$HOME_OUT"
mv "$STAGE_TMP/host-config" "$HOST_OUT"
mv "$STAGE_TMP/manifest.sha256" "$STACK_OUT/manifest.sha256"
mv "$STAGE_TMP/README.md" "$STACK_OUT/README.md"
rmdir "$STAGE_TMP"

log "OK: stack-envs=$STACK_COUNT home=$(du -sh "$HOME_OUT" | awk '{print $1}') host=$HOST_COUNT files"
