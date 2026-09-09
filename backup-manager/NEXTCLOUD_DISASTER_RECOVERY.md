# Nextcloud Disaster Recovery Runbook

## Overview
This runbook details the procedure for recovering a completely broken Nextcloud deployment (e.g., deleted database and lost data directory). The recovery uses `backup-manager` with Restic to extract the latest snapshot from Google Drive and restores both the PostgreSQL database and the `/srv/nextcloud_data` physical files.

## Prerequisites
- A functional Docker and Docker Compose environment.
- The `backup-manager` container up and running (contains Restic and Rclone configured for Google Drive).
- Access to the host machine as a user with `sudo` privileges.
- Nextcloud containers (`nextcloud` and `nextcloud-db`) present on the host (even if broken or empty).

---

## Method 1: Automated Recovery (Recommended)

For a fast and unattended recovery, you can use the automated bash script. 

### 1. Create the Script
Create a file named `restore_nextcloud.sh` (e.g., in `/opt/backup-manager/`):
```bash
nano /opt/backup-manager/restore_nextcloud.sh
```

Paste the following content, replacing `<YOUR_RESTIC_PASSWORD_HERE>` with your actual password:

```bash
#!/bin/bash
# Nextcloud Full Disaster Recovery Script
# WARNING: This script will DESTROY current data in /srv/nextcloud_data and the nextcloud database before restoring.

# Configuration variables
RESTIC_PASSWORD="<YOUR_RESTIC_PASSWORD_HERE>"
RESTIC_REPO="rclone:gdrive:backups/nextcloud"
DATA_DIR="/srv/nextcloud_data"
DB_USER="nextcloud_user"
DB_NAME="nextcloud"
TEMP_RECOVERY_DIR="/tmp/recovery_nc"

echo "=== [$(date '+%Y-%m-%d %H:%M:%S')] Starting Nextcloud Disaster Recovery ==="

echo "-> 1. Stopping Nextcloud container to prevent locks..."
docker stop nextcloud

echo "-> 2. Wiping existing database schema..."
docker exec -i nextcloud-db psql -U "$DB_USER" -d "$DB_NAME" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

echo "-> 3. Wiping and recreating the data directory..."
sudo rm -rf "${DATA_DIR}"
sudo mkdir -p "${DATA_DIR}"

echo "-> 4. Downloading the latest snapshot from Google Drive..."
docker exec -e RESTIC_PASSWORD="${RESTIC_PASSWORD}" backup-manager \
  restic -r "${RESTIC_REPO}" restore latest --target "${TEMP_RECOVERY_DIR}"

echo "-> 5. Restoring PostgreSQL database..."
docker exec -i backup-manager cat "${TEMP_RECOVERY_DIR}/tmp/nextcloud-db.sql" | \
  docker exec -i nextcloud-db psql -U "$DB_USER" -d "$DB_NAME"

echo "-> 6. Restoring physical files to ${DATA_DIR}..."
sudo docker cp backup-manager:"${TEMP_RECOVERY_DIR}${DATA_DIR}/." "${DATA_DIR}/"

echo "-> 7. Fixing ownership and permissions for the web server (www-data)..."
sudo chown -R 33:33 "${DATA_DIR}"
sudo chmod 0750 "${DATA_DIR}"

echo "-> 8. Fixing PostgreSQL database permissions (search_path and global access)..."
docker exec -i nextcloud-db psql -U "$DB_USER" -d "$DB_NAME" -c "
GRANT USAGE, CREATE ON SCHEMA public TO PUBLIC;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO PUBLIC;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO PUBLIC;
ALTER DATABASE ${DB_NAME} SET search_path TO public;
"

echo "-> 9. Restarting Nextcloud and Database containers to flush connections..."
docker restart nextcloud-db nextcloud

echo "-> 10. Waiting 10 seconds for the database to fully initialize..."
sleep 10

echo "-> 11. Disabling maintenance mode..."
docker exec -u www-data nextcloud php occ maintenance:mode --off || true

echo "-> 12. Cleaning up temporary recovery files..."
docker exec -i backup-manager rm -rf "${TEMP_RECOVERY_DIR}"

echo "=== [$(date '+%Y-%m-%d %H:%M:%S')] Nextcloud Recovery Completed Successfully ==="
```

### 2. Execute the Recovery
Make the script executable and run it:
```bash
chmod +x /opt/backup-manager/restore_nextcloud.sh
sudo /opt/backup-manager/restore_nextcloud.sh
```

---

## Method 2: Manual Recovery (Fallback)

If you prefer to run the steps manually to debug or understand the process, follow these instructions.

### 1. Stop Nextcloud Container
Before modifying the database or data files, the application container must be stopped:
```bash
docker stop nextcloud
```

### 2. Clean Existing Data
**Empty Database:**
```bash
docker exec -it nextcloud-db psql -U nextcloud_user -d nextcloud -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
```
**Empty Data Directory:**
```bash
sudo rm -rf /srv/nextcloud_data
sudo mkdir -p /srv/nextcloud_data
```

### 3. Download the Latest Snapshot from Google Drive
```bash
docker exec -it -e RESTIC_PASSWORD="YOUR_RESTIC_PASSWORD" backup-manager \
  restic -r rclone:gdrive:backups/nextcloud restore latest --target /tmp/recovery_nc
```

### 4. Restore the Database
```bash
docker exec -i backup-manager cat /tmp/recovery_nc/tmp/nextcloud-db.sql | \
  docker exec -i nextcloud-db psql -U nextcloud_user -d nextcloud
```

### 5. Restore Physical Data and Permissions
```bash
sudo docker cp backup-manager:/tmp/recovery_nc/srv/nextcloud_data/. /srv/nextcloud_data/
sudo chown -R 33:33 /srv/nextcloud_data
sudo chmod 0750 /srv/nextcloud_data
```

### 6. Fix Database Permissions (Crucial Step)
Apply global access to the schema and force the search path:
```bash
docker exec -it nextcloud-db psql -U nextcloud_user -d nextcloud -c "
GRANT USAGE, CREATE ON SCHEMA public TO PUBLIC;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO PUBLIC;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO PUBLIC;
ALTER DATABASE nextcloud SET search_path TO public;
"
```
Restart the database and application containers to flush connection caches:
```bash
docker restart nextcloud-db nextcloud
```
*Wait 10 seconds for the database to fully initialize.*

### 7. Disable Maintenance Mode
```bash
docker exec -u www-data nextcloud php occ maintenance:mode --off
```

### 8. Cleanup Temporary Files
```bash
docker exec -it backup-manager rm -rf /tmp/recovery_nc
```
