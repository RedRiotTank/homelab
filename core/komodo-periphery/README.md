# Komodo Periphery (Secondary Node Agent)

This directory contains the standalone Komodo Periphery agent designed for secondary or edge nodes in the homelab infrastructure (e.g., `CrimsonServer`).

For the primary orchestration stack containing the Web UI, API, and Database, refer to the [Komodo Core Stack](../komodo/README.md).

## Architecture & Design Decisions

Unlike the [primary Komodo stack](../komodo/README.md), this directory deploys a **single, lightweight agent container** — no database, no web UI, no bundled core service. Its only job is to expose a control-plane API that the primary Komodo Core server calls to manage containers, run builds, and stream metrics from this host.

- **Shared-secret authentication:** The agent trusts any request presenting the correct `KOMODO_PASSKEY`. There is no per-user auth on this side — identity and access control live entirely on the Core server. This is why the passkey must be treated as a credential and kept identical (byte-for-byte) between this `.env` and the primary server's `.env`.
- **`/var/run/docker.sock` mount:** Grants the agent full access to the host's Docker daemon, which is what allows Komodo Core to deploy, restart, and inspect stacks on this node remotely.
- **`${HOST_STACKS_PATH}:${CONTAINER_STACKS_PATH}` bind mount:** Mounted at matching paths (both default to `/opt`) so that stack definitions and relative paths referenced by Compose files resolve identically whether Core is orchestrating the primary node or this secondary node. This path parity removes the need for per-node path translation.
- **`komodo_periphery_data` volume:** Holds the agent's own internal state and stack metadata — kept separate from the Docker socket and stacks mount so the agent's runtime state survives independently of host path changes.
- **Host port exposure:** This service has no `docker-compose.override.yml`. The agent's port (`PERIPHERY_PORT`, default `8120`) is published directly in the base `docker-compose.yml` via `${PERIPHERY_BIND_IP:-0.0.0.0}:${PERIPHERY_PORT:-8120}:8120`. Unlike the other stacks in this repo, it does **not** join `proxy_net` or `monitoring_net` — it has no web UI to expose through a reverse proxy, and it is the primary Komodo Core server (potentially on a different host) that must be able to reach it directly over the LAN or the Tailscale/Headscale mesh.

```text
   ┌──────────────────────────┐
   │   Komodo Core (primary)  │
   │   ../komodo/README.md    │
   └────────────┬─────────────┘
                │  HTTP + KOMODO_PASSKEY
                │  (LAN or Tailscale/Headscale mesh)
                ▼
   ┌──────────────────────────────────────┐
   │   komodo-periphery (this agent)      │
   │   listens on :8120                   │
   └───────────────┬──────────────────────┘
                   │
         ┌─────────┴─────────┐
         ▼                   ▼
 /var/run/docker.sock   ${HOST_STACKS_PATH}
 (Docker daemon)        (stack definitions)
         │
         ▼
 Managed containers on this host
```

**Security note:** Binding to `0.0.0.0` by default makes the agent reachable from *any* network interface on the host, not just the one facing the primary Core server. In environments where the host is also connected to an untrusted LAN, restrict exposure by setting `PERIPHERY_BIND_IP` to the host's Tailscale interface IP (e.g., `100.64.0.x`) so only traffic arriving over the VPN mesh can reach the agent.

## Service Interconnections & Dependencies

- [komodo](../komodo/README.md) — the primary Core server this agent reports to. Authentication is via the shared `KOMODO_PASSKEY`; once authorized, Core can deploy stacks, run builds, and scrape container metrics from this node.
- [tailscale-client](../tailscale-client/README.md) — typically deployed alongside this agent on the same secondary/edge node to provide the Headscale VPN mesh connectivity Core uses to reach `PERIPHERY_BIND_IP`.
- [monitoring-agent-gpnc](../monitoring-agent-gpnc/README.md) — typically co-located on the same secondary node to ship host/container metrics and logs to the central [monitoring-stack-gpnc](../monitoring-stack-gpnc/README.md).

## File Structure

| File | Purpose |
| --- | --- |
| `docker-compose.yml` | Defines the single `komodo-periphery` agent service, its port binding, volumes, and Docker socket mount. There is no `docker-compose.override.yml` for this service — all configuration is handled through environment variables in the base file. |
| `.env.example` | Template for required environment variables (version, network binding, host paths, passkey). |

## Configuration & Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `KOMODO_VERSION` | `latest` | Image tag for `ghcr.io/moghtech/komodo-periphery`. |
| `PERIPHERY_BIND_IP` | `0.0.0.0` | Host interface the agent's API binds to. Restrict to a Tailscale IP for tighter exposure. |
| `PERIPHERY_PORT` | `8120` | Host port the primary Komodo Core server connects to. |
| `HOST_STACKS_PATH` | `/opt` | Host directory containing stack/compose definitions, bind-mounted into the agent. |
| `CONTAINER_STACKS_PATH` | `/opt` | Mount point inside the container — kept equal to `HOST_STACKS_PATH` for path parity. |
| `KOMODO_PASSKEY` | _(required)_ | Shared secret authenticating Core's requests to this agent. **Must match exactly** the `KOMODO_PASSKEY` configured on the primary Komodo Core server. |

## Deployment & Operational Commands

### 1. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and set `KOMODO_PASSKEY`. **This must be completely identical** to the passkey configured on the primary Komodo Core server.

### 2. Launch the Agent

```bash
docker compose up -d
```

Verify it started cleanly:

```bash
docker compose logs -f komodo-periphery
```

### 3. Connect to Core

Once the container is running, the node must be authorized in the primary Komodo dashboard:

1. Open the Komodo Web UI on the primary server.
2. Navigate to **Servers** > **Add Server**.
3. Set the Address to the secondary node's reachable IP and port (e.g., `http://100.64.0.2:8120` over Tailscale, or the LAN IP).
4. Enter the exact `KOMODO_PASSKEY` from the `.env` file.
5. Save and verify the server status turns green (Healthy).

## Specific Notes

- `PERIPHERY_ROOT_DIRECTORY` is fixed internally to `/config` (mapped to the `komodo_periphery_data` volume) and is not meant to be overridden via `.env`.
- `PERIPHERY_SSL_ENABLED` is hardcoded to `false` in `docker-compose.yml`, since TLS is expected to be handled by the transport layer (Tailscale/Headscale mesh or LAN) rather than the agent itself — there is no reverse-proxy termination for this service.
