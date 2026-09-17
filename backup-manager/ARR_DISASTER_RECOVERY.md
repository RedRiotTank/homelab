# Arr Stack Disaster Recovery Runbook

## Overview

This runbook details the procedure for recovering a broken Arr Stack deployment (qBittorrent, Sonarr, Prowlarr, Kitsunarr). The recovery uses `backup-manager` with Restic to extract the latest snapshot from Google Drive and restore `/opt/arr-stack` configurations and metadata.

## Prerequisites

- Functional Docker environment.
- The `backup-manager` container up and running.
- Access to the host machine with `sudo` privileges.

## Method 1: Automated Recovery (Recommended)

Execute the recovery script directly:

```bash
sudo /opt/backup-manager/restore_arr.sh
```

## Method 2: Manual Recovery (Fallback)

1. **Stop Arr Stack Containers:**
  ```Bash
  cd /opt/arr-stack
  docker compose down
  ```
2. **Clean Existing Corrupted Configuration Data:** Bash
  ```Bash
  sudo rm -rf /opt/arr-stack/qbit-config /opt/arr-stack/sonarr /opt/arr-stack/prowlarr /opt/arr-stack/kitsunarr-data /opt/arr-stack/kitsunarr-secrets
  ```
3. **Download Snapshot from Restic:** 
  ```Bash
  docker exec -it -e RESTIC_PASSWORD="YOUR_RESTIC_PASSWORD" backup-manager \
  restic -r rclone:gdrive:backups/arr restore latest --target /tmp/recovery_arr
  ```
4. **Restore Physical Data and Permissions:** Bash
  ```Bash
  sudo docker cp backup-manager:/tmp/recovery_arr/opt/arr-stack/. /opt/arr-stack/
  sudo chown -R 1001:1001 /opt/arr-stack/qbit-config /opt/arr-stack/sonarr /opt/arr-stack/prowlarr
  [ -d "/opt/arr-stack/kitsunarr-data" ] && sudo chown -R 1001:1001 /opt/arr-stack/kitsunarr-data /opt/arr-stack/kitsunarr-secrets || true
  ```
5. **Restart and Cleanup:** Bash
  ```
  cd /opt/arr-stack
  docker compose up -d --remove-orphans
  docker exec -it backup-manager rm -rf /tmp/recovery_arr
  ```
