# AppFlowy Cloud

A fully containerized, secure, and production-ready deployment of AppFlowy Cloud. This stack includes the core AppFlowy services, GoTrue (authentication), PostgreSQL (database), MinIO (S3-compatible storage), Redis, and an Nginx reverse proxy.

## Structure

- **`docker-compose.yml`**: The core, portable configuration for all AppFlowy services.
- **`.env.example`**: Template for required environment variables (domains, secrets, and database credentials).
- **`nginx/`**: Directory containing Nginx configurations and SSL certificates.
- **`docker-compose.override.yml`**: Override for injecting the Promtail/Loki monitoring stack (versioned in Git).
- **Volumes**: Data for `postgres_data` and `minio_data` are stored in named Docker volumes and are strictly ignored by Git to prevent data leaks.

## Setup & Deployment

### 1. Configure Environment Variables
Copy the template file to create your local `.env`:

```bash
cp .env.example .env
nano .env
```

**Critical settings to update:**

- Replace every `change-me` placeholder with a strong, unique secret.
- Set `APPFLOWY_BASE_URL`, `APPFLOWY_WEBSOCKET_BASE_URL`, and
  `APPFLOWY_WEB_URL` to the public URLs clients will use (for example
  `https://appflowy.example.com`).
- The WebSocket URL must use `wss://` when the site is served over HTTPS,
  otherwise clients report "Disconnected from cloud".
- Keep `APPFLOWY_DATABASE_URL`, `GOTRUE_DATABASE_URL`, and
  `APPFLOWY_WORKER_DATABASE_URL` consistent with `POSTGRES_*`.

### 2\. Configure Local Monitoring (Optional)

If your homelab uses an external logging stack, create a `docker-compose.override.yml` to attach the `monitoring` network and Promtail labels dynamically.

### 3\. Build and Start

Once configured, deploy the stack:

```bash
docker compose up -d
```

## Backups & Disaster Recovery

Back up both the PostgreSQL data and the MinIO bucket data, plus any bind-mounted
configuration. Stop the stack or use database-consistent snapshots before
copying the database files. [`core/backrest`](../../core/backrest/) is an
optional Restic-based example.

For recovery, restore the data directories before starting the containers
again.
