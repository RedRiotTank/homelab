# Arr Stack

A containerized media acquisition and management stack. The configuration is fully abstracted via environment variables, allowing seamless portability and secure handling of private remote destinations.

This stack integrates the following upstream projects:
* [**qBittorrent**](https://github.com/qbittorrent/qbittorrent): Torrent client.
* [**Sonarr**](https://github.com/sonarr/sonarr): Smart PVR for TV shows.
* [**Prowlarr**](https://github.com/prowlarr/prowlarr): Indexer manager/proxy.
* [**Kitsunarr**](https://github.com/Kaizy48/KITSUNARR) *(Optional)*: Smart Proxy & Torznab Indexer. Acts as a bridge between anime trackers and the *arr ecosystem* by scraping, normalizing metadata using AI and TheTVDB, and feeding clean titles to Sonarr.

## Structure

- **`docker-compose.yml`**: The core, portable configuration for the media services.
- **`.env.example`**: Template for required environment variables (ports, paths, UI toggles).
- **`rclone-upload.sh`**: Script to move local media to a private cloud remote.
- **`kitsunarr_src/`**: Source directory for building the optional Kitsunarr image.
- **`*_config/` & `*-data/`**: Directories for application configuration and metadata (ignored by Git).

## Setup & Deployment

### 1. Configure Environment Variables
Copy the template file to create your local `.env`:

```bash
cp .env.example .env
nano .env
```

Review the variables, paying special attention to the Rclone remote settings.

**Note on Kitsunarr:** By default, Kitsunarr is disabled. To enable it, uncomment `COMPOSE_PROFILES=kitsunarr_enabled` in your `.env` file.

### 2\. Configure Local Monitoring (Optional)

If you are using a logging stack like Promtail/Loki, create a `docker-compose.override.yml` file to inject your monitoring network and labels without polluting the main Git repository:


```YAML
version: "3.8"

services:
    qbittorrent:
    networks:
        - monitoring
    labels:
        logging_jobname: "torrent"
        logging: "qbittorrent"

networks:
    monitoring:
    external: true
```    

### 3\. Build and Start

Once configured, deploy the stack. The `--remove-orphans` flag ensures that if you disable Kitsunarr in the future, its container is safely removed:

```bash
docker-compose up -d --remove-orphans
```

## Cloud Sync Automation

This stack includes an upload script (`rclone-upload.sh`) to move completed media from local storage to a specified Rclone remote, freeing up local disk space.

-   **Usage:** You can execute this script manually whenever needed.
    
-   **Optional Automation:** For a hands-off approach, you can schedule it via `cron` (e.g., as a nightly job).
    
-   **Safety:** It utilizes a `.lock` file to prevent overlapping transfers and reads sensitive remote names exclusively from the `.env` file to maintain OPSEC.

