# Tailscale Client

Deploys the Tailscale client agent to connect host machines (nodes) to the self-hosted [Headscale](../headscale/README.md) VPN mesh network. This is how secondary/edge nodes — and any machine that needs a private, zero-config route back into the homelab — join the tailnet.

## Architecture & Design Decisions

Unlike every other stack in this repo, this service needs direct control over the host's networking stack to create and manage a WireGuard tunnel — it cannot operate from behind a bridge network.

- **`network_mode: host`:** The container shares the host's network namespace entirely. It does not join `proxy_net`, `monitoring_net`, or any custom Docker network, because creating a tunnel interface (`tailscale0`) and manipulating routing tables requires operating on the host's real network stack, not an isolated bridge.
- **`NET_ADMIN` and `SYS_MODULE` capabilities:** Required to create the tunnel interface, modify routing tables, and (on some kernels) load the WireGuard module.
- **`/dev/net/tun` device:** The userspace/kernel handoff point for the tunnel; without it, no VPN interface can be created.
- **`tailscale_data` volume:** Stores cryptographic node identity, keys, and tailnet state, abstracted away from host paths so the container can be destroyed and recreated without losing its identity (though not its authorization — see the reusable-key note below).

### Why the override file looks different here

Every other stack's `docker-compose.override.yml` in this repo exists to attach services to shared external networks (`proxy_net`, `monitoring_net`). This one cannot do that — `network_mode: host` is incompatible with also joining custom Docker networks. So the override here is reduced to its bare minimum: injecting `logging`/`logging_jobname` labels so the central Promtail (running on the same host, scraping the Docker socket directly) can still identify and tag this container's logs for shipment to Loki. No network attachment happens at all; the labels are the entire payload of the override.

```text
┌─────────────────────────── Host Network Namespace ───────────────────────────┐
│                                                                                │
│   ┌───────────────────────┐        NET_ADMIN / SYS_MODULE / /dev/net/tun      │
│   │  tailscale container  │ ─────────────────────────────────────────────┐   │
│   │  (network_mode: host) │                                              │   │
│   └───────────┬───────────┘                                              │   │
│               │ creates                                                  │   │
│               ▼                                                          │   │
│     [ tailscale0 tunnel interface ]  ── registers with ──▶  Headscale    │   │
│               │                                             control server│  │
│               │ 100.64.x.x                                                │   │
│               ▼                                                          │   │
│     Routable over the private tailnet mesh                               │   │
│                                                                            │   │
│   (No Docker bridge network joined — Promtail reads logs via the host's  │   │
│    own Docker socket, not via `monitoring_net`)                          │   │
└────────────────────────────────────────────────────────────────────────────┘
```

## Service Interconnections & Dependencies

- [headscale](../headscale/README.md) — the control server this client authenticates against. `HEADSCALE_URL` must point at its public/reachable address, and a pre-auth key generated there is required to join without manual web authentication.
- [monitoring-stack-gpnc](../monitoring-stack-gpnc/README.md) — receives this container's logs. Because the container has no Docker network of its own, log shipping relies on the host's local Promtail (or the one bundled in [monitoring-agent-gpnc](../monitoring-agent-gpnc/README.md)) reading the Docker socket directly rather than this service reaching Loki over `monitoring_net`.
- [komodo-periphery](../komodo-periphery/README.md) and [monitoring-agent-gpnc](../monitoring-agent-gpnc/README.md) — this client is typically deployed alongside both on secondary/edge nodes, since they rely on the tailnet IP this container establishes (e.g. `100.64.0.2`) for the primary node to reach them remotely.

## File Structure

| File | Purpose |
| --- | --- |
| `docker-compose.yml` | Defines the single `client` service: host networking, capabilities, device mount, and the `tailscale_data` volume. |
| `docker-compose.override.yml` | Injects logging labels only — no network attachment is possible under `network_mode: host`. |
| `.env.example` | Template for required environment variables (hostname, control server URL, auth key). |

## Configuration & Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `NODE_HOSTNAME` | _(required)_ | Identifying name for this machine in the Headscale/Headplane dashboard (e.g., `redserver`, `crimsonserver`). |
| `HEADSCALE_URL` | _(required)_ | The Headscale control server's login-server URL (e.g., `https://vpn.example.com`). |
| `HEADSCALE_AUTHKEY` | _(required)_ | Pre-auth key used to join the tailnet without manual browser authentication. |
| `CONTAINER_NAME` | `tailscale` | Docker container name. |
| `TAILSCALE_VERSION` | `stable` | Image tag for `tailscale/tailscale`. |
| `TAILSCALE_EXTRA_ARGS` | _(empty)_ | Appended to `--login-server=...` for advanced `tailscaled` flags. |
| `TAILSCALE_ACCEPT_DNS` | `true` | Whether to accept MagicDNS/nameserver settings pushed by Headscale (needed for the [Split-Brain DNS](../adguard/README.md) setup). |

### Generating a pre-auth key

Run this on the host running the Headscale backend:

```bash
docker exec headscale headscale preauthkeys create --expiration 90d --reusable
```

`--reusable` lets the container re-authenticate automatically if it's destroyed and recreated, which is convenient for ephemeral or frequently-rebuilt nodes. The trade-off is that a leaked reusable key can enroll multiple unauthorized devices until it expires or is revoked; for stricter security, generate a unique, single-use key per node instead.

## Deployment & Operational Commands

### Option A: GitOps via Komodo (Recommended)

1. Add this repository to your Komodo instance.
2. Set the environment variables in the Komodo UI based on `.env.example`.
3. In "File Paths", list both `docker-compose.yml` and `docker-compose.override.yml` (if shipping logs to the monitoring stack).
4. Click Deploy.

### Option B: Manual CLI Deployment

```bash
cp .env.example .env
nano .env
docker compose up -d
```

The override is entirely optional:

- **Komodo Users:** Omit `docker-compose.override.yml` from "File Paths" if you don't need logging labels.
- **CLI Users:** Run `docker compose -f docker-compose.yml up -d` to skip it.

### Post-deploy verification

Open the Headplane web UI (see [headscale](../headscale/README.md)). The new node should appear in the device list with a `Connected` status and an assigned `100.64.x.x` tailnet IP within a few seconds of startup.
