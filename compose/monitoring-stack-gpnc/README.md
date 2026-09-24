# Monitoring Stack (GPNC)

*Based on the original [docker-monitoring-stack-gpnc](https://github.com/ruanbekker/docker-monitoring-stack-gpnc) by Ruan Bekker.*

A centralized, containerized monitoring and logging stack for the server infrastructure (Grafana, Prometheus, Loki, cAdvisor, etc.). The configuration and domains have been extracted to environment variables to ensure portability.

## Structure

- **`docker-compose.yml`**: Core configuration for the monitoring services.
- **`.env.example`**: Template for required environment variables (domains, versions, limits).
- **`configs/` & `dashboards/`**: Provisioning files and pre-built Grafana dashboards.
- **`LICENSE`**: Original MIT License from the creator.

## Setup & Deployment

### 1. Configure Environment Variables
Copy the template file to create your local `.env`:

```bash
cp .env.example .env
nano .env
```

Ensure `GRAFANA_DOMAIN` and `GRAFANA_ROOT_URL` are correctly set for your reverse proxy.

### 2. Build and Start
Deploy the stack explicitly:

```bash
docker-compose up -d
```

The stack attaches to the external `monitoring` network to automatically scrape logs and metrics from other interconnected containers (Nextcloud, RomM, Jellyfin, etc.).
