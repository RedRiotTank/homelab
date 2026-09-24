# AppFlowy Cloud

A fully containerized, secure, and production-ready deployment of AppFlowy Cloud. This stack includes the core AppFlowy services, GoTrue (authentication), PostgreSQL (database), MinIO (S3-compatible storage), Redis, and an Nginx reverse proxy.

## Structure

- **`docker-compose.yml`**: The core, portable configuration for all AppFlowy services.
- **`.env.example`**: Template for required environment variables (domains, secrets, and database credentials).
- **`nginx/`**: Directory containing Nginx configurations and SSL certificates.
- **`docker-compose.override.yml`**: Local override for injecting the Promtail/Loki monitoring stack (ignored by Git by default).
- **Volumes**: Data for `postgres_data` and `minio_data` are stored in named Docker volumes and are strictly ignored by Git to prevent data leaks.

## Setup & Deployment

### 1. Configure Environment Variables
Copy the template file to create your local `.env`:

```bash
cp .env.example .env
nano .env
````
**Critical Settings to update:**

-   Replace all `your_secure_*` placeholders with real, strong passwords.
    
-   Ensure your `FQDN`, `APPFLOWY_BASE_URL`, and `APPFLOWY_WEBSOCKET_BASE_URL` match your actual domain (e.g., `workspace.yourdomain.com`).
    
-   **Important:** The WebSocket URL must use the `wss://` protocol (if behind HTTPS) to ensure real-time synchronization and avoid "Disconnected from cloud" errors in the clients.
    

### 2\. Configure Local Monitoring (Optional)

If your homelab uses an external logging stack, create a `docker-compose.override.yml` to attach the `monitoring` network and Promtail labels dynamically.

### 3\. Build and Start

Once configured, deploy the stack:

Bash

```
docker compose up -d
```

## Backups & Disaster Recovery

This deployment is fully integrated with the centralized `backup-manager`.

-   **Backups:** Handled dynamically via cron jobs in the `backup-manager` container, taking encrypted snapshots of both PostgreSQL and MinIO data.
    
-   **Recovery:** In the event of catastrophic failure or data corruption, refer to the `APPFLOWY_DISASTER_RECOVERY.md` runbook located in the `/opt/backup-manager/` directory. It contains automated bash scripts to wipe corrupted data and inject the latest Restic snapshot safely. EOF
    

```
