# Arr Stack Disaster Recovery Runbook

## Overview
This runbook details the procedure for recovering a broken Arr Stack deployment (qBittorrent, Sonarr, Prowlarr, Kitsunarr). The recovery uses the `backup-manager` container with Restic to extract the latest snapshot from Google Drive and restore `/opt/arr-stack` configurations and metadata.

## Prerequisites
- A functional Docker and Docker Compose environment.
- The `backup-manager` container up and running (contains Restic and Rclone configured for Google Drive).
- Access to the host machine as a user with `sudo` privileges.
- Valid credentials configured in `/opt/backup-manager/.env` (linked inside `disaster-recovery/.env`).

---

## Method 1: Automated Recovery (Recommended)

For a fast and unattended recovery, use the preconfigured script located in this directory. It automatically sources runtime credentials and variables from `.env`.

### Execute the Recovery
Run the dedicated restore script directly:

```bash
cd /opt/backup-manager/disaster-recovery
./restore_arr.sh
```

_(Alternatively, invoke it from anywhere using its full path: `bash /opt/backup-manager/disaster-recovery/restore_arr.sh`)_

## Method 2: Manual Recovery (Fallback)

If you prefer to run the steps manually to debug or inspect the process step-by-step, execute the following commands in order:

### 1\. Stop Arr Stack Containers

```Bash
cd /opt/arr-stack
docker compose down
```    

### 2\. Clean Existing Corrupted Configuration Data

```Bash
sudo rm -rf /opt/arr-stack/qbit-config /opt/arr-stack/sonarr /opt/arr-stack/prowlarr /opt/arr-stack/kitsunarr-data /opt/arr-stack/kitsunarr-secrets
```    

### 3\. Download the Latest Snapshot from Google Drive

```Bash
docker exec -it -e RESTIC_PASSWORD="$(grep RESTIC_PASSWORD /opt/backup-manager/.env | cut -d '=' -f2)" backup-manager \
restic -r rclone:gdrive:backups/arr restore latest --target /tmp/recovery_arr
```    

### 4\. Restore Physical Data and Permissions

```Bash
sudo docker cp backup-manager:/tmp/recovery_arr/opt/arr-stack/. /opt/arr-stack/
sudo chown -R 1001:1001 /opt/arr-stack/qbit-config /opt/arr-stack/sonarr /opt/arr-stack/prowlarr
[ -d "/opt/arr-stack/kitsunarr-data" ] && sudo chown -R 1001:1001 /opt/arr-stack/kitsunarr-data /opt/arr-stack/kitsunarr-secrets || true
```    

### 5\. Restart and Cleanup

```Bash
cd /opt/arr-stack
docker compose up -d --remove-orphans
docker exec -it backup-manager rm -rf /tmp/recovery_arr
```
