# Core

`core/` is the foundational infrastructure layer of this homelab: the handful of services every other application depends on but none of them *are*. It sits alongside [`../compose/`](../compose/) in the repository root, which holds the actual applications (Jellyfin, Nextcloud, RomM, the \*arr stack, etc.) — those services exist to be used; the services in `core/` exist so the rest of the homelab can run, be reached, be observed, be backed up, and be deployed consistently.

If a service in `compose/` goes down, you lose a feature. If a service in `core/` goes down, you typically lose DNS resolution, remote access, ingress routing, deployment tooling, observability, or backups for *everything else* — which is why these stacks are documented, versioned, and operated more conservatively than the application layer.

## What belongs in `core/` vs `compose/`

| | `core/` | `compose/` |
| --- | --- | --- |
| Purpose | Infrastructure: networking, identity, ingress, orchestration, observability, backups | Applications: the things people actually use day to day |
| Failure blast radius | Can take down access to or visibility into every other stack | Scoped to that one application |
| Depends on | Mostly itself (other `core/` stacks) | Almost always depends on one or more `core/` stacks (`proxy_net`, `monitoring_net`) |
| Examples | reverse proxy, DNS, VPN mesh, GitOps/orchestration, metrics/logs, backups | Jellyfin, Nextcloud, RomM, the \*arr stack, AppFlowy, Bookshelf, Homarr |

In short: if a new stack needs `proxy_net` or `monitoring_net` to be *reachable* or *observed*, but doesn't provide either of those things itself, it belongs in `compose/`, not here.

## The Services

| Service | Role |
| --- | --- |
| [proxy-stack](./proxy-stack/) | Nginx Proxy Manager + Cloudflare DDNS. Owns `proxy_net`, the external ingress network every exposed service attaches to; terminates TLS and routes traffic in. |
| [adguard](./adguard/) | Network-wide DNS (AdGuard Home). Implements the homelab's Split-Brain DNS, resolving internal domains differently for LAN vs. VPN clients so traffic never needlessly leaves the network. |
| [headscale](./headscale/) | Self-hosted Tailscale control server + Headplane UI. Issues identities and manages the private VPN mesh (tailnet) that connects every node, including remote/edge ones. |
| [tailscale-client](./tailscale-client/) | The VPN agent deployed on each node (primary or secondary) to join the tailnet managed by `headscale`. |
| [komodo](./komodo/) | GitOps orchestration: web UI, API, and MongoDB backing store for deploying and managing every stack in this repository (including `core/` itself) across multiple servers. |
| [komodo-periphery](./komodo-periphery/) | The standalone Komodo agent for secondary/edge nodes that don't run the full `komodo` core stack — lets the primary Komodo server manage containers on that remote host. |
| [monitoring-stack-gpnc](./monitoring-stack-gpnc/) | The central observability hub: Grafana, Prometheus, Loki, Alertmanager. Owns the `monitoring` network every other stack ships logs to, and pulls metrics from both local and remote exporters. |
| [monitoring-agent-gpnc](./monitoring-agent-gpnc/) | The lightweight per-node counterpart (cAdvisor, Node Exporter, Promtail) deployed on secondary/edge nodes to feed the central monitoring stack over the VPN mesh. |
| [backrest](./backrest/) | Restic-powered backup orchestrator. Has read-only visibility into every other stack's Docker volumes, `/opt`, `/srv`, and this Git repository, and ships snapshots to local or cloud storage. |

## Architecture & Node Topology

This repository assumes (but does not require) a multi-node homelab: one **primary node** running the full infrastructure, and zero or more **secondary/edge nodes** running a slimmer footprint that phones home over the VPN mesh.

```text
┌──────────────────────────────── Primary Node (e.g. redserver) ───────────────────────────────────┐
│                                                                                                  │
│  [ proxy-stack ] ── proxy_net ──┬── [ adguard ] ── [ headscale ] ── [ komodo ] ── (any exposed   │
│       (ingress, TLS)            │                                                 compose/ app)  │
│                                 │                                                                │
│  [ monitoring-stack-gpnc ] ── monitoring ── (every core/ and compose/ stack ships logs here)     │
│       (Grafana/Prometheus/Loki)                                                                  │
│                                 ▲                                                                │
│  [ backrest ] ── read-only ─────┴── /opt, /srv, Docker volumes, this repo                        │
│       (Restic backups)                                                                           │
└───────────────────────────────────────────┬──────────────────────────────────────────────────────┘
                                            │ Tailscale / Headscale mesh (100.64.x.x)
┌───────────────────────────────────────────┴──────────────────────────────────────────────────────┐
│                               Secondary / Edge Node (e.g. crimsonserver)                         │
│                                                                                                  │
│  [ tailscale-client ] ── mesh identity ── [ komodo-periphery ] ── [ monitoring-agent-gpnc ]      │
│                                              (remote mgmt)           (scraped/pushed over mesh)  │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Two shared Docker networks tie most of this together, both created as `external: true` so they outlive any single stack's lifecycle:

- **`proxy_net`** — owned by [proxy-stack](./proxy-stack/); anything that needs a public or reverse-proxied domain joins it (`docker network create proxy_net`).
- **`monitoring`** (referenced as `monitoring_net` in other stacks' overrides) — owned by [monitoring-stack-gpnc](./monitoring-stack-gpnc/); anything that wants its logs shipped to Loki joins it.

Everything else — `komodo_internal`, `headscale_internal` — is a private network scoped to a single stack's own components and isn't meant to be shared.

## Deployment Order

Because these stacks depend on each other's networks and services, bringing up a brand-new primary node roughly follows this order:

1. **[proxy-stack](./proxy-stack/)** — creates `proxy_net`; nothing else can expose a domain until this exists.
2. **[monitoring-stack-gpnc](./monitoring-stack-gpnc/)** — creates the `monitoring` network and the central Grafana/Prometheus/Loki hub.
3. **[adguard](./adguard/)** and **[headscale](./headscale/)** — DNS and VPN control plane; both attach to `proxy_net` for TLS-terminated UIs.
4. **[komodo](./komodo/)** — once the above exist, hand future deployments (including redeploying `core/` itself) to Komodo's GitOps workflow.
5. **[backrest](./backrest/)** — bring up backups once there's meaningful state worth protecting.

For a secondary/edge node: **[tailscale-client](./tailscale-client/)** first (to get a tailnet identity), then **[komodo-periphery](./komodo-periphery/)** and **[monitoring-agent-gpnc](./monitoring-agent-gpnc/)**, both of which rely on that identity to be reachable from the primary node.

Each stack's own README documents its specific `.env` setup, override file, and verification steps — this document only covers how they fit together.

## Conventions Shared Across `core/` Stacks

- **Env-driven configuration:** every stack ships a `.env.example`; real `.env` files are git-ignored (see [.gitignore](../.gitignore)).
- **Named Docker volumes over bind mounts** for internal state, to stay host-path-agnostic — [monitoring-stack-gpnc](./monitoring-stack-gpnc/) is the deliberate exception, using pre-existing `external: true` volumes so historical metrics/dashboards survive a stack teardown.
- **`docker-compose.override.yml` for host-specific concerns** (network attachment, logging labels) — kept separate from the portable base `docker-compose.yml` so the latter stays infrastructure-agnostic. [komodo](./komodo/) and [komodo-periphery](./komodo-periphery/) are exceptions and don't ship one; [tailscale-client](./tailscale-client/) ships one that carries labels only, since `network_mode: host` rules out network attachment.
- **Consistent logging labels** (`logging: promtail`, `logging_jobname: <stack>`) so the central Promtail in [monitoring-stack-gpnc](./monitoring-stack-gpnc/) can discover and tag every container's logs uniformly.
- **GitOps-first deployment:** every stack documents both a Komodo-managed path and a manual CLI path, since [komodo](./komodo/) is meant to be the normal way these get deployed and redeployed.
