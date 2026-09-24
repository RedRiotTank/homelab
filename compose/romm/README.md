# RomM (Retro Media Manager)

A containerized and secure deployment of RomM, serving as a unified retro gaming library and web-based emulator. The configuration is completely agnostic, with secrets and host-specific settings extracted to environment variables.

## Structure

- **`docker-compose.yml`**: The core, portable configuration for RomM and its MariaDB database.
- **`.env.example`**: Template for required environment variables.
- **`library/`**: Directory containing the actual ROM files (ignored by Git).
- **`database/`**: Directory for MariaDB database persistence (ignored by Git).
- **`assets/`, `config/`, `resources/`**: Directories for RomM internal configuration and downloaded metadata/cover art (ignored by Git).

## Setup & Deployment

### 1. Configure Environment Variables
Copy the template file to create your local `.env`:

```bash
cp .env.example .env
nano .env
```

Ensure you set strong database passwords, your `STEAMGRIDDB_API_KEY` for metadata scraping, and correctly map `ROM_LIBRARY_DIR` to your physical game storage.

### 2. Configure Local Monitoring (Optional)

If you are using a logging stack like Promtail/Loki, create a `docker-compose.override.yml` file to inject your monitoring network without polluting the main Git repository:

```yaml
version: '3.8'
services:
  romm:
    networks:
      - monitoring

  romm-db:
    networks:
      - monitoring

networks:
  monitoring:
    external: true
```

### 3. Build and Start

Once configured, deploy the stack explicitly passing the environment file:

```bash
docker-compose --env-file .env up -d
```

The service will be accessible locally at the port defined in your `.env` file (default `8082`).

## Backups & Disaster Recovery

This deployment is fully compatible with the centralized `backup-manager`.

-   **Backups:** Handled dynamically via cron jobs in the backup-manager container (excluding the heavy `library/` folder).
-   **Recovery:** If data corruption occurs, refer to the `ROMM_DISASTER_RECOVERY.md` runbook located in the `/opt/backup-manager/` directory for automated restoration scripts.
