# Backup Manager

A fully containerized, declarative, and automated backup engine for the homelab infrastructure. It leverages **Restic** for deduplicated, encrypted snapshots, **Rclone** to push backups securely to remote storage (e.g., Google Drive), and **jq** for JSON-driven service orchestration.

## Features

- **Centralized Engine (`backup_engine.sh`):** A single execution engine handles pre-hooks, database dumps, conditional volume mounts, exclusions, snapshot uploads, retention policies, and post-hooks.
- **Declarative Configuration (`services.json`):** All service parameters, paths, schedules, and container hooks are declared centrally in a clean JSON format.
- **Dynamic Cron Generation:** Scheduled tasks are read directly from `services.json` and registered into the crontab at container boot (`entrypoint.sh`).
- **Disaster Recovery Isolation:** Recovery runbooks and atomic recovery scripts are organized within a decoupled `disaster-recovery/` directory to prevent single-point-of-failure dependencies during emergencies.
- **Monitoring Integration:** Ready to plug into Prometheus/Promtail/Loki stacks without polluting the base configuration.

## Prerequisites

1. A working Docker and Docker Compose environment.
2. A valid `rclone.conf` file configured on the host machine (e.g., in `~/.config/rclone/`).
3. A remote storage backend supported by Rclone (e.g., `gdrive`).

## Setup & Installation

### 1. Configure Environment Variables
Copy the provided example template and populate it with your specific environment details:

```bash
cp .env.example .env
nano .env
```
Ensure you define a strong `RESTIC_PASSWORD` and match the paths to your host system:

-   **Static Hostname:** Set `BACKUP_HOSTNAME=RedServer` so Restic tracks parent snapshots correctly across container recreations.
    
-   **Opt-in Activation:** Set `ENABLE_BACKUP_<SERVICE>="true"` in your `.env` to activate automated cron schedules for that service.
    

### 2\. Configure Disaster Recovery Symlink

The atomic restore scripts resolve runtime variables from `.env`. Ensure the symlink inside `disaster-recovery/` is established:

```Bash
ln -s ../.env disaster-recovery/.env
```    

### 3\. Configure Local Monitoring (Optional)

If your homelab uses an external Docker network for logging (e.g., Promtail), create a `docker-compose.override.yml` file:

```YAML
version: '3.8'
services:
  backup-manager:
    networks:
      - monitoring_net
    labels:
      logging_jobname: "backup-manager-logs"
      logging: "promtail"

networks:
  monitoring_net:
    external:
      name: ${DOCKER_MONITORING_NETWORK:-monitoring}
```    

_(Note: `docker-compose.override.yml` is ignored by Git)._

### 4\. Build and Deploy

Build the image and launch the container:

```Bash
docker compose build --no-cache
docker compose up -d
```    

Verify that the crontab has been dynamically generated:

```Bash
docker exec backup-manager crontab -l
```    

### 5\. Initialize Restic Repositories (First Time Only)

Before taking your first backup on a fresh remote storage backend, initialize the Restic repositories:

```Bash

docker exec backup-manager restic -r rclone:gdrive:backups/appflowy init
docker exec backup-manager restic -r rclone:gdrive:backups/nextcloud init
docker exec backup-manager restic -r rclone:gdrive:backups/homarr init
docker exec backup-manager restic -r rclone:gdrive:backups/jellyfin init
docker exec backup-manager restic -r rclone:gdrive:backups/romm init
docker exec backup-manager restic -r rclone:gdrive:backups/bookshelf init
docker exec backup-manager restic -r rclone:gdrive:backups/arr init
```    

## Usage

### Trigger a Manual Backup

Run the central backup engine inside the container specifying the target service key from `services.json`:

```Bash
docker exec backup-manager /usr/local/bin/backup_engine.sh <service_name>
```    

Examples:

```Bash

docker exec backup-manager /usr/local/bin/backup_engine.sh nextcloud
docker exec backup-manager /usr/local/bin/backup_engine.sh jellyfin
docker exec backup-manager /usr/local/bin/backup_engine.sh arr
```    

### View Live Logs

Cron and engine execution outputs are streamed to stdout. Inspect them with:

```Bash
docker compose logs -f backup-manager
```    

## Disaster Recovery

Recovery scripts and guides are decoupled from the central engine to ensure atomic, zero-dependency restoration during outages. Refer to the runbooks in `disaster-recovery/`:

- [AppFlowy Disaster Recovery](disaster-recovery/APPFLOWY_DISASTER_RECOVERY.md)
- [Arr Stack Disaster Recovery](disaster-recovery/ARR_DISASTER_RECOVERY.md)
- [Bookshelf Disaster Recovery](disaster-recovery/BOOKSHELF_DISASTER_RECOVERY.md)
- [Homarr Disaster Recovery](disaster-recovery/HOMARR_DISASTER_RECOVERY.md)
- [Jellyfin Disaster Recovery](disaster-recovery/JELLYFIN_DISASTER_RECOVERY.md)
- [Nextcloud Disaster Recovery](disaster-recovery/NEXTCLOUD_DISASTER_RECOVERY.md)
- [RomM Disaster Recovery](disaster-recovery/ROMM_DISASTER_RECOVERY.md)

To run a recovery procedure:

```Bash
bash disaster-recovery/restore_<service_name>.sh
```
