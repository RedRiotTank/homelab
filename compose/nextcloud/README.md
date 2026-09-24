# Nextcloud

A containerized and secure deployment of Nextcloud, utilizing PostgreSQL for the database and Redis for caching. The configuration is completely agnostic, with secrets and host-specific settings extracted to environment variables.

## Structure

- **`docker-compose.yml`**: The core, portable configuration for Nextcloud, PostgreSQL, and Redis.
- **`.env.example`**: Template for required environment variables.
- **`app_config/`**: Directory for Nextcloud's internal configuration (ignored by Git).
- **`db_data/`**: Directory for PostgreSQL database persistence (ignored by Git).

## Setup & Deployment

### 1. Configure Environment Variables
Copy the template file to create your local `.env`:

```bash
cp .env.example .env
nano .env
```

Ensure you set a strong `POSTGRES_PASSWORD`. The other variables (like the port or host paths) can be left as default unless you need to change them.

### 2\. Configure Local Monitoring (Optional)

If you are using a logging stack like Promtail/Loki, create a `docker-compose.override.yml` file to inject your monitoring network and labels without polluting the main Git repository:

```yaml
version: '3.8'
services:
  nextcloud-db:
    networks:
      - default
      - monitoring
    labels:
      logging_jobname: "nextcloud-logs"
      logging: "promtail"

  nextcloud:
    networks:
      - default
      - monitoring
    labels:
      logging_jobname: "nextcloud-logs"
      logging: "promtail"

networks:
  monitoring:
    external: true
```

### 3\. Build and Start

Once configured, deploy the stack:

Bash

```
docker compose up -d
```

The service will be accessible locally at `http://127.0.0.1:8282` (or the port defined in your `.env` file).

## Backups & Disaster Recovery

This deployment is fully compatible with the centralized `backup-manager`.

-   **Backups:** Handled dynamically via cron jobs in the backup-manager container.
    
-   **Recovery:** If data corruption occurs, refer to the `NEXTCLOUD_DISASTER_RECOVERY.md` runbook located in the `/opt/backup-manager/` directory for automated restoration scripts.
    

```
