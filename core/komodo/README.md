# Komodo Orchestration Stack

Central multi-server container management, GitOps deployment automation, and build/monitoring dashboard for the homelab. This is the primary-node stack: it runs the Web UI/API, its database, and a local Periphery agent in one place so the primary host can both serve the dashboard and manage its own containers.

## Architecture & Design Decisions

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

### Zero Host Exposure by Default

The base `docker-compose.yml` publishes no host ports. All ingress routing is meant to be handled by a dedicated reverse proxy on an external network (`proxy_net`).

### Path Portability

Host paths are parameterized through environment variables:

- `HOST_STACKS_PATH`: Base path on the host where stacks are stored (defaults to `/opt`).
- `CONTAINER_STACKS_PATH`: Target mount point inside the periphery container (defaults to `/opt`).

Both can be overridden in `.env` to relocate the stacks directory anywhere on the host filesystem without altering repository code.

### Node Topology

- **Primary Node (RedServer):** Runs the full stack (Core + Periphery + MongoDB) via this directory.
- **Secondary Nodes (CrimsonServer):** Only require the lightweight agent, pointing back to the primary Core API using a shared `KOMODO_PASSKEY`. See the [Komodo Periphery Agent documentation](../komodo-periphery/README.md) for secondary node deployment.

### The Override Is Committed, But Komodo Must Not Manage Itself

Like every other stack in this repository, `docker-compose.override.yml` is committed here and carries the host-specific concerns (port binding, ingress network, observability labels) on top of the infrastructure-agnostic base `docker-compose.yml`.

Komodo itself is a GitOps engine that pulls this repository and applies compose files to the hosts it manages. Committing Komodo's own override would normally risk a circular dependency between "the config Komodo deploys" and "the config that deploys Komodo." This repo avoids that circularity with a deployment rule instead of hiding the file:

> **Never add this `core/komodo` directory as a Stack inside Komodo's own Web UI.** Deploy and upgrade it manually from this directory — `docker compose pull && docker compose up -d` — or through separate out-of-band automation that isn't Komodo itself. Every *other* stack in this repository is fine, and expected, to be managed as a Komodo Stack through the GitOps UI — just not Komodo itself.

Letting Komodo manage its own redeployment risks killing the very container performing the deploy mid-operation, or getting stuck with no working UI to roll back a bad config change.

**Example Override** (this is what `docker-compose.override.yml` in this directory contains):

```yaml
services:
  komodo:
    ports:
      # Binds the dashboard to localhost for initial configuration or emergency access
      - "${KOMODO_PORT:-127.0.0.1:9120}:9120"

    networks:
      # Ingress network: Allows reverse proxy (Nginx Proxy Manager) to reach the Core UI
      - proxy_net

      # Observability network: not required for log shipping (Promtail is label-driven,
      # see rationale below), kept for debugging/direct reachability from this container
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
```

**Rationale for each piece:**

- **Bootstrap Access (`ports`):** Exposes port `9120` strictly to `127.0.0.1`, preventing exposure to the LAN or Internet while allowing initial access directly via localhost or through an SSH tunnel (`ssh -L 9120:localhost:9120 user@host`).
- **Reverse Proxy Integration (`proxy_net`):** Connects the Core container directly to the ingress proxy so it can be exposed under a custom domain (e.g. `https://komodo.yourdomain.com`) with automated TLS termination.
- **Observability (`monitoring_net` & labels):** Injects metadata labels for central log shippers (Promtail/Loki/Alloy) so they can identify and categorize container logs under the `komodo` job without modifying the shared base repository. Note this is purely label-driven — Promtail discovers containers and reads their logs via the Docker socket, not over the network, so `monitoring_net` membership itself isn't what makes log shipping work. See [monitoring-stack-gpnc](../monitoring-stack-gpnc/README.md) for details.

## Service Interconnections & Dependencies

- [komodo-periphery](../komodo-periphery/README.md) — standalone agent deployed on secondary nodes; authenticates against this Core via the shared `KOMODO_PASSKEY`.
- [proxy-stack](../proxy-stack/README.md) — reverse proxy that terminates TLS and routes `https://komodo.yourdomain.com` to the Core UI over the external `proxy_net` network, attached through `docker-compose.override.yml`.
- [monitoring-stack-gpnc](../monitoring-stack-gpnc/README.md) — scrapes/ships Komodo logs and metrics over the external `monitoring_net` network (Docker network name: `monitoring`).

## File Structure

- `docker-compose.yml` — core, periphery, and MongoDB service definitions; infrastructure-agnostic, no host ports, no external networks.
- `docker-compose.override.yml` — host-specific port binding, ingress network (`proxy_net`), and observability (`monitoring_net`) labels. Committed, like every other stack's override — but **never deploy this directory as a Stack inside Komodo's own Web UI**; see [Architecture & Design Decisions](#architecture--design-decisions).
- `.env.example` — template for image versions, host paths, and secrets.

## Configuration & Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `KOMODO_VERSION` | `latest` | Image tag for `komodo-core` and `komodo-periphery`. |
| `MONGO_VERSION` | `6.0` | Image tag for the MongoDB instance. |
| `KOMODO_PORT` | `127.0.0.1:9120` | Host bind address/port for the dashboard (used only in `docker-compose.override.yml`). |
| `HOST_STACKS_PATH` | `/opt` | Host path where stack compose definitions live, mounted into Periphery. |
| `CONTAINER_STACKS_PATH` | `/opt` | Target mount point inside the Periphery container (usually matches `HOST_STACKS_PATH`). |
| `KOMODO_JWT_SECRET` | — | Secret used to sign Core session/auth tokens. |
| `KOMODO_PASSKEY` | — | Shared secret between Core and every Periphery agent (local or remote). |
| `KOMODO_FIRST_SERVER` | `true` | Set to `false` on secondary/satellite nodes. |

Generate secure secrets after copying the template:

```bash
cp .env.example .env

# Generate JWT Secret
sed -i "s/replace_with_a_secure_jwt_secret/$(openssl rand -hex 32)/" .env

# Generate Periphery Passkey
sed -i "s/replace_with_a_secure_periphery_passkey/$(openssl rand -hex 32)/" .env
```

## Deployment & Operational Commands

### 1. Configure Environment

```bash
cp .env.example .env
nano .env
```

### 2. Launch the Stack

```bash
docker compose up -d
```

Compose automatically merges `docker-compose.override.yml` on top of `docker-compose.yml`, attaching the ingress (`proxy_net`) and observability (`monitoring_net`) networks. **Do not** register this directory as a Stack inside Komodo's own Web UI — see [Architecture & Design Decisions](#architecture--design-decisions). Deploy and upgrade it manually from this directory instead.

### 3. Bootstrap Access

While only `127.0.0.1:9120` is exposed (via the override), reach the dashboard through an SSH tunnel for initial setup or emergency access:

```bash
ssh -L 9120:localhost:9120 user@host
```

### 4. Initial Onboarding

1. Access the dashboard via your reverse proxy domain or the SSH tunnel: `http://localhost:9120`.
2. Complete the initial administrator setup.
3. Add the local Periphery agent as a server, using the internal Docker DNS endpoint and the shared passkey:
   - **Periphery Address:** `http://komodo-periphery:8120`
   - **Passkey:** value of `KOMODO_PASSKEY`
4. For secondary nodes, repeat server registration using each node's reachable address — see [komodo-periphery](../komodo-periphery/README.md).

## Specific Notes

- **Directory & State Management:**

  | Resource | Purpose | Location |
  | --- | --- | --- |
  | `komodo_data` | Core state, server configurations, and certificates | Named Docker Volume |
  | `komodo_mongo_data` | MongoDB data collections | Named Docker Volume |
  | `${HOST_STACKS_PATH}` | Stack compose definitions managed by Periphery | Host path defined in `.env` (default: `/opt`) |

- **Never manage this stack from inside Komodo's own UI.** Add every other repository directory as a Komodo Stack normally; for `core/komodo` itself, deploy via `docker compose up -d` from this directory (manually, or through separate out-of-band automation) so Komodo never attempts to redeploy its own running instance.
