# Bookshelf (Calibre-Web & LazyLibrarian)

A containerized and secure deployment for managing and reading a digital book library, utilizing Calibre-Web for browsing/reading and LazyLibrarian for automated media acquisition. The configuration is completely agnostic, with paths, ports, and permissions extracted to environment variables.

## Structure

- **`docker-compose.yml`**: The core, portable configuration for Calibre-Web and LazyLibrarian.
- **`docker-compose.override.yml`**: Local monitoring labels and network overrides (ignored by Git).
- **`.env.example`**: Template for required environment variables.
- **`config/`**: Directory for application settings, internal databases, and logs (ignored by Git).
- **`data/`**: Directory for downloads and library symlinks (ignored by Git).

## Setup & Deployment

### 1. Configure Environment Variables
Copy the template file to create your local `.env`:

```bash
cp .env.example .env
nano .env
```

Ensure `PUID` and `PGID` match your host user permissions, and verify that `BOOKS_HOST_DIR` points correctly to your system's book library.

### 2. Configure Local Monitoring (Optional)

If you are using the centralized monitoring stack, ensure your `docker-compose.override.yml` file is in place to inject the external `monitoring` network and Promtail log labels without polluting the main repository:

```yaml
version: '3.8'
services:
  calibre-web:
    labels:
      logging_jobname: "bookshelf"
      logging: "promtail"

  lazylibrarian:
    labels:
      logging_jobname: "bookshelf"
      logging: "promtail"
```

### 3. Build and Start

Once configured, deploy the stack:

```bash
docker compose up -d
```

- **Calibre-Web** will be accessible at port `8083`.
- **LazyLibrarian** will be accessible at port `5299`.
