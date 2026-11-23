# Core

`core/` is the foundational infrastructure layer of this homelab: the handful of services every other application depends on but none of them *are*. It sits alongside [`../compose/`](../compose/) in the repository root, which holds the actual applications (Jellyfin, Nextcloud, RomM, the \*arr stack, etc.) — those services exist to be used; the services in `core/` exist so the rest of the homelab can run, be reached, be observed, be backed up, and be deployed consistently.

If a service in `compose/` goes down, you lose a feature. If a service in `core/` goes down, you typically lose DNS resolution, remote access, ingress routing, deployment tooling, observability, or backups for *everything else* — which is why these stacks are documented, versioned, and operated more conservatively than the application layer.

## What belongs in `core/` vs `compose/`

| | `core/` | `compose/` |
| --- | --- | --- |
| Purpose | Infrastructure: networking, identity, ingress, orchestration, observability, backups | Applications: the things people actually use day to day |
| Failure blast radius | Can take down access to or visibility into every other stack | Scoped to that one application |
| Depends on | Mostly itself (other `core/` stacks) | Almost always depends on one or more `core/` stacks (`proxy_net`, `monitoring_net`) |
| Examples | reverse proxy, DNS, VPN mesh, orchestration, metrics/logs, backups | Jellyfin, Nextcloud, RomM, the \*arr stack, AppFlowy, Bookshelf, Homarr |

In short: if a new stack needs `proxy_net` or `monitoring_net` to be *reachable* or *observed*, but doesn't provide either of those things itself, it belongs in `compose/`, not here.

## The Services

| Service | Role |
| --- | --- |
| [proxy-stack](./proxy-stack/) | Nginx Proxy Manager + Cloudflare DDNS. Owns `proxy_net`, the external ingress network every exposed service attaches to; terminates TLS and routes traffic in. |
| [adguard](./adguard/) | Network-wide DNS (AdGuard Home). Implements split-horizon DNS, resolving internal domains differently for LAN vs. VPN clients so traffic never needlessly leaves the network. |
| [headscale](./headscale/) | Self-hosted Tailscale control server + Headplane UI. Issues identities and manages the private VPN mesh (tailnet) that connects every node, including remote/edge ones. |
| [tailscale-client](./tailscale-client/) | The VPN agent deployed on each node to join the tailnet managed by `headscale`. |
| [komodo](./komodo/) | Optional GitOps orchestration: web UI, API, and MongoDB backing store for deploying and managing stacks across one or more servers. |
| [komodo-periphery](./komodo-periphery/) | The lightweight Komodo agent for edge nodes that don't run the full `komodo` core stack. |
| [monitoring-stack-gpnc](./monitoring-stack-gpnc/) | The central observability hub: Grafana, Prometheus, Loki, Alertmanager. Owns the `monitoring` network every other stack ships logs to, and pulls metrics from local and remote exporters. |
| [monitoring-agent-gpnc](./monitoring-agent-gpnc/) | The lightweight per-node counterpart (cAdvisor, Node Exporter, Promtail) deployed on edge nodes to feed the central monitoring stack over the private network. |
| [backrest](./backrest/) | Restic-powered backup orchestrator. Has read-only visibility into host data paths and Docker volumes, and ships snapshots to local or cloud storage. |
| [vaultwarden](./vaultwarden/) | Self-hosted Bitwarden-compatible password manager. Stores every other credential and serves the official Bitwarden clients. |

## Architecture & Node Topology

This repository supports, but does not require, a multi-node setup: one primary
node running the full infrastructure, and zero or more edge nodes running a
slimmer footprint that connects over a private network.

```text
┌──────────────────────────── Primary node ────────────────────────────┐
│                                                                     │
│  [ proxy-stack ] ── proxy_net ──┬── [ adguard ] ── [ headscale ]     │
│       (ingress, TLS)            │                                   │
│                                 ├── [ komodo ] ── (exposed apps)     │
│  [ monitoring-stack ] ── monitoring ── (all stacks ship logs here)   │
│       (Grafana/Prometheus/Loki)                                     │
│                                 ▲                                   │
│  [ backrest ] ── read-only ─────┴── <data paths>, Docker volumes    │
│       (optional)                                                    │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ private network / VPN mesh
┌──────────────────────────────────┴──────────────────────────────────┐
│                         Edge node(s)                                │
│                                                                     │
│  [ tailscale-client ] ── [ komodo-periphery ] ── [ monitoring-agent ]│
└─────────────────────────────────────────────────────────────────────┘
```

Two shared Docker networks tie most of this together, both created as `external: true` so they outlive any single stack's lifecycle:

- **`proxy_net`** — owned by [proxy-stack](./proxy-stack/); anything that needs a public or reverse-proxied domain joins it (`docker network create proxy_net`).
- **`monitoring`** — owned by [monitoring-stack-gpnc](./monitoring-stack-gpnc/); anything that wants its logs shipped to Loki joins it (usually as `monitoring_net`, with `name: monitoring`, in other stacks' overrides).

Everything else — `komodo_internal`, `headscale_internal` — is a private network scoped to a single stack's own components and isn't meant to be shared.

## Deployment Order

Because these stacks depend on each other's networks and services, bringing up a brand-new primary node roughly follows this order:

1. **[proxy-stack](./proxy-stack/)** — creates `proxy_net`; nothing else can expose a domain until this exists.
2. **[monitoring-stack-gpnc](./monitoring-stack-gpnc/)** — creates the `monitoring` network and the central Grafana/Prometheus/Loki hub.
3. **[adguard](./adguard/)** and **[headscale](./headscale/)** — DNS and VPN control plane; both attach to `proxy_net` for TLS-terminated UIs.
4. **[komodo](./komodo/)** — optional; once the above exist, hand future deployments to your orchestrator.
5. **[backrest](./backrest/)** — optional; bring up backups once there is meaningful state to protect.

For an edge node: **[tailscale-client](./tailscale-client/)** first (to get a private-network identity), then **[komodo-periphery](./komodo-periphery/)** and **[monitoring-agent-gpnc](./monitoring-agent-gpnc/)**, both of which rely on that identity to be reachable from the primary node.

Each stack's own README documents its `.env` setup, override file, and verification steps — this document only covers how they fit together.

## Deployment

Every stack is a standalone Docker Compose project. Copy its `.env.example` to
`.env`, adjust the values for your host, and run `docker compose up -d`. You can
also deploy it through any orchestrator or deployment tool. No specific host
layout is required; the paths in the examples are placeholders or documented
defaults. See [`../docs/deployment.md`](../docs/deployment.md).

## Conventions Shared Across `core/` Stacks

- **Env-driven configuration:** every stack ships a `.env.example`; real `.env` files are git-ignored (see [.gitignore](../.gitignore)).
- **Named Docker volumes over bind mounts** for internal state, to stay host-path-agnostic — [monitoring-stack-gpnc](./monitoring-stack-gpnc/) is the deliberate exception, using pre-existing `external: true` volumes so historical metrics/dashboards survive a stack teardown.
- **`docker-compose.override.yml` for host-specific concerns** (network attachment, logging labels) — kept separate from the portable base `docker-compose.yml` so the latter stays infrastructure-agnostic. [komodo](./komodo/) and [komodo-periphery](./komodo-periphery/) are exceptions and don't ship one; [tailscale-client](./tailscale-client/) ships one that carries labels only, since `network_mode: host` rules out network attachment.
- **Consistent logging labels** (`logging: promtail`, `logging_jobname: <stack>`) so the central Promtail in [monitoring-stack-gpnc](./monitoring-stack-gpnc/) can discover and tag every container's logs uniformly.
- **GitOps-first deployment:** every stack documents both an orchestrator-managed path and a manual CLI path; the repository does not require a specific orchestrator.
