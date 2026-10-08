# Backrest Backup Orchestrator Stack

Automated, web-managed backup orchestration powered by [Restic](https://restic.net) and [Backrest](https://github.com/garethgeorge/backrest). This stack acts as the centralized backup engine for the infrastructure, protecting configuration state, Docker persistent volumes, Compose definitions, and bulk application data across local and remote storage targets.

---

## Architecture & Storage Layout

To prevent accidental data loss or file locking during snapshots, all host directories targeted for backup are mounted **read-only (`:ro`)**. Storage destinations dedicated to holding the Restic repositories are isolated and mounted **read-write (`:rw`)**.

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

## Recommended Backup Strategy

To avoid repository lock collisions and maximize Restic's cross-snapshot deduplication, jobs should be organized by **data velocity and criticality** rather than by individual container:

| Plan Concept | Typical Included Paths | Schedule Pattern | Retention Target | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Configs & State** | `/backup/homelab`<br>`/backup/opt`<br>`/backup/docker_volumes` | Daily (e.g., `0 3 * * *`) | 7 Daily, 4 Weekly, 6 Monthly | Fast, lightweight snapshots containing application states, `.env` files, databases, and Docker specs. |
| **Bulk / Heavy Data** | `/backup/srv/<app_data>` | Weekly (e.g., `0 4 * * 0`) | 4 Weekly, 2–3 Monthly | Large media, shared drives, or archive directories. |

### Exclusion Guidelines

-   **For Configurations & Repositories:**
    
        **/node_modules/**
        **/.git/**
        **/cache/**
        **/*.log
        **/*.tmp
        
    
-   **For Bulk Storage:**
    
        **/downloads/**
        **/tmp/**
        **/.Trash-*/**
        **/*.part
        **/*.crdownload
        
    

> ⚠️ **Recursive Backup Protection:** If your backup destination directory (`BACKREST_REPO_DIR`) lives inside any of the source trees (such as inside `/srv`), explicitly add that path to the exclusion list (e.g., `/backup/srv/backups/**`) to prevent Restic from backing up its own repository in an infinite loop.

## Database Consistency & Hooks

While filesystem snapshots work seamlessly for static files, active database engines (PostgreSQL, MariaDB, MongoDB) may be writing transactions during backup runs.

Because `/var/run/docker.sock` is mounted into the container, you can define **Hooks** in Backrest plan settings to pause and unpause database containers around the snapshot phase:

-   **Pre-backup Hook:**
    
        docker pause <database_container_1> <database_container_2>
        
    
-   **Post-backup Hook (Always run):**
    
        docker unpause <database_container_1> <database_container_2>
        
    

Alternatively, use the pre-backup hook to invoke a logical dump command (such as `docker exec <db_container> pg_dumpall > /path/to/dump.sql`).

## Prerequisites

### 1\. External Ingress Network

Backrest is configured to sit behind a reverse proxy (such as [Nginx Proxy Manager](https://www.google.com/search?q=../proxy-stack/README.md)). Ensure the proxy network exists on the host:

    docker network create proxy_net
    

### 2\. Cloud Storage Setup (Optional)

If sending backups off-site using cloud storage (Cloudflare R2, AWS S3, Google Drive, Backblaze B2, Hetzner Storage Box):

1.  Configure your remote on the host using `rclone config`.
    
2.  Verify that `rclone.conf` is located in the directory mapped by `HOST_RCLONE_CONFIG_DIR`.
    

## Observability & The Override Layer

This repository includes a `docker-compose.override.yml` file designed to connect the stack to centralized logging (such as Promtail/Loki) via `monitoring_net`.

Refer to the [Monitoring Stack Documentation](https://www.google.com/search?q=../monitoring-stack-gpnc/README.md) for network details.

**⚠️ Optional Feature:** The override is completely optional:

-   **Komodo Users:** Exclude `docker-compose.override.yml` from the "File Paths" setting if monitoring is not required.
    
-   **CLI Users:** Run standalone using `docker compose -f docker-compose.yml up -d`.
    

## Setup & Deployment

### Option A: GitOps via Komodo (Recommended)

1.  Register this directory as a stack in your Komodo instance.
    
2.  Define the environment variables following `.env.example`.
    
3.  In **File Paths**, specify `docker-compose.yml` (and `docker-compose.override.yml` if using the monitoring network).
    
4.  Deploy the stack.
    

### Option B: Manual CLI Deployment

1.  Copy and configure the environment variables:
    
        cp .env.example .env
        nano .env
        
    
2.  Start the service:
    
        docker compose up -d
        
    

## Post-Deployment Access & Initialization

-   **Web UI Access:** Access through the reverse proxy using the container name `backrest` on port `9898`, or via `http://127.0.0.1:9898`.
    
-   **Configuring Repositories:**
    
    -   When creating a repository, enable **Auto Initialize** to allow Backrest to initialize the Restic repository structure automatically using the configured password.
        
    -   **Local paths:** Point to `/repos/external/<subfolder>`.
        
    -   **Cloud remotes:** Point to `rclone:<remote_name>:<bucket_or_path>`.
