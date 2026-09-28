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

**Solution:** This stack does not expose ports directly to the host. You must route traffic through a **Reverse Proxy** that handles TLS/SSL termination. Refer to the [Proxy Stack Documentation](../proxy-stack/README.md) to set up Nginx Proxy Manager, which will connect to this stack via the shared `proxy_net` network and serve Headplane over HTTPS with a valid certificate.

## Configuration Guide

Before starting the stack, you need to prepare the configuration directories and files on your host machine.

### 1. Headscale Configuration (`config.yaml`)

Create the directory defined in your `.env` (e.g., `/opt/core/headscale/config`) and place a `config.yaml` inside it.

You can download the base template from the [official Headscale repository](https://github.com/juanfont/headscale/blob/main/config-example.yaml?utm_source=gemini). Ensure you modify the following critical values:
- `server_url`: Your external domain (e.g., `https://vpn.example.com`).
- `listen_addr`: Set to `0.0.0.0:8080`.
- `metrics_listen_addr`: Set to `127.0.0.1:9090`.
- `database.sqlite.path`: Set to `/var/lib/headscale/db.sqlite` (mapping to the Docker volume).

### 2. Headplane Configuration (`config.yaml`)

Create the directory defined in your `.env` (e.g., `/opt/core/headscale/headplane-config`) and create a `config.yaml` file with the following structure:
```yaml
server:
  port: 3000
  cookie_secret: "replace_with_a_random_32_character_string"
headscale:
  url: http://headscale:8080
  api_key: "replace_with_generated_api_key"
  integration:
    type: docker
    container_name: headscale
```

**How to get the Headscale API Key:** Because Headplane needs an API key to communicate with Headscale, you may need to start Headscale first to generate it:

1.  Start the Headscale container.
    
2.  Run the following command on your host to generate a 90-day API key:
    
    Bash
    
        docker exec headscale headscale apikeys create --expiration 90d
        
    
3.  Copy the output (`hskey-...`) into your Headplane `config.yaml`.
    
4.  Restart the Headplane container.
    

## Observability & The Override Layer

This repository includes a `docker-compose.override.yml` file designed to integrate this stack with the homelab's central observability infrastructure (Promtail/Loki) and the Ingress Proxy.

For more details on the telemetry network, see the [Monitoring Stack Documentation](https://www.google.com/search?q=../monitoring-stack-gpnc/README.md).

**⚠️ Optional Feature:** The override is completely optional. If you do not have the monitoring stack or proxy stack deployed:

-   **Komodo Users:** Simply omit `docker-compose.override.yml` from the "File Paths" configuration.
    
-   **CLI Users:** Delete the override file, or explicitly run `docker compose -f docker-compose.yml up -d`.
    

## Setup & Deployment

### Option A: GitOps via Komodo (Recommended)

1.  Add this repository to your Komodo instance.
    
2.  Ensure `HOST_CONFIG_PATH` and `HEADPLANE_CONFIG_DIR` point to the directories where you placed your `config.yaml` files on the host.
    
3.  In "File Paths", list both `docker-compose.yml` and `docker-compose.override.yml`.
    
4.  Click Deploy.
    

### Option B: Manual CLI Deployment

1.  Copy and populate the environment variables:
    
    
        cp .env.example .env
        
    
2.  Start the stack:

        docker compose up -d
        
    

## Next Steps: Connecting Nodes

Once the Headscale control server is up and running, you need to attach your host machines to the VPN mesh network.

-   **For homelab servers (Linux/Docker):** Refer to the [Tailscale Client Node documentation](https://www.google.com/search?q=../tailscale-client/README.md) to deploy the client agent alongside this stack.
    
-   **For personal devices (iOS/Android/Windows/Mac):** Download the official Tailscale app, change the Alternate Server to your custom domain (`https://vpn.example.com`), and authenticate using the Headplane UI.
