# Backup Manager

A fully containerized, agnostic, and automated backup solution for the homelab infrastructure. It leverages **Restic** for deduplicated, encrypted snapshots and **Rclone** to push backups securely to remote storage (e.g., Google Drive).

## Features

- **Automated Cron Jobs:** Built-in scheduling for daily backups.
- **Environment Driven:** Zero hardcoded paths, credentials, or container names. Fully portable.
- **Disaster Recovery Ready:** Includes step-by-step runbooks and automated restore scripts.
- **Monitoring Integration:** Ready to plug into Prometheus/Promtail/Loki stacks without polluting the base configuration.

## Prerequisites

1. A working Docker and Docker Compose environment.
2. A valid `rclone.conf` file configured on the host machine (e.g., in `~/.config/rclone/`).
3. A remote storage backend supported by Rclone.

## Setup & Installation

### 1. Configure Environment Variables
Copy the provided example template and populate it with your specific environment details:

```bash
cp .env.example .env
nano .env

```

Ensure you define a strong RESTIC_PASSWORD and match the paths to your host system.

### 2\. Configure Local Monitoring (Optional)

If your homelab uses an external Docker network for monitoring (e.g., Promtail), create a `docker-compose.override.yml` file to inject those settings without affecting the core `.yml`:

Bash

```
cat << 'EOF' > docker-compose.override.yml
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
EOF
```

_(Note: `docker-compose.override.yml` is ignored by Git)._

### 3\. Build and Deploy

Build the image (which dynamically sets up the timezone and cron jobs) and start the container:

Bash

```
docker compose up -d --build
```

## Usage

### Trigger a Manual Backup

You can manually trigger any backup script directly inside the running container:

Bash

```
docker exec backup-manager /usr/local/bin/backup_appflowy.sh
docker exec backup-manager /usr/local/bin/backup_nextcloud.sh
```

### View Logs

Cron job outputs are redirected to the container's standard output. View them using:

Bash

```
docker logs backup-manager -f
```

## Disaster Recovery

If a service goes down or data is corrupted, do not panic. Refer to the specific runbooks included in this directory for safe, tested recovery procedures:

-   [AppFlowy Disaster Recovery](APPFLOWY_DISASTER_RECOVERY.md)
    
-   [Nextcloud Disaster Recovery](NEXTCLOUD_DISASTER_RECOVERY.md)
