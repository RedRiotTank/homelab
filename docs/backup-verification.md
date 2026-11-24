# Backup verification and disaster-recovery drills

Status: **Phase 3 — verification visible in Telegram, Grafana and alerts**
Last reviewed: 2026-11-23

This document defines how the homelab proves that its Backrest/Restic backups are
restorable, how often that proof is produced, where the result is visible, and
what is intentionally outside the backup scope. It complements
[`disaster-recovery.md`](./disaster-recovery.md), which is the step-by-step
runbook for rebuilding the environment on a clean host.

## 1. Objectives

| Item | Target |
| --- | --- |
| RPO (maximum acceptable data loss) | **24 hours** |
| RTO (target recovery time) | **4–8 hours** |
| Automated restore test | **Monthly**, day 16 at 04:00 Europe/Madrid |
| Clean-room disaster drill | **Quarterly** (Phase 5) |
| Result visibility | Telegram `/verify`, Grafana dashboard, persistent report |
| Failure notification | Prometheus → Alertmanager → existing Telegram bot |

The goal is not to prove that a backup job ran. It is to prove that a snapshot
can be opened with the repository password, decrypted, restored, and that the
restored state contains the files and database dumps needed to rebuild the
environment on another server.

## 2. Decisions

| Topic | Decision |
| --- | --- |
| Monthly depth | Full restore + static validation. **No Docker socket** is mounted into `backrest-verify`. |
| Container-level validation | Reserved for the quarterly clean-room drill on a disposable host/VM. |
| Remote rotation | Even months: `GDrive-RedServer`. Odd months: `miixzify`. Local repo is restored every month. |
| Local HeavyData plan | **Not added.** `/srv/nextcloud_data` and `local-repo-srv` share the same physical disk, so a local copy adds no disk-failure redundancy. The two cloud copies are the protection. |
| Recovery kit | External VeraCrypt USB. Contains the Restic repository password and `rclone.conf`. **Do not store `rclone.conf` in the backup.** |
| Home directory | Include `.ssh`, `.gnupg`, `bin`, shell dotfiles, selected `.config`, and the Telegram Alertmanager config. Exclude caches, history, editor data and `rclone.conf`. |
| Obsolete repo | `/srv/backrest_repo` is obsolete. Scripts and docs ignore it; delete it manually later. |
| Schedule | Day **16** of each month at **04:00 Europe/Madrid**. |
| Rclone warnings | `backrest-verify` copies `rclone.conf` to a writable temporary file inside the container before use. |

## 3. Current baseline (2026-11-23)

### 3.1 Repositories and plans

| Repository | URI | Plans | Last snapshot |
| --- | --- | --- | --- |
| `local-repo-srv` | `/repos/external/backrest_repo` (`/srv/backups/backrest_repo`) | Core only | 2026-11-24 02:00 |
| `GDrive-RedServer` | `rclone:gdrive:backups/redserver` | Core + HeavyData | 2026-11-24 02:30 / 06:00 |
| `miixzify` | `rclone:chitogeshared:backrest_backup` | Core + HeavyData | 2026-11-24 03:00 / 06:30 |

Core plans (one per repository) run daily at 02:00, 02:30 and 03:00 and include:

```text
/backup/docker_volumes
/backup/homelab
/backup/opt
/data/dbdumps
/data/scripts
```

HeavyData plans (cloud only) run daily at 06:00 and 06:30 and include:

```text
/backup/srv/nextcloud_data
/backup/opt/minecraft_servers
/backup/docker_volumes/appflowy_minio_data
```

The Core plans keep configuration and small state. Minecraft, Nextcloud user
files and AppFlowy files are in HeavyData. Romm cover art/metadata and Nextcloud
application code are excluded and regenerated.

Retention is 7 daily, 4 weekly and 6 monthly snapshots. `prune` runs on day 1 at
01:00. `check` runs on day 15 at 01:00 (next: **2026-12-15 01:00**).

### 3.2 What the current `check` proves

The scheduled check executes:

```text
restic check
```

This validates repository structure, indexes, packs and snapshot metadata. It
does **not** read and decrypt the data blobs. A repository can pass this check
while some data is unreadable. The monthly verification must therefore include
`--read-data-subset` and a real `restic restore --verify`.

### 3.3 Database dumps

The Core plan runs `/data/scripts/dbdump.sh` at snapshot start. It writes
logical, consistent dumps to `/data/dbdumps`:

- PostgreSQL: AppFlowy (`pg_dumpall`) and Nextcloud (`pg_dump -Fc`).
- MariaDB: Romm (`mariadb-dump --all-databases`).
- MongoDB: Komodo (`mongodump --archive --gzip`).
- SQLite: Vaultwarden, Nginx Proxy Manager, Headscale, Homarr, Sonarr,
  Prowlarr, Calibre-Web and Grafana.
- Vaultwarden attachments, `config.json` and `rsa_key.pem`.

The hook is idempotent: if a successful dump is younger than six hours, it skips
so the three Core plans can share the same dump set. The maximum age of a dump
inside a snapshot is therefore six hours.

### 3.4 Size and capacity

- After the 2026-11-24 slim change, a Core snapshot restores to approximately
  **733 MiB** (22,210 entries, including 13,972 Romm symlinks). Before the slim
  change it was 17.86 GiB; those old snapshots were removed by the controlled
  prune described in §3.5.
- HeavyData (Nextcloud user files, Minecraft and AppFlowy) is approximately
  **9.4 GiB** per snapshot.
- `/srv` has **948 GB free**.
- A monthly drill restores sequentially and needs roughly **40 GiB** of scratch
  space; the service refuses to start below the configured minimum.

### 3.5 Controlled prune (2026-11-24)

After the slim change, all pre-slim snapshots were removed with an explicit
`restic forget --prune`, keeping only the new snapshots:

| Repository | Before | After | Remaining snapshots |
| --- | ---: | ---: | --- |
| `local-repo-srv` | 14.6 GiB | **516.5 MiB** | `ccbe0a4f` (Core) |
| `GDrive-RedServer` | 16.833 GiB | **7.867 GiB** | `d2661153` (Core), `3ca5dd9d` (Heavy) |
| `miixzify` | 16.692 GiB | **7.867 GiB** | `0d69c0ec` (Core), `0f81c337` (Heavy) |

The `GDrive` and `miixzify` figures are the compressed/deduplicated repository
sizes reported by `restic stats`. Old pre-slim restore points no longer exist;
the new daily retention starts from these snapshots.

## 4. Coverage matrix

| Data | Source path | Covered by | Notes |
| --- | --- | --- | --- |
| Docker named volumes | `/var/lib/docker/volumes` | Core | Small state volumes only; exclusions in §4.1 |
| Infrastructure and app config trees | `/opt` (except `/opt/stacks`) | Core | Config and tiny state; bulk paths listed below are excluded |
| Homelab Git working tree | `/home/deployer/homelab` | Core | Includes gitignored local files such as Prometheus target files. The `.git` directory is excluded; GitHub is the history source. |
| SQLite/DB dumps and helper scripts | `/data/dbdumps`, `/data/scripts` | Core | Generated inside the Backrest volume |
| Nextcloud user files | `/srv/nextcloud_data` | HeavyData (cloud only) | Intentionally absent from the local repo |
| Nextcloud database | `/opt/compose/nextcloud/db_data` | Core dump (`nextcloud-postgres.dump`) | Volume excluded; logical dump restored |
| Nextcloud code | `/opt/compose/nextcloud/app_config` | Excluded (code) | Keep `config/`, `custom_apps/`, `themes/`; the image provides the rest |
| Minecraft servers | `/opt/minecraft_servers` | HeavyData (cloud only) | Worlds, mods and server config |
| Romm library covers | `/opt/compose/romm/library/*/covers` | Excluded | Generated cover art; reindexable |
| Romm resources | `/opt/compose/romm/resources` | Excluded | Romm-generated covers/metadata; reindexable |
| Romm symlinks and gamelist | `/opt/compose/romm/library` (except covers) | Core | Tiny mapping to `/mnt/media/Juegos/Retro`; actual ROMs are not backed up |
| Romm database | `/opt/compose/romm/database` | Core dump (`romm-mariadb.sql.gz`) | Volume excluded |
| AppFlowy MinIO files | `appflowy_minio_data` | HeavyData (cloud only) | User files, not configuration |
| AdGuard query log | `adguard_work` | Excluded | Runtime logs; configuration remains in `adguard_conf` |
| Home configuration and SSH keys | `/home/deployer` selected paths | Core (`/data/home-config`) | See §5.3 |
| Stack `.env` files rendered by Komodo | `/opt/stacks/**/.env` | Komodo MongoDB dump + `/data/stack-envs` | `/opt/stacks` is excluded from Restic; the hook stages a copy |
| Komodo database / stack definitions | `komodo_mongo_data` | `komodo-mongo.archive.gz` | Volume excluded, logical dump included |
| Private Prometheus targets | `core/monitoring-stack-gpnc/configs/prometheus/targets/*.yml` | Core | Source copy lives in the homelab working tree |
| TLS certificates | `npm_letsencrypt` | Core | Plus NPM database dump |
| DNS, Cloudflare, VPN identity | External / secrets | Recovery kit + runbook | Not fully reproducible from backup alone |
| Host OS configuration (`/etc`, systemd units) | Host | Core (`/data/host-config`) | Selective whitelist; machine identity and host keys excluded |
| Media, ROM data, torrents, Jellyfin metadata | `/srv/media`, `/mnt/media`, `/srv/torrents`, `/srv/appdata` | Intentionally excluded | Replaceable or re-creatable; Romm reindexes from `/mnt/media` |

Romm reindex tooling is preserved in `/opt/compose/romm/tools` (inside the Core
backup). The active library symlinks point to `/mnt/media/Juegos/Retro`; cover
art and `resources` are regenerable. The old `/srv/roms` staging tree was
removed as an obsolete deployment artifact.

### 4.1 Current plan exclusions

The Core plan deliberately excludes:

```text
/backup/docker_volumes/monitoring-stack-gpnc_prometheus-data
/backup/docker_volumes/monitoring-stack-gpnc_loki-data
/backup/docker_volumes/appflowy_postgres_data
/backup/docker_volumes/komodo_mongo_data
/backup/docker_volumes/backrest_cache
/backup/docker_volumes/backrest_data
/backup/docker_volumes/backrest_tmp
/backup/docker_volumes/pseudorandom-m2
/backup/docker_volumes/backup-manager_restic_cache
/backup/docker_volumes/nextcloud-backup_restic_cache
/backup/opt/compose/nextcloud/db_data
/backup/opt/compose/romm/database
/backup/opt/compose/romm/library/*/covers
/backup/opt/compose/romm/resources
/backup/opt/minecraft_servers
/backup/opt/compose/nextcloud/app_config/apps
/backup/opt/compose/nextcloud/app_config/core
/backup/opt/compose/nextcloud/app_config/dist
/backup/opt/compose/nextcloud/app_config/3rdparty
/backup/opt/compose/nextcloud/app_config/lib
/backup/opt/compose/nextcloud/app_config/resources
/backup/docker_volumes/appflowy_minio_data
/backup/docker_volumes/adguard_work
/backup/opt/romm
/backup/opt/stacks
```

Database volumes are excluded because their logical dumps are included instead.
Metrics, logs, caches and generated cover art are excluded because they are
regenerable. Nextcloud bundled code is excluded because the container image
provides it; `config/`, `custom_apps/` and `themes/` remain in Core.

## 5. Configuration and secret coverage

This section records what was verified in read-only mode on 2026-11-23. It is the
basis for the Phase 1 coverage hook.

### 5.1 Where the real stack `.env` files live

Komodo renders one `.env` per deployed stack under `/opt/stacks`. There are 12
real files:

```text
/opt/stacks/adguard/core/adguard/.env
/opt/stacks/appflowy/compose/appflowy/.env
/opt/stacks/backrest/core/backrest/.env
/opt/stacks/bookshelf/compose/bookshelf/.env
/opt/stacks/headscale/core/headscale/.env
/opt/stacks/homarr/compose/homarr/.env
/opt/stacks/monitoring-stack-gpnc/core/monitoring-stack-gpnc/.env
/opt/stacks/nextcloud/compose/nextcloud/.env
/opt/stacks/proxy-stack/core/proxy-stack/.env
/opt/stacks/romm/compose/romm/.env
/opt/stacks/tailscale-redserver/core/tailscale-client/.env
/opt/stacks/vaultwarden/core/vaultwarden/.env
```

They contain secrets such as `BACKREST_EXPORTER_PASSWORD`, `CF_API_TOKEN`,
`SECRET_ENCRYPTION_KEY`, `TS_AUTHKEY` and `HEADSCALE_AUTHKEY`.

`/opt/stacks` is excluded from Restic because it is a Komodo-managed deployment
directory. The stack environment is stored in the Komodo MongoDB database, in
`Stack.config.environment`, and `dbdump.sh` already dumps that database to
`komodo-mongo.archive.gz`. That dump is the source of truth for a clean restore.

The `collect-config.sh` hook now copies the 12 `.env` files to
`/data/stack-envs/`, mirrored under `opt/stacks/...`, and adds that path to the
Core plans. This is a small second copy that does not depend on the Komodo schema
or on a running Komodo instance. Both copies are validated by the drill.

### 5.2 Files outside the repository that matter

| File | Coverage | Action |
| --- | --- | --- |
| `/home/deployer/alertmanager-telegram.local.yml` | `/data/home-config` | Restore to `/home/deployer/`; required for the existing Telegram bot |
| `/home/deployer/.config/rclone/rclone.conf` | **Not covered by design** | Keep only in the VeraCrypt recovery kit |
| `/home/deployer/.ssh/*` | `/data/home-config/.ssh` | Restore with `deployer` ownership |
| `/home/deployer/.gnupg/*` | `/data/home-config/.gnupg` | Restore with `deployer` ownership |
| `/home/deployer/homelab` | Covered | No change |
| `/opt/core/komodo/.env` | Covered | Contains `KOMODO_JWT_SECRET` and `KOMODO_PASSKEY` |
| `/opt/compose/*/.env` | Covered | Hand-managed / legacy stack copies |
| `/opt/stacks/**/.env` | Komodo DB + `/data/stack-envs` | Mirrored under `opt/stacks/...` with a manifest |

The Telegram bot token and chat ID live in
`/home/deployer/alertmanager-telegram.local.yml`, referenced by
`ALERTMANAGER_CONFIG_FILE` in the monitoring stack `.env`. If that file is lost,
the bot can be recreated with BotFather, but the existing chat history and bot
identity are lost. It must be in the backup.

### 5.3 Home-configuration set (implemented)

Keep it small and explicit. Do **not** back up the whole home directory. The
`collect-config.sh` hook stages the following into `/data/home-config`:

| Path | Approx. size | Reason |
| --- | --- | --- |
| `.ssh/` | 84 KB | Git access and server keys |
| `.gnupg/` | 12 KB | Signing/encryption material |
| `bin/` | 8 KB | Local helper scripts |
| `.gitconfig`, `.bashrc`, `.bash_aliases`, `.profile`, `.selected_editor` | < 20 KB | Shell and Git identity |
| `.config/` excluding `opencode/`, `rclone/`, `herdr/` | < 1 MB | Tool configuration |
| `alertmanager-telegram.local.yml` | 1 KB | Telegram bot token and chat ID |

Explicitly excluded: `homelab/` (already covered), `.cache/`, `.local/`,
`.npm/`, `.claude*`, `.opencode/`, `.docker/`, `.m2/`, `.pm2/`, `.vscode*`,
`.config/opencode/`, `.config/rclone/`, shell history, media, `dev/`,
`sdbackup/`, and throwaway recovery directories.

A one-shot helper container mounts `HOST_HOME_DIR` and `HOST_ETC_DIR` read-only
and the `backrest_data` volume read-write, so the long-running Backrest container
does not need broad host mounts.

**Security note:** private SSH keys and GPG material are inside the encrypted
Restic repository. The repository password is in the external VeraCrypt kit. Do
not create a second copy of `rclone.conf` in the backup.

### 5.4 Host configuration coverage

`collect-config.sh` also stages a selective `/etc` whitelist into
`/data/host-config`:

- `systemd/system` units, `sysctl.d`, `cron.d`, `crontab`
- `ssh/sshd_config`, `ssh/ssh_config`, `ssh/sshd_config.d`
- `fstab`, `hosts`, `hostname`, `timezone`, `nsswitch.conf`, `sysctl.conf`
- `default/grub`, `network/interfaces`
- `apt/sources.list`, `apt/sources.list.d`
- `iptables/rules.v4` and `iptables/rules.v6`
- `NetworkManager/system-connections` (if present)
- `docker/daemon.json` (if present)

Machine identity is deliberately excluded: `/etc/machine-id`,
`/etc/docker/key.json`, `/etc/ssh/ssh_host_*` and `/etc/shadow`. Router/NAT rules
and the public DNS plan remain manual steps in the runbook.

## 6. Verification service

### 6.1 Placement

Add a `backrest-verify` sidecar to the existing `core/backrest` stack:

```text
core/backrest/
├── docker-compose.yml          # backrest-verify + status volume
├── docker-compose.override.yml # monitoring_net + Promtail labels
├── .env.example                # BACKREST_VERIFY_* variables
├── backrest-exporter.py        # repository check metrics
├── scripts/
│   ├── dbdump.sh               # consistent logical database dumps
│   └── collect-config.sh       # stack env, home config and host config staging
└── verify/
    ├── Dockerfile              # restic 0.19.1 + rclone + sqlite3 + postgres client
    ├── backrest-verify.py      # scheduler, restore, validation, /status, /metrics
    └── README.md               # build and troubleshooting notes
```

The service follows the existing conventions:

- No published host port; reachable only on the `monitoring` network.
- CPU and memory limits in Compose.
- `logging` / `logging_jobname` labels for Promtail.
- Configuration through environment variables, secrets outside Git.
- `TZ=Europe/Madrid`.

### 6.2 Mounts

```yaml
volumes:
  - backrest_config:/config:ro
  - ${BACKREST_REPO_DIR:-/srv/backups}:/repos/external:ro
  - ${HOST_RCLONE_CONFIG_DIR:-/home/deployer/.config/rclone}:/rclone:ro
  - ${HOST_BACKREST_VERIFY_SCRATCH_DIR:-/var/tmp/backrest-verify}:/verify/scratch
  - backrest_verify_data:/verify/state
```

Repositories are mounted **read-only**. Restores use `--no-lock`; the service
never writes to a repository. The scratch directory is outside every backup
source so a restored tree cannot be captured by the next backup. It defaults to
`/var/tmp/backrest-verify` on the root filesystem to avoid competing with the
repository on `/srv`; it needs roughly 40 GiB free.

### 6.3 Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `BACKREST_VERIFY_ENABLED` | `true` | Enable the scheduled drill (manual `--run-now` still works) |
| `BACKREST_VERIFY_DAY` | `16` | Day of month |
| `BACKREST_VERIFY_HOUR` | `4` | Hour in local time |
| `BACKREST_VERIFY_MINUTE` | `0` | Minute |
| `BACKREST_VERIFY_TIMEZONE` | `Europe/Madrid` | Scheduler timezone |
| `BACKREST_VERIFY_REMOTE_ROTATION` | `GDrive-RedServer,miixzify` | Repos alternated by month |
| `BACKREST_VERIFY_READ_DATA_PERCENT` | `10` | `restic check --read-data-subset` percentage |
| `BACKREST_VERIFY_MIN_FREE_GB` | `40` | Abort if scratch free space is lower |
| `BACKREST_VERIFY_MAX_SNAPSHOT_AGE_HOURS` | `36` | Maximum snapshot age |
| `BACKREST_VERIFY_MAX_RETRIES` | `3` | Retries after a failed drill |
| `BACKREST_VERIFY_RETRY_HOURS` | `24` | Delay between retries |
| `BACKREST_VERIFY_KEEP_REPORTS` | `12` | Reports retained |
| `BACKREST_VERIFY_CORE_PATHS` | Core paths | Coverage assertions |
| `BACKREST_VERIFY_HEAVY_PATHS` | `/backup/srv/nextcloud_data`, `/backup/opt/minecraft_servers`, `/backup/docker_volumes/appflowy_minio_data` | HeavyData coverage |
| `BACKREST_VERIFY_PORT` | `9798` | `/status` and `/metrics` port |
| `BACKREST_URL` | `http://backrest:9898` | Backrest API for active-operation checks |
| `BACKREST_EXPORTER_USER` | `prometheus` | API user, same as the exporter |
| `BACKREST_EXPORTER_PASSWORD` | _(required)_ | API password; reuse the exporter credential |
| `HOST_BACKREST_VERIFY_SCRATCH_DIR` | `/var/tmp/backrest-verify` | Compose host path for scratch (outside backups) |

### 6.4 Scheduling semantics

- Compute `next_run` from day/hour/minute in `Europe/Madrid`.
- Persist `last_run`, `last_success` and `next_run` in `status.json` so a
  container restart does not lose the schedule.
- On startup, if the current month's run is overdue and has not completed, run
  it once (catch-up). Do not run twice for the same month.
- Use a lock file to prevent overlapping runs. Clear a stale lock older than the
  configured maximum duration.
- Query the Backrest API in preflight. If another operation is in progress, the
  `backrest_idle` check fails and the scheduler retries after
  `BACKREST_VERIFY_RETRY_HOURS` (up to `BACKREST_VERIFY_MAX_RETRIES`).
- Clean the scratch directory at the start and at the end, even on failure.
- A full Core restore can run for hours on the current USB HDD and may overlap
  the 06:00/06:30 HeavyData backups. The drill is read-only and does not take a
  repository lock, so backups can proceed; expect slower backups on that day.

### 6.5 Monthly procedure

1. **Preflight**
   - Read `/config/config.json`; resolve repository IDs, URIs and passwords.
   - Verify `restic` and `rclone` versions.
   - Copy `rclone.conf` to a writable temp path and set `RCLONE_CONFIG`.
   - Check free space; abort if below `BACKREST_VERIFY_MIN_FREE_GB`.
2. **Repository integrity**
   - `restic -r <repo> check --read-data-subset=10% --no-lock`.
   - Use a scratch cache directory.
   - The sample rotates between runs; over a year it reads more than the full
     repository size on average.
3. **Snapshot selection and coverage**
   - Select the latest Core snapshot and the latest HeavyData snapshot.
   - Assert the expected paths are present.
   - Assert age < 36 hours and file/byte counts above minimum thresholds.
   - Record snapshot ID, timestamp and hostname.
4. **Full restore**
   - `restic restore <snapshot> --target <scratch>/core --verify --no-lock`.
   - Restore HeavyData to a separate directory.
   - Validate ownership, modes and file counts.
5. **Database dumps**
   - `gzip -t` for every compressed dump.
   - `sqlite3 <file> 'PRAGMA integrity_check;'` for every SQLite dump.
   - `pg_restore --list` for the Nextcloud custom-format dump.
   - Marker/size checks for the AppFlowy plain SQL dump and the MariaDB dump.
   - Size and gzip checks for the Komodo MongoDB archive.
   - The quarterly drill performs actual imports into throwaway databases.
6. **Configuration**
   - YAML parse for Compose and Headscale/NPM-related files.
   - JSON parse for `config.json`, Vaultwarden config and other JSON.
   - `git -C ... rev-parse HEAD` for the restored homelab tree; record the SHA.
   - Assert that staged `.env`, home-config and host-config manifests exist.
7. **Secrets and keys**
   - Vaultwarden `rsa_key.pem`, `config.json`, attachments.
   - Headscale `config.yaml` and `policy.hujson`.
   - NPM `database.sqlite` and Let's Encrypt directory.
   - Backrest `config.json`.
   - `.ssh` keys and `.gnupg`.
   - 12 staged stack `.env` files.
8. **Report**
   - Write `status.json` atomically.
   - Append a summary line to `history.jsonl`.
   - Write `report-YYYY-MM.md` with per-check results.
   - Expose `/status` and `/metrics`.
9. **Cleanup**
   - Delete the restored trees.
   - Keep the reports and the manifest hashes.

### 6.6 Pass/fail rules

A run is **PASS** only if every mandatory check passes. Mandatory checks:

- Repository check and read-data subset.
- Latest snapshots exist, are fresh and contain every expected path.
- Full restore succeeds with `--verify`.
- Every database dump passes its structural check.
- Every expected key/secret file exists and is non-empty.
- The staged configuration manifests are present and parse correctly.

A missing optional file (for example, a package that is not installed) must be
recorded as `skip`, not silently ignored. Any `fail` makes the run fail.

## 7. Status and metrics contract

### 7.1 `GET /status`

```json
{
  "up": true,
  "last_run": 1795507200,
  "last_success": 1795507200,
  "next_run": 1798099200,
  "result": "pass",
  "duration_seconds": 1830,
  "repo": "GDrive-RedServer",
  "rotation": ["local-repo-srv", "GDrive-RedServer"],
  "snapshots": {
    "core": "2f574dad",
    "heavy": "5c25c5ec"
  },
  "checks": [
    {"name": "repo_check", "status": "pass", "detail": "10% read-data, no errors"},
    {"name": "snapshot_coverage", "status": "pass", "detail": "5/5 paths"},
    {"name": "restore_verify", "status": "pass", "detail": "88761 files"},
    {"name": "db_dumps", "status": "pass", "detail": "15/15"},
    {"name": "config", "status": "pass", "detail": "12 env files"},
    {"name": "secrets", "status": "pass", "detail": "all present"}
  ],
  "metrics": {
    "restored_bytes": 16500000000,
    "restored_files": 88761,
    "read_data_bytes": 1900000000
  },
  "error": ""
}
```

The Telegram bot uses `next_run` for the countdown and `checks` for the failure
summary. Keep the JSON stable; add fields rather than renaming them.

### 7.2 Metrics

| Metric | Labels | Meaning |
| --- | --- | --- |
| `backrest_verify_up` | — | Service responded to the last scrape |
| `backrest_verify_last_run_timestamp_seconds` | — | Start time of the last run |
| `backrest_verify_last_success_timestamp_seconds` | — | Last PASS |
| `backrest_verify_next_run_timestamp_seconds` | — | Scheduled next run |
| `backrest_verify_success` | — | `1` for PASS, `0` for FAIL |
| `backrest_verify_duration_seconds` | — | Last run duration |
| `backrest_verify_checks_total` | — | Number of checks |
| `backrest_verify_checks_failed` | — | Number of failed checks |
| `backrest_verify_restored_bytes` | — | Bytes restored |
| `backrest_verify_restored_files` | — | Files restored |
| `backrest_verify_snapshot_age_seconds` | `repo`, `kind` | Age of the selected snapshot |
| `backrest_verify_read_data_percent` | — | `--read-data-subset` percentage |
| `backrest_verify_config_files` | — | Staged `.env` files found |

### 7.3 Backrest exporter extension

Implemented in `backrest-exporter.py`:

| Metric | Labels | Meaning |
| --- | --- | --- |
| `backrest_repo_last_check_timestamp_seconds` | `repo_id` | Last completed check |
| `backrest_repo_last_check_failed` | `repo_id` | `1` if the last check failed |
| `backrest_repo_last_check_success_timestamp_seconds` | `repo_id` | Last successful check |

Implement by calling `GetOperations` with the instance selector and filtering
`operationCheck` entries. This closes the current blind spot where a failed
`restic check` produces no metric and no alert.

If `GetOperations` is temporarily unavailable, the exporter keeps the last known
check state instead of resetting it to zero, avoiding a false
`BackupRepoCheckNeverRan` alert.

## 8. Alerts

Add a `backup-verification` group to
`core/monitoring-stack-gpnc/configs/prometheus/alerting-rules.yml`.

| Alert | PromQL | Severity | Status |
| --- | --- | --- | --- |
| `BackupRepoCheckFailed` | `backrest_repo_last_check_failed == 1` | critical | implemented |
| `BackupRepoCheckStale` | `(time() - backrest_repo_last_check_timestamp_seconds) > 40 * 24 * 3600 and backrest_repo_last_check_timestamp_seconds > 0` | warning | implemented |
| `BackupRepoCheckNeverRan` | `backrest_repo_last_check_timestamp_seconds == 0` | warning | implemented |
| `BackupVerificationDown` | `up{job="backrest-verify"} == 0 or absent(up{job="backrest-verify"})` | critical | implemented |
| `BackupVerificationFailed` | `backrest_verify_success == 0 and backrest_verify_last_run_timestamp_seconds > 0` | critical | implemented |
| `BackupVerificationOverdue` | `(time() - backrest_verify_last_run_timestamp_seconds) > 35 * 24 * 3600 and backrest_verify_last_run_timestamp_seconds > 0` | warning | implemented |
| `BackupVerificationNeverRan` | `backrest_verify_last_run_timestamp_seconds == 0` | warning | implemented |
| `BackupVerificationCompleted` | `changes(backrest_verify_last_success_timestamp_seconds[10m]) > 0` | info | implemented |

`BackupVerificationNeverRan` uses `for: 24h` so a fresh deployment does not alert
immediately. `BackupVerificationDown` uses `for: 10m`.

## 9. Telegram and Grafana

### 9.1 Telegram

Implemented in `core/monitoring-stack-gpnc/bot/telegram-bot.py`:

- `/verify` command and a `🧪 Verify` keyboard button.
- `/verify` added to the help text and to the Telegram commands menu.
- `/backups` now includes the last `restic check` per repository.

Current output shape:

```text
🧪 Backup verification
Last: ✅ PASS · 2026-11-23 23:00 · 54s
Last success: 31m ago
Remote: miixzify (rotation)
Restored: 90.1 MiB · 1,166 files
Checks: 29 passed · 0 failed
Next: 2026-12-16 04:00 (in 22d 4h)
Snapshots:
• local-repo-srv: core 0506d0bb
```

On failure, the message lists up to three failed checks with their detail. The
monthly `BackupVerificationCompleted` alert provides the push notification
through the existing Alertmanager route.

`BACKREST_VERIFY_STATUS_URL` is set in the monitoring Compose file (default
`http://backrest-verify:9798/status`).

### 9.2 Grafana

Implemented as `core/monitoring-stack-gpnc/dashboards/backup-verification.json`
and mounted into the Grafana service. Dashboard UID: `backup-verification`.
The Prometheus datasource UID is pinned to `PBFA97CFB590B2093` in
`configs/grafana/provisioning/datasources.yml` so the dashboard survives a fresh
Grafana deployment.

Panels:

- Last drill result (green/red stat).
- Next drill (`dateTimeFromNow`).
- Days since last success.
- Failed checks.
- Last run, restored bytes, restored files and duration.
- Drill duration and restored bytes over time.
- Snapshot age by repository and kind.
- Last repository check per repository.
- Repository check failures.

The dashboard is provisioned from the file and present in Grafana. `/backups`
also shows the last repository check per repo, so the Telegram command remains
useful without opening Grafana.

## 10. Recovery kit

The external VeraCrypt USB is the root of trust. It must contain:

- Restic repository password(s) for all three repositories.
- `rclone.conf` for `gdrive` and `chitogeshared`.
- The repository URIs and the Backrest export of the repository configuration.
- A copy of this document and `disaster-recovery.md`.
- Access details for GitHub (`RedRiotTank/homelab`) and the Cloudflare account.
- Optionally, the Telegram bot token and the Komodo passkey.

It must **not** contain a copy of the backup itself. Keep it offline and test it
at least once per quarter (Phase 5). If the kit cannot be read, the backups are
not recoverable.

## 11. Implementation phases

| Phase | Deliverable | Status |
| --- | --- | --- |
| 0 | This document, the runbook skeleton, and the read-only coverage audit | **Done** |
| 1 | `collect-config.sh` hook, home/host config staging, plan paths, exporter check metrics, check alerts | **Done (2026-11-23)** |
| 2 | `backrest-verify` image and service, monthly restore + validation, `/status`, `/metrics` | **Done (2026-11-23)** |
| 3 | Telegram `/verify`, Grafana dashboard, verification alerts | **Done (2026-11-23)** |
| 4 | First manual drill, fix findings, enable the schedule | **Partially done**: selective drill passed; full monthly run scheduled 2026-12-16 |
| 5 | Clean-room disaster drill on a disposable host, measure RTO, finalize the runbook | Pending |

### 11.1 Phase 1 details (implemented)

- `core/backrest/scripts/collect-config.sh` runs at `CONDITION_SNAPSHOT_START` in
  all three Core plans, after `dbdump.sh`.
- It stages:
  - `/data/stack-envs` — 12 `.env` files mirrored as `opt/stacks/...`, with a
    SHA-256 manifest.
  - `/data/home-config` — `.ssh`, `.gnupg`, `bin`, dotfiles, selected `.config`
    and `alertmanager-telegram.local.yml`.
  - `/data/host-config` — the `/etc` whitelist described in §5.4.
- It uses a one-shot helper container with the Backrest image, mounting
  `HOST_HOME_DIR` and `HOST_ETC_DIR` read-only and `backrest_data` read-write.
  No broad host mount is added to the long-running container.
- It is fail-closed: missing `.ssh`, missing Telegram Alertmanager config, too
  few stack `.env` files, or an empty host whitelist fails the plan.
- `scripts/` is versioned in Git and mounted read-only at `/data/scripts`.
- The Core plans now include `/data/stack-envs`, `/data/home-config` and
  `/data/host-config`.
- `backrest-exporter.py` exposes:
  - `backrest_repo_last_check_timestamp_seconds{repo_id}`
  - `backrest_repo_last_check_failed{repo_id}`
  - `backrest_repo_last_check_success_timestamp_seconds{repo_id}`
- Alert rules `BackupRepoCheckFailed`, `BackupRepoCheckStale` and
  `BackupRepoCheckNeverRan` are active.
- `HOST_HOME_DIR` and `HOST_ETC_DIR` were added to `.env.example` and Compose.

Validation: a manual backup of `RedServer_local_CoreConfigs` on 2026-11-23 at
22:12 produced snapshot `f6692b30` with 8 paths, including the three staged
trees. The snapshot contains the 12 stack `.env` files, the home config (240 KB)
and 23 host config files. The earlier run (`fa6df796`) validated the same flow
before the last host-whitelist additions.

The running Backrest plan configuration was updated in place; a copy is kept at
`/config/config.json.bak.pre-phase1-20261123-*`. The Compose changes in Git
(the scripts mount and `HOST_HOME_DIR` / `HOST_ETC_DIR`) apply on the next
GitOps deploy. The currently running container already has the hook script in
the `backrest_data` volume, so the backup schedule works in the meantime.

### 11.2 Phase 2 details (implemented)

- `verify/Dockerfile` builds a Python 3.12 Alpine image with Restic 0.19.1
  (copied from the Backrest image), rclone, the PostgreSQL client, PyYAML,
  sqlite and the usual text utilities.
- `verify/backrest-verify.py` implements:
  - a monthly scheduler (day 16, 04:00 Europe/Madrid, lock, catch-up and retry);
  - `restic check --read-data-subset=10%` on every repository;
  - snapshot freshness and path-coverage assertions;
  - full `restic restore --verify` of the Core snapshot from local + one remote;
  - manifest, database, configuration and secret validation;
  - HeavyData restore from the selected remote;
  - `/status`, `/metrics` and `/healthz`;
  - Markdown reports and a JSON history.
- The Compose service `backrest-verify` runs with 1 CPU / 1 GB, no published
  port, no Docker socket, read-only repositories and a scratch bind outside the
  backup sources.
- `backrest_verify_data` stores status and reports; the writable `rclone.conf`
  copy stays in `/tmp` and is never persisted.
- Prometheus now scrapes `backrest-verify:9798` as job `backrest-verify`.

Manual validation commands:

```bash
# Repository checks and snapshot coverage only (fast)
docker run --rm --network monitoring \
  -e BACKREST_EXPORTER_PASSWORD=... \
  -v backrest_config:/config:ro \
  -v /srv/backups:/repos/external:ro \
  -v /home/deployer/.config/rclone:/rclone:ro \
  -v /var/tmp/backrest-verify:/verify/scratch \
  -v backrest_verify_data:/verify/state \
  backrest-verify:local --run-now --repos local-repo-srv --skip-heavy --no-restore
```

HeavyData restores are I/O-bound by the portable HDD. The Core snapshot is now
small (~733 MiB); the drill time is dominated by the ~9.4 GiB HeavyData restore.
Scratch on the SSD reduces write and verification time but not source reads.

Validation performed:

- **2026-11-24 05:30**, before the slim change: a full drill passed **54 checks
  with 0 failures** in 38m28s, restoring 38.6 GiB (local Core, remote Core and
  remote HeavyData).
- **2026-11-24, slim change**: a manual Core backup produced snapshot `ccbe0a4f`
  with **733 MiB** (22,210 entries, including 13,972 Romm symlinks). The
  excluded Romm covers/resources, Minecraft, Nextcloud code, AppFlowy MinIO and
  AdGuard work were absent; Nextcloud `config.php`, `custom_apps`, Romm
  `gamelist.xml` and the reindex tools were present.
- A manual HeavyData backup produced snapshot `0f81c337` with **9.39 GiB**
  (14,648 entries) and all three expected paths: Nextcloud data, Minecraft and
  AppFlowy MinIO.
- A `--no-restore` coverage run against the new snapshots passed **10 checks with
  0 failures**.
- A **post-slim full drill** on 2026-11-24 at 20:58 passed **56 checks with 0
  failures** in 35m10s. It restored the slim local Core (`ccbe0a4f`, 0.72 GiB),
  the still-pre-slim remote Core (`4466f527`, 17.86 GiB) and the new HeavyData
  (`0f81c337`, 9.39 GiB).
- A **controlled forget/prune** then removed all pre-slim snapshots. Repository
  sizes dropped to **516.5 MiB** (local), **7.867 GiB** (GDrive) and
  **7.867 GiB** (miixzify). The remaining snapshots are `ccbe0a4f` (local
  Core), `d2661153`/`3ca5dd9d` (GDrive Core/Heavy) and
  `0d69c0ec`/`0f81c337` (miixzify Core/Heavy).
- A **post-prune full drill** at 21:59 passed **56 checks with 0 failures** in
  12m10s, restoring **10.8 GiB / 28,340 files**: slim local Core, slim remote
  Core and HeavyData (Nextcloud 2.90 GiB, Minecraft 5.78 GiB, AppFlowy 729 MiB).
- The service is running, the Prometheus target is `up`, and the next scheduled
  drill is **2026-12-16 04:00 CET**.

### 11.3 Phase 3 details (implemented)

- `telegram-bot.py`: `/verify` command, `🧪 Verify` button, help text, Telegram
  commands menu, `/backups` repository-check lines and `human_bytes` formatting.
- `dashboards/backup-verification.json`: provisioned dashboard UID
  `backup-verification`; Prometheus datasource UID pinned.
- `docker-compose.yml`: dashboard mount and `BACKREST_VERIFY_STATUS_URL`.
- `alerting-rules.yml`: `BackupVerificationDown`, `BackupVerificationFailed`,
  `BackupVerificationOverdue`, `BackupVerificationNeverRan` and
  `BackupVerificationCompleted`.
- `datasources.yml`: Prometheus UID pinned for reproducibility.

Validation on 2026-11-23:

- `/verify` output verified against the running service: PASS, 29 checks,
  90.1 MiB, 1,166 files, next drill 2026-12-16 04:00.
- `/backups` shows `last check` per repository.
- Grafana dashboard present in the Grafana database with UID
  `backup-verification`.
- Prometheus loaded the group with 8 rules; `promtool` reported 38 total rules.
- No `BackupVerification*` alert was firing at the end of the deployment.

### 11.4 Phase 4 details

- Run the first drill manually and review every check.
- Fix missing coverage (for example, a stale `.env` or a missing key).
- Confirm the report is readable and the countdown is correct.
- Enable the monthly schedule.

### 11.5 Phase 5 details

- Provision a disposable VM or spare host with Debian 12, Docker and an empty
  `/srv`.
- Follow `disaster-recovery.md` end to end.
- Bring up the core stacks, restore databases, validate logins and data.
- Measure the actual RTO and record it in the runbook.
- Update this document with anything that was missing.

## 12. Acceptance criteria

- A monthly drill runs unattended and produces PASS/FAIL with a report.
- `/verify` shows the last result and a countdown to the next run.
- Grafana shows the last result, days since success and the per-repo check state.
- A failed drill or a failed `restic check` reaches Telegram.
- A quarterly clean-room drill has been completed and the measured RTO is
  recorded.
- The VeraCrypt kit is sufficient to open every repository without the original
  host.
- No secret is committed to Git.

## 13. Known limitations

- A monthly restore on the same host proves the repository and data, not that a
  new host can boot the environment. The quarterly clean-room drill covers that.
- Some services need external state that is not in the backup: Cloudflare DNS,
  router port forwarding, domain registrar, Telegram bot identity, and the
  physical network. These are documented as manual steps.
- `latest` image tags reduce reproducibility. Phase 2 should pin the Backrest,
  Romm, AppFlowy and other critical images to versions or digests; the staging
  hook also uses the Backrest image as its helper container.
- The homelab `.git` directory is excluded. The working tree is backed up, but
  the commit history comes from GitHub; losing both the host and GitHub access
  would lose the history.
- The host-configuration whitelist is selective. Machine identity, SSH host keys,
  router/NAT rules and the public DNS plan remain manual steps.
- `/srv/backrest_repo` is obsolete. Ignore it in scripts and delete it manually
  after confirming nothing references it.
- Media, ROMs, torrents and Jellyfin metadata are intentionally excluded.
- The monthly validation checks dump structure, not a live import. Live imports
  are part of the quarterly drill.
- HeavyData restores are I/O-bound by the local repository on the portable USB
  HDD. The Core snapshot is now ~733 MiB; the drill is dominated by the ~9.4 GiB
  HeavyData restore. Scratch on the SSD helps writes and verification, but not
  source reads. The 6-hour command timeout is intentional.
