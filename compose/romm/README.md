# RomM (Retro Media Manager)

A containerized and secure deployment of RomM, serving as a unified retro gaming library and web-based emulator. The configuration is completely agnostic, with secrets and host-specific settings extracted to environment variables.

## Structure

- **`docker-compose.yml`**: The core, portable configuration for RomM and its MariaDB database.
- **`.env.example`**: Template for required environment variables.
- **`build_library.py`**: Builds the RomM library from the rclone mount and the community covers (see [BUILD_LIBRARY.md](BUILD_LIBRARY.md)).
- **`config.example.yml`**: RomM configuration to use the local `gamelist.xml` and avoid reading the ROMs while scanning.
- **`ROMM_LIBRARY_DIR/`**: Generated library (symlinks + gamelist + covers, ignored by Git).
- **`RETRO_DATA_DIR/database`**: MariaDB data directory (ignored by Git).
- **`RETRO_DATA_DIR/assets`, `config`, `resources`**: RomM internal data and copied covers (ignored by Git).

## Setup & Deployment

### 1. Configure Environment Variables
Copy the template file to create your local `.env`:

```bash
cp .env.example .env
nano .env
```

Ensure you set strong database passwords and `ROMM_LIBRARY_DIR`. For the rclone
library, set `RCLONE_MOUNT_DIR=/mnt/media` and generate the tree with
`build_library.py` (see [BUILD_LIBRARY.md](BUILD_LIBRARY.md)). **Do not set
`SCREENSCRAPER_USER`/`SCREENSCRAPER_PASSWORD`** if you want to use only the
local `gamelist.xml` covers.

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

### 4. Build the library from rclone

Follow [BUILD_LIBRARY.md](BUILD_LIBRARY.md). The compose file mounts:

- `ROMM_LIBRARY_DIR` -> `/romm/library/roms`
- `RCLONE_MOUNT_DIR` -> `/mnt/media` (for the symlinks)

## Backups & Disaster Recovery

This deployment is fully compatible with the centralized `backup-manager`.

-   **Backups:** Handled dynamically via cron jobs in the backup-manager container (excluding the heavy `library/` folder).
-   **Recovery:** If data corruption occurs, refer to the `ROMM_DISASTER_RECOVERY.md` runbook located in the `/opt/backup-manager/` directory for automated restoration scripts.
