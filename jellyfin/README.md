# Jellyfin Media Server

A containerized and portable deployment of the Jellyfin media system, configured with resource limits and monitoring hooks.

## Structure

- **`docker-compose.yml`**: Core configuration decoupled via environment variables.
- **`.env.example`**: Template for required environment variables and storage paths.
- **`docker-compose.override.yml`**: Local override for attaching the `monitoring_net` network (ignored by Git).
- **Persistent Data**: Configurations live in `/srv/appdata/jellyfin/config`, while media is mounted from `/mnt/media`.

## Setup & Deployment

### 1. Configure Environment Variables
Copy the template file to create your local `.env`:

```bash
cp .env.example .env
nano .env
```
Ensure `JELLYFIN_CONFIG_DIR` and `MEDIA_DIR` point to the correct storage locations.

### 2\. Configure Monitoring (Optional)

If using Promtail/Loki, define a `docker-compose.override.yml` to attach the container to the external network.

### 3\. Deploy

Bash

    docker compose up -d 

Backups & Disaster Recovery
---------------------------

Configured for automated, surgical backups via `backup-manager` (excluding high-churn volatile caches and regenerable metadata).
