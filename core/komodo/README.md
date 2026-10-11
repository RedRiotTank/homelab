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

### Why the Override Layer Lives Outside the Repo

Unlike every other stack in this repository, Komodo does **not** ship a committed `docker-compose.override.yml`. This is intentional: Komodo itself is a GitOps engine that pulls this very repository and applies compose files to the host it manages, so keeping host-specific concerns (port binding, ingress network, observability labels) inside the tracked repo would force host-specific values into version control and create a circular dependency between "the config Komodo deploys" and "the config that deploys Komodo."

Instead, Docker Compose automatically merges a `docker-compose.override.yml` on top of `docker-compose.yml` when both are present in the *working directory* — so the override is placed directly on the host, outside Git, at:

```
${HOST_STACKS_PATH}/core/komodo/docker-compose.override.yml
```

This keeps the repository version of `docker-compose.yml` clean, portable, and infrastructure-agnostic, while host-specific concerns — local port binding for emergency bootstrap, reverse-proxy ingress, and observability — stay out of source control.

**Example Production Override:**

```yaml
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
```

**Rationale for each piece:**

- **Bootstrap Access (`ports`):** Exposes port `9120` strictly to `127.0.0.1`, preventing exposure to the LAN or Internet while allowing initial access directly via localhost or through an SSH tunnel (`ssh -L 9120:localhost:9120 user@host`).
- **Reverse Proxy Integration (`proxy_net`):** Connects the Core container directly to the ingress proxy so it can be exposed under a custom domain (e.g. `https://komodo.yourdomain.com`) with automated TLS termination.
- **Observability (`monitoring_net` & labels):** Injects metadata labels for central log shippers (Promtail/Loki/Alloy) so they can identify and categorize container logs under the `komodo` job without modifying the shared base repository.

## Service Interconnections & Dependencies

- [komodo-periphery](../komodo-periphery/README.md) — standalone agent deployed on secondary nodes; authenticates against this Core via the shared `KOMODO_PASSKEY`.
- [proxy-stack](../proxy-stack/README.md) — reverse proxy that terminates TLS and routes `https://komodo.yourdomain.com` to the Core UI over the external `proxy_net` network (configured via the host-side override, not the committed compose file).
- [monitoring-stack-gpnc](../monitoring-stack-gpnc/README.md) — scrapes/ships Komodo logs and metrics over the external `monitoring_net` network (Docker network name: `monitoring`).

## File Structure

- `docker-compose.yml` — core, periphery, and MongoDB service definitions; infrastructure-agnostic, no host ports, no external networks.
- `.env.example` — template for image versions, host paths, and secrets.
- *(not committed)* `docker-compose.override.yml` — host-specific port binding, ingress network, and observability labels; lives at `${HOST_STACKS_PATH}/core/komodo/docker-compose.override.yml` (see above).

## Configuration & Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `KOMODO_VERSION` | `latest` | Image tag for `komodo-core` and `komodo-periphery`. |
| `MONGO_VERSION` | `6.0` | Image tag for the MongoDB instance. |
| `KOMODO_PORT` | `127.0.0.1:9120` | Host bind address/port for the dashboard (used only in the host-side override). |
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

If a host-side `docker-compose.override.yml` exists at `${HOST_STACKS_PATH}/core/komodo/`, run Compose from that directory (or pass both files explicitly) so ingress and observability networks are attached.

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

- Because the override lives on the host rather than in Git, upgrading or cloning this repository to a new primary node requires manually recreating that file — it is not something `git pull` will ever bring back.
