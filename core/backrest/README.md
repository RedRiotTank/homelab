# Backrest Backup Orchestrator

Automated, web-managed backup orchestration powered by [Restic](https://restic.net) and [Backrest](https://github.com/garethgeorge/backrest). This stack acts as the centralized backup engine for the infrastructure, protecting configuration state, Docker persistent volumes, Compose definitions, and bulk application data across local and remote storage targets.

## Architecture & Design Decisions

To prevent accidental data loss or file locking during snapshots, all host directories targeted for backup are mounted **read-only (`:ro`)**. Storage destinations dedicated to holding the Restic repositories are isolated and mounted **read-write (`:rw`)**.

The Docker daemon socket (`/var/run/docker.sock`) is mounted read-only so Backrest can inspect running containers and invoke pre/post-backup **Hooks** (e.g. pausing a database before a snapshot) without granting the container full control over the host's containers. The host's `rclone` configuration directory is mounted so Backrest can push deduplicated snapshots to remote/cloud storage providers in addition to (or instead of) local repository targets.

```text
  [ Read-Only Backup Sources ]                                      [ Repository Targets ]
  ────────────────────────────                                      ──────────────────────
  • /backup/homelab        (Git code & compose)
  • /backup/docker_volumes (/var/lib/docker/volumes)   ──┐
  • /backup/opt            (/opt configs & apps)         │
  • /backup/srv            (/srv heavy/bulk data)        │
                                                         ▼
                                            +────────────────────────+
  [ Rclone Config ]                         |     BACKREST STACK     |
  • /root/.config/rclone ──────────────────>|   (Restic Engine & UI) |
                                            +────────────┬───────────+
  [ Docker Daemon Socket ]                               │
  • /var/run/docker.sock (Container hooks) ─┘            │
                                                         ▼
                                      ┌──────────────────────────────────────┐
                                      │ Snapshot Targets (Deduplicated/Crypt)│
                                      └──────────────────┬───────────────────┘
                                                         │
                                ┌────────────────────────┴────────────────────────┐
                                ▼                                                 ▼
                     [ Local / External Drive ]                         [ Remote Cloud Storage ]
                       /repos/external                                     rclone:<remote_name>:<path>
```

## Service Interconnections & Dependencies

- [proxy-stack](../proxy-stack/README.md) — Backrest exposes no public ports; it sits behind Nginx Proxy Manager and is reached over the shared external `proxy_net` network, attached through `docker-compose.override.yml`.
- [monitoring-stack-gpnc](../monitoring-stack-gpnc/README.md) — `docker-compose.override.yml` attaches the container to the external `monitoring_net` network (the real Docker network name is `monitoring`) and injects `logging`/`logging_jobname` labels so Promtail can ship its logs to Loki.

## File Structure

| File | Purpose |
| --- | --- |
| `docker-compose.yml` | Base, portable service definitions for Backrest and its read-only status exporter. No network attachment — not reachable through the reverse proxy on its own. |
| `docker-compose.override.yml` | Attaches Backrest to `proxy_net` and `monitoring_net`, attaches the exporter to `monitoring_net`, and injects Promtail labels. **Not optional** — `proxy_net` lives here instead of the base file, so the UI isn't reachable via Nginx Proxy Manager without it. |
| `backrest-exporter.py` | Read-only exporter that queries the Backrest API and exposes `/metrics` and `/status` on the internal monitoring network. |
| `.env.example` | Template for all environment variables consumed by `docker-compose.yml`. |

## Configuration & Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `BACKREST_PORT` | `127.0.0.1:9898` | Web UI port binding; keep bound to localhost and expose only via the reverse proxy. |
| `TZ` | `UTC` | Container timezone, used for schedule evaluation. |
| `HOST_RCLONE_CONFIG_DIR` | `~/.config/rclone` | Host directory containing `rclone.conf` for cloud storage remotes (S3, B2, GDrive, etc.). |
| `HOST_HOMELAB_DIR` | `~/homelab` | Host path to the homelab Git repository, mounted read-only as a backup source. |
| `HOST_DOCKER_VOLUMES_DIR` | `/var/lib/docker/volumes` | Backup source for all named Docker volumes. |
| `HOST_OPT_DIR` | `/opt` | Backup source for `/opt` configs and apps. |
| `HOST_SRV_DIR` | `/srv` | Backup source for bulk/shared data. |
| `BACKREST_REPO_DIR` | `/mnt/external_backups` | Read-write destination for Restic repositories. |
| `DOCKER_SOCKET_PATH` | `/var/run/docker.sock` | Host Docker socket, enabling pre/post-snapshot hooks. |
| `BACKREST_EXPORTER_USER` | `prometheus` | Dedicated Backrest API user used by the exporter. |
| `BACKREST_EXPORTER_PASSWORD` | _(required)_ | Password for that API user. Keep it local; never commit it. |
| `BACKREST_STALE_SECONDS` | `129600` | Age after which a plan is considered stale (36 hours). |
| `BACKREST_REFRESH_SECONDS` | `60` | How often the exporter refreshes its cached status. |

> ⚠️ **Recursive Backup Protection:** If `BACKREST_REPO_DIR` lives inside any of the source trees (for example, inside `/srv`), explicitly add that path to the exclusion list (e.g., `/backup/srv/backups/**`) to prevent Restic from backing up its own repository in an infinite loop.

> **Disposable clones:** if an orchestrator keeps throwaway Git clones inside a backup source (for example under `/opt/stacks`), exclude that directory so snapshots do not duplicate the repository.

> **Vaultwarden:** make sure the directory configured by `VAULTWARDEN_DATA_DIR` is inside one of the backup sources; the pre-backup hook takes a consistent SQLite dump and copies attachments/keys.

## Deployment & Operational Commands

### Prerequisites

1. **External ingress network** — Backrest sits behind a reverse proxy. Ensure the network exists:

       docker network create proxy_net

2. **Cloud storage setup (optional)** — if sending backups off-site (Cloudflare R2, AWS S3, Google Drive, Backblaze B2, Hetzner Storage Box):

   1. Configure your remote on the host using `rclone config`.
   2. Verify `rclone.conf` is located in the directory mapped by `HOST_RCLONE_CONFIG_DIR`.

### Option A: GitOps via Komodo (Recommended)

1. Register this directory as a stack in your Komodo instance.
2. Define the environment variables following `.env.example`.
3. In **File Paths**, specify **both** `docker-compose.yml` and `docker-compose.override.yml` — the override carries the `proxy_net` attachment, so it's required for the UI to be reachable via the reverse proxy. If the monitoring stack isn't deployed, edit the override to drop the `monitoring_net` entry and the two `logging*` labels rather than omitting the file.
4. Deploy the stack.

### Option B: Manual CLI Deployment

1. Copy and configure the environment variables:

       cp .env.example .env
       nano .env

2. Start the service:

       docker compose up -d

   Compose automatically merges `docker-compose.override.yml` on top of `docker-compose.yml`, so a plain `docker compose up -d` picks up both — running `-f docker-compose.yml` alone leaves the container off `proxy_net` and unreachable via the reverse proxy.

### Post-Deployment Access & Initialization

- **Web UI Access:** Through the reverse proxy using the container name `backrest` on port `9898`, or via `http://127.0.0.1:9898`.
- **Configuring Repositories:**
  - When creating a repository, enable **Auto Initialize** to let Backrest initialize the Restic repository structure automatically using the configured password.
  - **Local paths:** Point to `/repos/external/<subfolder>`.
  - **Cloud remotes:** Point to `rclone:<remote_name>:<bucket_or_path>`.

## Specific Notes

### Prometheus, Alerting and Telegram

The stack includes `backrest-exporter`, a read-only helper that authenticates to the Backrest API and exposes:

- `/metrics` for Prometheus.
- `/status` JSON for the Telegram bot's `/backups` command.

Create a dedicated Backrest API user (for example `prometheus`):

1. In the Backrest UI, open **Settings → Authentication** and add a user with a
   strong random password.
2. Set `BACKREST_EXPORTER_USER` and `BACKREST_EXPORTER_PASSWORD` in the stack
   environment (for example in Komodo), not in the compose file or Git.
3. Optionally adjust `BACKREST_STALE_SECONDS` (default 36 hours) and
   `BACKREST_REFRESH_SECONDS` (default 60 seconds).

The exporter runs on the internal `monitoring` network and does not publish a
host port. If you restore Backrest from an older config backup, recreate the API
user and update the password.

Prometheus alerts on:

- `BackrestDown` — exporter/API unreachable.
- `BackrestBackupFailed` — the last backup for a plan failed.
- `BackrestBackupMissing` — no successful backup in the 30-day history.
- `BackrestBackupStale` — last successful backup older than `BACKREST_STALE_SECONDS`.
- `BackrestBackupCompleted` — a successful backup timestamp changed (one info notification per group).

A repository outage normally surfaces as a failed or stale plan backup; the
exporter's `backrest_up` metric covers the API itself being unreachable.

### Recommended Backup Strategy

To avoid repository lock collisions and maximize Restic's cross-snapshot deduplication, jobs should be organized by **data velocity and criticality** rather than by individual container:

| Plan Concept | Typical Included Paths | Schedule Pattern | Retention Target | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Configs & State** | `/backup/homelab`<br>`/backup/opt`<br>`/backup/docker_volumes` | Daily (e.g., `0 3 * * *`) | 7 Daily, 4 Weekly, 6 Monthly | Fast, lightweight snapshots containing application states, `.env` files, databases, and Docker specs. |
| **Bulk / Heavy Data** | `/backup/srv/<app_data>` | Weekly (e.g., `0 4 * * 0`) | 4 Weekly, 2–3 Monthly | Large media, shared drives, or archive directories. |

#### Exclusion Guidelines

- **For Configurations & Repositories:**

      **/node_modules/**
      **/.git/**
      **/cache/**
      **/*.log
      **/*.tmp

- **For Bulk Storage:**

      **/downloads/**
      **/tmp/**
      **/.Trash-*/**
      **/*.part
      **/*.crdownload

### Database Consistency & Hooks

While filesystem snapshots work seamlessly for static files, active database engines (PostgreSQL, MariaDB, MongoDB) may be writing transactions during backup runs.

Because `/var/run/docker.sock` is mounted into the container, you can define **Hooks** in Backrest plan settings to pause and unpause database containers around the snapshot phase:

- **Pre-backup Hook:**

      docker pause <database_container_1> <database_container_2>

- **Post-backup Hook (Always run):**

      docker unpause <database_container_1> <database_container_2>

Alternatively, use the pre-backup hook to invoke a logical dump command (such as `docker exec <db_container> pg_dumpall > /path/to/dump.sql`).
