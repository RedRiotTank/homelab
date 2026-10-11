# Headscale & Headplane

Self-hosted Tailscale control server ([Headscale](https://github.com/juanfont/headscale)) paired with its web-based management UI ([Headplane](https://github.com/tale/headplane)), providing a private VPN mesh ("tailnet") for the homelab without depending on Tailscale's hosted coordination server.

## Architecture & Design Decisions

The stack is split into two decoupled components that share an internal Docker network (`headscale_internal`):

- **`headscale`** — The core backend. Handles node registration, key exchange (noise/DERP), and network/ACL policy. Runs `headscale serve`.
- **`headplane`** — A frontend dashboard that talks to the Headscale API (and, via a read-only Docker socket mount, to the `headscale` container itself) to manage nodes, users, and pre-auth keys without hand-editing CLI commands.

Persistence is split between a Docker volume and host bind mounts:

| Resource | Type | Purpose |
| --- | --- | --- |
| `headscale_data` | Docker Volume | Stores the Headscale SQLite database and noise/DERP private keys. |
| `${HOST_CONFIG_PATH}` | Bind Mount | Host directory containing the Headscale `config.yaml`. |
| `${HEADPLANE_CONFIG_DIR}` | Bind Mount | Host directory containing the Headplane `config.yaml` and secrets. |

### Why Headplane needs TLS termination upstream

Headplane requires a secure context (HTTPS) to function correctly — browsers block access to its authentication and internal crypto APIs over plain HTTP, resulting in a broken interface or inability to log in. Because of this, the base `docker-compose.yml` publishes **no host ports at all** for either container. Traffic only reaches these services through a reverse proxy that terminates TLS and forwards to the container names (`headscale`, `headplane`) over the shared `proxy_net` network — see [Service Interconnections & Dependencies](#service-interconnections--dependencies) below.

## Service Interconnections & Dependencies

This stack is attached to the homelab's shared infrastructure entirely through `docker-compose.override.yml` — the base compose file only defines the internal `headscale_internal` network.

- **[proxy-stack](../proxy-stack/README.md)** — Provides TLS termination and public/private ingress via the external `proxy_net` network. Required for Headplane to be usable at all (see above).
- **[monitoring-stack-gpnc](../monitoring-stack-gpnc/README.md)** — Central Promtail/Loki log ingestion via the external network literally named `monitoring` (referenced here as `monitoring_net`). Both containers are labeled `logging: "headscale"` / `logging_jobname: "headscale-stack"` for log-shipper discovery.
- **[adguard](../adguard/README.md)** — Headscale's MagicDNS is configured to hand out AdGuard Home as the tailnet-wide nameserver, which is what makes the homelab's Split-Brain DNS architecture work for VPN clients.
- **[tailscale-client](../tailscale-client/README.md)** — The client agent deployed on homelab servers to join the tailnet this stack controls.

## File Structure

| File | Purpose |
| --- | --- |
| `docker-compose.yml` | Core, portable definition of the `headscale` and `headplane` services and the internal network. Publishes no host ports. |
| `docker-compose.override.yml` | Attaches both services to the external `proxy_net` and `monitoring_net` networks and injects logging labels. Optional. |
| `.env.example` | Template for host config paths. |

## Configuration & Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `HOST_CONFIG_PATH` | `/opt/core/headscale/config` | Host directory mounted to `/etc/headscale` containing Headscale's `config.yaml`. |
| `HEADPLANE_CONFIG_DIR` | `/opt/core/headscale/headplane-config` | Host directory whose `config.yaml` is mounted to `/etc/headplane/config.yaml`. |

Before starting the stack, prepare both configuration files on the host.

### 1. Headscale Configuration (`config.yaml`)

Create the directory defined by `HOST_CONFIG_PATH` and place a `config.yaml` inside it. Start from the [official example template](https://github.com/juanfont/headscale/blob/main/config-example.yaml) and set:

- `server_url`: Your external domain (e.g., `https://vpn.example.com`).
- `listen_addr`: `0.0.0.0:8080`.
- `metrics_listen_addr`: `127.0.0.1:9090`.
- `database.sqlite.path`: `/var/lib/headscale/db.sqlite` (maps to the `headscale_data` volume).
- **DNS configuration** — to enable the [Split-Brain DNS architecture](../adguard/README.md), enable MagicDNS and set the global nameserver to AdGuard Home's Tailscale tunnel IP:

  ```yaml
  dns:
    magic_dns: true
    base_domain: tailnet.example.com
    override_local_dns: true
    nameservers:
      global:
        - 100.64.0.1 # Routes VPN DNS queries to AdGuard Home
  ```

### 2. Headplane Configuration (`config.yaml`)

Create the directory defined by `HEADPLANE_CONFIG_DIR` and add a `config.yaml`:

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

**Generating the Headscale API key:** Headplane needs an API key to talk to Headscale, so start Headscale first:

1. Start the Headscale container.
2. Generate a 90-day API key on the host:

   ```bash
   docker exec headscale headscale apikeys create --expiration 90d
   ```

3. Copy the output (`hskey-...`) into Headplane's `config.yaml`.
4. Restart the Headplane container.

## Deployment & Operational Commands

### Option A: GitOps via Komodo (Recommended)

1. Add this repository to your Komodo instance.
2. Ensure `HOST_CONFIG_PATH` and `HEADPLANE_CONFIG_DIR` point to the directories where you placed your `config.yaml` files on the host.
3. In "File Paths", list both `docker-compose.yml` and `docker-compose.override.yml`.
4. Click Deploy.

### Option B: Manual CLI Deployment

```bash
cp .env.example .env
docker compose up -d
```

The override layer (proxy + monitoring network attachment and logging labels) is entirely optional:

- **Komodo users:** Omit `docker-compose.override.yml` from "File Paths" if proxy/monitoring are not deployed.
- **CLI users:** Delete the override file, or run `docker compose -f docker-compose.yml up -d` explicitly.

## Specific Notes

### Connecting Nodes

Once the Headscale control server is up, attach machines to the mesh:

- **Homelab servers (Linux/Docker):** Deploy the [Tailscale Client](../tailscale-client/README.md) agent alongside this stack.
- **Personal devices (iOS/Android/Windows/macOS):** Install the official Tailscale app, change the Alternate Server to your custom domain (`https://vpn.example.com`), and authenticate via the Headplane UI.
