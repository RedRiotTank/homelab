# Komodo Orchestration Stack

A lightweight, multi-server Docker orchestrator and container manager serving as the primary infrastructure dashboard (Portainer replacement).

## Architecture

- **Komodo Core:** Web UI, API, and central dashboard for container lifecycles.
- **Komodo Periphery:** Host agent interfacing directly with the Docker daemon via `/var/run/docker.sock`.
- **MongoDB:** Internal datastore for build logs, deployment metadata, and server health.

## Prerequisites

1. Create the external network for reverse proxy routing:
   ```bash
   docker network create proxy_net
   ```
2.  If monitoring is enabled via override, ensure the `monitoring` network exists.
    

## Setup & Deployment

1.  Copy the example configuration and generate secrets:
    
    ```Bash
    cp .env.example .env
    nano .env
    ```    
    
2.  Ensure `KOMODO_PASSKEY` matches between the Core and Periphery agent.
    
3.  Deploy the stack:
    
    ```Bash
    docker compose up -d
    ```   
    
4.  Access the setup wizard on port `9120` (or via reverse proxy). When prompted to add the local server, point Periphery to `http://komodo-periphery:8120` with your configured passkey.
