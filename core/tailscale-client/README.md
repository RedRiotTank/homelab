# Tailscale Client Stack

Deploys the Tailscale client agent to connect host machines (nodes) to your self-hosted [Headscale](../headscale/README.md) VPN mesh network.

## Architecture Overview

Unlike standard web services, the Tailscale client requires deep integration with the host machine's networking stack to create and manage WireGuard tunnels directly.

- **Network Mode:** Runs in `host` network mode. It does not join internal Docker networks.
- **Capabilities:** Requires `NET_ADMIN` and `SYS_MODULE` privileges to manage routing tables and interfaces.
- **Devices:** Requires access to the host's `/dev/net/tun` interface.
- **State Management:** Cryptographic identity, keys, and node state are stored in a dedicated Docker volume (`tailscale_data`), abstracting away from local host paths.

## Configuration Guide

Before starting the stack, you need to prepare your `.env` file and generate an authentication key from your Headscale control server.

### 1. Generate a Headscale Auth Key

To join the network without manual web authentication, the client requires a pre-auth key. Generate this key from your primary server running the Headscale backend:

```bash
docker exec headscale headscale preauthkeys create --expiration 90d --reusable
```

_Note: Using `--reusable` allows the container to re-authenticate if destroyed and recreated, though generating unique, single-use keys per node is recommended for strict security._

### 2\. Configure the Environment

Copy the environment template:

    cp .env.example .env
    

Edit the `.env` file with your specific values:

-   `NODE_HOSTNAME`: The identifying name for this machine in the Headscale dashboard (e.g., `redserver`, `crimsonserver`).
    
-   `HEADSCALE_URL`: Your Headscale control server domain (e.g., `https://vpn.example.com`).
    
-   `HEADSCALE_AUTHKEY`: The key generated in the previous step (e.g., `hskey-auth-...`).
    

## Observability & The Override Layer

Because this container runs in `network_mode: host`, it **cannot** be attached to Docker networks (like `proxy_net` or `monitoring_net`).

Instead, this repository includes a `docker-compose.override.yml` file strictly to inject logging metadata (labels) for central log shippers (such as Promtail/Loki) to capture the client's output. For more details, see the [Monitoring Stack Documentation](https://www.google.com/search?q=../monitoring-stack-gpnc/README.md).

**⚠️ Optional Feature:** The override is completely optional. If you do not have the monitoring stack deployed:

-   **Komodo Users:** Simply omit `docker-compose.override.yml` from the "File Paths" configuration.
    
-   **CLI Users:** Delete the override file, or explicitly run `docker compose -f docker-compose.yml up -d`.
    

## Setup & Deployment

### Option A: GitOps via Komodo (Recommended)

1.  Add this repository to your Komodo instance.
    
2.  Set the environment variables in the Komodo UI based on the `.env.example` structure.
    
3.  In "File Paths", list both `docker-compose.yml` and `docker-compose.override.yml` (if using monitoring).
    
4.  Click Deploy.
    

### Option B: Manual CLI Deployment

1.  Copy and populate the environment variables:
    
        cp .env.example .env
        nano .env
        
    
2.  Start the stack:
    
        docker compose up -d
        
    
3.  Verify the connection by opening your Headplane web UI. The new node should appear in the device list with a `Connected` status and an assigned `100.64.x.x` IP address.
