# RomM Disaster Recovery Runbook

## Overview

This runbook details the procedure for recovering a completely broken RomM deployment (e.g., deleted database and lost configuration/assets). The recovery uses `backup-manager` with Restic to extract the latest snapshot from Google Drive and restores both the MariaDB database and the `/opt/romm` configuration files.

**Note:** The `library/` folder (ROMs) is typically excluded from backups to save space (unless explicitly configured otherwise) and will not be affected by this restoration process.

## Prerequisites

- A functional Docker and Docker Compose environment.
- The `backup-manager` container up and running (contains Restic and Rclone configured for Google Drive).
- Access to the host machine as a user with `sudo` privileges.
- RomM containers (`romm` and `romm-db`) present on the host (even if broken or empty).

## Method 1: Automated Recovery (Recommended)

For a fast and unattended recovery, you can use the automated bash script already present in your deployment.

### 1. Locate the Script

The recovery script is located at `/opt/backup-manager/restore_romm.sh`.

### 2. Execute the Recovery

Run the script with sudo privileges:

```
sudo /opt/backup-manager/restore_romm.sh
```

## Method 2: Manual Recovery (Fallback)

If you prefer to run the steps manually to debug or understand the process, follow these instructions.

### 1. Stop RomM Container

Before modifying the database or data files, the application container must be stopped to prevent locks:

```
docker stop romm
```

### 2. Clean Existing Data (Keeping Library)

Wipe the corrupted metadata folders while leaving the ROM library intact:

```
sudo rm -rf /opt/romm/assets /opt/romm/config /opt/romm/resources
sudo mkdir -p /opt/romm/assets /opt/romm/config /opt/romm/resources
```

### 3. Download the Latest Snapshot

Download the latest backup from Google Drive to a temporary location:

```
docker exec -it -e RESTIC_PASSWORD="YOUR_RESTIC_PASSWORD" backup-manager \
  restic -r rclone:gdrive:backups/romm restore latest --target /tmp/recovery_romm
```

### 4. Restore the Database

Inject the downloaded SQL dump directly into the running MariaDB container (replace variables with your actual credentials if not using the automated script):

```
docker exec -i backup-manager cat /tmp/recovery_romm/tmp/romm-db.sql | \
  docker exec -i romm-db sh -c 'mariadb -u "$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE"'
```

### 5. Restore Physical Data and Permissions

Copy the restored files back to the host and fix permissions:

```
sudo docker cp backup-manager:/tmp/recovery_romm/opt/romm/. /opt/romm/
sudo chown -R 1000:1000 /opt/romm/assets /opt/romm/config /opt/romm/resources
```

### 6. Restart Container

Start the RomM container back up:

```
docker start romm
```

### 7. Cleanup Temporary Files

Remove the downloaded snapshot data from the backup manager:

```
docker exec -it backup-manager rm -rf /tmp/recovery_romm
```
