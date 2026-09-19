# Homarr Disaster Recovery Runbook

## Overview
This runbook details the procedure for recovering a completely broken Homarr deployment (e.g., deleted or corrupted SQLite database and configuration files). The recovery uses `backup-manager` with Restic to extract the latest snapshot from Google Drive and restores the `/opt/homarr/appdata` physical files.

## Prerequisites
- A functional Docker and Docker Compose environment.
- The `backup-manager` container up and running (contains Restic and Rclone configured for Google Drive).
- Access to the host machine as a user with `sudo` privileges.
- Homarr container (`homarr`) present on the host (even if broken or empty).
- Valid credentials configured in `/opt/backup-manager/.env` (linked inside `disaster-recovery/.env`).

---

## Method 1: Automated Recovery (Recommended)

For a fast and unattended recovery, use the preconfigured script located in this directory. It automatically sources runtime credentials and variables from `.env`.

### Execute the Recovery
Run the dedicated restore script directly:

```bash
cd /opt/backup-manager/disaster-recovery
./restore_homarr.sh
```

_(Alternatively, invoke it from anywhere using its full path: `bash /opt/backup-manager/disaster-recovery/restore_homarr.sh`)_

Wait for the terminal to display `"Homarr Recovery Completed Successfully"`. Once finished, refresh your browser to access your restored Homarr dashboard.

## Method 2: Manual Recovery (Fallback)

If you prefer to run the steps manually to debug or inspect the process step-by-step, execute the following commands in order:

### 1\. Stop Homarr Container

Before modifying the SQLite database or configuration files, the application container must be stopped to prevent locks or corruption:

```Bash
docker stop homarr
```    

### 2\. Clean Existing Corrupted Data

Wipe the current data directory and recreate it empty:

```Bash
sudo rm -rf /opt/homarr/appdata
sudo mkdir -p /opt/homarr/appdata
```    

### 3\. Download the Latest Snapshot from Google Drive

```Bash
docker exec -it -e RESTIC_PASSWORD="$(grep RESTIC_PASSWORD /opt/backup-manager/.env | cut -d '=' -f2)" backup-manager \
restic -r rclone:gdrive:backups/homarr restore latest --target /tmp/recovery_homarr
```    

### 4\. Restore Physical Data and Permissions

Copy the recovered files back to the host path and apply standard user ownership (PUID/PGID 1000:1000):

```Bash
sudo docker cp backup-manager:/tmp/recovery_homarr/opt/homarr/appdata/. /opt/homarr/appdata/
sudo chown -R 1000:1000 /opt/homarr/appdata
```    

### 5\. Cleanup and Restart

Start the Homarr container to load the restored data:

```Bash
docker start homarr
```    

Clean up the temporary recovery files inside the backup manager container:

```Bash
docker exec -it backup-manager rm -rf /tmp/recovery_homarr
```
