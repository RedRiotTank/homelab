# Disaster recovery runbook

Status: **Draft — Phase 1 coverage implemented; clean-room drill pending (Phase 5)**
Last reviewed: 2026-11-23
Companion document: [`backup-verification.md`](./backup-verification.md)

This is the procedure to rebuild the homelab on a clean host after loss of the
primary server. It assumes the external VeraCrypt recovery kit is available and
that the Backrest/Restic repositories are reachable.

> **Do not treat this runbook as validated until Phase 5 has been completed on a
> disposable host and the measured RTO has been recorded in §12.**

## 1. Scope and assumptions

| Item | Value |
| --- | --- |
| RPO | 24 hours (database dumps at most 6 hours old inside a snapshot) |
| RTO target | 4–8 hours |
| Primary host | `RedServer`, Debian 12, Docker 20.10.24, `/srv` on a 1.8 TB disk |
| Edge host | `CrimsonServer` (Tailscale/Headscale client, Komodo periphery, monitoring agent) |
| Domain | `redriottank.com` (Cloudflare) |
| Repositories | `local-repo-srv`, `GDrive-RedServer`, `miixzify` |
| Recovery kit | VeraCrypt USB with Restic password and `rclone.conf` |

The runbook covers the **primary node**. The edge node is covered in §10.

## 2. Recovery kit checklist

Before starting, confirm the USB contains:

- [ ] Restic repository password(s) for all three repositories.
- [ ] `rclone.conf` with the `gdrive` and `chitogeshared` remotes.
- [ ] Repository URIs and a recent Backrest config export.
- [ ] GitHub access for `RedRiotTank/homelab` (SSH key or token).
- [ ] Cloudflare account access and the `CF_API_TOKEN` used by DDNS.
- [ ] Telegram bot token and chat ID (also inside the backup, but useful now).
- [ ] Komodo passkey and `KOMODO_JWT_SECRET` (also in `/opt/core/komodo/.env`).
- [ ] This runbook and `backup-verification.md`.
- [ ] A known-good snapshot ID and date.

If the kit cannot be read, stop. The repositories cannot be opened without the
Restic password.

## 3. Decision tree

| Situation | Action |
| --- | --- |
| Disk failure, host otherwise intact | Replace disk, restore from the most recent local/remote snapshot. |
| Host lost / stolen / unrecoverable | Full runbook on a new host. |
| Ransomware or destructive change | Isolate the host, preserve evidence, restore from a snapshot **older than the compromise**. |
| Only one service damaged | Restore that service's files/volume from a snapshot; no full rebuild. |
| Cloud repo unavailable | Use the other cloud repo or the local repo. Local lacks `nextcloud_data`. |
| Local repo unavailable | Use either cloud repo. Both contain Core and HeavyData. |

## 4. Phase A — Declare and contain

1. Record the incident start time and the chosen recovery point.
2. If the host is still running and compromised, disconnect it from the network.
3. Do **not** start new backups over the affected repository.
4. Note which snapshot you intend to restore and why (timestamp and repository).
5. Keep a timing log: every phase start/end goes into §12.

## 5. Phase B — Provision the replacement host

1. Install Debian 12 (or the current stable equivalent).
2. Create the `deployer` user with the same UID/GID if possible (`1001:1001` is
   used by several bind-mounted services).
3. Install Docker Engine and the Compose plugin.
4. Install the recovery tooling: `restic`, `rclone`, `rsync`, `sqlite3`,
   `postgresql-client` and `jq`.
5. Create the data disk layout:
   - `/srv` on the large disk (1.8 TB or larger).
   - Root filesystem with enough space for Docker images and the restored
     `/var/lib/docker/volumes`.
6. Configure timezone `Europe/Madrid`, NTP and the hostname `RedServer`.
7. Restore or recreate SSH access for `deployer`.
8. Do **not** copy `/etc/machine-id`, `/etc/docker/key.json` or the old SSH host
   keys from the backup. Generate new ones.
9. Install any host-level prerequisites that are not in the backup:
   - `pm2` if `/etc/systemd/system/pm2-root.service` is used.
   - `rclone` if `rclone-media.service` is used.
   - Firewall rules and any GPU/transcoding drivers for Jellyfin.
10. Create external networks only after the owning stacks are restored:
    - `proxy_net` is created by `proxy-stack`.
    - `monitoring` is created by `monitoring-stack-gpnc`.
    - `headscale_internal` and `komodo_internal` are created by their stacks.

## 6. Phase C — Access the repositories

On the new host, mount the VeraCrypt USB and export the secrets **in the current
shell only** (do not write them to disk):

```bash
export RESTIC_PASSWORD='<from the recovery kit>'
export RCLONE_CONFIG=/run/media/deployer/<usb>/rclone.conf
```

Verify each repository:

```bash
restic -r /srv/backups/backrest_repo snapshots --no-lock
restic -r rclone:gdrive:backups/redserver snapshots --no-lock
restic -r rclone:chitogeshared:backrest_backup snapshots --no-lock
```

If `--no-lock` is rejected by the installed Restic version, use a writable
temporary copy of the repository or run the command as a user that can write the
lock file. Never run a write operation against a repository you are only
inspecting.

Choose the repository and snapshot:

```bash
export RESTIC_REPOSITORY=/srv/backups/backrest_repo   # or a rclone: URI
export SNAP=<snapshot-id>
export REMOTE_REPOSITORY=<rclone:...>                 # if restoring HeavyData
export HEAVY_SNAP=<heavy-snapshot-id>
```

Prefer the newest snapshot that predates the incident. For a destructive change,
choose one before the change.

## 7. Phase D — Restore the host data

Restore into a staging directory first; do not overwrite `/` blindly.

```bash
mkdir -p /restore
restic -r "$RESTIC_REPOSITORY" restore "$SNAP" \
  --target /restore --verify --no-lock
```

Then copy the required trees into place. The snapshot uses the paths as they
existed inside the Backrest container (`/backup/...`, `/data/...`), not the host
paths.

### 7.1 Restore order

1. Stop Docker before restoring `/var/lib/docker/volumes`:
   ```bash
   systemctl stop docker
   ```
2. Restore `/opt` (excluding `/opt/stacks`, which is not in the snapshot):
   ```bash
   rsync -aHAX /restore/backup/opt/ /opt/
   ```
3. Restore the homelab working tree. The `.git` directory is excluded from the
   backup, so clone the repository first and then overlay the restored files
   (including gitignored local files):
   ```bash
   git clone git@github.com:RedRiotTank/homelab.git /home/deployer/homelab
   rsync -aHAX /restore/backup/homelab/ /home/deployer/homelab/
   chown -R deployer:deployer /home/deployer/homelab
   git -C /home/deployer/homelab status --short
   ```
   If GitHub is unreachable, restore the working tree and run `git init` plus
   the remote configuration manually.
4. Restore Docker volumes (the snapshot path is `/backup/docker_volumes`; this
   includes `metadata.db`):
   ```bash
   rsync -aHAX /restore/backup/docker_volumes/ /var/lib/docker/volumes/
   ```
5. Start Docker and verify that the volumes are visible:
   ```bash
   systemctl start docker
   docker volume ls
   ```
   If Docker rejects the restored `metadata.db`, create the missing volumes with
   `docker volume create <name>` and restore only their `_data` directories.
6. Create the excluded Backrest volume and restore its dump staging tree:
   ```bash
   docker volume create backrest_data
   rsync -aHAX /restore/data/dbdumps/ /var/lib/docker/volumes/backrest_data/_data/dbdumps/
   rsync -aHAX /restore/data/scripts/ /var/lib/docker/volumes/backrest_data/_data/scripts/
   ```
   The `backrest_data` volume itself is excluded from the backup, but the
   `/data/dbdumps` and `/data/scripts` subtrees are included and are restored
   here.
7. Restore the staged configuration trees (Phase 1):
   ```bash
   rsync -aHAX /restore/data/stack-envs/ /var/lib/docker/volumes/backrest_data/_data/stack-envs/
   rsync -aHAX /restore/data/home-config/ /var/lib/docker/volumes/backrest_data/_data/home-config/
   rsync -aHAX /restore/data/host-config/ /var/lib/docker/volumes/backrest_data/_data/host-config/
   ```
8. Restore the home configuration to `/home/deployer` (see §7.3).
9. Restore `nextcloud_data` from a HeavyData snapshot:
   ```bash
   restic -r "$REMOTE_REPOSITORY" restore "$HEAVY_SNAP" \
     --target /restore-heavy --include /backup/srv/nextcloud_data --verify --no-lock
   rsync -aHAX /restore-heavy/backup/srv/nextcloud_data/ /srv/nextcloud_data/
   chown -R www-data:www-data /srv/nextcloud_data
   ```
10. Restore the host configuration whitelist from §7.4, or recreate it manually.

### 7.2 Ownership and permissions

Restic restores ownership and modes. After copying, verify:

```bash
stat -c '%U:%G %a %n' /opt/core/vaultwarden/vw-data /srv/nextcloud_data
```

- Nextcloud data must be owned by `www-data` (`33:33`).
- Bind mounts used by LinuxServer images expect `PUID=1001` / `PGID=1001`.
- Files under `/opt/core` and `/opt/compose` are mostly root-owned; preserve
  that.

### 7.3 Home configuration

The backup contains the staged home configuration under
`/data/home-config/`, not a raw copy of the whole home directory. Restore:

```bash
install -d -m 0700 /home/deployer/.ssh /home/deployer/.gnupg
rsync -aHAX /restore/data/home-config/.ssh/ /home/deployer/.ssh/
rsync -aHAX /restore/data/home-config/.gnupg/ /home/deployer/.gnupg/
rsync -aHAX /restore/data/home-config/.config/ /home/deployer/.config/
rsync -aHAX /restore/data/home-config/bin/ /home/deployer/bin/
for f in .gitconfig .bashrc .bash_aliases .profile .selected_editor; do
  cp -a "/restore/data/home-config/$f" "/home/deployer/$f"
done
cp -a /restore/data/home-config/alertmanager-telegram.local.yml /home/deployer/
chown -R deployer:deployer /home/deployer/.ssh /home/deployer/.gnupg \
  /home/deployer/.config /home/deployer/bin /home/deployer/.gitconfig \
  /home/deployer/.bashrc /home/deployer/.bash_aliases /home/deployer/.profile \
  /home/deployer/.selected_editor
chmod 600 /home/deployer/alertmanager-telegram.local.yml
```

`/home/deployer/.config/rclone/rclone.conf` is **not** in the backup. Copy it
from the VeraCrypt kit only when needed, and remove it afterwards if the host is
not the normal backup host.

### 7.4 Host configuration

The Phase 1 whitelist is stored under `/restore/data/host-config/`. Restore it
selectively and run `systemctl daemon-reload` afterwards:

```bash
rsync -aHAX /restore/data/host-config/ /etc/
systemctl daemon-reload
```

Use `/restore/data/stack-envs/manifest.sha256` to verify the staged files. The
whitelist includes systemd units, `sshd_config`, `fstab`, `hosts`, `hostname`,
timezone, sysctl, APT sources, cron, iptables and `docker/daemon.json` when
present. It deliberately excludes `/etc/machine-id`, `/etc/docker/key.json`,
`/etc/ssh/ssh_host_*` and `/etc/shadow`.

Router/NAT rules, public DNS records, the VeraCrypt kit and the domain registrar
remain manual steps. See §10.

## 8. Phase E — Restore databases

Start only the database services first. Use the stack's own Compose file and
`.env` so the container names, users and passwords match.

> The raw database volumes are excluded from the backup. Start each database
> with an empty volume/bind, then import the logical dump.

### 8.1 PostgreSQL — AppFlowy

```bash
gunzip -c /restore/data/dbdumps/appflowy-postgres.sql.gz \
  | docker exec -i appflowy-postgres-1 sh -c 'psql -U "$POSTGRES_USER" -d postgres'
```

`pg_dumpall` includes roles and databases. If the restore reports existing
objects, use a clean volume and retry.

### 8.2 PostgreSQL — Nextcloud

```bash
docker exec -i nextcloud-db sh -c \
  'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
   --clean --if-exists --no-owner --no-privileges' \
  < /restore/data/dbdumps/nextcloud-postgres.dump
```

`--no-owner` avoids failures if role names differ. Validate with a `psql` count
on `oc_users` or the Nextcloud admin page.

### 8.3 MariaDB — Romm

```bash
gunzip -c /restore/data/dbdumps/romm-mariadb.sql.gz \
  | docker exec -i romm-db sh -c \
    'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb -uroot'
```

The dump uses `--all-databases`, so it recreates the Romm schema.

### 8.4 MongoDB — Komodo

```bash
docker exec -i komodo-mongo mongorestore --archive --gzip --drop \
  < /restore/data/dbdumps/komodo-mongo.archive.gz
```

This restores the `komodo` database, including `Stack.config.environment`, which
is the source of truth for the 12 stack `.env` files.

### 8.5 SQLite

Prefer the consistent `.sqlite` dumps over the raw live files restored from the
volume. Copy each dump to its runtime path:

| Dump | Runtime path |
| --- | --- |
| `sqlite/vaultwarden.sqlite` | `/opt/core/vaultwarden/vw-data/db.sqlite3` |
| `sqlite/npm.sqlite` | `/var/lib/docker/volumes/npm_data/_data/database.sqlite` |
| `sqlite/headscale.sqlite` | `/var/lib/docker/volumes/headscale_data/_data/db.sqlite` |
| `sqlite/homarr.sqlite` | `/opt/compose/homarr/appdata/db/db.sqlite` |
| `sqlite/sonarr.sqlite` | `/opt/compose/arr-stack/sonarr/config/sonarr.db` |
| `sqlite/prowlarr.sqlite` | `/opt/compose/arr-stack/prowlarr/config/prowlarr.db` |
| `sqlite/calibre.sqlite` | `/opt/compose/bookshelf/config/calibre-web/app.db` |
| `sqlite/grafana.sqlite` | `/var/lib/docker/volumes/monitoring-stack-gpnc_grafana-data/_data/grafana.db` |

For Vaultwarden, also restore `vaultwarden-data/config.json`,
`vaultwarden-data/rsa_key.pem`, `attachments/`, `sends/` and `icon_cache/` to
`/opt/core/vaultwarden/vw-data/`.

Verify each SQLite file:

```bash
sqlite3 <file> 'PRAGMA integrity_check;'
```

## 9. Phase F — Restore stack configuration and start the stacks

### 9.1 Stack `.env` files

Komodo stores the rendered `.env` content in MongoDB. After §8.4:

1. Start Komodo (`komodo` + `komodo-mongo`).
2. Open Komodo and confirm every stack has its environment variables.
3. Deploy each stack from Komodo, which recreates `/opt/stacks` and writes the
   `.env` files.

If Komodo is not available, use the staged copies:

```bash
ls /var/lib/docker/volumes/backrest_data/_data/stack-envs/opt/stacks/
```

Each file is mirrored under its original `opt/stacks/...` path. Copy it to the
matching stack directory after cloning the repository. The manifest records the
original source path and SHA-256.

### 9.2 Start order

Follow [`core/README.md`](../core/README.md):

1. `proxy-stack` — creates `proxy_net`.
2. `monitoring-stack-gpnc` — creates `monitoring`.
3. `adguard` and `headscale` — DNS and VPN control plane.
4. `komodo` — orchestration.
5. `backrest` — confirm the repositories are visible and schedules are active.
6. Application stacks: `nextcloud`, `romm`, `appflowy`, `arr-stack`,
   `bookshelf`, `homarr`, `vaultwarden`, `fester`, etc.

Start each with:

```bash
cd /opt/stacks/<stack>/<path>
docker compose up -d
docker compose ps
docker compose logs --tail=50
```

### 9.3 Backrest after restore

1. Start `backrest` and `backrest-exporter`.
2. Open the Backrest UI and confirm the three repositories and five plans.
3. Confirm the API user `prometheus` exists. If the config was restored from an
   older snapshot, recreate the user and update `BACKREST_EXPORTER_PASSWORD`.
4. Run a manual backup of the Core plan and confirm it succeeds.
5. Confirm the Telegram `/backups` and `/verify` commands respond.
6. Confirm `backrest-verify` is running and its `/status` endpoint shows the next
   drill. Run a manual `--run-now` if the schedule needs to be validated before
   the next monthly slot.

> Prometheus and Loki historical data are intentionally excluded from the backup.
> Their volumes start empty. Dashboards are provisioned from Git; accept the loss
> of historical metrics and logs.

## 10. Phase G — DNS, Cloudflare, VPN and edge node

### 10.1 Cloudflare DNS and DDNS

- Zone: `redriottank.com`.
- `cloudflare-ddns` runs every 5 minutes with `PROXIED=false` and updates the
  A record for the zone. The token is `CF_API_TOKEN` in the `proxy-stack` stack
  environment.
- All observed subdomains (`monitoring`, `vpn`, `cloud`, `vault`, `home`)
  currently resolve to the same public IP. Confirm whether they are individual A
  records or CNAMEs to the apex.
- After the new host has a public IP:
  ```bash
  dig +short redriottank.com
  dig +short monitoring.redriottank.com
  ```
  If the records do not update, run the DDNS container manually and inspect its
  logs.
- Router port forwarding for 80/443 is external and must be recreated manually.

### 10.2 Nginx Proxy Manager and TLS

- `npm_data` and `npm_letsencrypt` are restored from the backup.
- Start NPM and verify the proxy hosts and certificates in the admin UI.
- If the public IP or DNS changed and certificates are invalid, re-issue them in
  NPM. HTTP-01 requires port 80 to reach the new host.

### 10.3 AdGuard Home

- Configuration is in `adguard_conf`; runtime data in `adguard_work`.
- Restore both volumes.
- Verify the admin UI and DNS rewrites.
- Update the router/DHCP DNS setting if the host IP changed.

### 10.4 Headscale and the Tailscale client

- Headscale config: `/opt/core/headscale/config/config.yaml` (covered by
  `/opt`), database: `headscale_data` plus `sqlite/headscale.sqlite`.
- Headplane config: `/opt/core/headscale/headplane-config/config.yaml`.
- The `tailscale` container is a **Headscale client**:
  `--login-server=https://vpn.redriottank.com`, state in `tailscale_data`.
- If the restored state is rejected, create a new pre-auth key:
  ```bash
  docker exec headscale headscale users list
  docker exec headscale headscale preauthkeys create --user <user> --expiration 24h
  docker exec tailscale tailscale up \
    --login-server=https://vpn.redriottank.com \
    --authkey=<key> --hostname=redserver
  ```
- Verify with `docker exec tailscale tailscale status` and the Headplane UI.

### 10.5 Edge node (CrimsonServer)

The edge node runs:

- `tailscale-client`
- `komodo-periphery`
- `monitoring-agent-gpnc`

After the primary is back:

1. Re-auth the edge Tailscale client with a new Headscale pre-auth key if needed.
2. Confirm `komodo-periphery` reconnects to the Komodo server URL.
3. Confirm the Prometheus target file
   `core/monitoring-stack-gpnc/configs/prometheus/targets/node-exporter.yml`
   contains the correct edge address and that Prometheus shows the target as UP.
4. Confirm `cadvisor` and `node-exporter` metrics from the edge node appear in
   Grafana.

## 11. Phase H — Validation checklist

- [ ] `docker ps` shows every expected container, none restarting.
- [ ] `docker compose ps` for each core stack is healthy.
- [ ] NPM admin UI reachable; all proxy hosts green.
- [ ] Grafana reachable; Prometheus targets `up`; Loki receiving logs.
- [ ] Alertmanager reachable; Telegram `/status` responds.
- [ ] Telegram `/backups` shows fresh plans; `/verify` works after Phase 3.
- [ ] Vaultwarden login works and an item decrypts.
- [ ] Nextcloud login works and a file downloads.
- [ ] Romm, AppFlowy, Homarr, Bookshelf and the \*arr stack respond.
- [ ] Komodo UI shows all stacks and can deploy one.
- [ ] AdGuard resolves internal names; Headscale shows the edge node.
- [ ] Backrest UI shows repositories and plans; a manual Core backup succeeds.
- [ ] No alert fires for missing data after the first scrape interval.

## 12. Phase I — Post-recovery

1. Rotate secrets that may have been exposed:
   - Restic repository password (`restic key passwd`), then update Backrest and
     the VeraCrypt kit.
   - Telegram bot token.
   - Cloudflare API token.
   - SSH keys and Komodo passkey if compromise is suspected.
2. Re-enable the monthly verification schedule and confirm `next_run`.
3. Update DNS TTLs and documentation.
4. Record the actual RTO and any deviations in the table below.
5. Add any missing file or step to `backup-verification.md` and the Phase 1
   coverage hook.

### RTO log

| Date | Scenario | RPO achieved | RTO achieved | Gaps found |
| --- | --- | --- | --- | --- |
| _pending Phase 5_ | Clean-room restore | | | |

## 13. Appendix A — Useful commands

```bash
# List snapshots
restic -r "$REPO" snapshots --no-lock

# Inspect a snapshot
restic -r "$REPO" ls "$SNAP" --no-lock | head

# Restore a single file
restic -r "$REPO" dump "$SNAP" /backup/opt/core/komodo/.env > /tmp/komodo.env

# Verify a restored tree
restic -r "$REPO" restore "$SNAP" --target /restore --verify --no-lock

# Check repository data (10% sample)
restic -r "$REPO" check --read-data-subset=10% --no-lock

# Mount a repository read-only for browsing
mkdir -p /mnt/restic
restic -r "$REPO" mount /mnt/restic --no-lock --allow-other
```

## 14. Appendix B — Data map

| Host path | Snapshot path | Plan | Restore target |
| --- | --- | --- | --- |
| `/var/lib/docker/volumes` | `/backup/docker_volumes` | Core | `/var/lib/docker/volumes` |
| `/opt` (except `/opt/stacks`) | `/backup/opt` | Core | `/opt` |
| `/home/deployer/homelab` | `/backup/homelab` | Core | `/home/deployer/homelab` |
| Backrest dumps/scripts | `/data/dbdumps`, `/data/scripts` | Core | `backrest_data` volume |
| Staged stack envs | `/data/stack-envs` | Core (Phase 1) | `backrest_data` volume |
| Staged home config | `/data/home-config` | Core (Phase 1) | `/home/deployer` |
| Staged host config | `/data/host-config` | Core (Phase 1) | `/etc` whitelist |
| Nextcloud files | `/backup/srv/nextcloud_data` | HeavyData | `/srv/nextcloud_data` |

## 15. Appendix C — Known gaps and TODOs

- [x] Validate the Phase 1 staging hook and the exact home/host whitelist.
- [ ] Confirm the Cloudflare records are A records or CNAMEs and document the
      update procedure with screenshots or commands.
- [ ] Document the router/NAT rules.
- [ ] Pin critical image versions/digests.
- [ ] Confirm `KOMODO_PASSKEY` and `KOMODO_JWT_SECRET` restore path.
- [ ] Confirm the Telegram bot token restore path.
- [ ] Exercise the edge-node reconnection.
- [x] Validate the `backrest-verify` pipeline and its `/status` and `/metrics`
      endpoints (selective restore of all critical paths passed).
- [ ] Complete a full-size `backrest-verify` run and record its duration.
- [ ] Record the measured RTO.
- [ ] Delete the obsolete `/srv/backrest_repo` after confirming it is unused.

## 16. Performance note

The local Restic repository lives on the portable 1.8 TB USB HDD. Full restores
are I/O-bound by that disk (roughly 1–3 MB/s for the Core file mix). Scratch on
the SSD speeds writes and verification, but not source reads. Plan the RTO
accordingly and prefer a cloud repository restore when the local disk is the
bottleneck.
