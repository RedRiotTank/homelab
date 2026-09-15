# Bookshelf Disaster Recovery Runbook

## Overview
This runbook details the procedure for recovering a completely broken Bookshelf deployment (Calibre-Web and LazyLibrarian configurations, databases, and optionally the physical book library). The recovery uses `backup-manager` with Restic to extract the latest snapshot from Google Drive and restores the `/opt/bookshelf` configuration directory (and `/srv/media/books` if backed up).

## Prerequisites
- A functional Docker and Docker Compose environment.
- The `backup-manager` container up and running (contains Restic and Rclone configured for Google Drive).
- Access to the host machine as a user with `sudo` privileges.
- A properly configured `.env` file in `/opt/backup-manager` containing your `RESTIC_PASSWORD`.

## Method 1: Automated Recovery (Recommended)

For a fast and unattended recovery, you can use the pre-built automated bash script. This script automatically reads your `.env` file, downloads the snapshot, and determines if it needs to restore the physical books based on your variables.

### 1\. Execute the Recovery

Run the script with sudo privileges directly from the backup-manager directory:

```Bash

    cd /opt/backup-manager
    sudo ./restore_bookshelf.sh
```    

## Method 2: Manual Recovery (Fallback)

If you prefer to run the steps manually to debug or understand the process, follow these instructions.

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

### 3\. Download the Latest Snapshot

Extract the latest snapshot from Google Drive into a temporary directory inside the `backup-manager` container. _(Replace `YOUR_RESTIC_PASSWORD` with your actual password)._

```Bash

    docker exec -it -e RESTIC_PASSWORD="YOUR_RESTIC_PASSWORD" backup-manager \
      restic -r rclone:gdrive:backups/bookshelf restore latest --target /tmp/recovery_bookshelf
```    

### 4\. Restore Configuration Files and Permissions

Copy the restored configuration files from the container back to your host and set the correct permissions (PUID/PGID 1001):

```Bash

    sudo docker cp backup-manager:/tmp/recovery_bookshelf/opt/bookshelf/. /opt/bookshelf/
    sudo chown -R 1001:1001 /opt/bookshelf
```    

### 4.1 Restore Physical Book Library (Optional)

**IMPORTANT:** Only run this step if you have set `BOOKSHELF_BACKUP_BOOKS=true` and your snapshot actually contains the `/srv/media/books` directory.

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
