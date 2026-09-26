# Headscale & Headplane Stack

Self-hosted Tailscale control server (Headscale) and its web-based management UI (Headplane) for managing a private VPN mesh network.

## Architecture Overview

- **Headscale:** The core backend. Manages Tailscale node registrations, key exchanges, and network routing policies.
- **Headplane:** A frontend dashboard connected to the Headscale API, providing a graphical interface to manage nodes, users, and pre-auth keys.

This stack is entirely decoupled. It relies on a Docker volume for persistent internal state (the SQLite database and cryptographic keys) and bind mounts for configuration files.

| Resource | Type | Purpose |
| --- | --- | --- |
| `headscale_data` | Docker Volume | Stores the Headscale SQLite database and noise/derp private keys. |
| `${HOST_CONFIG_PATH}` | Bind Mount | Host directory containing the Headscale `config.yaml`. |
| `${HEADPLANE_CONFIG_DIR}`| Bind Mount | Host directory containing the Headplane `config.yaml` and secrets. |

## ⚠️ Important: Headplane SSL Requirement

Headplane requires a secure context (HTTPS) to function correctly. Browsers will block access to its authentication and internal crypto APIs if accessed via plain HTTP, resulting in a broken interface or inability to log in.

**Solution:** This stack does not expose ports directly to the host. You must route traffic through a **Reverse Proxy** (such as Nginx Proxy Manager, Traefik, or Caddy) that handles TLS/SSL termination. The reverse proxy will connect to the containers via a shared Docker network (see _The Override Layer_ below) and serve Headplane over HTTPS with a valid certificate.

## Configuration Guide

Before starting the stack, you need to prepare the configuration directories and files on your host machine.

### 1\. Headscale Configuration (`config.yaml`)

Create the directory defined in your `.env` (e.g., `/opt/core/headscale/config`) and place a `config.yaml` inside it.

You can download the base template from the [official Headscale repository](https://github.com/juanfont/headscale/blob/main/config-example.yaml?utm_source=gemini). Ensure you modify the following critical values:

-   `server_url`: Your external domain (e.g., `https://vpn.example.com`).
    
-   `listen_addr`: Set to `0.0.0.0:8080`.
    
-   `metrics_listen_addr`: Set to `127.0.0.1:9090`.
    
-   `database.sqlite.path`: Set to `/var/lib/headscale/db.sqlite` (mapping to the Docker volume).
    

### 2\. Headplane Configuration (`config.yaml`)

Create the directory defined in your `.env` (e.g., `/opt/core/headscale/headplane-config`) and create a `config.yaml` file with the following structure:

    server:
      port: 3000
      cookie_secret: "replace_with_a_random_32_character_string"
      
    headscale:
      url: http://headscale:8080
      api_key: "replace_with_generated_api_key"
      integration:
        type: docker
        container_name: headscale
    

**How to get the Headscale API Key:** Because Headplane needs an API key to communicate with Headscale, you may need to start Headscale first to generate it:

1.  Start the Headscale container.
    
2.  Run the following command on your host to generate a 90-day API key:
    
    Bash
    
        docker exec headscale headscale apikeys create --expiration 90d
        
    
3.  Copy the output (`hskey-...`) into your Headplane `config.yaml`.
    
4.  Restart the Headplane container.
    

## The Override Layer (`docker-compose.override.yml`)

The base `docker-compose.yml` in this repository isolates the containers within an internal network (`headscale_internal`).

To grant your Reverse Proxy access to Headscale and Headplane without altering the base repository, create a `docker-compose.override.yml` in your host's deployment directory (e.g., `/opt/core/headscale/`):

    sservices:
      headscale:
        networks:
          # Ingress network for reverse proxy access
          - proxy_net
          # Telemetry network for Prometheus/Grafana/Alloy metric scraping
          - monitoring_net
        labels:
          logging_jobname: "headscale-stack"
          logging: "headscale"

      headplane:
        networks:
          - proxy_net
          - monitoring_net
        labels:
          logging_jobname: "headscale-stack"
          logging: "headscale"

    networks:
      proxy_net:
        external: true
      monitoring_net:
        external: true
        name: monitoring
    

_Note: Replace `proxy_net` and `monitoring_net` with the actual names of the external Docker networks used by your reverse proxy and observability stack. Both services share the same `logging_jobname` so they can be grouped in Grafana/Loki and filtered via the automatic `container` label._


## Deployment Steps

1.  Clone the repository and configure your `.env` from the `.env.example`:
    
        cp .env.example .env
        
    
2.  Ensure `HOST_CONFIG_PATH` and `HEADPLANE_CONFIG_DIR` point to the directories where you placed your `config.yaml` files.
    
3.  Ensure your `docker-compose.override.yml` is in the same deployment directory.
    
4.  Launch the stack:
    
        docker compose up -d
        
    
5.  Configure your Reverse Proxy to point your domains to the `headscale` (port 8080) and `headplane` (port 3000) containers.
