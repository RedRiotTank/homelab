# Jellyfin Disaster Recovery Runbook

## Overview
This runbook details the procedure for recovering a broken Jellyfin media server deployment. The recovery uses the `backup-manager` container with Restic to extract the latest snapshot from Google Drive and restore `/srv/appdata/jellyfin/config`.

## Prerequisites
- A functional Docker and Docker Compose environment.
- The `backup-manager` container up and running (contains Restic and Rclone configured for Google Drive).
- Access to the host machine as a user with `sudo` privileges.
- Jellyfin container (`jellyfin`) present on the host (even if broken or empty).
- Valid credentials configured in `/opt/backup-manager/.env` (linked inside `disaster-recovery/.env`).

---

## Method 1: Automated Recovery (Recommended)

For a fast and unattended recovery, use the preconfigured script located in this directory. It automatically sources runtime credentials and variables from `.env`.

### Execute the Recovery
Run the dedicated restore script directly:

```bash
cd /opt/backup-manager/disaster-recovery
./restore_jellyfin.sh
```

_(Alternatively, invoke it from anywhere using its full path: `bash /opt/backup-manager/disaster-recovery/restore_jellyfin.sh`)_

Wait for the terminal to display `"Jellyfin Recovery Completed Successfully"`. Once finished, access Jellyfin through your browser to verify that libraries and user profiles load properly.

## Method 2: Manual Recovery (Fallback)

If you prefer to run the steps manually to debug or inspect the process step-by-step, execute the following commands in order:

### 1\. Stop Jellyfin Container

```Bash
docker stop jellyfin
```   

### 2\. Clean Existing Corrupted Data

```Bash
sudo rm -rf /srv/appdata/jellyfin/config
sudo mkdir -p /srv/appdata/jellyfin/config
```    

### 3\. Download the Latest Snapshot from Google Drive

```Bash
docker exec -it -e RESTIC_PASSWORD="$(grep RESTIC_PASSWORD /opt/backup-manager/.env | cut -d '=' -f2)" backup-manager \
restic -r rclone:gdrive:backups/jellyfin restore latest --target /tmp/recovery_jellyfin
```    

### 4\. Restore Physical Data and Permissions

```Bash
sudo docker cp backup-manager:/tmp/recovery_jellyfin/srv/appdata/jellyfin/config/. /srv/appdata/jellyfin/config/
sudo chown -R 1000:1000 /srv/appdata/jellyfin/config
```    

### 5\. Restart and Cleanup

```Bash
docker start jellyfin
docker exec -it backup-manager rm -rf /tmp/recovery_jellyfin
```
