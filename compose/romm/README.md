# RomM (Retro Media Manager)

A containerized and secure deployment of RomM, serving as a unified retro gaming library and web-based emulator. The configuration is completely agnostic, with secrets and host-specific settings extracted to environment variables.

## Structure

- **`docker-compose.yml`**: The core, portable configuration for RomM and its MariaDB database.
- **`.env.example`**: Template for required environment variables.
- **`config.example.yml`**: Optional RomM configuration that relies on a local `gamelist.xml` and avoids re-reading ROM files while scanning.
- **`ROMM_LIBRARY_DIR/`**: Generated library (symlinks + gamelist + covers, ignored by Git).
- **`RETRO_DATA_DIR/database`**: MariaDB data directory (ignored by Git).
- **`RETRO_DATA_DIR/assets`, `config`, `resources`**: RomM internal data and copied covers (ignored by Git).

Any custom import or cover-generation tooling is environment-specific; keep it outside this repository.

## Setup & Deployment

### 1. Configure Environment Variables
Copy the template file to create your local `.env`:

```bash
cp .env.example .env
nano .env
```

Ensure you set strong database passwords, `ROMM_AUTH_SECRET_KEY`, and
`ROMM_LIBRARY_DIR`. If your ROMs live on a network share, set
`RCLONE_MOUNT_DIR` to the host mount point and generate a `gamelist.xml` with
your own tooling. ScreenScraper is not passed to the container: metadata and
covers come only from the local `gamelist.xml`.

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

### 4. Library layout

If you mount ROMs from a network share, the compose file exposes:

- `ROMM_LIBRARY_DIR` -> `/romm/library/roms`
- `RCLONE_MOUNT_DIR` -> `/mnt/media` (for symlinks)

RomM can scan that directory directly. A `gamelist.xml` is optional and only
needed if you want metadata or covers that are not embedded in the ROM files.

## Backups & Disaster Recovery

Back up the MariaDB data directory, the RomM config/assets/resources
directories, and any host paths you mounted into the container. The ROM library
itself is usually regenerable and can be excluded to keep snapshots small.

Use any backup tool you prefer. [`core/backrest`](../../core/backrest/) is an
optional example based on Restic.
