# Jellyfin Media Server

A containerized and portable deployment of the Jellyfin media system, configured with resource limits and monitoring hooks.

## Structure

- **`docker-compose.yml`**: Core configuration decoupled via environment variables.
- **`.env.example`**: Template for required environment variables and storage paths.
- **`docker-compose.override.yml`**: Override for attaching the `monitoring_net` network (committed with the stack).
- **Persistent Data**: Configurations live in `/srv/appdata/jellyfin/config`, while media is mounted from `/mnt/media`.

## Resource Limits

Jellyfin is the primary workload on its node, so its defaults are intentionally
generous: **6 CPUs and 10 GiB of memory**. Override them with `JELLYFIN_CPUS` and
`JELLYFIN_MEMORY_LIMIT` in `.env`. The limits are expressed through
`deploy.resources` because the same block reserves the NVIDIA GPU.

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

```bash
docker compose up -d
```

Backups & Disaster Recovery
---------------------------

Back up the config, cache, and media directories configured through `.env`.
Regenerable metadata and transcode caches can be excluded to keep snapshots
small. [`core/backrest`](../../core/backrest/) is an optional Restic-based
example.
