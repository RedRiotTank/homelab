# Homarr Dashboard

A lightweight, customizable, and containerized dashboard for your homelab services. This deployment is sanitized, with externalized secrets and decoupled monitoring to ensure a portable and secure setup.

## Structure

- **`docker-compose.yml`**: The core, portable configuration for the Homarr service.
- **`.env.example`**: Template for required environment variables (encryption secrets).
- **`docker-compose.override.yml`**: Local override for injecting the Promtail/Loki `monitoring` network dynamically (ignored by Git).
- **`appdata/`**: Directory containing the persistent database, Redis cache, and configurations. Strictly ignored by Git to prevent data leaks.

## Setup & Deployment

### 1. Configure Environment Variables
Copy the template file to create your local `.env`:
```bash
cp .env.example .env
nano .env
```

**Critical Settings:**

-   Generate a new, secure encryption key using `openssl rand -hex 32` and assign it to `SECRET_ENCRYPTION_KEY`. This key protects the API keys and credentials stored within the Homarr UI.
    

### 2\. Configure Local Monitoring (Optional)

If your homelab uses an external logging stack, create a `docker-compose.override.yml` to attach the `monitoring` network dynamically without altering the main compose file.

### 3\. Build and Start

Once configured, deploy the stack:

Bash

```
docker compose up -d
```
