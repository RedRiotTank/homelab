# APPFLOWY DISASTER RECOVERY RUNBOOK
 
## Overview 
This runbook details the procedure for recovering a completely broken AppFlowy deployment. The recovery uses the backup-manager container with Restic to extract the latest snapshot from Google Drive, restoring both the PostgreSQL database and the MinIO storage volumes dynamically.

## Prerequisites

-   A functional Docker environment.
    
-   The backup-manager container running with Restic and Rclone configured.
    
-   AppFlowy containers present on the host (even if the data is corrupted or empty).
    
-   The automated recovery script located at /opt/backup-manager/restore\_appflowy.sh.
    

## Method 1: Automated Recovery (Recommended)

For a fast, unattended recovery, use the existing bash script. This script will safely stop the application, wipe corrupted data, and rebuild the environment from the latest snapshot.

**Execute the Recovery** Run the script directly with root privileges:

sudo /opt/backup-manager/restore\_appflowy.sh

Wait for the terminal to display "AppFlowy Recovery Completed Successfully". Once finished, clear your browser cache (Ctrl + F5) and access your AppFlowy instance.

## Method 2: Manual Recovery (Fallback)

If the script fails or you need to debug the process step by step, follow this manual sequence.

**1\. Stop Application Containers** Keep only PostgreSQL and MinIO running to inject data: docker stop appflowy\_appflowy\_cloud\_1 appflowy\_appflowy\_worker\_1 appflowy\_appflowy\_web\_1 appflowy\_gotrue\_1 appflowy\_nginx\_1 appflowy\_redis\_1

**2\. Clean Corrupted Data** Wipe the database schemas: docker exec -i appflowy\_postgres\_1 psql -U postgres -d postgres -c "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;" docker exec -i appflowy\_postgres\_1 psql -U postgres -d postgres -c "DROP SCHEMA IF EXISTS auth CASCADE;"

Wipe the MinIO volume: docker exec -i appflowy\_minio\_1 sh -c 'rm -rf /data/\* /data/.\[!.\]\* 2>/dev/null || true'

**3\. Download Backup via Restic** docker exec -it -e RESTIC\_PASSWORD="YOUR\_PASSWORD" backup-manager restic -r rclone:gdrive:backups/appflowy restore latest --target /tmp/recovery\_af

**4\. Restore Data** Inject the SQL dump: docker exec -i backup-manager cat /tmp/recovery\_af/tmp/appflowy-db.sql | docker exec -i appflowy\_postgres\_1 psql -U postgres -d postgres

Copy MinIO files: docker exec -i backup-manager bash -c "docker cp /tmp/recovery\_af/tmp/minio\_data\_dump/. appflowy\_minio\_1:/data/"

**5\. Cleanup and Restart** docker exec -i backup-manager rm -rf /tmp/recovery\_af docker start appflowy\_appflowy\_cloud\_1 appflowy\_appflowy\_worker\_1 appflowy\_appflowy\_web\_1 appflowy\_gotrue\_1 appflowy\_nginx\_1 appflowy\_redis\_1
