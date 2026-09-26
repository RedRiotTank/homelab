# Bookshelf Disaster Recovery Runbook

## Overview
This runbook details the procedure for recovering a completely broken Bookshelf deployment (Calibre-Web and LazyLibrarian configurations, databases, and optionally the physical book library). The recovery uses `backup-manager` with Restic to extract the latest snapshot from Google Drive and restores the `/opt/bookshelf` configuration directory (and `/srv/media/books` if backed up).

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
./restore_bookshelf.sh
```

_(Alternatively, invoke it from anywhere using its full path: `bash /opt/backup-manager/disaster-recovery/restore_bookshelf.sh`)_

## Method 2: Manual Recovery (Fallback)

If you prefer to run the steps manually to debug or inspect the process step-by-step, execute the following commands in order:

### 1\. Stop Containers

Before modifying any configuration files, the application containers must be stopped to prevent locks or partial writes:

```Bash
docker stop calibre-web lazylibrarian
```    

### 2\. Clean Existing Config

Wipe the existing configuration metadata to ensure a clean slate:

```Bash
sudo rm -rf /opt/bookshelf/config
sudo mkdir -p /opt/bookshelf/config
```    

### 3\. Download the Latest Snapshot from Google Drive

```Bash
docker exec -it -e RESTIC_PASSWORD="$(grep RESTIC_PASSWORD /opt/backup-manager/.env | cut -d '=' -f2)" backup-manager \
restic -r rclone:gdrive:backups/bookshelf restore latest --target /tmp/recovery_bookshelf
```    

### 4\. Restore Configuration Files and Permissions

Copy the restored configuration files from the container back to your host and set the correct permissions (PUID/PGID 1001):

```Bash
sudo docker cp backup-manager:/tmp/recovery_bookshelf/opt/bookshelf/. /opt/bookshelf/
sudo chown -R 1001:1001 /opt/bookshelf
```    

### 4.1 Restore Physical Book Library (Optional)

**IMPORTANT:** Only run this step if you have set `BOOKSHELF_BACKUP_BOOKS=true` and your snapshot actually contains the `/srv/media/books` directory:

```Bash
sudo mkdir -p /srv/media/books
sudo docker cp backup-manager:/tmp/recovery_bookshelf/srv/media/books/. /srv/media/books/
sudo chown -R 1001:1001 /srv/media/books
```    

### 5\. Restart Containers

Start the containers back up using your existing Docker Compose configuration:

```Bash
cd /opt/bookshelf
docker compose up -d
```    

### 6\. Cleanup Temporary Files

Remove the extracted snapshot from the `backup-manager` container to free up space:

```Bash
docker exec -it backup-manager rm -rf /tmp/recovery_bookshelf
```    
