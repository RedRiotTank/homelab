# Jellyfin Disaster Recovery Runbook

## Overview

This runbook details the procedure for recovering a broken Jellyfin media server deployment. The recovery uses `backup-manager` with Restic to extract the latest snapshot from Google Drive and restore `/srv/appdata/jellyfin/config`.

## Prerequisites

-   Functional Docker environment.
    
-   The `backup-manager` container up and running.
    
-   Access to the host machine with `sudo` privileges.
    

## Method 1: Automated Recovery (Recommended)

Execute the recovery script directly:

Bash

```
sudo /opt/backup-manager/restore_jellyfin.sh
```

## Method 2: Manual Recovery (Fallback)

1.  **Stop Jellyfin Container:**
    
    Bash
    
    ```
    docker stop jellyfin
    ```
    
2.  **Clean Existing Corrupted Data:**
    
    Bash
    
    ```
    sudo rm -rf /srv/appdata/jellyfin/config
    sudo mkdir -p /srv/appdata/jellyfin/config
    ```
    
3.  **Download Snapshot from Restic:**
    
    Bash
    
    ```
    docker exec -it -e RESTIC_PASSWORD="YOUR_RESTIC_PASSWORD" backup-manager \
      restic -r rclone:gdrive:backups/jellyfin restore latest --target /tmp/recovery_jellyfin
    ```
    
4.  **Restore Physical Data and Permissions:**
    
    Bash
    
    ```
    sudo docker cp backup-manager:/tmp/recovery_jellyfin/srv/appdata/jellyfin/config/. /srv/appdata/jellyfin/config/
    sudo chown -R 1000:1000 /srv/appdata/jellyfin/config
    ```
    
5.  **Restart and Cleanup:**
    
    Bash
    
    ```
    docker start jellyfin
    docker exec -it backup-manager rm -rf /tmp/recovery_jellyfin
    ```
