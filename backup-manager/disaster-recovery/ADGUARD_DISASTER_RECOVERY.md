# AdGuard Home Disaster Recovery Runbook

## Overview
This runbook details the procedure for recovering an AdGuard Home DNS sinkhole deployment. The recovery uses the `backup-manager` container with Restic to extract the latest snapshot from Google Drive, restoring the main configuration file (`AdGuardHome.yaml`), which contains DNS upstream servers, filter subscriptions, custom filtering rules, clients, and DNS rewrites.

## Prerequisites
- A functional Docker and Docker Compose environment.
- The `backup-manager` container up and running (contains Restic and Rclone configured for Google Drive).
- Access to the host machine as a user with `sudo` privileges.
- Target directory `/opt/adguard` present on the host.
- Valid credentials configured in `/opt/backup-manager/.env` (accessible via symlink in `disaster-recovery/.env`).

---

## Method 1: Automated Recovery (Recommended)

For a fast and unattended recovery, use the preconfigured script located in this directory. It automatically loads runtime credentials and environment variables.

### Execute the Recovery
Run the dedicated restore script directly:

```bash
cd /opt/backup-manager/disaster-recovery
./restore_adguard.sh
```
_(Alternatively, invoke it from anywhere using its full path: `bash /opt/backup-manager/disaster-recovery/restore_adguard.sh`)_

## Method 2: Manual Recovery (Fallback)

If you prefer to run the steps manually to debug or inspect the process step-by-step, execute the following commands in order:

### 1\. Stop AdGuard Home Container

Stop the container to ensure the YAML configuration is not overwritten upon container shutdown:

```Bash
cd /opt/adguard
docker compose down
```    

### 2\. Clean Corrupted or Existing Configuration Directory

```Bash
sudo rm -rf /opt/adguard/conf
sudo mkdir -p /opt/adguard/conf
```    

### 3\. Download the Latest Snapshot from Google Drive

Extract the latest snapshot from the remote Restic repository to a staging directory inside `backup-manager`:

```Bash
docker exec -it -e RESTIC_PASSWORD="$(grep RESTIC_PASSWORD /opt/backup-manager/.env | cut -d '=' -f2)" backup-manager \
restic -r rclone:gdrive:backups/adguard restore latest --target /tmp/recovery_adguard
```    

### 4\. Restore Configuration Files

Copy the configuration files from the container's staging path into the host's `/opt/adguard/conf`:

```Bash
sudo docker cp backup-manager:/tmp/recovery_adguard/opt/adguard/conf/. /opt/adguard/conf/
```    

### 5\. Verify Permissions and Ownership

Ensure the restored files have correct host permissions:

```Bash
sudo chown -R deployer:deployer /opt/adguard/conf
```    

### 6\. Restart AdGuard Home Container

Start the AdGuard Home service:

```Bash
cd /opt/adguard
docker compose up -d
```    

_Wait 10 seconds for the DNS daemon and administrative web server to initialize._

### 7\. Verify DNS Resolution and Status

Confirm the container is operational and answering local DNS queries:

```Bash
docker compose ps
docker logs --tail 30 adguardhome
nslookup -port=53 google.com 127.0.0.1
```    

### 8\. Cleanup Temporary Staging Files

Remove the extracted files inside `backup-manager`:

```Bash
docker exec -it backup-manager rm -rf /tmp/recovery_adguard
```
