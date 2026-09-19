# RomM Disaster Recovery Runbook

## Overview
This runbook details the procedure for recovering a completely broken RomM deployment (e.g., deleted database and lost configuration/assets). The recovery uses `backup-manager` with Restic to extract the latest snapshot from Google Drive and restores both the MariaDB database and the `/opt/romm` configuration files.

**Note:** The `library/` folder (ROMs) is typically excluded from backups to save space (unless explicitly configured otherwise) and will not be affected by this restoration process.

## Prerequisites
- A functional Docker and Docker Compose environment.
- The `backup-manager` container up and running (contains Restic and Rclone configured for Google Drive).
- Access to the host machine as a user with `sudo` privileges.
- RomM containers (`romm` and `romm-db`) present on the host (even if broken or empty).
- Valid credentials configured in `/opt/backup-manager/.env` (linked inside `disaster-recovery/.env`).

---

## Method 1: Automated Recovery (Recommended)

For a fast and unattended recovery, use the preconfigured script located in this directory. It automatically sources runtime credentials and variables from `.env`.

### Execute the Recovery
Run the dedicated restore script directly:

```bash
cd /opt/backup-manager/disaster-recovery
./restore_romm.sh
```

_(Alternatively, invoke it from anywhere using its full path: `bash /opt/backup-manager/disaster-recovery/restore_romm.sh`)_

Wait for the terminal to display `"RomM Recovery Completed Successfully"`. Once finished, access the RomM web UI to verify that covers, metadata, and user libraries have restored properly.

## Method 2: Manual Recovery (Fallback)

If you prefer to run the steps manually to debug or inspect the process step-by-step, execute the following commands in order:

### 1\. Stop RomM Container

Before modifying the database or data files, stop the application container to prevent locks:

```Bash
docker stop romm
```    

### 2\. Clean Existing Data (Keeping Library)

Wipe the corrupted metadata folders while leaving the ROM library intact:

```Bash
sudo rm -rf /opt/romm/assets /opt/romm/config /opt/romm/resources
sudo mkdir -p /opt/romm/assets /opt/romm/config /opt/romm/resources
```    

### 3\. Download the Latest Snapshot from Google Drive

```Bash
docker exec -it -e RESTIC_PASSWORD="$(grep RESTIC_PASSWORD /opt/backup-manager/.env | cut -d '=' -f2)" backup-manager \
restic -r rclone:gdrive:backups/romm restore latest --target /tmp/recovery_romm
```    

### 4\. Restore the Database

Inject the downloaded SQL dump directly into the running MariaDB container:

```Bash
docker exec -i backup-manager cat /tmp/recovery_romm/tmp/romm-db.sql | \
docker exec -i romm-db sh -c 'mariadb -u "$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE"'
```    

### 5\. Restore Physical Data and Permissions

Copy the restored files back to the host and fix ownership (PUID/PGID 1000:1000):

```Bash
sudo docker cp backup-manager:/tmp/recovery_romm/opt/romm/. /opt/romm/
sudo chown -R 1000:1000 /opt/romm/assets /opt/romm/config /opt/romm/resources
```    

### 6\. Restart Container

Start the RomM container back up:

```Bash
docker start romm
```    

### 7\. Cleanup Temporary Files

Remove the downloaded snapshot data from the backup manager:

```Bash
docker exec -it backup-manager rm -rf /tmp/recovery_romm
```
