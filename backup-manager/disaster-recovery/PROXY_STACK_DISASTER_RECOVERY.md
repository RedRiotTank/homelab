# Proxy Stack Disaster Recovery Runbook

## Overview
This runbook details the procedure for recovering a completely broken or corrupted Proxy Stack (Nginx Proxy Manager + Cloudflare DDNS) deployment. The recovery uses the `backup-manager` container with Restic to extract the latest snapshot from Google Drive, restoring the internal SQLite configuration database, custom Nginx configurations, and Let's Encrypt SSL/TLS certificates and renewal metadata.

## Prerequisites
- A functional Docker and Docker Compose environment.
- The `backup-manager` container up and running (contains Restic and Rclone configured for Google Drive).
- Access to the host machine as a user with `sudo` privileges.
- Target directories `/opt/proxy-stack` present on the host.
- Valid credentials configured in `/opt/backup-manager/.env` (accessible via symlink in `disaster-recovery/.env`).

---

## Method 1: Automated Recovery (Recommended)

For a fast and unattended recovery, use the preconfigured script located in this directory. It automatically loads runtime credentials and environment variables.

### Execute the Recovery
Run the dedicated restore script directly:

```bash
cd /opt/backup-manager/disaster-recovery
./restore_proxy_stack.sh
```

_Alternatively, invoke it from anywhere using its full path: `bash /opt/backup-manager/disaster-recovery/restore_proxy_stack.sh`)_

## Method 2: Manual Recovery (Fallback)

If you prefer to run the steps manually to debug or inspect the process step-by-step, execute the following commands in order:

### 1\. Stop Proxy Stack Containers

Before replacing configuration databases or certificates, stop the containers to avoid file lock collisions (especially with SQLite):

```Bash
cd /opt/proxy-stack
docker compose down
```    

### 2\. Clean Corrupted or Existing Data Directories

Clean the data and certificate directories while preserving the base folder:

```Bash
sudo rm -rf /opt/proxy-stack/data /opt/proxy-stack/letsencrypt
sudo mkdir -p /opt/proxy-stack/data /opt/proxy-stack/letsencrypt
```    

### 3\. Download the Latest Snapshot from Google Drive

Extract the latest snapshot from the remote Restic repository to a staging directory inside `backup-manager`:

```Bash
docker exec -it -e RESTIC_PASSWORD="$(grep RESTIC_PASSWORD /opt/backup-manager/.env | cut -d '=' -f2)" backup-manager \
restic -r rclone:gdrive:backups/proxy-stack restore latest --target /tmp/recovery_proxy
```    

### 4\. Restore Physical Data and Certificates

Copy the extracted files from the container's staging path into the host's physical directory:

```Bash
sudo docker cp backup-manager:/tmp/recovery_proxy/opt/proxy-stack/data/. /opt/proxy-stack/data/
sudo docker cp backup-manager:/tmp/recovery_proxy/opt/proxy-stack/letsencrypt/. /opt/proxy-stack/letsencrypt/
```    

### 5\. Verify Permissions and Ownership

Ensure files are readable by the user/group or container runtime:

```Bash
sudo chown -R deployer:deployer /opt/proxy-stack/data /opt/proxy-stack/letsencrypt
```    

### 6\. Restart the Proxy Stack Containers

Start Nginx Proxy Manager and Cloudflare DDNS:

```Bash
cd /opt/proxy-stack
docker compose up -d
```    

_Wait 15–20 seconds for NPM to migrate schemas and load SSL certificates into memory._

### 7\. Verify Health and Status

Check that the containers are healthy and Nginx Proxy Manager has bound to its configured ports:

```Bash
docker compose ps
docker logs --tail 30 nginx-proxy-manager
```    

### 8\. Cleanup Temporary Staging Files

Remove the extracted files inside `backup-manager`:

```Bash
docker exec -it backup-manager rm -rf /tmp/recovery_proxy
```
