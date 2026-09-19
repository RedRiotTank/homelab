# Nextcloud Disaster Recovery Runbook

## Overview
This runbook details the procedure for recovering a completely broken Nextcloud deployment (e.g., deleted database and lost data directory). The recovery uses `backup-manager` with Restic to extract the latest snapshot from Google Drive and restores both the PostgreSQL database and the `/srv/nextcloud_data` physical files.

## Prerequisites
- A functional Docker and Docker Compose environment.
- The `backup-manager` container up and running (contains Restic and Rclone configured for Google Drive).
- Access to the host machine as a user with `sudo` privileges.
- Nextcloud containers (`nextcloud` and `nextcloud-db`) present on the host (even if broken or empty).
- Valid credentials configured in `/opt/backup-manager/.env` (linked inside `disaster-recovery/.env`).

---

## Method 1: Automated Recovery (Recommended)

For a fast and unattended recovery, use the preconfigured script located in this directory. It automatically sources runtime credentials and variables from `.env`.

### Execute the Recovery
Run the dedicated restore script directly:

```bash
cd /opt/backup-manager/disaster-recovery
./restore_nextcloud.sh
```

_(Alternatively, invoke it from anywhere using its full path: `bash /opt/backup-manager/disaster-recovery/restore_nextcloud.sh`)_

## Method 2: Manual Recovery (Fallback)

If you prefer to run the steps manually to debug or inspect the process step-by-step, execute the following commands in order:

### 1\. Stop Nextcloud Container

Before modifying the database or data files, stop the web application container:

```Bash
docker stop nextcloud
```
    

### 2\. Clean Existing Data

**Empty Database:**

```Bash
docker exec -it nextcloud-db psql -U nextcloud_user -d nextcloud -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
```    

**Empty Data Directory:**

```Bash
sudo rm -rf /srv/nextcloud_data
sudo mkdir -p /srv/nextcloud_data
```    

### 3\. Download the Latest Snapshot from Google Drive

```Bash
docker exec -it -e RESTIC_PASSWORD="$(grep RESTIC_PASSWORD /opt/backup-manager/.env | cut -d '=' -f2)" backup-manager \
restic -r rclone:gdrive:backups/nextcloud restore latest --target /tmp/recovery_nc
```    

### 4\. Restore the Database

```Bash
docker exec -i backup-manager cat /tmp/recovery_nc/tmp/nextcloud-db.sql | \
docker exec -i nextcloud-db psql -U nextcloud_user -d nextcloud
```    

### 5\. Restore Physical Data and Permissions

```Bash
sudo docker cp backup-manager:/tmp/recovery_nc/srv/nextcloud_data/. /srv/nextcloud_data/
sudo chown -R 33:33 /srv/nextcloud_data
sudo chmod 0750 /srv/nextcloud_data
 ```   

### 6\. Fix Database Permissions (Crucial Step)

Apply global access to the schema and force the search path:

```Bash
docker exec -it nextcloud-db psql -U nextcloud_user -d nextcloud -c "
GRANT USAGE, CREATE ON SCHEMA public TO PUBLIC;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO PUBLIC;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO PUBLIC;
ALTER DATABASE nextcloud SET search_path TO public;
"
```    

Restart the database and application containers to flush connection caches:

```Bash
docker restart nextcloud-db nextcloud
```

_Wait 10 seconds for the database to fully initialize._

### 7\. Disable Maintenance Mode

```Bash
docker exec -u www-data nextcloud php occ maintenance:mode --off
```    

### 8\. Cleanup Temporary Files

```Bash
docker exec -it backup-manager rm -rf /tmp/recovery_nc
```
