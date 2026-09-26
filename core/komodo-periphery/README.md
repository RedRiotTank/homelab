# Komodo Periphery (Secondary Node Agent)

This directory contains the standalone Komodo Periphery agent designed for secondary or edge nodes in the homelab infrastructure (e.g., `CrimsonServer`). 

For the primary orchestration stack containing the Web UI, API, and Database, refer to the [Komodo Core Stack](../komodo/README.md).

## Architecture & State Management

This stack deploys a single agent container that listens for deployment commands and metric scrapes from the primary Komodo Core server. It operates without hardcoding system paths, using Docker volumes for internal state.

| Resource | Purpose | Target / Location |
| --- | --- | --- |
| `/var/run/docker.sock` | Grants the agent access to manage host containers and read metrics | Host socket mount |
| `komodo_periphery_data` | Internal Periphery state, configuration, and stack metadata | Named Docker Volume |
| `${HOST_STACKS_PATH}` | Host bind mount where the agent writes and executes stack definitions | `/opt` (host-specific via `.env`) |

## Deployment & Setup

### 1. Configure Environment

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` and set the `KOMODO_PASSKEY`. **This must be completely identical** to the passkey configured on the primary Komodo Core server.

### 2\. Launch the Agent

Start the service using Docker Compose:



    docker compose up -d
    

### 3\. Connect to Core

Once the container is running, the node must be authorized in the primary Komodo dashboard:

1.  Open the Komodo Web UI on the primary server.
    
2.  Navigate to **Servers** > **Add Server**.
    
3.  Set the Address to the secondary node's reachable IP (e.g., `http://:8120`).
    
4.  Enter the exact `KOMODO_PASSKEY` from the `.env` file.
    
5.  Save and verify the server status turns green (Healthy).
