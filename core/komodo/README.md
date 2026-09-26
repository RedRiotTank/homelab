# Komodo Orchestration Stack

Central multi-server container management, deployment automation, and monitoring dashboard.

## Architecture Overview

The stack consists of three decoupled components:

- **komodo (Core):** Web UI, REST API, authentication layer, and central coordination engine.
- **komodo-periphery:** Node agent interfacing directly with the Docker daemon (`/var/run/docker.sock`) to manage stacks, build containers, and stream execution metrics.
- **komodo-mongo:** Dedicated MongoDB instance for persistence of build logs, deployment metadata, and multi-server state.

```text
                          ┌───────────────────────┐
                          │  Komodo Web UI / API  │
                          └───────────┬───────────┘
                                      │ (internal network)
              ┌───────────────────────┴───────────────────────┐
              │                                               │
   ┌──────────▼──────────┐                         ┌──────────▼──────────┐
   │    komodo-mongo     │                         │   komodo-periphery  │
   │  (Database State)   │                         │  (/var/run/docker)  │
   └─────────────────────┘                         └──────────┬──────────┘
                                                              │
                                                   ┌──────────▼──────────┐
                                                   │ ${HOST_STACKS_PATH} │
                                                   │ (e.g. /opt)         │
                                                   └─────────────────────┘
```
## Design & Abstraction Principles

### Zero Host Exposure by Default

The base `docker-compose.yml` publishes no host ports.

All ingress routing is meant to be handled by a dedicated reverse proxy on an external network (`proxy_net`).

### Path Portability

Host paths are parameterized through environment variables:

-   `HOST_STACKS_PATH`: Base path on the host where stacks are stored (defaults to `/opt`).
    
-   `CONTAINER_STACKS_PATH`: arget mount point inside the periphery container (defaults to `/opt`).
    

Both can be overridden in `.env` to relocate the stacks directory anywhere on the host filesystem without altering repository code.

### Node Topology

-   **Primary Node (RedServer):** Runs the full stack (Core + Periphery + MongoDB).

-   **Secondary Nodes (CrimsonServer):** Only require the lightweight agent, pointing back to the primary Core API using a shared `KOMODO_PASSKEY`. See the [Komodo Periphery Agent documentation](../komodo-periphery/README.md) for secondary node deployment.
    

## Directory & State Management

| Resource Type | Purpose | Location |
| --- | --- | --- |
| `komodo_data` | Core state, server configurations, and certificates | Named Docker Volume |
| `komodo_mongo_data` | MongoDB data collections | Named Docker Volume |
| `${HOST_STACKS_PATH}` | Stack compose definitions managed by Periphery | Host path defined in `.env` (default: `/opt`) |

## Deployment & Setup

### 1\. Configure Environment

Copy the example file and adjust the values:

    cp .env.example .env
    

Generate secure random secrets:

    # Generate JWT Secret
    sed -i "s/replace_with_a_secure_jwt_secret/$(openssl rand -hex 32)/" .env
    
    # Generate Periphery Passkey
    sed -i "s/replace_with_a_secure_periphery_passkey/$(openssl rand -hex 32)/" .env
    

### 2\. Launch the Stack

Start the service using Docker Compose:

    docker compose up -d
    

## The Host Override Layer (`docker-compose.override.yml`)

The repository version of `docker-compose.yml` remains clean, portable, and infrastructure-agnostic.

Host-specific concerns—such as:

-   Local port binding for emergency bootstrap
    
-   Reverse-proxy ingress
    
-   Observability
    

are separated into:

    ${HOST_STACKS_PATH}/core/komodo/docker-compose.override.yml
    

Docker Compose automatically merges `docker-compose.override.yml` on top of `docker-compose.yml` when both are present in the working directory.

### Example Production Override

    services:
      komodo:
        ports:
          # Binds the dashboard to localhost for initial configuration or emergency access
          - "${KOMODO_PORT:-127.0.0.1:9120}:9120"
    
        networks:
          # Ingress network: Allows reverse proxy (Traefik/Nginx/Caddy) to reach the Core UI
          - proxy_net
    
          # Telemetry network: Allows Prometheus/Grafana/Alloy to scrape metrics
          - monitoring_net
    
        labels:
          logging_jobname: "komodo"
          logging: "komodo"
    
      komodo-mongo:
        labels:
          logging_jobname: "komodo-mongo"
          logging: "komodo"
    
    networks:
      proxy_net:
        external: true
    
      monitoring_net:
        external: true
        name: monitoring
    

## Why This Structure?

### Bootstrap Access

Exposes port `9120` strictly to `127.0.0.1`.

This prevents exposure to the LAN or Internet while allowing initial access directly via localhost or through an SSH tunnel:

    ssh -L 9120:localhost:9120 user@host
    

### Reverse Proxy Integration (`proxy_net`)

Connects the Core container directly to the ingress proxy so it can be exposed under a custom domain, for example:

    https://komodo.yourdomain.com
    

with automated TLS termination.

### Observability (`monitoring_net` & labels)

Injects metadata labels for central log shippers such as:

-   Promtail
    
-   Loki
    
-   Alloy
    

These labels allow log shippers to identify and categorize container logs under the `komodo` job without modifying the shared base repository.

## Initial Onboarding

1.  Access the dashboard via your reverse proxy domain or via an SSH tunnel:
    
        http://localhost:9120
        
    
2.  Complete the initial administrator setup.
    
3.  When adding the local server agent, connect to the internal Periphery endpoint:
    
    **Periphery Address:**
    
        http://komodo-periphery:8120
        
    
    **Passkey:**
    
    Use the value specified in `KOMODO_PASSKEY`.
